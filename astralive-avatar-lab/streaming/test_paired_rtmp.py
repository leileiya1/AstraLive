import asyncio,unittest,tempfile,os
from app.config import RTMPSettings
from app.providers import AudioChunk,VideoFrame
from app.soulx_rtmp_clock import PairedRTMPMediaOutput
class Tests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();os.makedirs(self.temp.name+'/integration');os.environ['SOULX_EXPERIMENT_DIR']=self.temp.name
  self.sink=PairedRTMPMediaOutput(RTMPSettings(enabled=True,url='rtmp://127.0.0.1:19355/live',stream_key='test',width=8,height=8,fps=25));self.sink.running=True
 def tearDown(self):self.sink.clock_log.close();self.temp.cleanup()
 async def test_video_does_not_run_ahead_of_audio_on_underflow(self):
  await self.sink.push_video(VideoFrame(1,400000,8,8,bytes(192)));self.assertIsNone(self.sink._next_pair());self.assertEqual(self.sink.video_queue.qsize(),1)
  await self.sink.push_audio(AudioChunk(1,0,bytes(640)));self.assertIsNone(self.sink._next_pair());self.assertEqual(self.sink.audio_queue.qsize(),1)
  await self.sink.push_audio(AudioChunk(1,1,bytes(640)));pair=self.sink._next_pair();self.assertEqual(len(pair[0])//2,1920);self.assertEqual(pair[2],400000);self.assertEqual(self.sink.audio_consumed,2);self.assertEqual(self.sink.video_consumed,1)
 async def test_audio_does_not_run_ahead_of_missing_video(self):
  for i in range(2):await self.sink.push_audio(AudioChunk(1,i,bytes(640)))
  self.assertIsNone(self.sink._next_pair());self.assertEqual(self.sink.audio_queue.qsize(),2)
 async def test_force_discards_both_queues_and_keeps_idle_image(self):
  await self.sink.push_video(VideoFrame(1,0,8,8,bytes(192)))
  await self.sink.push_audio(AudioChunk(1,0,bytes(640)));self.sink._latest_video=b'last-good-idle'
  await self.sink.interrupt(2);self.assertTrue(self.sink.audio_queue.empty());self.assertTrue(self.sink.video_queue.empty());self.assertEqual(self.sink._latest_video,b'last-good-idle');self.assertIsNone(self.sink._next_pair())
 async def test_shared_output_quantum_stays_exact_after_write_delay(self):
  writes=[]
  async def write(fd,payload):
   await asyncio.sleep(.003 if fd==2 else 0);writes.append((fd,len(payload)))
   if len(writes)>=12:self.sink.running=False
  self.sink._audio_fd=1;self.sink._video_fd=2;self.sink._write_fd=write
  await asyncio.wait_for(self.sink._audio_clock(),1)
  self.assertEqual([n for fd,n in writes if fd==1],[3840]*6);self.assertEqual(len([1 for fd,n in writes if fd==2]),6);self.assertEqual(self.sink.paired_ticks,6)
if __name__=='__main__':unittest.main(verbosity=2)
