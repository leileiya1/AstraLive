import asyncio,unittest
from async_link import WorkerLink
from prefetch import WorkerUnavailable
class Link(WorkerLink):
 def __init__(self):
  super().__init__('unused');self.incoming=asyncio.Queue();self.sent_packets=[];self.epoch='test';self.active=100;self.writer=True
 async def _read(self):return await self.incoming.get()
 async def _write(self,h,p=b''):self.sent_packets.append(h)
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_zero_credit_recovers_when_gpu_drain_is_reported(self):
  link=Link();rx=asyncio.create_task(link._receive_loop())
  send=asyncio.create_task(link.send_audio(100,0,0,bytes(640),False));await asyncio.sleep(.01);self.assertFalse(send.done())
  await link.incoming.put((dict(type='Health',worker_epoch='test',ready=True,active_generation_id=100,audio_queue_ms=0),b''))
  await asyncio.wait_for(send,.2);self.assertEqual(link.available,31680);rx.cancel();await rx
 async def test_health_snapshot_reserves_inflight_audio(self):
  link=Link();link.pending={0:320};rx=asyncio.create_task(link._receive_loop())
  await link.incoming.put((dict(type='Health',worker_epoch='test',ready=True,active_generation_id=100,audio_queue_ms=1000),b''))
  await asyncio.sleep(.01);self.assertEqual(link.available,15680);rx.cancel();await rx
 async def test_consumer_credits_are_in_order_and_old_job_is_ignored(self):
  link=Link()
  await link.consumed(dict(generation_id=100,frame_sequence=1));self.assertEqual(link.sent_packets,[])
  await link.consumed(dict(generation_id=99,frame_sequence=0));self.assertEqual(link.sent_packets,[])
  await link.consumed(dict(generation_id=100,frame_sequence=0));self.assertEqual([x['latest_consumed_sequence'] for x in link.sent_packets],[0,1])
if __name__=='__main__':unittest.main()
