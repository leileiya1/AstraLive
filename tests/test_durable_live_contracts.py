"""Contract-only checks: no service, database, network or paid GPU is started."""
import copy
import importlib.util
from pathlib import Path
import unittest

from jsonschema import ValidationError

spec = importlib.util.spec_from_file_location(
    "durable_contract_validator",
    Path(__file__).resolve().parents[1] / "scripts/validate-durable-live-contracts.py",
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class DurableLiveContractTests(unittest.TestCase):
    def setUp(self):
        self.objects = {item["name"]: item["value"]
                        for item in contract.load("examples/objects.json")}
        self.examples = {item["operationId"]: item
                         for item in contract.load("examples/protocol.json")}

    def test_all_schemas_operations_examples_vectors_and_frozen_files(self):
        result = contract.check_all()
        self.assertEqual(result["operations"], 20)
        self.assertEqual(result["machines"], 5)

    def test_objects_have_required_stable_identity(self):
        fields = {"BroadcastRun": "runId", "ContentPlan": "planId",
                  "SpeechSegment": "segmentId", "Turn": "turnId",
                  "ExecutionAttempt": "attemptId", "DispatchIntent": "intentId",
                  "RunSession": "runSessionId", "RunLease": "runId",
                  "PlaybackCheckpoint": "checkpointId"}
        for name, field in fields.items():
            with self.subTest(name=name):
                value = copy.deepcopy(self.objects[name])
                del value[field]
                with self.assertRaises(ValidationError):
                    contract.validate("#/$defs/" + name, value)

    def test_epoch_is_safe_positive_integer_and_unknown_fields_rejected(self):
        for epoch in (0, -1, True, "1", 1.5, 9007199254740992):
            with self.subTest(epoch=epoch):
                command = copy.deepcopy(self.objects["RuntimeCommand"])
                command["runEpoch"] = epoch
                with self.assertRaises(ValidationError):
                    contract.validate("#/$defs/RuntimeCommand", command)
        command = copy.deepcopy(self.objects["RuntimeCommand"])
        command["providerKey"] = "forbidden-extra-field"
        with self.assertRaises(ValidationError):
            contract.validate("#/$defs/RuntimeCommand", command)

    def test_time_must_be_valid_utc_z(self):
        for timestamp in ("2026-10-16T08:00:00+08:00", "2026-02-31T00:00:00Z", 1792108800):
            with self.subTest(timestamp=timestamp):
                turn = copy.deepcopy(self.objects["Turn"])
                turn["scheduledAt"] = timestamp
                with self.assertRaises(ValidationError):
                    contract.validate("#/$defs/Turn", turn)

    def test_turn_source_is_typed_and_comment_requires_stable_sources(self):
        for name, edit in (("Turn", {"sourceCommentTraceId": "trace_wrong"}),
                           ("CommentTurn", {"sourceIdentities": []}),
                           ("CommentTurn", {"expiresAt": None}),
                           ("CommentTurn", {"sourceSegmentId": "segment_wrong"})):
            with self.subTest(name=name, edit=edit):
                value = {**copy.deepcopy(self.objects[name]), **edit}
                with self.assertRaises(ValidationError):
                    contract.validate("#/$defs/Turn", value)

    def test_plan_rejects_cross_scope_sequence_and_changed_text(self):
        bundle = self.examples["SaveContentPlan"]["request"]["bundle"]
        mutations = [("tenantId", "tenant_wrong"), ("planId", "plan_wrong"),
                     ("sequence", 2), ("content", "更换商品后的旧文案。")]
        for key, value in mutations:
            with self.subTest(key=key):
                broken = copy.deepcopy(bundle)
                broken["segments"][0][key] = value
                with self.assertRaises(ValueError):
                    contract.validate_bundle(broken)
        broken = copy.deepcopy(bundle)
        broken["plan"]["snapshot"]["productId"] = "product_wrong"
        with self.assertRaises(ValueError):
            contract.validate_bundle(broken)

    def test_command_hash_pins_content_epoch_and_retry_metadata(self):
        for key, value in (("traceId", "trace_changed"), ("runEpoch", 2),
                           ("createdAt", "2026-10-16T00:00:01Z")):
            with self.subTest(key=key):
                command = copy.deepcopy(self.objects["RuntimeCommand"])
                command[key] = value
                with self.assertRaises(ValueError):
                    contract.validate_command(command)

    def test_drain_requires_all_named_sinks_and_full_ranges(self):
        checkpoint = self.objects["PlaybackCheckpoint"]
        for change in ("missing_sink", "audio_tail", "video_tail", "duplicate_sink"):
            with self.subTest(change=change):
                broken = copy.deepcopy(checkpoint)
                evidence = broken["evidence"]
                if change == "missing_sink":
                    evidence["requiredSinks"].append("webrtc_required")
                if change == "audio_tail":
                    evidence["sinkProofs"][0]["audioConsumedThroughExclusive"] -= 1
                if change == "video_tail":
                    evidence["sinkProofs"][0]["videoConsumedThroughFrame"] -= 1
                if change == "duplicate_sink":
                    evidence["sinkProofs"].append(copy.deepcopy(evidence["sinkProofs"][0]))
                with self.assertRaises(ValueError):
                    contract.validate_checkpoint(broken)

    def test_pcm_does_not_prove_complete_or_audience_playback(self):
        for change in ("pcm", "audible", "no_tail_proof"):
            with self.subTest(change=change):
                checkpoint = copy.deepcopy(self.objects["PlaybackCheckpoint"])
                checkpoint["state"] = "COMPLETED"
                checkpoint["evidence"]["evidenceType"] = "BUSINESS_COMMIT"
                if change == "pcm":
                    checkpoint["evidence"]["evidenceType"] = "TTS_PCM_READY"
                if change == "audible":
                    checkpoint["evidence"]["audienceVisibility"] = "AUDIENCE_HEARD"
                if change == "no_tail_proof":
                    checkpoint["evidence"]["sinkProofs"] = []
                with self.assertRaises(ValidationError):
                    contract.validate_checkpoint(checkpoint)

    def test_unknown_requires_last_known_evidence_and_reason(self):
        checkpoint = copy.deepcopy(self.objects["PlaybackCheckpoint"])
        checkpoint["state"] = "UNKNOWN"
        checkpoint["evidence"]["evidenceType"] = "KNOWLEDGE_GAP"
        with self.assertRaises(ValidationError):
            contract.validate_checkpoint(checkpoint)
        checkpoint.update(lastKnownState="PLAYING", reasonCode="RUNTIME_CRASH")
        contract.validate_checkpoint(checkpoint)

    def test_stop_terminal_and_unknown_no_blind_dispatch_edges(self):
        machines = contract.load("state-machines.json")["machines"]
        for name in ("BroadcastRun", "Turn", "DispatchIntent", "PlaybackCheckpoint"):
            edges = machines[name]["transitions"]
            terminal = {"BroadcastRun": {"STOPPED", "FAILED"},
                        "Turn": {"COMPLETED", "INTERRUPTED"},
                        "DispatchIntent": {"COMPLETED", "FAILED"},
                        "PlaybackCheckpoint": {"COMPLETED", "INTERRUPTED"}}[name]
            self.assertFalse(any(e["fromState"] in terminal for e in edges))
        run_edges = {(e["fromState"], e["toState"])
                     for e in machines["BroadcastRun"]["transitions"]}
        for state in ("CREATED", "PREPARING", "LIVE", "RECOVERING", "PAUSED"):
            self.assertIn((state, "STOPPING"), run_edges)
        dispatch_edges = {(e["fromState"], e["toState"])
                          for e in machines["DispatchIntent"]["transitions"]}
        self.assertNotIn(("UNKNOWN", "PENDING"), dispatch_edges)
        self.assertNotIn(("UNKNOWN", "CLAIMED"), dispatch_edges)

    def test_privilege_boundaries_and_single_use_start_authorization(self):
        operations = {o["operationId"]: o for o in contract.load("protocol.json")["operations"]}
        for name in ("ResumeBroadcastRun", "StopBroadcastRun", "SaveContentPlan", "RuntimeExecute"):
            self.assertEqual(operations[name]["roles"], ["CONTROL"])
        self.assertEqual(operations["JournalStart"]["roles"], ["RUNTIME_JOURNAL"])
        self.assertEqual(operations["ConfirmOutputFence"]["roles"], ["OUTPUT_GUARDIAN"])
        response = copy.deepcopy(self.examples["JournalStart"]["response"])
        del response["startAuthorized"]
        with self.assertRaises(ValidationError):
            contract.validate("#/$defs/JournalStartResponse", response)
        response.update(startAuthorized=True, state="UNKNOWN")
        with self.assertRaises(ValidationError):
            contract.validate("#/$defs/JournalStartResponse", response)

    def test_control_cleanup_can_precede_session_and_does_not_invent_turn(self):
        intent = self.objects["PreSessionStopIntent"]
        command = self.objects["StopCommand"]
        contract.validate("#/$defs/DispatchIntent", intent)
        contract.validate("#/$defs/StopCommand", command)
        self.assertEqual(intent["requestHash"], contract.digest(
            {k: v for k, v in command.items() if k != "requestHash"}))
        self.assertEqual(intent["commandId"], command["commandId"])
        self.assertIsNone(intent["turnId"])
        self.assertIsNone(intent["utteranceId"])
        with self.assertRaises(ValidationError):
            contract.validate("#/$defs/RuntimeStopRequest", command)
        intent = {**intent, "operation": "EXECUTE_TURN"}
        with self.assertRaises(ValidationError):
            contract.validate("#/$defs/DispatchIntent", intent)

    def test_canonical_parser_rejects_duplicates_nonfinite_floats_and_overflow(self):
        for text in ('{"commandId":"a","commandId":"b"}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                contract.parse(text)
        for value in ({"price": 129.9}, {"epoch": 9007199254740992}):
            with self.assertRaises(ValueError):
                contract.canonical(value)


if __name__ == "__main__":
    unittest.main()
