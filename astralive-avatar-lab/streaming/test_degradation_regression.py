import asyncio,unittest,time
from async_link import WorkerLink
from prefetch import PrefetchPipeline,PCM,WorkerUnavailable
class Link(WorkerLink):
 def __init__(self):
  super().__init__('unused');self.active=100;self.writer=True;self.epoch='test';self.ready={'cache_id':'test'};self.sent_packets=[];self.clock=lambda:100.0
 async def _write(self,h,p=b''):self.sent_packets.append(h)
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_aged_input_horizon_with_recent_video_progress_is_not_stalled(self):
  link=Link();link.received=187;link.sent=130000;link.ready_times.append((122880,time.monotonic()-6));link.last_video_progress_at=time.monotonic();pending=asyncio.create_task(link.receive(100));await asyncio.sleep(.015)
  self.assertFalse(pending.done(),'healthy recent progress must not be classified from old source admission time')
  item={'generation_id':100,'frame_sequence':187};link.frames.put_nowait(item)
  async with link.cv:link.cv.notify_all()
  self.assertEqual(await asyncio.wait_for(pending,.2),item)
 async def test_real_no_video_progress_still_times_out(self):
  link=Link();link.received=1;link.sent=15360;link.ready_times.append((15360,time.monotonic()-10));link.video_stall_window=.03;link.last_video_progress_at=time.monotonic()-10
  with self.assertRaises(WorkerUnavailable):await asyncio.wait_for(link.receive(100),.2)
 async def test_source_not_ready_is_not_misclassified(self):
  link=Link();link.sent=320;link.received=0;link.video_stall_window=.01
  t=asyncio.create_task(link.receive(100));await asyncio.sleep(.03);self.assertFalse(t.done());t.cancel();await asyncio.gather(t,return_exceptions=True)
 async def test_begin_waits_for_cancel_acknowledgment(self):
  link=Link();cancel=asyncio.create_task(link.cancel(100));await asyncio.sleep(.01);begin=asyncio.create_task(link.begin(101,16000));await asyncio.sleep(.01)
  self.assertFalse(begin.done(),'next job cannot reuse cancellation state before old ack')
  link.cancelled.set();await cancel;await begin;self.assertEqual(link.active,101)
 async def test_degraded_pipeline_never_opens_real_gpu_job(self):
  class Backend:
   def __init__(self):self.begins=[];self.cancels=[]
   async def begin(self,gid,origin):self.begins.append(gid)
   async def cancel(self,gid):self.cancels.append(gid)
  backend=Backend();p=PrefetchPipeline(backend,100,1,buffer_s=0);await p.degrade()
  async def src():yield PCM(1,bytes(640))
  data=[c async for c in p.stream(src())];self.assertTrue(data);self.assertEqual(backend.begins,[])
 async def test_degradation_reason_is_journaled(self):
  class Backend:
   def __init__(self):self.events=[]
   def log(self,event,**kw):self.events.append((event,kw))
   async def cancel(self,gid):pass
  b=Backend();p=PrefetchPipeline(b,100,1,buffer_s=0);await p.degrade('expected video progress stalled',stage='video-receive')
  self.assertTrue(any(event=='PipelineDegraded' and kw['reason']=='expected video progress stalled' for event,kw in b.events))
if __name__=='__main__':unittest.main(verbosity=2)

class OwnershipTests(unittest.IsolatedAsyncioTestCase):
 async def test_old_speech_cleanup_preserves_new_generation_owner(self):
  import tempfile,pathlib,types
  from unittest.mock import patch
  from app import soulx_remote as module
  class Pipeline:
   def __init__(self,*a,**kw):self.job_id=100;self.origin=0;self.delivered=320;self.degraded=True
   async def cancel(self):pass
   async def stream(self,source):
    async for chunk in source:yield chunk
  async def converted(source,generation):
   yield PCM(generation,bytes(640))
   yield PCM(generation,bytes(640))
  e=module.RemoteAvatarEngine.__new__(module.RemoteAvatarEngine);e.generation_id=1;e.running=True;e.first_pcm=None;e.marker=0;e.timeline_samples=0;e.degraded=False;e.link=None;e.speaking=False;e.pipeline=None;e._job=lambda:100;e.log=lambda *a,**kw:None
  async def stop_idle():pass
  e._stop_idle=stop_idle;e._fallback=None;e._start_idle=lambda:self.fail('old cleanup restarted idle')
  with tempfile.TemporaryDirectory() as temp,patch.object(module,'PrefetchPipeline',Pipeline),patch.object(module,'resampled',converted):
   e.evidence=pathlib.Path(temp);stream=e.stream_audio(None,1);await anext(stream);new_owner=object();e.pipeline=new_owner;e.generation_id=2;e.speaking=True
   await stream.aclose();self.assertIs(e.pipeline,new_owner);self.assertTrue(e.speaking);self.assertFalse(e.degraded);self.assertEqual(e.timeline_samples,0)
 async def test_cancelled_audio_sender_does_not_trigger_fallback(self):
  class Backend:
   async def send_audio(self,*args):raise AssertionError('inactive pipeline cannot publish audio')
  p=PrefetchPipeline(Backend(),100,1);p.active=False
  with self.assertRaises(asyncio.CancelledError):await p._send_audio(0,bytes(640),False)
