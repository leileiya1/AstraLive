"""Observer control oracle only; no real media or provider acceptance."""
import unittest
from narration_real_golden import require_observable_state, require_browser_av, GoldenFailure

class GoldenObserverPolicyTests(unittest.TestCase):
    def test_natural_finished_plan_allowed_for_normal_session_stop(self):
        require_observable_state({"state":"STOPPED","reason":"FINISHED"})
        require_observable_state({"state":"NARRATING","reason":""})
    def test_other_stop_recovery_and_failure_never_called_finished(self):
        for state in ("STOPPED","STOPPING","RECOVERY_REQUIRED","FAILED"):
            with self.assertRaises(GoldenFailure):require_observable_state({"state":state,"reason":"OPERATOR_STOP"})

    def test_browser_silence_stall_and_empty_recorder_never_pass_with_normal_stop(self):
        observed={"audioPreflight":{"ready":True},"audioEnergy":[{"rms":.01}],"video":[{}],"recordedBytes":100,"recordingChunks":1}
        require_browser_av(observed,True)
        for broken in (observed|{"audioPreflight":None},observed|{"audioPreflight":{"ready":False}},
                       observed|{"audioEnergy":[{"rms":0}]},observed|{"video":[]},
                       observed|{"recordedBytes":0},observed|{"recordingChunks":0}):
            with self.assertRaises(GoldenFailure):require_browser_av(broken,True)
        with self.assertRaises(GoldenFailure):require_browser_av(observed,False)
