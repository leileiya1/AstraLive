import asyncio,unittest
from prefetch import PCM,PrefetchPipeline,WorkerUnavailable

class FakeBackend:
    """CPU orchestration simulator; not SoulX, not a latency/FPS benchmark."""
    def __init__(self):self.loads=1;self.active=None;self.samples=0;self.frameseq=0;self.q=None;self.eof=False;self.cv=asyncio.Condition();self.credit=4;self.done=asyncio.Event();self.peak_inflight=0;self.outstanding=0;self.model=None;self.errors=[]
    async def begin(self,gid,origin):
        self.active=gid;self.origin=origin;self.samples=0;self.frameseq=0;self.credit=4;self.outstanding=0;self.eof=False;self.done=asyncio.Event();self.q=asyncio.Queue(4)
        self.model=asyncio.create_task(self._model(gid))
    async def send_audio(self,gid,seq,index,pcm,final):
        async with self.cv:
            if gid!=self.active:raise asyncio.CancelledError()
            if index!=self.origin+self.samples:raise ValueError('source discontinuity')
            self.samples+=len(pcm)//2;self.eof=final;self.cv.notify_all()
    async def _model(self,gid):
        try:
            while gid==self.active:
                async with self.cv:
                    while self.samples-self.frameseq*640<15360 and not self.eof:await self.cv.wait()
                    target=self.samples//640 if self.eof else (self.samples//15360)*24
                if self.eof and self.frameseq>=target:return
                while self.frameseq<target:
                    async with self.cv:
                        while self.credit==0:await self.cv.wait()
                        if gid!=self.active:return
                        self.credit-=1;self.outstanding+=1;self.peak_inflight=max(self.peak_inflight,self.outstanding)
                    await self.q.put(dict(generation_id=gid,frame_sequence=self.frameseq,pts_us=self.origin*1000000//16000+self.frameseq*40000))
                    self.frameseq+=1
        except asyncio.CancelledError:pass
    async def receive(self,gid):
        p=await self.q.get()
        if gid!=self.active:raise asyncio.CancelledError()
        return p
    async def consumed(self,p):
        async with self.cv:
            self.credit+=1;self.outstanding-=1
            if self.eof and p['frame_sequence']+1==self.samples//640:self.done.set()
            self.cv.notify_all()
    async def complete(self,gid):await self.done.wait()
    async def cancel(self,gid):
        if self.active!=gid:return
        async with self.cv:self.active=None;self.cv.notify_all()
        self.model.cancel();await asyncio.gather(self.model,return_exceptions=True)
        while not self.q.empty():self.q.get_nowait()

class Tests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,counts):
        b=FakeBackend();p=PrefetchPipeline(b,100,1,origin=16000,buffer_s=0)
        producer_done=False
        async def source():
            nonlocal producer_done
            for count in counts:yield PCM(1,bytes(count*2))
            producer_done=True
        n=frames=0
        async for c in p.stream(source()):
            out=await p.render(c);n+=len(c.pcm)//2
            for f in out:
                self.assertEqual(f['pts_us'],1000000+frames*40000);frames+=1
                # This test consumes before crediting, without pretending a browser displayed it.
                await b.consumed(f)
        self.assertEqual(n,((sum(counts)+639)//640)*640)
        self.assertEqual(frames,n//640);self.assertLessEqual(p.audio.peak,32000);self.assertLessEqual(b.peak_inflight,4);self.assertTrue(producer_done)
        return p,b
    async def test_20ms_first_chunk_does_not_deadlock(self):await asyncio.wait_for(self.exercise([320]*500),5)
    async def test_short_eof_flushes_without_960ms_audio(self):await asyncio.wait_for(self.exercise([320]*7),2)
    async def test_multiple_sentences_share_one_contiguous_job(self):await asyncio.wait_for(self.exercise([2240,5440,8320]),2)
    async def test_force_while_first_frame_waits(self):
        b=FakeBackend();p=PrefetchPipeline(b,100,1,buffer_s=0);hold=asyncio.Event()
        async def source():
            yield PCM(1,bytes(640));await hold.wait()
        async def consume():
            async for c in p.stream(source()):await p.render(c)
        task=asyncio.create_task(consume());await asyncio.sleep(.02);task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertFalse(p.active);self.assertIsNone(b.active);self.assertEqual(p.audio.samples,0)
        p2,b2=await self.exercise([320]*50);self.assertEqual(b2.loads,1)
    async def test_worker_failure_preserves_all_audio_before_and_after_first_frame(self):
        for fail_frame in (0,3):
            class Failing(FakeBackend):
                async def receive(self,gid):
                    if getattr(self,'receives',0)==fail_frame:raise WorkerUnavailable('simulated link loss')
                    self.receives=getattr(self,'receives',0)+1
                    return await super().receive(gid)
            b=Failing(); rendered=[]
            async def fallback(chunk,first_sample,next_frame_sample):
                rendered.append(next_frame_sample)
                return [dict(generation_id=100,pts_us=next_frame_sample*1000000//16000,source='LIGHTWEIGHT_AVATAR')]
            p=PrefetchPipeline(b,100,1,buffer_s=0,fallback=fallback)
            original=b'\x13\x07'*160000
            async def source():
                for i in range(0,len(original),640):yield PCM(1,original[i:i+640])
            result=bytearray()
            async def consume():
                async for c in p.stream(source()):
                    result.extend(c.pcm)
                    for frame in await p.render(c):
                        if frame.get('source')!='LIGHTWEIGHT_AVATAR':await b.consumed(frame)
            await asyncio.wait_for(consume(),2)
            self.assertEqual(result,original);self.assertTrue(p.degraded);self.assertTrue(rendered)
            self.assertEqual(p.frames,250);self.assertLessEqual(p.audio.peak,32000)

    async def test_source_failure_is_not_masked(self):
        b=FakeBackend();p=PrefetchPipeline(b,100,1,buffer_s=0)
        async def source():
            yield PCM(1,bytes(640));raise ValueError('TTS failure')
        async def run():
            async for c in p.stream(source()):await p.render(c)
        with self.assertRaises(ValueError):await asyncio.wait_for(run(),.5)

if __name__=='__main__':unittest.main(verbosity=2)
