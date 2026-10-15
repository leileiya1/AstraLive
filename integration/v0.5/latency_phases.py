#!/usr/bin/env python3
"""Closed-evidence timing attribution. No media decoding or acceptance upgrade.

SQL receipt timestamps measure PostgreSQL insertion, not the physical instant
of sink/device consumption. Cross-clock estimates remain conditional.
"""
import argparse
import gzip
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path


class LatencyEvidenceError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise LatencyEvidenceError(code)


def number(x):
    require(type(x) in (int, float) and math.isfinite(x), "NONFINITE_NUMBER")
    return x


def timestamp(value):
    require(isinstance(value, str), "TIMESTAMP_MISSING")
    try:
        # Python 3.9 fromisoformat only accepts selected fractional lengths;
        # Go RFC3339Nano/PG legitimately emit 1..9 fractional digits.
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})", value)
        require(match is not None, "TIMESTAMP_TIMEZONE_OR_FORMAT_INVALID")
        base, fraction, zone = match.groups()
        dt = datetime.fromisoformat(base + ("+00:00" if zone == "Z" else zone))
        return dt.timestamp()*1000 + (int(fraction)*1000/(10**len(fraction)) if fraction else 0)
    except (ValueError, OverflowError) as exc:
        raise LatencyEvidenceError("INVALID_TIMESTAMP") from exc


def quantiles(values):
    a = sorted(number(v) for v in values)
    if not a:
        return {"count": 0, "status": "NOT_VERIFIABLE"}
    def q(p):
        k = (len(a)-1)*p
        i = int(k)
        return a[i] + (a[min(i+1, len(a)-1)]-a[i])*(k-i)
    return {"count": len(a), "P50": q(.5), "P95": q(.95), "P99": q(.99),
            "max": a[-1], "mean": sum(a)/len(a), "unit": "ms",
            "method": "linear interpolation at (n-1)*p; marginal quantiles do not add"}


def unique(rows, key):
    out = {}
    for row in rows:
        value = row[key]
        require(value not in out, "DUPLICATE_"+key.upper())
        out[value] = row
    return out


PHASES = (
    ("selectedToSuspendRecorded", "selected", "suspend", "CONDITIONAL_GO_DB_CLOCK"),
    ("suspendToBoundaryCompletedRecorded", "suspend", "boundary", "MEASURED_DB_RECEIPT_INTERVAL"),
    ("boundaryCompletedToAnswerEpochRecorded", "boundary", "epoch", "MEASURED_DB_RECEIPT_INTERVAL"),
    ("answerEpochToAnswerPreparedRecorded", "epoch", "prepared", "MEASURED_DB_RECEIPT_INTERVAL"),
    ("answerPreparedToCommitCommandCreated", "prepared", "created", "CONDITIONAL_GO_DB_CLOCK"),
    ("commitCommandCreatedToInboxAccepted", "created", "accepted", "CONDITIONAL_GO_DB_CLOCK"),
    ("inboxAcceptedToGeneratingRecorded", "accepted", "generating", "MEASURED_DB_RECEIPT_INTERVAL"),
    ("generatingToReadyRecorded", "generating", "ready", "MEASURED_DB_RECEIPT_INTERVAL"),
    ("readyToCommitIntentRecorded", "ready", "intent", "MEASURED_DB_RECEIPT_INTERVAL"),
    ("commitIntentToInstalledRecorded", "intent", "installed", "MEASURED_DB_RECEIPT_INTERVAL"),
    ("installedToChromeCorrelatedAV", "installed", "chrome", "CONDITIONAL_DB_GO_CHROME_RECORDING_CLOCK"),
)
IDENTITY_SQL = {"commandId": "command_id", "sessionId": "session_id", "runEpoch": "run_epoch",
                "narrationId": "narration_id", "segmentId": "segment_id", "lane": "lane",
                "attemptId": "attempt_id", "utteranceId": "utterance_id", "generationId": "generation_id",
                "timelineEpoch": "timeline_epoch", "workerEpoch": "worker_epoch",
                "workerGenerationId": "worker_generation_id"}


class Evidence:
    def __init__(self, sql, session_id, run_epoch):
        self.sql, self.scope = sql, (session_id, run_epoch)

    def scoped(self, receipt):
        if receipt is not None:
            require((receipt["session_id"], receipt["run_epoch"]) == self.scope, "FOREIGN_RECEIPT_SCOPE")
        return receipt

    def observed(self, receipt):
        """Bind actual A ACK to its real SQL receipt; never use final updated_at."""
        if receipt is None:
            return None
        self.scoped(receipt)
        found = [o for o in self.sql["observations"]
                 if o["command_id"] == receipt["command_id"] and o["operation"] == receipt["evidence_ref"]]
        require(len(found) == 1, "OBSERVATION_BINDING_MISSING_OR_AMBIGUOUS")
        o = found[0]; a = o["response_json"]
        require((o["session_id"], o["run_epoch"], o["observation_hash"], a["observationHash"],
                 a["receiptSeq"], a["producerIncarnation"]) ==
                (receipt["session_id"], receipt["run_epoch"], receipt["observation_hash"],
                 receipt["observation_hash"], receipt["receipt_seq"], receipt["producer_incarnation"]),
                "OBSERVATION_RECEIPT_MISMATCH")
        return receipt

    def event(self, command_id, operation):
        found = [r for r in self.sql["receipts"] if r["command_id"] == command_id
                 and r["evidence_type"] == "timeline_journal" and r["evidence_ref"] == operation]
        require(len(found) <= 1, "AMBIGUOUS_EVENT")
        return self.observed(found[0]) if found else None

    def control(self, predicate):
        found = [r for r in self.sql["receipts"] if r["evidence_type"] == "timeline_journal" and predicate(r)]
        require(len(found) <= 1, "AMBIGUOUS_CONTROL")
        return self.observed(found[0]) if found else None

    def receipt(self, command_id, predicate):
        found = [r for r in self.sql["receipts"] if r["command_id"] == command_id and predicate(r)]
        require(len(found) <= 1, "AMBIGUOUS_RECEIPT")
        return self.scoped(found[0]) if found else None


def receipt_time(row):
    return timestamp(row["observed_at"]) if row else None


def interval(points, name, start, end, status):
    if points[start] is None or points[end] is None:
        return {"status": "NOT_VERIFIABLE", "missingAnchors": [k for k in (start, end) if points[k] is None]}
    value = points[end]-points[start]
    require(value >= 0, "NONMONOTONIC_"+name.upper())
    return {"status": status, "valueMs": value}


def turn_row(sql, turn, by_segment, by_ordinal, attempts, commits, prepared_commands, metric_rows):
    doc = turn["document_json"]; sid = turn["session_id"]
    require(turn["state"] == "COMPLETED", "ANSWER_NOT_COMPLETED")
    entry = by_segment[doc["answer"]["segmentId"]]; ident = entry["identity"]
    attempt = attempts[ident["attemptId"]]; commit = commits[ident["commandId"]]
    ev = Evidence(sql, sid, ident["runEpoch"])
    require(ident["interactionTurnId"] == turn["turn_id"] and ident["sessionId"] == sid
            and ident["narrationId"] == turn["narration_id"] and ident["lane"] == "AUDIENCE_ANSWER",
            "FOREIGN_TURN_IDENTITY")
    require(all(ident[k] == attempt[v] for k, v in IDENTITY_SQL.items()), "REFERENCE_SQL_IDENTITY_MISMATCH")
    require(attempt["status"] == "COMPLETED" and commit["play_state"] == "COMPLETED"
            and commit["attempt_id"] == ident["attemptId"] and commit["segment_id"] == ident["segmentId"]
            and commit["session_id"] == sid and commit["run_epoch"] == ident["runEpoch"], "ANSWER_NOT_COMPLETED")
    descriptor = attempt["descriptor_json"]["stagingDescriptor"]
    require(descriptor["identity"] == ident, "DESCRIPTOR_IDENTITY_MISMATCH")
    boundary_entry = by_ordinal.get(entry["ordinal"]-1)
    require(boundary_entry is not None and boundary_entry["identity"]["lane"] == "NARRATION", "BOUNDARY_SOURCE_ID_MISSING")
    bi = boundary_entry["identity"]; bc = commits[bi["commandId"]]
    require(bi["sessionId"] == sid and bi["runEpoch"] == ident["runEpoch"]
            and bi["timelineEpoch"] < ident["timelineEpoch"] and bc["play_state"] == "COMPLETED",
            "FOREIGN_OR_INCOMPLETE_BOUNDARY")
    scoped = lambda r: r["session_id"] == sid and r["run_epoch"] == ident["runEpoch"]
    suspend = ev.control(lambda r: scoped(r) and r["evidence_ref"] == "SUSPEND_REQUESTED"
                         and r["range_sinks"].get("segmentId") == bi["segmentId"])
    epoch = ev.control(lambda r: scoped(r) and r["evidence_ref"] == "BEGIN_EPOCH_ACTIVE"
                       and r["range_sinks"].get("reason") == "ANSWER"
                       and r["range_sinks"].get("newEpoch") == ident["timelineEpoch"])
    prepared = prepared_commands[turn["turn_id"]]
    require((prepared["sessionId"], prepared["runEpoch"], prepared["narrationId"], prepared["commandType"]) ==
            (sid, ident["runEpoch"], ident["narrationId"], "START_AUDIENCE_ANSWER"), "FOREIGN_PREPARED_COMMAND")
    cid = ident["commandId"]
    ready = ev.event(cid, "SEGMENT_READY"); intent = ev.event(cid, "COMMIT_INTENT")
    installed = ev.event(cid, "COMMIT_INSTALLED")
    if ready:
        require(ready["range_sinks"]["attemptId"] == ident["attemptId"], "FOREIGN_READY_BUSINESS_ATTEMPT")
    created = None
    if intent:
        # Read only these public timing/identity fields; never serialize payload.
        original = intent["range_sinks"]["commit"]["command"]
        require(original["commandId"] == cid and original["commandType"] == "COMMIT_SEGMENT", "FOREIGN_CREATED_COMMAND")
        created = timestamp(original["createdAt"])
    points = {"selected": timestamp(doc["selectedAt"]), "suspend": receipt_time(suspend),
              "boundary": receipt_time(ev.event(bi["commandId"], "SEGMENT_COMPLETED")),
              "epoch": receipt_time(epoch), "prepared": receipt_time(ev.event(prepared["commandId"], "ANSWER_PREPARED")),
              "created": created,
              "accepted": receipt_time(ev.receipt(cid, lambda r: r["evidence_type"] == "inbox_acceptance")),
              "generating": receipt_time(ev.receipt(cid, lambda r: r["state"] == "generating")),
              "ready": receipt_time(ready), "intent": receipt_time(intent), "installed": receipt_time(installed), "chrome": None}
    metric = metric_rows.get(turn["turn_id"], {}).get("selectedToChromeEstimate", {})
    if metric.get("status") == "CONDITIONAL_CLOCK_ESTIMATE":
        require(timestamp(metric["selectedAt"]) == points["selected"] and metric["ordinal"] == entry["ordinal"]
                and metric["anchorSequence"] == 0 and metric["anchorField"] in ("presentationTime", "at"), "FOREIGN_CHROME_ESTIMATE")
        estimate = number(metric["selectedToBothCorrelatedAVMs"])
        require(estimate >= 0 and metric.get("audienceAudible") is False, "INVALID_CHROME_ESTIMATE")
        points["chrome"] = points["selected"]+estimate
    phases = {name: interval(points, name, start, end, status) for name, start, end, status in PHASES}
    native = number(descriptor["resources"]["inference_elapsed_us"])
    require(native >= 0, "NEGATIVE_NATIVE_DURATION")
    reconciled = None
    if all("valueMs" in phase for phase in phases.values()):
        reconciled = abs(sum(phase["valueMs"] for phase in phases.values())-(points["chrome"]-points["selected"])) <= .001
        require(reconciled, "PHASE_RECONCILIATION_FAILED")
    return {"turnId": turn["turn_id"], "answerCommandId": cid, "answerAttemptId": ident["attemptId"],
            "boundarySegmentId": bi["segmentId"], "ordinal": entry["ordinal"], "selectedAt": doc["selectedAt"],
            "status": "ATTRIBUTED_METADATA_ONLY", "phases": phases, "phaseSumReconcilesWithin001ms": reconciled,
            "selectedToChromeCorrelatedAV": interval(points, "total", "selected", "chrome", "CONDITIONAL_CLOCK_ESTIMATE"),
            "nativeInferenceMs": native/1000,
            "nativeInferenceScope": "sum of synchronized native inference calls only; overlaps generatingToReady, not an additive phase",
            "answerPreparedTextSource": "actual nonempty Go prepared answer; no answer LLM duration inferred" if prepared.get("answerText") else "NOT_VERIFIABLE"}


def build_report(sql, refs, metrics, llm_calls=()):
    require(metrics.get("artifactSource"), "SOURCE_PIN_MISSING")
    by_segment = {r["identity"]["segmentId"]: r for r in refs}
    require(len(by_segment) == len(refs), "DUPLICATE_SEGMENT_SOURCE")
    by_ordinal = unique(refs, "ordinal"); attempts = unique(sql["attempts"], "attempt_id")
    commits = unique(sql["commits"], "command_id")
    pc = unique(sql["answerPreparedCommands"], "interactionTurnId")
    mr = unique(metrics["questionsAndResume"]["rows"], "turnId")
    unique(sql["turns"], "turn_id")
    rows = []
    for turn in sorted(sql["turns"], key=lambda t: t["document_json"].get("selectedAt", "")):
        try:
            rows.append(turn_row(sql, turn, by_segment, by_ordinal, attempts, commits, pc, mr))
        except (LatencyEvidenceError, KeyError, TypeError) as exc:
            rows.append({"turnId": turn.get("turn_id"), "status": "EVIDENCE_REJECTED",
                         "code": str(exc) if isinstance(exc, LatencyEvidenceError) else "MISSING_OR_INVALID_SCHEMA"})
    accepted = [r for r in rows if r["status"] == "ATTRIBUTED_METADATA_ONLY"]
    summaries = {}
    for name, _, _, status in PHASES:
        summaries[name] = {"evidenceClass": status, **quantiles(r["phases"][name]["valueMs"] for r in accepted
                                if "valueMs" in r["phases"][name])}
    llm_durations = []
    for x in llm_calls:
        if x.get("scope") == "REAL_BOUND_LLM_CALL_OBSERVER" and x.get("role") == "bridge_choice" and x.get("status") == "COMPLETED":
            duration = number(x["durationMs"]); require(duration >= 0, "NEGATIVE_LLM_DURATION")
            llm_durations.append(duration)
    return {"scope": "CLOSED_METADATA_TIMING_COMPONENT_ONLY", "artifactSource": metrics["artifactSource"],
            "originalObserverStatus": metrics["originalObserverStatus"], "originalAuditStatus": metrics["originalAuditStatus"],
            "originalOverallAcceptance": metrics["overallAcceptance"],
            "unknownAttempts": [{"attemptId": a["attempt_id"], "state": a["status"]} for a in sql["attempts"] if a["status"] == "UNKNOWN"],
            "rows": rows, "phaseSummary": summaries,
            "selectedToChromeCorrelatedAV": quantiles(r["selectedToChromeCorrelatedAV"]["valueMs"] for r in accepted
                                                     if "valueMs" in r["selectedToChromeCorrelatedAV"]),
            "nativeInferenceOverlapping": quantiles(r["nativeInferenceMs"] for r in accepted),
            "bridgeLLMDurationUnassigned": {**quantiles(llm_durations), "scope": "bridge only, after answers; no command/turn/absolute-time anchor; never assigned by array order"},
            "missingAnchors": {"selectedToPhysicalLastNarrationSample": "NOT_VERIFIABLE: receipt completion is post-consumption DB insertion, not last physical sample",
                               "perTurnAnswerLLM": "NOT_VERIFIABLE: no success per-turn LLM timing; nonempty prepared factual answers bypass LLM",
                               "ttsEmbeddingEncodeTransferDecodeOverlaySplit": "NOT_VERIFIABLE: no per-attempt start/end anchors; generating-to-READY bundles these with native inference",
                               "workerToHostClock": "NOT_VERIFIABLE: native elapsed duration only, no calibrated clock mapping"},
            "clockLimits": ["DB intervals are receipt insertion timestamps, not device or exact effect timestamps; DB wall-clock jumps not independently checked",
                            "Go created/selected UTC to DB clock assumes same host clock; no independent NTP-jump audit",
                            "Chrome estimate is inherited from hash-pinned hour_metrics with same-host UTC/timeOrigin and recording-marker mapping assumptions; audio-device clock uncalibrated"],
            "busyCommentSLA": "NOT_VERIFIABLE", "audienceAudible": False, "humanNaturalness": "NOT_TESTED"}


def pairs(items):
    out = {}
    for key, value in items:
        require(key not in out, "DUPLICATE_JSON_KEY")
        out[key] = value
    return out


def read_input(path, jsonl=False):
    path = Path(path); limit = 128*1024*1024
    before = path.stat()
    require(before.st_size <= limit, "INPUT_SIZE_LIMIT")
    raw = path.read_bytes()
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as stream:
            data = stream.read(limit+1)
    else:
        data = raw
    require(len(data) <= limit, "INPUT_SIZE_LIMIT")
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "INPUT_CHANGED_DURING_READ")
    parse = lambda b: json.loads(b, object_pairs_hook=pairs,
                                parse_constant=lambda _: (_ for _ in ()).throw(LatencyEvidenceError("NONFINITE_JSON")))
    value = [parse(line) for line in data.splitlines() if line.strip()] if jsonl else parse(data)
    return value, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                   "decodedSHA256": hashlib.sha256(data).hexdigest()}


def validate_pinned_inputs(metrics, manifest):
    for position, basename in ((0, "sql-proof.json"), (1, "refs.json")):
        pinned = [x for x in metrics.get("inputManifest", []) if Path(x["path"]).name == basename]
        require(len(pinned) == 1 and pinned[0]["sha256"] == manifest[position]["decodedSHA256"], "METRICS_INPUT_HASH_MISMATCH")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("sql", "refs", "metrics", "llm", "output"):
        p.add_argument("--"+name, required=True)
    args = p.parse_args(); values = []; manifest = []
    for name in ("sql", "refs", "metrics", "llm"):
        value, entry = read_input(getattr(args, name), jsonl=name == "llm")
        values.append(value); manifest.append(entry)
    # The selected-to-Chrome estimates must belong to these exact SQL/source
    # inputs. Accept original JSON or a byte-equivalent decompressed backup.
    validate_pinned_inputs(values[2], manifest)
    result = build_report(*values); result["inputManifest"] = manifest
    result["toolSHA256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"output": args.output, "attributedTurns": sum(r["status"] == "ATTRIBUTED_METADATA_ONLY" for r in result["rows"]),
                      "rejectedTurns": sum(r["status"] == "EVIDENCE_REJECTED" for r in result["rows"]),
                      "originalObserverStatus": result["originalObserverStatus"], "busyCommentSLA": result["busyCommentSLA"]}))


if __name__ == "__main__":
    main()
