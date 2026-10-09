"""Isolated optional provider, retaining the existing MediaOutput implementation."""
import asyncio,json,os,pathlib,time,wave,traceback
import numpy as np
from .providers import AudioChunk,VideoFrame
from .lightweight_avatar import LightweightAvatarEngine
from .real_tts import SherpaOnnxTTSProvider
from prefetch import PCM,PrefetchPipeline,WorkerUnavailable
from async_link import WorkerLink
from resample import resampled

class RemoteAvatarEngine:
    def __init__(self):
        self.running=False;self.generation_id=1;self.timeline_samples=0;self.pipeline=None;self.idle_task=None;self.media=None;self.speaking=False;self.degraded=False;self.marker=0
        self.config=None;self.link=None;self.cached_idle=None;self.first_pcm=None;self.last_frame=None
        self.root=pathlib.Path(os.environ['SOULX_EXPERIMENT_DIR']);self.evidence=self.root/'integration';self.evidence.mkdir(exist_ok=True)
        self.logfile=(self.evidence/'avatar-events.jsonl').open('a',buffering=1)
        self.light=LightweightAvatarEngine(os.getenv('AVATAR_IMAGE_PATH') or None)
    def log(self,event,**kw):
        self.logfile.write(json.dumps(dict(event=event,monotonic_s=time.monotonic(),business_generation_id=self.generation_id,**kw))+'\n')
    def configure_session(self,config):self.config=config;self.light.configure_session(config)
    async def prepare(self,config):
        await self.light.prepare(config)
        self.link=WorkerLink(self.root/'.private/token',self.log)
        try:
            if self.config.fps!=25:raise WorkerUnavailable('remote requires 25FPS')
            await self.link.connect()
        except WorkerUnavailable as e:self.degraded=True;self.log('ProviderDegraded',reason=str(e))
    async def start(self):self.running=True;await self.light.start()
    def _job(self):return time.time_ns()//1000
    async def _fallback(self,chunk,first_sample,next_frame_sample):
        self.degraded=True
        self.light.audio_us=first_sample*1000000//16000;self.light.next_frame_us=next_frame_sample*1000000//16000
        out=await self.light.push_audio(chunk)
        return [dict(source='LIGHTWEIGHT_AVATAR',generation_id=self.pipeline.job_id if self.pipeline else 0,frame_sequence=0,pts_us=f.pts_us,width=f.width,height=f.height,rgb=f.rgb) for f in out]
    async def _stop_idle(self):
        task=self.idle_task;self.idle_task=None
        if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
    def _start_idle(self):
        if self.running and not self.speaking and self.pipeline is None and (self.idle_task is None or self.idle_task.done()):
            self.idle_task=asyncio.create_task(self._idle())
    async def _idle(self):
        p=None
        try:
            while self.running and not self.speaking and not self.media.has_peer():await asyncio.sleep(.1)
            if not self.running or self.speaking:return
            self.marker=(self.marker+1)%8192 or 1;marker=self.marker
            p=PrefetchPipeline(self.link,self._job(),self.generation_id,origin=self.timeline_samples,fallback=self._fallback)
            if self.degraded:await p.degrade()
            self.pipeline=p
            async def silence():
                start=time.monotonic();seq=0
                while self.running and not self.speaking:
                    seq+=1;await asyncio.sleep(max(0,start+seq*.02-time.monotonic()));yield PCM(self.generation_id,bytes(640))
            async for chunk in p.stream(silence()):
                if self.speaking or not self.running:break
                frames=await p.render(chunk)
                await self.media.push_audio(AudioChunk(self.generation_id,0,chunk.pcm))
                for packet in frames:
                    packet['activity']='IDLE';packet['marker']=marker
                    frame=self.convert(packet);self.media.metadata[id(frame)]=packet
                    await self.media.push_video(frame)
                self.timeline_samples=p.origin+p.delivered
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.degraded=True;self.log('IdleDegraded',reason=str(exc),error_type=type(exc).__name__,traceback=traceback.format_exc())
        finally:
            if p:await p.cancel()
            if self.pipeline is p:self.pipeline=None
            if self.idle_task is asyncio.current_task():self.idle_task=None
    async def stream_audio(self,source,generation_id):
        converted=resampled(source,generation_id)
        try:first=await anext(converted)
        except StopAsyncIteration:return
        if generation_id!=self.generation_id or not self.running:
            await converted.aclose();return
        self.first_pcm=time.monotonic();self.log('FirstPCM',native_resampled=True)
        self.speaking=True;await self._stop_idle()
        if generation_id!=self.generation_id or not self.running:
            await converted.aclose();return
        self.marker=(self.marker+1)%8192 or 1;marker=self.marker
        p=PrefetchPipeline(self.link,self._job(),generation_id,origin=self.timeline_samples,fallback=self._fallback)
        if self.degraded:await p.degrade()
        self.pipeline=p
        self.log('BeginSpeechJob',job_id=p.job_id,marker=marker,first_sample_index=p.origin)
        async def with_first():
            yield first
            async for chunk in converted:yield chunk
        capture=wave.open(str(self.evidence/f'speech-{p.job_id}.wav'),'wb');capture.setnchannels(1);capture.setsampwidth(2);capture.setframerate(16000)
        try:
            sequence=0
            async for chunk in p.stream(with_first()):
                capture.writeframesraw(chunk.pcm)
                yield AudioChunk(generation_id,sequence,chunk.pcm,16000,1);sequence+=1
            self.log('SpeechEOF',eof_pad_samples=p.eof_pad_samples,frames=p.frames,degraded=p.degraded)
        finally:
            capture.close()
            await p.cancel()
            # A cancelled utterance may finish native-source cleanup after a newer
            # generation has installed its pipeline. It owns only its own state.
            if self.pipeline is p:
                self.timeline_samples=max(self.timeline_samples,p.origin+p.delivered)
                if generation_id==self.generation_id:self.degraded=self.degraded or p.degraded
                self.pipeline=None;self.speaking=False
                if generation_id==self.generation_id:self._start_idle()
            else:self.log('StaleSpeechCleanupIgnored',job_id=p.job_id,source_generation_id=generation_id)
    async def push_audio(self,chunk):
        if chunk.generation_id!=self.generation_id or not self.pipeline:return []
        packets=await self.pipeline.render(chunk);self.timeline_samples=self.pipeline.origin+self.pipeline.delivered
        out=[]
        for packet in packets:
            packet['activity']='TALKING';packet['marker']=self.marker
            frame=self.convert(packet);self.media.metadata[id(frame)]=packet;out.append(frame)
        return out
    def convert(self,packet):
        rgb=packet['rgb']
        if os.getenv('SOULX_LATENCY_MARKER')=='1':
            image=np.frombuffer(rgb,dtype=np.uint8).reshape(packet['height'],packet['width'],3).copy()
            marker=packet.get('marker',0)
            if packet['source']=='LIGHTWEIGHT_AVATAR':marker|=0x8000
            for bit in range(16):image[:8,bit*8:bit*8+8]=[220,40,40] if marker&(1<<bit) else [40,220,40]
            # Lab-only packet identifiers for a fenced canvas and timestamp audit.
            # The unmodified RGB remains the sole input to committed motion history.
            for row,value,bits in [(8,packet.get('frame_sequence',0),24),(16,self.generation_id,16)]:
                for bit in range(bits):image[row:row+8,bit*8:bit*8+8]=[220,40,40] if value&(1<<bit) else [40,220,40]
            rgb=image.tobytes()
        return VideoFrame(self.generation_id,packet['pts_us'],packet['width'],packet['height'],rgb)
    async def interrupt(self,generation_id):
        self.generation_id=generation_id
        # Early delegate to the unchanged sink fence, before native-source cleanup waits.
        if self.media:await self.media.invalidate(generation_id)
        previous=self.pipeline
        if previous:await previous.cancel()
        await self._stop_idle()
        if self.pipeline is previous:self.pipeline=None
        self.speaking=False;await self.light.interrupt(generation_id)
    async def stop(self):
        self.running=False
        if self.pipeline:await self.pipeline.cancel()
        await self._stop_idle()
        if self.link:await self.link.close()
        await self.light.stop();self.log('ProviderStopped');self.logfile.close()

class ConsumptionMediaOutput:
    def __init__(self,output,avatar):
        self.output=output;self.avatar=avatar;avatar.media=self;self.metadata={};self.acks=set()
    def __getattr__(self,name):return getattr(self.output,name)
    def configure_session(self,config):self.output.configure_session(config)
    def _webrtc(self):
        if hasattr(self.output,'peers'):return self.output
        for c in getattr(self.output,'channels',[]):
            if c.name=='webrtc':return c.output
        return None
    def has_peer(self):
        sink=self._webrtc()
        return bool(sink and any(p.connection.connectionState=='connected' for p in sink.peers))
    async def start(self):await self.output.start();self.avatar._start_idle()
    async def push_audio(self,chunk):
        sink=self._webrtc();pipeline=self.avatar.pipeline
        before={id(p):p.audio.enqueued for p in sink.peers} if sink else {}
        await self.output.push_audio(chunk)
        if pipeline and hasattr(self.output,'channels'):
            for channel in self.output.channels:
                if channel.name=='webrtc':await asyncio.wait_for(channel.audio.join(),2)
        if not pipeline or not sink:return
        sample=pipeline.origin+pipeline.delivered-len(chunk.pcm)//2
        targets=[(p,p.audio.enqueued) for p in sink.peers if p.audio.enqueued>before.get(id(p),0)]
        async def ack_audio():
            while self.avatar.running and chunk.generation_id==self.avatar.generation_id:
                for peer,target in targets:
                    if peer.audio.consumed>=target:
                        self.avatar.log('AudioActuallyConsumed',job_id=pipeline.job_id,first_sample_index=sample,consumed_monotonic_s=peer.audio.last_recv_monotonic)
                        return
                await asyncio.sleep(.005)
        if targets:
            task=asyncio.create_task(ack_audio());self.acks.add(task);task.add_done_callback(self.acks.discard)
    async def push_video(self,frame):
        packet=self.metadata.pop(id(frame),None);sink=self._webrtc()
        await self.output.push_video(frame)
        if packet is not None and hasattr(self.output,'channels'):
            for channel in self.output.channels:
                if channel.name=='webrtc':
                    await asyncio.wait_for(channel.video.join(),2)
        if packet is None:return
        self.avatar.last_frame=packet
        self.avatar.log('FrameEnqueued',source=packet['source'],activity=packet.get('activity'),marker=packet.get('marker'),pts_us=frame.pts_us)
        if packet['source']!='GPU_INFERENCE':return
        # MVP targets one actual WebRTC peer, not Fanout admission or queue emptiness.
        targets=[(p,p.video.enqueued) for p in sink.peers] if sink else []
        if not targets:raise WorkerUnavailable('no playback consumer for GPU credit')
        async def ack():
            generation=frame.generation_id
            while self.avatar.running and generation==self.avatar.generation_id:
                if any(p in sink.peers and p.video.generation_id==generation and p.video.consumed>=target for p,target in targets):
                    try:await self.avatar.link.consumed(packet)
                    except WorkerUnavailable as exc:
                        self.avatar.log('CreditLinkUnavailable',reason=str(exc));self.avatar.degraded=True
                        if self.avatar.pipeline:await self.avatar.pipeline.degrade()
                        return
                    cached=self.avatar.cached_idle
                    if packet.get('activity')=='IDLE' and (cached is None or (packet['generation_id'],packet['frame_sequence'])>(cached['generation_id'],cached['frame_sequence'])):self.avatar.cached_idle=packet
                    self.avatar.log('FrameActuallyConsumed',pts_us=frame.pts_us,consumed_monotonic_s=next(p.video.last_recv_monotonic for p,target in targets if p.video.consumed>=target),source='GPU_INFERENCE',job_id=packet['generation_id'],frame_sequence=packet['frame_sequence'],marker=packet.get('marker'))
                    return
                if not any(p in sink.peers and p.connection.connectionState not in {'failed','closed','disconnected'} for p,_ in targets):return
                await asyncio.sleep(.005)
        task=asyncio.create_task(ack());self.acks.add(task);task.add_done_callback(self.acks.discard)
    async def invalidate(self,generation):
        for task in tuple(self.acks):task.cancel()
        await asyncio.gather(*tuple(self.acks),return_exceptions=True);self.metadata.clear()
        await self.output.interrupt(generation)
    async def interrupt(self,generation):
        await self.invalidate(generation)
        # Reversible authorized idle cache. Never relabel it as new GPU inference.
        cached=self.avatar.cached_idle
        if cached:
            packet=dict(cached,source='CACHED_IDLE',pts_us=self.avatar.timeline_samples*1000000//16000,marker=0x4000)
            await self.output.push_video(self.avatar.convert(packet));self.avatar.log('CachedIdlePlaceholder')
        self.avatar._start_idle()
    async def drain(self,generation):await self.output.drain(generation)
    async def stop(self):
        for task in tuple(self.acks):task.cancel()
        await asyncio.gather(*tuple(self.acks),return_exceptions=True);await self.output.stop()
