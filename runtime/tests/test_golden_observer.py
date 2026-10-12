"""Observer control oracle only; no real media or provider acceptance."""
import unittest
from narration_real_golden import require_observable_state, GoldenFailure

class GoldenObserverPolicyTests(unittest.TestCase):
    def test_natural_finished_plan_allowed_for_normal_session_stop(self):
        require_observable_state({"state":"STOPPED","reason":"FINISHED"})
        require_observable_state({"state":"NARRATING","reason":""})
    def test_other_stop_recovery_and_failure_never_called_finished(self):
        for state in ("STOPPED","STOPPING","RECOVERY_REQUIRED","FAILED"):
            with self.assertRaises(GoldenFailure):require_observable_state({"state":state,"reason":"OPERATOR_STOP"})
