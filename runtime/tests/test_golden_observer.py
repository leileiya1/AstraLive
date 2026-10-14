"""Observer control oracle only; no real media or provider acceptance."""
import unittest
import io
import base64
import hashlib
from narration_real_golden import require_observable_state, require_browser_av, require_fixture_completion, comment_positions, GoldenFailure, ChromeRecordingWriter

class GoldenObserverPolicyTests(unittest.TestCase):
    def test_hour_comments_are_seeded_single_session_stratified_not_bursts(self):
        points=comment_positions('soak',3600,25,5012)
        self.assertEqual(points,comment_positions('soak',3600,25,5012))
        self.assertEqual(len(points),25)
        self.assertGreater(min(points),90)
        self.assertLess(max(points),3600*.87)
        self.assertGreater(min(b-a for a,b in zip(points,points[1:])),50)
        import random
        rng=random.Random(5012)
        self.assertEqual(comment_positions('short',60,5,5012),sorted(rng.uniform(4.8,52.2) for _ in range(5)))
    def test_natural_finished_plan_allowed_for_normal_session_stop(self):
        require_observable_state({"state":"STOPPED","reason":"FINISHED"})
        require_observable_state({"state":"NARRATING","reason":""})
    def test_other_stop_recovery_and_failure_never_called_finished(self):
        for state in ("STOPPED","STOPPING","RECOVERY_REQUIRED","FAILED"):
            with self.assertRaises(GoldenFailure):require_observable_state({"state":state,"reason":"OPERATOR_STOP"})

    def test_browser_silence_stall_and_empty_recorder_never_pass_with_normal_stop(self):
        observed={"audioPreflight":{"ready":True},"audioEnergy":[{"rms":.01}],"video":[{}],"recordedBytes":100,"recordingChunks":1,"deliveredRecordingBytes":100,"deliveredRecordingChunks":1}
        require_browser_av(observed,True)
        for broken in (observed|{"audioPreflight":None},observed|{"audioPreflight":{"ready":False}},
                       observed|{"audioEnergy":[{"rms":0}]},observed|{"video":[]},
                       observed|{"recordedBytes":0},observed|{"recordingChunks":0},observed|{"recordingFailed":True},
                       observed|{"recorderErrors":[{"operation":"recording_delivery"}]},observed|{"deliveredRecordingBytes":99},observed|{"deliveredRecordingChunks":0}):
            with self.assertRaises(GoldenFailure):require_browser_av(broken,True)
        with self.assertRaises(GoldenFailure):require_browser_av(observed,False)

    def test_recording_storage_checks_exact_blob_hash_size_and_sequence(self):
        file=io.BytesIO();writer=ChromeRecordingWriter(file);payload=b'actual blob bytes'
        writer.store(0,base64.b64encode(payload).decode(),len(payload),hashlib.sha256(payload).hexdigest())
        self.assertEqual(file.getvalue(),payload)
        self.assertEqual(writer.chunks,[{'sequence':0,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}])
        with self.assertRaises(GoldenFailure):writer.store(2,base64.b64encode(payload).decode())
        with self.assertRaises(GoldenFailure):writer.store(1,base64.b64encode(payload).decode())
        self.assertEqual(file.getvalue(),payload)

    def test_invalid_multicodec_old_delimiter_hash_and_size_reject_before_write(self):
        payload=b'blob';encoded=base64.b64encode(payload).decode()
        for data,size,sha in [('opus;base64',4,None),(encoded+'!',4,None),(encoded,5,None),(encoded,4,'0'*64)]:
            with self.subTest(data=data,size=size,sha=sha):
                file=io.BytesIO();writer=ChromeRecordingWriter(file)
                with self.assertRaises(GoldenFailure):writer.store(0,data,size,sha)
                self.assertTrue(writer.failed);self.assertEqual(file.getvalue(),b'')

    def test_fixture_completion_never_accepts_stopped_pending_or_missing_facts_comments(self):
        finished={'state':'STOPPED','reason':'FINISHED','cursor':{'completedFactIds':['name','price']}}
        require_fixture_completion(finished,{'name','price'},1,1)
        for snapshot,injected in [(finished|{'reason':'OPERATOR_STOP'},1),(finished|{'state':'NARRATING'},1),
                                  (finished|{'cursor':{'completedFactIds':['name']}},1),(finished,0)]:
            with self.assertRaises(GoldenFailure):require_fixture_completion(snapshot,{'name','price'},injected,1)
