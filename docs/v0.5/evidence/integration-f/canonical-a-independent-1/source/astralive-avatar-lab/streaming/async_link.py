"""Private async Worker client. Ready-only admission; epoch/job fenced H264."""
import asyncio,collections,fractions,json,pathlib,struct,time
import av
from prefetch import WorkerUnavailable
from wire import MAX_HEADER,MAX_PAYLOAD

class WorkerLink:
    def __init__(self,token_file,log=lambda *a,**k:None):
        self.token_file=token_file;self.log=log;self.writer=None;self.reader=None;self.rx=None;self.health_task=None
        self.job_lock=asyncio.Lock();self.cancelling_gid=None;self.last_video_progress_at=None;self.video_stall_window=5.0;self.health_requests={};self.last_health=None
        self.lock=asyncio.Lock();self.cv=asyncio.Condition();self.frames=asyncio.Queue(4)
        self.active=None;self.epoch=None;self.ready=None;self.error=None;self.available=0;self.pending={}
        self.finished=asyncio.Event();self.cancelled=asyncio.Event();self.decoder=None;self.received=0;self.sent=0;self.eof=False;self.ready_times=collections.deque(maxlen=8);self.credit_lock=asyncio.Lock();self.consumed_ready=set();self.last_ack=-1
    async def _write(self,h,p=b''):
        if self.error:raise WorkerUnavailable(self.error)
        encoded=json.dumps(h,separators=(',',':')).encode()
        if len(encoded)>MAX_HEADER or len(p)>MAX_PAYLOAD:raise ValueError('oversize private packet')
        async with self.lock:
            try:
                self.writer.write(struct.pack('!II',len(encoded),len(p))+encoded+p)
                await asyncio.wait_for(self.writer.drain(),5)
            except (OSError,ConnectionError,asyncio.TimeoutError) as e:raise WorkerUnavailable(type(e).__name__) from e
    async def _read(self):
        h,p=struct.unpack('!II',await self.reader.readexactly(8))
        if h>MAX_HEADER or p>MAX_PAYLOAD:raise WorkerUnavailable('oversize worker response')
        return json.loads(await self.reader.readexactly(h)),await self.reader.readexactly(p)
    async def connect(self):
        try:
            self.reader,self.writer=await asyncio.wait_for(asyncio.open_connection('127.0.0.1',17087),1)
            await self._write(dict(type='Auth',protocol_version=1,token=pathlib.Path(self.token_file).read_text().strip()))
            self.ready,_=await asyncio.wait_for(self._read(),5)
            if self.ready.get('type')!='GPU_WORKER_READY':raise WorkerUnavailable('worker has not completed warmup')
            self.epoch=self.ready['worker_epoch'];self.rx=asyncio.create_task(self._receive_loop());self.health_task=asyncio.create_task(self._health())
            await self._write(dict(type='PrepareAvatar',avatar_id='official-girl',input_asset_sha256=self.ready['input_asset_sha256']))
            self.log('GPU_WORKER_READY',worker_epoch=self.epoch)
        except Exception as e:
            await self.close();raise WorkerUnavailable(type(e).__name__) from e
    async def begin(self,gid,origin):
        async with self.job_lock:
            await self._begin(gid,origin)
    async def _begin(self,gid,origin):
        if self.writer is None or self.error:raise WorkerUnavailable(self.error or 'worker disconnected')
        if self.active is not None:raise ValueError('overlapping worker jobs')
        self.active=gid;self.finished=asyncio.Event();self.cancelled=asyncio.Event();self.sent=self.received=0;self.eof=False;self.available=0;self.pending.clear();self.ready_times.clear();self.consumed_ready.clear();self.last_ack=-1;self.last_video_progress_at=None
        self.decoder=av.CodecContext.create('h264','r');self.decoder.thread_count=1;self.decoder.open()
        await self._write(dict(type='BeginGeneration',generation_id=gid,cache_id=self.ready['cache_id'],sample_rate=16000,channels=1,pcm_format='s16le',first_sample_index=origin,output_fps=25))
    async def send_audio(self,gid,seq,index,pcm,final):
        count=len(pcm)//2
        async with self.cv:
            while self.available<count:
                self._check(gid)
                await self.cv.wait()
            self._check(gid);self.available-=count;self.pending[seq]=count
        before=self.sent;self.sent+=count;self.eof=final
        for boundary in range((before//15360+1)*15360,self.sent+1,15360):self.ready_times.append((boundary,time.monotonic()))
        if final:self.ready_times.append((self.sent,time.monotonic()))
        await self._write(dict(type='AudioChunk',generation_id=gid,sample_rate=16000,channels=1,pcm_format='s16le',chunk_sequence=seq,first_sample_index=index,sample_count=count,final_chunk=final),pcm)
    def _check(self,gid):
        if self.error or self.active!=gid:raise WorkerUnavailable(self.error or 'worker job invalidated')
    async def receive(self,gid):
        waiting_since=None
        while True:
            self._check(gid)
            try:return self.frames.get_nowait()
            except asyncio.QueueEmpty:pass
            async with self.cv:
                self._check(gid)
                if not self.frames.empty():continue
                required=((self.received//24)+1)*15360
                if self.eof:required=min(required,self.sent)
                ready=next((stamp for end,stamp in self.ready_times if end>=required),None)
                # Source admission can precede paced playout by many seconds. A
                # bounded consumer/credit wait is not a dead GPU. Only age a period
                # with a ready horizon and no newly decoded video progress.
                if ready is not None:
                    now=time.monotonic()
                    if waiting_since is None:waiting_since=now
                    progress=max(waiting_since,self.last_video_progress_at or waiting_since)
                    if now-progress>self.video_stall_window:
                        self.log('VideoProgressStalled',generation_id=gid,required_samples=required,sent_samples=self.sent,received_frames=self.received,last_ack=self.last_ack,wait_without_progress_s=now-progress,source_horizon_age_s=now-ready)
                        raise WorkerUnavailable('expected video progress stalled')
                try:await asyncio.wait_for(self.cv.wait(),.05)
                except asyncio.TimeoutError:pass
    async def consumed(self,packet):
        if packet['generation_id']!=self.active:return
        async with self.credit_lock:
            if packet['generation_id']!=self.active:return
            self.consumed_ready.add(packet['frame_sequence'])
            while self.last_ack+1 in self.consumed_ready:
                seq=self.last_ack+1
                await self._write(dict(type='Credit',generation_id=self.active,latest_consumed_sequence=seq))
                self.consumed_ready.remove(seq);self.last_ack=seq
    async def complete(self,gid):
        while not self.finished.is_set():
            self._check(gid)
            try:await asyncio.wait_for(self.finished.wait(),.1)
            except asyncio.TimeoutError:pass
    async def cancel(self,gid):
        async with self.job_lock:
            await self._cancel(gid)
    async def _cancel(self,gid):
        if self.active!=gid:return
        normal=self.finished.is_set();self.active=None
        while not self.frames.empty():self.frames.get_nowait()
        async with self.cv:self.pending.clear();self.available=0;self.cv.notify_all()
        if self.error:return
        if not normal:
            self.cancelling_gid=gid
            try:
                await self._write(dict(type='CancelGeneration',generation_id=gid))
                await asyncio.wait_for(self.cancelled.wait(),2)
            except asyncio.TimeoutError:raise WorkerUnavailable('cancel acknowledgment timeout')
            finally:self.cancelling_gid=None
    async def _receive_loop(self):
        try:
            while True:
                h,p=await asyncio.wait_for(self._read(),5)
                if h['worker_epoch']!=self.epoch:raise WorkerUnavailable('worker epoch changed')
                kind=h['type']
                if kind=='VideoPacket':
                    if h['generation_id']!=self.active:
                        self.log('StaleWorkerFrameRejected',generation_id=h['generation_id']);continue
                    if h['frame_sequence']!=self.received:raise WorkerUnavailable('worker frame sequence gap')
                    if self.received==0 and not h['keyframe_flag']:raise WorkerUnavailable('missing generation IDR')
                    packet=av.Packet(p);packet.pts=packet.dts=h['frame_sequence'];packet.time_base=fractions.Fraction(1,25)
                    decoded=self.decoder.decode(packet)
                    if len(decoded)!=1 or decoded[0].pts!=h['frame_sequence']:raise WorkerUnavailable('decode/PTS failure')
                    image=decoded[0].to_ndarray(format='rgb24')
                    h.update(rgb=image.tobytes(),width=image.shape[1],height=image.shape[0],source='GPU_INFERENCE')
                    self.frames.put_nowait(h);self.received+=1;self.last_video_progress_at=time.monotonic()
                    self.log('WorkerFrameDecoded',generation_id=self.active,frame_sequence=h['frame_sequence'],pts_us=h['pts_us'])
                elif kind=='GenerationBegun' and h['generation_id']==self.active:self.available=h['audio_credit_samples']
                elif kind=='AudioAccepted' and h['generation_id']==self.active:
                    self.pending.pop(h['chunk_sequence'],None);self.available=max(0,h['audio_credit_samples']-sum(self.pending.values()))
                elif kind=='GenerationComplete' and h['generation_id']==self.active:self.finished.set()
                elif kind=='GenerationCancelled' and h['generation_id']==self.cancelling_gid:self.cancelled.set()
                elif kind=='Health':
                    self.last_health={k:v for k,v in h.items() if k!='token'}
                    stamp=self.health_requests.pop(h.get('nonce'),None)
                    if stamp is not None:self.last_health['rtt_ms']=(time.monotonic()-stamp)*1000
                    if h.get('nonce',0)%20==0:self.log('WorkerHealthSnapshot',**self.last_health)
                    if not h['ready']:raise WorkerUnavailable(h.get('error') or 'unhealthy worker')
                    if h.get('active_generation_id')==self.active:
                        # Accepted audio credits can reach zero while the GPU subsequently
                        # drains PCM. Refresh from this ordered snapshot; pending sends
                        # after the Health request still reserve their own samples.
                        self.available=max(0,32000-round(h['audio_queue_ms']*16)-sum(self.pending.values()))
                async with self.cv:self.cv.notify_all()
        except asyncio.CancelledError:pass
        except Exception as e:
            self.error=str(e) or type(e).__name__;self.log('WorkerUnavailable',reason=self.error)
            async with self.cv:self.cv.notify_all()
    async def _health(self):
        nonce=0
        try:
            while True:
                await asyncio.sleep(.5);nonce+=1;self.health_requests[nonce]=time.monotonic()
                if len(self.health_requests)>32:self.health_requests.pop(next(iter(self.health_requests)))
                await self._write(dict(type='Health',nonce=nonce))
        except (WorkerUnavailable,asyncio.CancelledError):pass
    async def close(self):
        for task in (self.rx,self.health_task):
            if task:task.cancel()
        await asyncio.gather(*(t for t in (self.rx,self.health_task) if t),return_exceptions=True)
        if self.writer:
            self.writer.close()
            try:await self.writer.wait_closed()
            except OSError:pass
        self.writer=None
