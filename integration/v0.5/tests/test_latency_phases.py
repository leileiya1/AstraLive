"""Synthetic evidence rejection tests only; no live/GPU performance claim."""
import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1]/"latency_phases.py"
spec = importlib.util.spec_from_file_location("latency_phases", path)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def fixture():
    def ts(ms):
        return "2025-01-01T00:00:%02d.%03dZ" % (ms//1000, ms % 1000)
    identity = {"sessionId": "s", "runEpoch": 1, "timelineEpoch": 2, "narrationId": "n",
                "segmentId": "answer", "lane": "AUDIENCE_ANSWER", "commandId": "answer-cmd",
                "attemptId": "business-attempt", "utteranceId": "u", "generationId": 9,
                "workerEpoch": "worker-epoch", "workerGenerationId": 12, "interactionTurnId": "t",
                "stageId": "stage", "traceId": "trace", "workerRef": "worker", "beatId": "beat"}
    before = {**identity, "segmentId": "before", "lane": "NARRATION", "commandId": "before-cmd",
              "timelineEpoch": 1, "interactionTurnId": None}
    refs = [{"ordinal": 1, "identity": before}, {"ordinal": 2, "identity": identity}]
    attempt = {value: identity[key] for key, value in m.IDENTITY_SQL.items()}
    attempt.update(status="COMPLETED", descriptor_json={"stagingDescriptor": {
        "identity": copy.deepcopy(identity), "resources": {"inference_elapsed_us": 150000}}})
    sql = {"attempts": [attempt, {"attempt_id": "tail", "status": "UNKNOWN"}],
           "commits": [{"command_id": "answer-cmd", "attempt_id": "business-attempt", "play_state": "COMPLETED",
                        "segment_id": "answer", "session_id": "s", "run_epoch": 1},
                       {"command_id": "before-cmd", "play_state": "COMPLETED"}],
           "turns": [{"turn_id": "t", "session_id": "s", "narration_id": "n", "state": "COMPLETED",
                      "document_json": {"selectedAt": ts(0), "answer": {"segmentId": "answer"}}}],
           "answerPreparedCommands": [{"commandId": "prepared-cmd", "interactionTurnId": "t", "sessionId": "s",
               "runEpoch": 1, "narrationId": "n", "commandType": "START_AUDIENCE_ANSWER", "answerText": "事实。"}],
           "receipts": [], "observations": []}
    def receipt(cid, op, at, proof=None, state="ready", evidence="timeline_journal"):
        seq = len(sql["receipts"])+1
        row = {"command_id": cid, "evidence_ref": op, "evidence_type": evidence, "state": state,
               "session_id": "s", "run_epoch": 1, "range_sinks": proof or {}, "observed_at": ts(at),
               "observation_hash": "hash-"+str(seq), "receipt_seq": seq, "producer_incarnation": "runtime",
               "attempt_id": "backend-execution-attempt-is-distinct"}
        sql["receipts"].append(row)
        if evidence == "timeline_journal":
            sql["observations"].append({"command_id": cid, "operation": op, "session_id": "s", "run_epoch": 1,
                "observation_hash": row["observation_hash"], "response_json": {"observationHash": row["observation_hash"],
                "receiptSeq": seq, "producerIncarnation": "runtime"}})
    receipt("suspend-cmd", "SUSPEND_REQUESTED", 100, {"segmentId": "before"})
    receipt("before-cmd", "SEGMENT_COMPLETED", 600)
    receipt("epoch-cmd", "BEGIN_EPOCH_ACTIVE", 700, {"newEpoch": 2, "reason": "ANSWER"})
    receipt("prepared-cmd", "ANSWER_PREPARED", 800)
    receipt("answer-cmd", "INBOX", 910, state="accepted", evidence="inbox_acceptance")
    receipt("answer-cmd", "START", 920, state="generating", evidence="execution_started")
    receipt("answer-cmd", "SEGMENT_READY", 1200, {"attemptId": "business-attempt"})
    receipt("answer-cmd", "COMMIT_INTENT", 1210, {"commit": {"command": {
        "commandId": "answer-cmd", "commandType": "COMMIT_SEGMENT", "createdAt": ts(900), "payload": {"not_exported": "private"}}}})
    receipt("answer-cmd", "COMMIT_INSTALLED", 1220)
    metrics = {"artifactSource": "source", "originalObserverStatus": "FAIL", "originalAuditStatus": "FAIL",
               "overallAcceptance": "FAIL", "questionsAndResume": {"rows": [{"turnId": "t", "selectedToChromeEstimate": {
                   "status": "CONDITIONAL_CLOCK_ESTIMATE", "selectedAt": ts(0), "ordinal": 2, "anchorSequence": 0,
                   "anchorField": "presentationTime", "selectedToBothCorrelatedAVMs": 1400, "audienceAudible": False}}]}}
    return sql, refs, metrics, []


class LatencyRejectionTests(unittest.TestCase):
    def result(self, data):
        return m.build_report(*data)

    def test_closed_timestamps_reconcile_without_adding_nested_gpu_duration(self):
        r = self.result(fixture()); row = r["rows"][0]
        self.assertEqual(row["status"], "ATTRIBUTED_METADATA_ONLY")
        self.assertEqual(sum(p["valueMs"] for p in row["phases"].values()), 1400)
        self.assertEqual(row["nativeInferenceMs"], 150)
        self.assertEqual(r["originalObserverStatus"], "FAIL")
        self.assertEqual(r["originalOverallAcceptance"], "FAIL")
        self.assertEqual(r["unknownAttempts"], [{"attemptId": "tail", "state": "UNKNOWN"}])
        self.assertEqual(r["busyCommentSLA"], "NOT_VERIFIABLE")
        self.assertFalse(r["audienceAudible"])
        self.assertNotIn("not_exported", str(r))

    def test_receipt_hash_cannot_be_substituted_by_similar_final_state(self):
        a = fixture(); a[0]["observations"][0]["response_json"]["observationHash"] = "forged"
        self.assertEqual(self.result(a)["rows"][0]["code"], "OBSERVATION_RECEIPT_MISMATCH")

    def test_foreign_producer_and_receipt_sequence_rejected(self):
        for field, value in (("producerIncarnation", "other"), ("receiptSeq", 999)):
            a = fixture(); a[0]["observations"][0]["response_json"][field] = value
            self.assertEqual(self.result(a)["rows"][0]["status"], "EVIDENCE_REJECTED")

    def test_consistently_foreign_receipt_and_ack_cannot_escape_run_scope(self):
        a = fixture()
        next(r for r in a[0]["receipts"] if r["evidence_ref"] == "SEGMENT_READY")["run_epoch"] = 8
        next(o for o in a[0]["observations"] if o["operation"] == "SEGMENT_READY")["run_epoch"] = 8
        self.assertEqual(self.result(a)["rows"][0]["code"], "FOREIGN_RECEIPT_SCOPE")

    def test_ready_receipt_business_attempt_must_match_reference(self):
        a = fixture(); next(r for r in a[0]["receipts"] if r["evidence_ref"] == "SEGMENT_READY")["range_sinks"]["attemptId"] = "foreign"
        self.assertEqual(self.result(a)["rows"][0]["code"], "FOREIGN_READY_BUSINESS_ATTEMPT")

    def test_business_attempt_not_confused_with_inbox_attempt(self):
        a = fixture(); self.assertEqual(self.result(a)["rows"][0]["answerAttemptId"], "business-attempt")
        a[1][1]["identity"]["attemptId"] = "backend-execution-attempt-is-distinct"
        self.assertEqual(self.result(a)["rows"][0]["status"], "EVIDENCE_REJECTED")

    def test_missing_suspend_anchor_is_unknown_not_zero_or_nearest_time(self):
        a = fixture(); a[0]["receipts"] = a[0]["receipts"][1:]
        row = self.result(a)["rows"][0]
        self.assertEqual(row["phases"]["selectedToSuspendRecorded"]["status"], "NOT_VERIFIABLE")
        self.assertNotIn("valueMs", row["phases"]["selectedToSuspendRecorded"])
        self.assertEqual(row["phases"]["generatingToReadyRecorded"]["valueMs"], 280)

    def test_foreign_chrome_selection_or_marker_rejected(self):
        for field, value in (("selectedAt", "2025-01-01T00:00:01Z"), ("ordinal", 999), ("anchorSequence", 4)):
            a = fixture(); a[2]["questionsAndResume"]["rows"][0]["selectedToChromeEstimate"][field] = value
            self.assertEqual(self.result(a)["rows"][0]["code"], "FOREIGN_CHROME_ESTIMATE")

    def test_unmatched_or_censored_chrome_not_promoted(self):
        for state in ("AMBIGUOUS", "CENSORED", "UNRESOLVED"):
            a = fixture(); a[2]["questionsAndResume"]["rows"][0]["selectedToChromeEstimate"]["status"] = state
            r = self.result(a)
            self.assertEqual(r["rows"][0]["phases"]["installedToChromeCorrelatedAV"]["status"], "NOT_VERIFIABLE")
            self.assertEqual(r["selectedToChromeCorrelatedAV"]["count"], 0)

    def test_bridge_durations_never_assigned_to_answer_by_array_position(self):
        a = fixture(); a[3].append({"scope": "REAL_BOUND_LLM_CALL_OBSERVER", "role": "bridge_choice", "status": "COMPLETED", "durationMs": 8000})
        r = self.result(a)
        self.assertEqual(r["bridgeLLMDurationUnassigned"]["P50"], 8000)
        self.assertNotIn("answerLLMMs", r["rows"][0])
        self.assertEqual(r["selectedToChromeCorrelatedAV"]["P50"], 1400)

    def test_duplicate_control_or_clock_regression_rejected(self):
        a = fixture(); a[0]["receipts"].append(copy.deepcopy(a[0]["receipts"][0]))
        self.assertEqual(self.result(a)["rows"][0]["code"], "AMBIGUOUS_CONTROL")
        a = fixture(); a[0]["receipts"][1]["observed_at"] = "2025-01-01T00:00:00.050Z"
        self.assertTrue(self.result(a)["rows"][0]["code"].startswith("NONMONOTONIC_"))

    def test_final_updated_at_is_never_used_as_missing_ready_time(self):
        a = fixture(); a[0]["attempts"][0]["updated_at"] = "2025-01-01T00:00:01.200Z"
        a[0]["receipts"] = [r for r in a[0]["receipts"] if r["evidence_ref"] != "SEGMENT_READY"]
        row = self.result(a)["rows"][0]
        self.assertEqual(row["phases"]["generatingToReadyRecorded"]["status"], "NOT_VERIFIABLE")

    def test_naive_or_nonfinite_time_cannot_make_latency(self):
        with self.assertRaises(m.LatencyEvidenceError): m.timestamp("2025-01-01T00:00:00")
        with self.assertRaises(m.LatencyEvidenceError): m.quantiles([float("nan")])

    def test_actual_pg_and_go_fractional_second_lengths_are_supported(self):
        base = m.timestamp("2026-10-14T20:38:32+08:00")
        self.assertAlmostEqual(m.timestamp("2026-10-14T20:38:32.84645+08:00")-base, 846.45, places=3)
        self.assertAlmostEqual(m.timestamp("2026-10-14T12:38:32.846450123Z")-base, 846.450123, places=3)

    def test_estimate_metrics_cannot_be_reused_for_other_raw_sql(self):
        metrics = {"inputManifest": [{"path": "/original/sql-proof.json", "sha256": "sql"},
                                     {"path": "/original/refs.json", "sha256": "ref"}]}
        manifest = [{"decodedSHA256": "sql"}, {"decodedSHA256": "ref"}]
        m.validate_pinned_inputs(metrics, manifest)
        manifest[0]["decodedSHA256"] = "other-run"
        with self.assertRaisesRegex(m.LatencyEvidenceError, "METRICS_INPUT_HASH_MISMATCH"):
            m.validate_pinned_inputs(metrics, manifest)


if __name__ == "__main__":
    unittest.main()
