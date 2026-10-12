"""CCR-BC-002 staging-contract-1 strict DTO/hash contract; no transport/native effects.

All staging integers are JSON safe. Legacy 1.1 and A Timeline int63 typed
paths remain in their original implementations; this module never relaxes them.
"""
import copy
import hashlib
import json
import math
import re

REVISION = "staging-contract-1"
CAPABILITY = "immutable_segment_staging_v1"
MAX_INTEGER = 9007199254740991
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
IDENTITY_FIELDS = ("sessionId", "runEpoch", "timelineEpoch", "generationId", "narrationId", "beatId", "segmentId", "interactionTurnId", "utteranceId", "commandId", "traceId", "attemptId", "stageId", "lane", "workerRef", "workerEpoch", "workerGenerationId")

class ContractError(ValueError):
    pass

def integer(minimum=0, maximum=MAX_INTEGER):
    return {"type": "integer", "minimum": minimum, "maximum": maximum}
def string():
    return {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"^[^\x00-\x1f\x7f]+$"}
def enum(*items):
    return {"enum": list(items)}
def const(value):
    return {"const": value}
def ref(name):
    return {"$ref": "#/$defs/" + name}
def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
def array(items, minimum=0, maximum=256, unique=False):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum, "uniqueItems": unique}
def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}
HASH = {"type": "string", "pattern": HASH_PATTERN}
BOOL = {"type": "boolean"}
ID = string()
IDENTITY = obj({k: (integer(1) if k.endswith("Epoch") and k != "workerEpoch" or k in ("generationId", "workerGenerationId") else nullable(ID) if k == "interactionTurnId" else enum("NARRATION", "AUDIENCE_ANSWER", "RESUME_BRIDGE") if k == "lane" else ID) for k in IDENTITY_FIELDS})
SOURCE_FORMAT = obj({"sample_rate": const(16000), "channels": const(1), "pcm_format": const("s16le"), "fps_num": const(25), "fps_den": const(1), "width": const(512), "height": const(512), "native_format": const("rgb24"), "codec": const("h264")})
PROFILES = {}
for name, samples, rgb, artifact, host in (("staging-short-1", 30720, 48, 96, 256), ("staging-segment-8s-1", 128000, 160, 192, 512)):
    PROFILES[name] = {"limits_revision": name, "max_source_samples": samples, "worker_rgb_bytes": rgb*1048576, "worker_pose_bytes": 8*1048576, "runtime_artifact_bytes": artifact*1048576, "runtime_transient_bytes": 24*1048576, "worker_attempt_bytes": host*1048576, "gpu_incremental_allocated_bytes": 512*1048576, "audio_queue_samples": 32000, "native_queue_frames": 24, "network_window_frames": 4, "lease_ms_max": 60000}
LIMITS = {"oneOf": [obj({k: const(v) for k, v in value.items()}) for value in PROFILES.values()]}
PROVENANCE = obj({"workerRef": ID, "workerEpoch": ID, "model_source_revision": ID, "weights_manifest_sha256": HASH, "avatar_sha256": HASH, "input_asset_sha256": HASH, "cache_id": ID, "preprocessing_version": ID, "capability": const(CAPABILITY), "source": enum("GPU_INFERENCE", "CPU_SIMULATION")})
RESOURCES = obj({k: nullable(integer()) if k.startswith("gpu_") else integer() for k in ("worker_rgb_peak_bytes", "worker_attempt_peak_bytes", "gpu_baseline_allocated_bytes", "gpu_incremental_allocated_peak_bytes", "gpu_incremental_reserved_peak_bytes", "inference_elapsed_us")})
DESCRIPTOR = obj({"descriptor_revision": const("staging-descriptor-1"), "identity": ref("identity"), "request_fingerprint": HASH, "source_format": ref("source_format"), "original_samples": integer(1), "pad_samples": integer(0,639), "source_samples": integer(640,128000), "pcm_sha256": HASH, "frame_count": integer(1,200), "first_sequence": const(0), "last_sequence": integer(0,199), "first_pts_us": const(0), "last_pts_us": integer(), "video_bytes": integer(1), "video_stream_sha256": HASH, "native_rgb_stream_sha256": HASH, "eof": const(True), "final_marker": const(True), "native_final": const(True), "limits": ref("limits"), "provenance": ref("provenance"), "resources": ref("resources")})
SINK = obj({"sinkId": ID, "incarnation": ID})
INSTALLED = obj({"operation": const("COMMIT_INSTALLED"), "producerIncarnation":ID, "sessionId": ID, "runEpoch": integer(1), "timelineEpoch": integer(1), "commandId": ID, "segmentId": ID, "attemptId": ID, "generationId": integer(1), "receiptSeq": integer(1), "observationHash": HASH, "timelineRevision": integer(1)})
OUTPUT = obj({"sampleRate": integer(1), "startSample": integer(), "endSample": integer(1), "sourceRate": const(16000), "sourceSamples": integer(640,128000), "ratioNumerator": integer(1), "ratioDenominator": integer(1)})
B_INSTALLED = obj({"receipt_ref": ID, "revision": integer(1), "installed": const(True)})
COMMIT = obj({"descriptor_sha256": HASH, "a_installed_ref": ref("installed_reference"), "b_installed_ref": B_INSTALLED, "output": ref("output"), "required_sinks": array(ref("sink"),1,16,True), "optional_sinks": array(ref("sink"),0,16,True)})
SINK_RANGE = obj({"sinkId": ID, "incarnation": ID, "evidenceRef": ID, "localRevision": integer(1), "startSample": integer(), "audioEndSample": integer(), "videoEndSample": integer(), "evidenceType": const("sink_consumed")})
POSE = obj({"pose_ack_id": ID, "descriptor_sha256": HASH, "commit_proof_fingerprint": HASH, "latest_consumed_sequence": integer(-1,199), "source_end_sample": integer(), "output_end_sample": integer(), "required_sink_receipts": array(ref("sink_range"),1,16,True)})
CONTROL = {"control_id": ID, "reason": enum("STOP", "FORCE", "EXPIRED", "STALE", "FAILED")}
COMMON = {"contract_revision": const(REVISION), "session_id": ID, "worker_epoch": ID, "identity": ref("identity")}
MESSAGES = {}
def message(name, fields):
    MESSAGES[name] = obj({"type": const(name), **COMMON, **fields})
GRANT = obj({"sessionId": ID, "runEpoch": integer(1), "leaseToken": integer(1), "barrierSeq": integer(), "commandSeq": integer(1), "remainingMs": integer(1)})
LEASE_FIELDS = {"a_grant": GRANT, "a_rtt_ms": integer(), "grant_age_ms": integer(), "worker_rtt_ms": integer(), "safety_ms": integer(100,1000)}
message("StageBegin", {"command_request_fingerprint": HASH, **LEASE_FIELDS, "request_fingerprint": HASH, "cache_id": ID, "pcm_sha256": HASH, "original_samples": integer(1), "pad_samples": integer(0,639), "source_samples": integer(640,128000), "source_format": ref("source_format"), "lease_ms": integer(1,60000), "limits_revision": enum(*PROFILES)})
message("StageBegun", {"request_fingerprint": HASH, "audio_credit_samples": integer(0,32000), "limits": ref("limits"), "pose_history_sha256": HASH})
message("StageAudio", {"chunk_sequence": integer(), "first_sample_index": integer(), "sample_count": integer(1,32000), "final_chunk": BOOL, "chunk_sha256": HASH})
message("StageAudioAccepted", {"chunk_sequence": integer(), "chunk_sha256": HASH, "accepted": const(True), "audio_credit_samples": integer(0,32000)})
VIDEO = {"frame_sequence": integer(0,199), "pts_us": integer(), "duration_us": const(40000), "sample_start": integer(), "sample_end": integer(1), "codec": const("h264"), "width": const(512), "height": const(512), "keyframe": BOOL, "payload_sha256": HASH, "native_rgb_sha256": HASH, "provenance": ref("provenance")}
message("StageVideo", VIDEO)
RECEIVED = {"frame_sequence": integer(0,199), "payload_sha256": HASH, "native_rgb_sha256": HASH, "storage_receipt_id": ID}
message("StageReceived", RECEIVED);message("StageReceivedAck", RECEIVED)
message("StageProduced", {"descriptor": ref("descriptor"), "descriptor_sha256": HASH})
message("StageCommit", {"commit_proof": ref("commit_proof"), "commit_proof_fingerprint": HASH})
message("StageCommitAck", {"descriptor_sha256": HASH, "commit_proof_fingerprint": HASH, "state": const("COMMIT_ARMED")})
message("StagePoseConsumed", {"pose_proof": ref("pose_proof"), "pose_proof_fingerprint": HASH})
message("StagePoseConsumedAck", {"pose_ack_id": ID, "pose_proof_fingerprint": HASH, "latest_consumed_sequence": integer(-1,199), "pose_history_sha256": HASH})
message("StageCancel", CONTROL)
message("StageFenced", {"control_id": ID, "publication_fenced": const(True), "latest_consumed_sequence": integer(-1,199), "pose_history_sha256": HASH})
RELEASE = {"control_id": ID, "reason": enum("COMPLETE", "CANCELLED"), "descriptor_sha256": nullable(HASH), "commit_proof_fingerprint": nullable(HASH), "pose_proof_fingerprint": nullable(HASH), "latest_consumed_sequence": integer(-1,199)}
message("StageRelease", RELEASE)
message("StageReleased", {"control_id": ID, "native_safe_boundary": const(True), "retained_artifact_bytes": const(0), "latest_consumed_sequence": integer(-1,199), "pose_history_sha256": HASH, "terminal_disposition": enum("PROVEN_COMPLETE", "PROVEN_CANCELLED", "UNKNOWN"), "reusable": BOOL})
message("StageStatus", {"nonce": ID})
message("StageStatusResult", {"nonce": ID, "audio_credit_samples":integer(0,32000), "native_queue_frames":integer(0,24), "network_inflight_frames":integer(0,4), "state": enum("STAGING","PRODUCED","COMMIT_ARMED","RELEASED","FENCED","RETIRED"), "descriptor_sha256": nullable(HASH), "received_sequence": integer(-1,199), "latest_consumed_sequence": integer(-1,199), "retained_artifact_bytes": integer(), "lease_age_ms": integer(), "publication_fenced": BOOL, "native_safe_boundary": BOOL, "terminal_disposition": nullable(enum("PROVEN_COMPLETE","PROVEN_CANCELLED","UNKNOWN")), "reusable": BOOL})
message("StageError", {"code": enum("STAGING_UNSUPPORTED","STAGING_IDENTITY_MISMATCH","STAGING_GENERATION_COLLISION","STAGING_CONFLICT","STAGING_SEQUENCE_GAP","STAGING_BUDGET_EXCEEDED","STAGING_LEASE_EXPIRED","STAGING_COMMIT_UNPROVEN","STAGING_POSE_UNPROVEN","STAGING_RETIRED","STAGING_CLEANUP_PENDING"), "operation_id": nullable(ID), "publication_fenced": BOOL, "state": enum("STAGING","PRODUCED","COMMIT_ARMED","RELEASED","FENCED","RETIRED")})
message("StageRenew", {"renewal_sequence": integer(1), "lease_ms": integer(1,10000), **LEASE_FIELDS, "renewal_fingerprint": HASH})
message("StageRenewAck", {"renewal_sequence": integer(1), "renewal_fingerprint": HASH, "lease_remaining_ms": integer(0,10000), "total_age_ms": integer(0,60000)})
MESSAGES["Auth"] = obj({"type": const("Auth"), "protocol_version": const(1), "internal_version": const("1.2"), "session_id": ID, "token": {"type":"string","minLength":32,"maxLength":512}, "requested_capabilities": const([CAPABILITY]), "requested_limits_revision": enum(*PROFILES)})
MESSAGES["GPU_WORKER_READY"] = obj({"type":const("GPU_WORKER_READY"),"status":const("GPU_WORKER_READY"),"contract_revision":const(REVISION),"internal_version":const("1.2"),"session_id":ID,"worker_epoch":ID,"cache_id":ID,"input_asset_sha256":HASH,"model_revision":ID,"model_load_count":integer(1),"codec":const("h264"),"av_version":ID,"torch_version":ID,"weights_manifest_sha256":HASH,"simulation":BOOL,"selected_capabilities":const([CAPABILITY]),"highest_generation_id":integer(),"selected_limits":ref("limits"),"profile_gate_ref":nullable(HASH)})
HEALTH_COMMON={"contract_revision":const(REVISION),"session_id":ID,"worker_epoch":ID,"nonce":ID}
MESSAGES["StageHealth"]=obj({"type":const("StageHealth"),**HEALTH_COMMON})
MESSAGES["StageHealthAck"]=obj({"type":const("StageHealthAck"),**HEALTH_COMMON,"audio_credit_samples":integer(0,32000),"native_queue_frames":integer(0,24),"network_inflight_frames":integer(0,4)})
DEFS = {"captured_settings":obj({"soulxStagingEnabled":BOOL,"soulxStagingLimitsRevision":nullable(enum(*PROFILES)),"soulxStagingShortGateSHA256":nullable(HASH)}), "identity": IDENTITY, "source_format": SOURCE_FORMAT, "limits": LIMITS, "provenance": PROVENANCE, "resources": RESOURCES, "descriptor": DESCRIPTOR, "sink": SINK, "installed_reference": INSTALLED, "output": OUTPUT, "commit_proof": COMMIT, "sink_range": SINK_RANGE, "pose_proof": POSE, **MESSAGES}
SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:astralive:staging-contract-1", "oneOf": [ref(name) for name in MESSAGES], "$defs": DEFS}

def canonical_bytes(value):
    def check(v):
        if isinstance(v, float): raise ContractError("floating point forbidden")
        if type(v) is int and abs(v)>MAX_INTEGER: raise ContractError("unsafe integer")
        if isinstance(v, str):
            try: v.encode("utf-8", "strict")
            except UnicodeError as e: raise ContractError("invalid Unicode") from e
        elif isinstance(v, dict):
            if any(type(k) is not str for k in v): raise ContractError("nonstring key")
            for k,x in v.items(): check(k);check(x)
        elif isinstance(v, list):
            for x in v:check(x)
        elif v is not None and type(v) not in (int,bool): raise ContractError("nonJSON value")
    check(value)
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
def digest(value):
    return "sha256:"+hashlib.sha256(canonical_bytes(value)).hexdigest()
def bytes_digest(value):
    return "sha256:"+hashlib.sha256(value).hexdigest()
def decode_header(raw):
    if len(raw)>16384:raise ContractError("header budget exceeded")
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ContractError("duplicate key")
            out[k]=v
        return out
    try: value=json.loads(raw.decode("utf-8","strict"),object_pairs_hook=pairs)
    except (UnicodeError,json.JSONDecodeError) as e:raise ContractError("invalid JSON header") from e
    canonical_bytes(value)
    if not isinstance(value,dict):raise ContractError("header must be object")
    return value

def _validate(value,schema,path="$"):
    if "$ref" in schema:return _validate(value,DEFS[schema["$ref"].split("/")[-1]],path)
    for mode in ("oneOf","anyOf"):
        if mode in schema:
            valid=0
            for alternative in schema[mode]:
                try:_validate(value,alternative,path);valid+=1
                except ContractError:pass
            if valid==0 or mode=="oneOf" and valid!=1:raise ContractError(path+": invalid alternative")
            return
    if "const" in schema and (type(value) is not type(schema["const"]) or value!=schema["const"]):raise ContractError(path+": invalid constant")
    if "enum" in schema and not any(type(value) is type(x) and value==x for x in schema["enum"]):raise ContractError(path+": invalid enum")
    kind=schema.get("type")
    if kind=="integer":
        if type(value) is not int or not schema["minimum"]<=value<=schema["maximum"]:raise ContractError(path+": invalid integer")
    elif kind=="boolean" and type(value) is not bool:raise ContractError(path+": invalid boolean")
    elif kind=="null" and value is not None:raise ContractError(path+": expected null")
    elif kind=="string":
        if type(value) is not str or not schema.get("minLength",0)<=len(value)<=schema.get("maxLength",MAX_INTEGER) or "pattern" in schema and re.fullmatch(schema["pattern"],value) is None:raise ContractError(path+": invalid string")
    elif kind=="object":
        if type(value) is not dict or set(value)!=set(schema["required"]):raise ContractError(path+": missing/unknown fields")
        for k,v in value.items():_validate(v,schema["properties"][k],path+"."+k)
    elif kind=="array":
        if type(value) is not list or not schema["minItems"]<=len(value)<=schema["maxItems"]:raise ContractError(path+": invalid array")
        if schema.get("uniqueItems") and len({canonical_bytes(x) for x in value})!=len(value):raise ContractError(path+": duplicate item")
        for i,v in enumerate(value):_validate(v,schema["items"],path+"["+str(i)+"]")

def validate_identity(identity):
    canonical_bytes(identity);_validate(identity,IDENTITY)
    if (identity["interactionTurnId"] is None)!=(identity["lane"]=="NARRATION"):raise ContractError("turn/lane mismatch")
    return identity

def profile(revision, *, short_gpu_gate=False):
    if revision not in PROFILES:raise ContractError("unknown profile")
    if revision=="staging-segment-8s-1" and not short_gpu_gate:raise ContractError("8s requires explicit short realGPU gate")
    return copy.deepcopy(PROFILES[revision])

def stage_begin_fingerprint(header):
    fields=("command_request_fingerprint","a_grant","a_rtt_ms","grant_age_ms","worker_rtt_ms","safety_ms","cache_id","pcm_sha256","original_samples","pad_samples","source_samples","source_format","lease_ms","limits_revision")
    return digest({"domain":"astralive-stage-begin-1","identity":header["identity"],"request":{k:header[k] for k in fields}})
def descriptor_hash(descriptor):
    return digest({"domain":"astralive-stage-descriptor-1","descriptor":descriptor})
def commit_fingerprint(identity,proof):
    return digest({"domain":"astralive-stage-commit-1","identity":identity,"proof":proof})
def pose_fingerprint(identity,proof):
    return digest({"domain":"astralive-stage-pose-1","identity":identity,"proof":proof})

def renewal_fingerprint(header):
    fields=("renewal_sequence","lease_ms","a_grant","a_rtt_ms","grant_age_ms","worker_rtt_ms","safety_ms")
    return digest({"domain":"astralive-stage-renew-1","identity":header["identity"],"renewal":{k:header[k] for k in fields}})

def validate_capture(settings):
    names=("soulxStagingEnabled","soulxStagingLimitsRevision","soulxStagingShortGateSHA256")
    if any(k not in settings for k in names) or type(settings[names[0]]) is not bool:raise ContractError("invalid captured staging settings")
    enabled,revision,gate=(settings[k] for k in names)
    if not enabled:
        if revision is not None or gate is not None:raise ContractError("disabled capture must be null")
    else:
        if revision not in PROFILES:raise ContractError("invalid captured profile")
        if revision=="staging-short-1" and gate is not None:raise ContractError("short gate must be null")
        if revision=="staging-segment-8s-1":_validate(gate,HASH)
    return settings

def validate_negotiation(auth,ready):
    validate_message(auth);validate_message(ready)
    if auth["session_id"]!=ready["session_id"] or auth["requested_limits_revision"]!=ready["selected_limits"]["limits_revision"]:raise ContractError("negotiation profile/session mismatch")
    if ready["selected_limits"]["limits_revision"]=="staging-short-1":
        if ready["profile_gate_ref"] is not None:raise ContractError("short profile gate must be null")
    elif ready["profile_gate_ref"] is None:raise ContractError("8s requires operator-pinned shortGPU evidence")
    return ready

def negotiation_watermark(highest):
    if type(highest) is not int or not -1<=highest<=MAX_INTEGER:raise ContractError("legacy high watermark outside staging domain")
    return max(0,highest)

def pose_prefix(commit_proof, watermark):
    out=commit_proof["output"]
    if type(watermark) is not int or not out["startSample"]<=watermark<=out["endSample"]:raise ContractError("invalid absolute watermark")
    return min(out["sourceSamples"]//640-1,(watermark-out["startSample"])*16000//(out["sampleRate"]*640)-1)

def validate_message(header,payload=b""):
    canonical_bytes(header)
    name=header.get("type") if isinstance(header,dict) else None
    if name not in MESSAGES:raise ContractError("unsupported staging message")
    _validate(header,MESSAGES[name])
    if name in ("Auth","GPU_WORKER_READY","StageHealth","StageHealthAck"):
        if payload or len(canonical_bytes(header))>16384:raise ContractError("invalid negotiation framing")
        if name=="GPU_WORKER_READY":
            if (header["profile_gate_ref"] is None)!=(header["selected_limits"]["limits_revision"]=="staging-short-1"):raise ContractError("profile/gate mismatch")
            if header["simulation"] and header["selected_limits"]["limits_revision"]!="staging-short-1":raise ContractError("simulation cannot authorize 8s profile")
        return header
    identity=validate_identity(header["identity"])
    if header["session_id"]!=identity["sessionId"] or header["worker_epoch"]!=identity["workerEpoch"]:raise ContractError("connection identity mismatch")
    if len(canonical_bytes(header))>16384 or len(payload)>2097152:raise ContractError("wire budget exceeded")
    if name not in ("StageAudio","StageVideo") and payload:raise ContractError("unexpected payload")
    if name=="StageAudio" and (len(payload)!=2*header["sample_count"] or bytes_digest(payload)!=header["chunk_sha256"]):raise ContractError("PCM integrity failure")
    if name=="StageVideo":
        seq=header["frame_sequence"]
        if not payload or bytes_digest(payload)!=header["payload_sha256"] or (header["pts_us"],header["sample_start"],header["sample_end"])!=(seq*40000,seq*640,(seq+1)*640):raise ContractError("video integrity/range failure")
    if name in ("StageBegin","StageRenew"):
        grant=header["a_grant"]
        if grant["sessionId"]!=identity["sessionId"] or grant["runEpoch"]!=identity["runEpoch"] or grant["commandSeq"]<grant["barrierSeq"] or header["lease_ms"]>min(10000,grant["remainingMs"]-header["a_rtt_ms"]-header["grant_age_ms"]-header["worker_rtt_ms"]-header["safety_ms"]):raise ContractError("grant/lease mismatch")
        if name=="StageRenew" and renewal_fingerprint(header)!=header["renewal_fingerprint"]:raise ContractError("renewal hash failure")
    if name in ("StageBegin","StageProduced"):
        d=header if name=="StageBegin" else header["descriptor"]
        limits=PROFILES[d["limits_revision"]] if name=="StageBegin" else d["limits"]
        if d["pad_samples"]!=(-d["original_samples"])%640 or d["source_samples"]!=d["original_samples"]+d["pad_samples"] or d["source_samples"]>limits["max_source_samples"]:raise ContractError("source duration/pad failure")
        if name=="StageBegin" and stage_begin_fingerprint(header)!=header["request_fingerprint"]:raise ContractError("request hash failure")
        if name=="StageProduced":
            if d["identity"]!=identity or d["frame_count"]!=d["source_samples"]//640 or d["last_sequence"]!=d["frame_count"]-1 or d["last_pts_us"]!=(d["frame_count"]-1)*40000 or descriptor_hash(d)!=header["descriptor_sha256"]:raise ContractError("descriptor integrity failure")
            if d["provenance"]["workerRef"]!=identity["workerRef"] or d["provenance"]["workerEpoch"]!=identity["workerEpoch"]:raise ContractError("provenance identity mismatch")
            resources=d["resources"]
            gpu_keys=[k for k in resources if k.startswith("gpu_")]
            if d["provenance"]["source"]=="GPU_INFERENCE" and any(resources[k] is None for k in gpu_keys):raise ContractError("real GPU metrics required")
            if d["provenance"]["source"]=="CPU_SIMULATION" and any(resources[k] is not None for k in gpu_keys):raise ContractError("simulation GPU metrics must be null")
            for observed,limit in (("worker_rgb_peak_bytes","worker_rgb_bytes"),("worker_attempt_peak_bytes","worker_attempt_bytes"),("gpu_incremental_allocated_peak_bytes","gpu_incremental_allocated_bytes")):
                if resources[observed] is not None and resources[observed]>limits[limit]:raise ContractError("resource budget exceeded")
    if name=="StageCommit":
        proof=header["commit_proof"];out=proof["output"];a=proof["a_installed_ref"]
        if commit_fingerprint(identity,proof)!=header["commit_proof_fingerprint"]:raise ContractError("commit hash failure")
        for key in ("sessionId","runEpoch","timelineEpoch","commandId","segmentId","attemptId","generationId"):
            if a[key]!=identity[key]:raise ContractError("installed identity mismatch")
        if math.gcd(out["ratioNumerator"],out["ratioDenominator"])!=1 or out["sourceSamples"]%640 or out["endSample"]-out["startSample"]!=out["sourceSamples"]*out["sampleRate"]//16000 or out["sourceSamples"]*out["sampleRate"]%16000 or out["ratioNumerator"]*16000!=out["ratioDenominator"]*out["sampleRate"]:raise ContractError("output mapping mismatch")
        if proof["b_installed_ref"]["revision"]!=a["timelineRevision"]:raise ContractError("installed revision mismatch")
        for sinks in (proof["required_sinks"],proof["optional_sinks"]):
            if any(s["incarnation"]!=a["producerIncarnation"] for s in sinks):raise ContractError("sink producer incarnation mismatch")
            if sinks!=sorted(sinks,key=lambda s:(s["sinkId"],s["incarnation"])) or len({s["sinkId"] for s in sinks})!=len(sinks):raise ContractError("sink order/identity mismatch")
        if {s["sinkId"] for s in proof["required_sinks"]}&{s["sinkId"] for s in proof["optional_sinks"]}:raise ContractError("overlapping sink roles")
    if name=="StagePoseConsumed":
        proof=header["pose_proof"]
        if pose_fingerprint(identity,proof)!=header["pose_proof_fingerprint"] or proof["source_end_sample"]!=(proof["latest_consumed_sequence"]+1)*640:raise ContractError("pose hash/range failure")
        receipts=proof["required_sink_receipts"]
        if receipts!=sorted(receipts,key=lambda s:(s["sinkId"],s["incarnation"])) or len({s["sinkId"] for s in receipts})!=len(receipts):raise ContractError("sink receipt order mismatch")
    if name=="StageRelease":
        refs=[header[k] for k in ("descriptor_sha256","commit_proof_fingerprint","pose_proof_fingerprint")]
        if header["reason"]=="COMPLETE" and (header["latest_consumed_sequence"]<0 or any(v is None for v in refs)):raise ContractError("complete requires final confirmed proof")
        if refs[1] is not None and refs[0] is None:raise ContractError("commit requires descriptor")
        if refs[1] is None and (refs[2] is not None or header["latest_consumed_sequence"]!=-1):raise ContractError("precommit release must have no pose")
    if name in ("StageReleased","StageStatusResult"):
        disposition=header["terminal_disposition"]
        if header["reusable"] and (disposition not in ("PROVEN_COMPLETE","PROVEN_CANCELLED") or not header["native_safe_boundary"]):raise ContractError("unknown is never reusable")
    return header


class LeaseBudget:
    """Pure monotonic lease accounting. Caller supplies integer monotonic ms.
    This is capacity state only, not A authorization or publication authority.
    """
    def __init__(self, begin, now_ms):
        validate_message(begin)
        self.identity=copy.deepcopy(begin["identity"]);self.grant=copy.deepcopy(begin["a_grant"]);self.started=now_ms
        self.deadline=now_ms+begin["lease_ms"];self.fenced=False
        self.sequence=0;self.renewals={}
    def fence(self):
        self.fenced=True
    def renew(self, request, now_ms):
        validate_message(request)
        if request["identity"]!=self.identity:raise ContractError("foreign renewal")
        if any(request["a_grant"][k]!=self.grant[k] for k in ("leaseToken","commandSeq")):raise ContractError("retired executor renewal")
        seq=request["renewal_sequence"];fingerprint=request["renewal_fingerprint"]
        if seq in self.renewals:
            old_hash,ack=self.renewals[seq]
            if old_hash!=fingerprint:raise ContractError("renewal conflict")
            return copy.deepcopy(ack) # original ACK; deadline never reset
        if self.fenced or now_ms>=self.deadline or now_ms>=self.started+60000:
            self.fenced=True;raise ContractError("expired/fenced renewal")
        if seq!=self.sequence+1:raise ContractError("renewal sequence gap")
        self.deadline=min(now_ms+request["lease_ms"],self.started+60000)
        self.sequence=seq
        ack={"type":"StageRenewAck",**{k:copy.deepcopy(request[k]) for k in COMMON},"renewal_sequence":seq,"renewal_fingerprint":fingerprint,"lease_remaining_ms":self.deadline-now_ms,"total_age_ms":now_ms-self.started}
        self.renewals[seq]=(fingerprint,copy.deepcopy(ack))
        if len(self.renewals)>64: self.fenced=True;raise ContractError("renewal tombstone budget exceeded")
        return ack


def installed_reference(identity, ack):
    """Only called with this operation's fresh authenticated A transaction ACK.
    Older persisted ACKs without observationHash fail staging closed; callers
    must not invent that hash or interpret this helper as new authorization.
    """
    validate_identity(identity)
    if ack.get('durable') is not True or ack.get('state')!='committed':
        raise ContractError('COMMIT_INSTALLED ACK required')
    result={k:identity[k] for k in ('sessionId','runEpoch','timelineEpoch','commandId','segmentId','attemptId','generationId')}
    result.update(operation='COMMIT_INSTALLED',producerIncarnation=ack.get('producerIncarnation'),receiptSeq=ack.get('receiptSeq'),observationHash=ack.get('observationHash'),timelineRevision=ack.get('revision'))
    _validate(result,INSTALLED)
    return result


def validate_pose_consumed(header, commit_header):
    """Validate a transient B partial proof against the stored armed commit.
    Caller owns ordering, fence, fresh A authority and real sink evidence.
    """
    validate_message(header);validate_message(commit_header)
    if header['type']!='StagePoseConsumed' or commit_header['type']!='StageCommit':raise ContractError('wrong pose/commit operation')
    if header['identity']!=commit_header['identity']:raise ContractError('foreign pose identity')
    p=header['pose_proof'];commit=commit_header['commit_proof'];out=commit['output']
    if p['commit_proof_fingerprint']!=commit_header['commit_proof_fingerprint'] or p['descriptor_sha256']!=commit['descriptor_sha256']:raise ContractError('foreign pose commit')
    receipts=p['required_sink_receipts']
    if [{k:r[k] for k in ('sinkId','incarnation')} for r in receipts]!=commit['required_sinks']:raise ContractError('captured required set mismatch')
    for r in receipts:
        if r['startSample']!=out['startSample'] or not out['startSample']<=r['audioEndSample']<=out['endSample'] or not out['startSample']<=r['videoEndSample']<=out['endSample']:raise ContractError('noncontiguous/outside receipt')
    watermark=min(min(r['audioEndSample'],r['videoEndSample']) for r in receipts)
    if p['output_end_sample']!=watermark or p['latest_consumed_sequence']!=pose_prefix(commit,watermark):raise ContractError('unproved pose prefix')
    return header
