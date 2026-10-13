"""Independent internal audio prefetch experiment. No production Runtime imports."""
import asyncio
from dataclasses import dataclass

class WorkerUnavailable(RuntimeError):
    pass

@dataclass(frozen=True)
class PCM:
    generation_id: int
    pcm: bytes
    sample_rate: int = 16000
    channels: int = 1

class SampleQueue:
    def __init__(self,budget=32000):
        self.cv=asyncio.Condition();self.items=[];self.samples=0;self.budget=budget;self.peak=0;self.closed=False
    async def put(self,item):
        count=len(item.pcm)//2
        if count>self.budget:raise ValueError('split PCM before queue admission')
        async with self.cv:
            while self.samples+count>self.budget and not self.closed:await self.cv.wait()
            if self.closed:raise asyncio.CancelledError()
            self.items.append(item);self.samples+=count;self.peak=max(self.peak,self.samples);self.cv.notify_all()
    async def get(self):
        async with self.cv:
            while not self.items and not self.closed:await self.cv.wait()
            if not self.items:return None
            item=self.items.pop(0);self.samples-=len(item.pcm)//2;self.cv.notify_all();return item
    async def end(self,discard=False):
        async with self.cv:
            self.closed=True
            if discard:self.items.clear();self.samples=0
            self.cv.notify_all()

class PrefetchPipeline:
    """Backend owns a bounded receive queue and consumption-based video credit."""
    def __init__(self,backend,job_id,business_generation,origin=0,buffer_s=.120,fallback=None):
        self.backend=backend;self.job_id=job_id;self.generation=business_generation;self.origin=origin;self.buffer_s=buffer_s
        self.audio=SampleQueue();self.source_samples=0;self.delivered=0;self.frames=0;self.first=None;self.task=None;self.active=True;self.error=None;self.eof_pad_samples=0;self.failed=asyncio.Event();self.degraded=False;self.degraded_event=asyncio.Event();self.degrade_lock=asyncio.Lock();self.fallback=fallback
    async def stream(self,source):
        if not self.degraded:
            try:await self.backend.begin(self.job_id,self.origin)
            except WorkerUnavailable as exc:await self.degrade(str(exc),stage='begin')
        async def produce():
            try:
                seq=0
                async for chunk in source:
                    if chunk.generation_id!=self.generation:continue
                    if (chunk.sample_rate,chunk.channels)!=(16000,1):raise ValueError('stateful resampling must precede this pipeline')
                    if len(chunk.pcm)%2:raise ValueError('unaligned PCM')
                    # This core's source is already converted; split even oversized producer chunks.
                    for i in range(0,len(chunk.pcm),640):
                        part=chunk.pcm[i:i+640]
                        await self._send_audio(seq,part,False)
                        self.source_samples+=len(part)//2;seq+=1
                        await self.audio.put(PCM(self.generation,part))
                # Explicit final frame-grid silence. This is media, not fake model lookahead.
                pad=(-self.source_samples)%640;self.eof_pad_samples=pad
                if pad:
                    for i in range(0,pad,320):
                        part=bytes(min(320,pad-i)*2)
                        await self._send_audio(seq,part,False)
                        self.source_samples+=len(part)//2;seq+=1;await self.audio.put(PCM(self.generation,part))
                await self._send_audio(seq,b'',True)
                await self.audio.end()
            except asyncio.CancelledError:
                await self.audio.end(True);raise
            except Exception as exc:
                self.error=exc;self.failed.set();await self.audio.end(True)
                await self.backend.cancel(self.job_id)
        self.task=asyncio.create_task(produce())
        try:
            # Do not await render from the source producer: it must supply the model horizon.
            if not self.degraded:
                try:self.first=await self._receive_frame()
                except WorkerUnavailable as exc:await self.degrade(str(exc),stage='worker-io')
            if self.error:raise self.error
            await asyncio.sleep(self.buffer_s)
            while self.active:
                chunk=await self.audio.get()
                if chunk is None:break
                yield chunk
            if self.error:raise self.error
            await self.task
            if not self.degraded:
                try:await self.backend.complete(self.job_id)
                except WorkerUnavailable as exc:await self.degrade(str(exc),stage='worker-io')
        finally:
            await self.cancel()
    async def _receive_frame(self):
        receive=asyncio.create_task(self.backend.receive(self.job_id))
        fault=asyncio.create_task(self.failed.wait())
        degraded=asyncio.create_task(self.degraded_event.wait())
        try:
            await asyncio.wait((receive,fault,degraded),return_when=asyncio.FIRST_COMPLETED)
            if not self.active:raise asyncio.CancelledError()
            if self.error:raise self.error
            if self.degraded:raise WorkerUnavailable('worker fenced')
            return await receive
        finally:
            for task in (receive,fault,degraded):
                if not task.done():task.cancel()
            await asyncio.gather(receive,fault,degraded,return_exceptions=True)
    async def render(self,chunk):
        if not self.active or chunk.generation_id!=self.generation:return []
        end=self.delivered+len(chunk.pcm)//2;out=[]
        while self.frames*640<end:
            if self.degraded:
                if self.fallback is None:raise WorkerUnavailable('fallback renderer not configured')
                out=await self.fallback(chunk,self.origin+self.delivered,self.origin+self.frames*640)
                self.frames=(end+639)//640;self.delivered=end
                return out
            try:packet=self.first if self.first is not None else await self._receive_frame()
            except WorkerUnavailable as exc:
                if not self.active:raise asyncio.CancelledError()
                await self.degrade(str(exc),stage='video-receive')
                continue
            self.first=None
            if not self.active:return []
            if packet['generation_id']!=self.job_id or packet['frame_sequence']!=self.frames:
                raise RuntimeError('stale/missing worker frame')
            expected=self.origin*1000000//16000+self.frames*40000
            if packet['pts_us']!=expected:raise RuntimeError('worker PTS mismatch')
            out.append(packet);self.frames+=1
        self.delivered=end
        return out
    async def _send_audio(self,seq,pcm,final):
        if not self.active:raise asyncio.CancelledError()
        if self.degraded:return
        try:await self.backend.send_audio(self.job_id,seq,self.origin+self.source_samples,pcm,final)
        except WorkerUnavailable as exc:
            if not self.active:raise asyncio.CancelledError()
            await self.degrade(str(exc),stage='worker-io')
    async def degrade(self,reason='explicit fallback',stage='control'):
        async with self.degrade_lock:
            if self.degraded:return
            journal=getattr(self.backend,'log',None)
            if journal:journal('PipelineDegraded',job_id=self.job_id,reason=reason,stage=stage,delivered_samples=self.delivered,source_samples=self.source_samples,frames=self.frames)
            self.degraded=True;self.first=None;self.degraded_event.set()
            try:await self.backend.cancel(self.job_id)
            except WorkerUnavailable:pass
    async def cancel(self):
        if not self.active:return
        self.active=False;self.first=None
        await self.audio.end(True)
        if self.task and not self.task.done():self.task.cancel()
        # Invalidate GPU work before waiting for a native TTS CPU callback to settle.
        try:await self.backend.cancel(self.job_id)
        except WorkerUnavailable:pass
        if self.task:await asyncio.gather(self.task,return_exceptions=True)
