"""Lab-only paired media clock. Source audio and video advance together.

The production FFmpeg command, output provider and public contract stay intact.
For 16k PCM at 25fps, each GPU frame owns 640 samples (40ms). On
underflow, repeat the previous image and output silence as one paired tick.
"""
import asyncio,json,os,pathlib,time,hashlib
from runtime.app.rtmp_media import FFmpegRTMPMediaOutput

class PairedRTMPMediaOutput(FFmpegRTMPMediaOutput):
    def __init__(self,settings,clock_log):
        super().__init__(settings)
        if settings.fps!=25 or settings.audio_sample_rate!=48000:
            raise ValueError('paired experimental clock requires 25fps / 48k output')
        self.paired_ticks=0;self.pair_underflow_ticks=0;self.last_source_pts=None
        self.pipe_audio=asyncio.Queue(2);self.pipe_video=asyncio.Queue(2);self.clock_closing=False
        self.clock_log=clock_log
    async def push_video(self,frame):
        if not self.running or frame.generation_id!=self.generation_id:return
        payload=await asyncio.to_thread(self._scale_and_pad,frame,self.settings.width,self.settings.height)
        if frame.generation_id!=self.generation_id:return
        self.video_enqueued+=1;self.video_enqueued_total+=1
        await self.video_queue.put((frame.generation_id,payload,frame.pts_us))
    def _next_pair(self):
        # Never consume just one media timeline. PCM grouping is exact, not a
        # fixed audio delay; both tracks get identical filler duration if empty.
        if self.audio_queue.qsize()<2 or self.video_queue.empty():return None
        ga,a=self.audio_queue.get_nowait();gb,b=self.audio_queue.get_nowait();gv,v,pts=self.video_queue.get_nowait()
        self.audio_queue.task_done();self.audio_queue.task_done();self.video_queue.task_done()
        if ga!=self.generation_id or gb!=self.generation_id or gv!=self.generation_id:
            self.audio_dropped+=2;self.video_dropped+=1;return None
        self.audio_consumed+=2;self.audio_consumed_total+=2;self.video_consumed+=1;self.video_consumed_total+=1
        self.last_source_pts=pts;self._latest_video=v
        return a+b,v,pts
    async def _pipe_writer(self,queue,fd_name):
        while True:
            payload=await queue.get()
            try:await self._write_fd(getattr(self,fd_name),payload)
            except asyncio.TimeoutError:
                self.write_failures+=1;await self._abort_process('paired_write_timeout')
            finally:queue.task_done()
    async def _audio_clock(self):
        period=1/self.settings.fps;silence=bytes(round(self.settings.audio_sample_rate*period)*2);next_at=time.monotonic()
        writers=[asyncio.create_task(self._pipe_writer(self.pipe_audio,'_audio_fd')),asyncio.create_task(self._pipe_writer(self.pipe_video,'_video_fd'))]
        try:
            while self.running and not self.clock_closing:
                await asyncio.sleep(max(0,next_at-time.monotonic()))
                if not self.running or self.clock_closing:break
                next_at+=period
                if next_at<time.monotonic()-period:next_at=time.monotonic()+period
                pair=self._next_pair()
                if pair is None:self.pair_underflow_ticks+=1;audio,video,pts=silence,self._latest_video,None
                else:audio,video,pts=pair
                # FFmpeg may need more than one PCM quantum while opening a large
                # rawvideo input. Separate bounded writers permit that demux read
                # without allowing either source timeline to advance independently.
                await asyncio.gather(self.pipe_audio.put(audio),self.pipe_video.put(video))
                self.clock_log.write(json.dumps({'monotonic_s':time.monotonic(),'generation_id':self.generation_id,'tick':self.paired_ticks,'output_pts_us':self.paired_ticks*40000,'source_video_pts_us':pts,'audio_samples':len(audio)//2,'filler':pair is None})+'\n');self.paired_ticks+=1
            await asyncio.wait_for(asyncio.gather(self.pipe_audio.join(),self.pipe_video.join()),2)
        finally:
            for task in writers:task.cancel()
            await asyncio.gather(*writers,return_exceptions=True)
    async def _video_clock(self):
        # The paired task is the sole writer for both pipes.
        return
    async def interrupt(self,generation_id):
        idle=self._latest_video
        await super().interrupt(generation_id)
        self._latest_video=idle;self.last_source_pts=None
    async def stop(self):
        self.clock_closing=True
        if self._audio_clock_task:
            try:await asyncio.wait_for(asyncio.shield(self._audio_clock_task),2.5)
            except asyncio.TimeoutError:pass
        await super().stop()
        for q in [self.audio_queue,self.video_queue]:
            while not q.empty():q.get_nowait();q.task_done()
        self._audio_pending.clear();self.clock_log.close()
    def diagnostics(self):
        return {**super().diagnostics(),'clock':'source-paired-40ms','pairedTicks':self.paired_ticks,'pairUnderflowTicks':self.pair_underflow_ticks,'lastSourceVideoPts':self.last_source_pts,'pipeAudioQueue':self.pipe_audio.qsize(),'pipeVideoQueue':self.pipe_video.qsize(),'pipeQueueMaxPairs':2}
