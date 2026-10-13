import asyncio
import io
import unittest
from runtime.app.config import RTMPSettings
from runtime.app.providers import VideoFrame
from gpu_worker.validated.paired_rtmp import PairedRTMPMediaOutput

class PairedClockTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        return PairedRTMPMediaOutput(RTMPSettings(enabled=True,url='rtmp://127.0.0.1:19355/live',stream_key='cpu-test'),io.StringIO())
    async def test_both_tracks_underflow_together_and_force_clears_queues(self):
        s=self.make();s.generation_id=1
        s.audio_queue.put_nowait((1,b'a'));s.audio_queue.put_nowait((1,b'b'))
        self.assertIsNone(s._next_pair())
        self.assertEqual(s.audio_queue.qsize(),2)
        s.video_queue.put_nowait((1,b'v',40000))
        self.assertEqual(s._next_pair(),(b'ab',b'v',40000))
        s.audio_queue.put_nowait((1,b'old'))
        s.video_queue.put_nowait((1,b'old',80000))
        await s.interrupt(2)
        self.assertEqual(s.audio_queue.qsize(),0)
        self.assertEqual(s.video_queue.qsize(),0)
        self.assertEqual(s._latest_video,b'v')
        self.assertIsNone(s.last_source_pts)

if __name__=='__main__':unittest.main()
