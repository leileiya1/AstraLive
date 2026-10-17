"""Reproduce Agent 4 PR9 findings against a pinned archive, without editing it."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("snapshot", type=Path)
args = parser.parse_args()
spec = importlib.util.spec_from_file_location("candidate_tests", args.snapshot / "tests/test_durable_answer_contracts.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
t = m.AnswerContractTests()
t.setUp()
t.prepare_and_start()
t.drain()
q = copy.deepcopy(t.prepare)
q.update(artifact=t.artifacts[1], idempotencyKey="review-slow-next-unit", expectedInboxRevision=t.j.inbox_revision, expectedAnswerRevision=t.j.answer_revision)
try:
    t.j.prepare(q)
    slow = "ACCEPTED"
except m.r.Rejected as exc:
    slow = str(exc)
t.setUp()
t.prepare_and_start()
t.prepare_second()
t.drain()
q = copy.deepcopy(t.rows["JournalStartAnswerSegment"]["request"])
q["expectedAnswerRevision"] = t.j.answer_revision
t.j.start_segment(q)  # discard its grant as an ACK-loss simulation
print(json.dumps({"drainBeforeNextPrepare": slow, "lostContinuationAckRetry": t.j.start_segment(q), "globalStartCount": t.j.command_start_count}, indent=2))
assert slow == "ANSWER_GAP", "candidate changed: re-review its digest"
