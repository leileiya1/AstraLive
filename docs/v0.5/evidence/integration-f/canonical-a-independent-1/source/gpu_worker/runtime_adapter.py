"""Opt-in bound provider. Existing Runtime defaults and accepted sinks remain unchanged."""
import asyncio
import collections
import json
from pathlib import Path
import time
from runtime.app.lightweight_avatar import LightweightAvatarEngine
from .client import WorkerLink, resolve_binding
from .telemetry import logger
from .validated.prefetch import WorkerUnavailable
from .validated.runtime_avatar import RemoteAvatarEngine as ValidatedAvatar, ConsumptionMediaOutput
from .validated.paired_rtmp import PairedRTMPMediaOutput


class RemoteAvatarEngine(ValidatedAvatar):
    def __init__(self, endpoint, session_id, log_config, image_path=None):
        self.running=False; self.generation_id=1; self.timeline_samples=0
        self.pipeline=self.idle_task=self.media=None
        self.speaking=self.degraded=False; self.marker=0
        self.config=self.link=self.cached_idle=self.first_pcm=self.last_frame=None
        self.endpoint,self.session_id=endpoint,session_id
        self.recovery_window_s=log_config.startup_timeout_s
        self.light=LightweightAvatarEngine(image_path)
        self.recovery_task=None; self.recovery_candidate=None; self.recovery_attempted=False
        self.logfile=logger(log_config,'avatar-'+log_config.worker_ref)

    def log(self,event,**kw):
        # Only static reason codes and numeric/media identifiers, never exception strings.
        safe={k:v for k,v in kw.items() if k not in {'reason','traceback','error'}}
        self.logfile.info(json.dumps(dict(event=event,business_generation_id=self.generation_id,monotonic_s=time.monotonic(),**safe)))

    async def prepare(self,config):
        await self.light.prepare(config)
        self.link=WorkerLink(self.endpoint,self.session_id,self.log)
        try:
            if self.config.fps!=25:raise WorkerUnavailable('remote requires 25fps')
            await self.link.connect()
        except WorkerUnavailable:
            self.degraded=True
            self.log('ProviderDegraded')

    async def _fallback(self,chunk,first_sample,next_frame_sample):
        self._schedule_recovery()
        return await super()._fallback(chunk,first_sample,next_frame_sample)

    def _schedule_recovery(self):
        if self.recovery_attempted or not self.running:return
        self.recovery_attempted=True
        async def recover():
            try:
                # Cancellation happens inside PrefetchPipeline.degrade before fallback rendering.
                candidate=await self.link.reconnect(attempts=24,recovery_window_s=self.recovery_window_s)
                if not self.running:
                    await candidate.close()
                    return
                self.recovery_candidate=candidate
                self.log('WorkerRecoveryReady')
            except WorkerUnavailable:
                self.log('WorkerRecoveryExhausted')
        self.recovery_task=asyncio.create_task(recover())

    async def stream_audio(self,source,generation_id):
        # Promote only at a new speech boundary. Current fallback job stays local.
        if self.recovery_candidate and generation_id==self.generation_id and self.running:
            await self._stop_idle()
            previous=self.pipeline
            if previous:await previous.cancel()
            if self.pipeline is previous:self.pipeline=None
            self.link,self.recovery_candidate=self.recovery_candidate,None
            self.degraded=False
            self.recovery_attempted=False
            self.log('WorkerRecoveryPromoted')
        async for chunk in super().stream_audio(source,generation_id):
            yield chunk

    async def stop(self):
        self.running=False
        if self.recovery_task:
            self.recovery_task.cancel()
            await asyncio.gather(self.recovery_task,return_exceptions=True)
        if self.recovery_candidate:
            await self.recovery_candidate.close()
            self.recovery_candidate=None
        if self.pipeline:await self.pipeline.cancel()
        await self._stop_idle()
        if self.link:await self.link.close()
        await self.light.stop()
        self.log('ProviderStopped')
        # Shared rotating logger has one fixed filename per logical worker.


class ClockJournal:
    def __init__(self,log_config):self.log=logger(log_config,'paired-clock')
    def write(self,value):self.log.info(value.rstrip())
    def close(self):
        for h in self.log.handlers[:]:self.log.removeHandler(h);h.close()


def bound_factories(binding,registry_path,scope,session_id,log_config,llm_factory,tts_factory,media_factory,image_path=None):
    """Integration entry point for an AUTHORIZED pinned binding, not a new binding API.

    Factory group admits one Session. Its binding is immutable and resolved by Go.
    Caller owns release/expiry and Session route integration.
    """
    endpoint=resolve_binding(binding,registry_path,scope)
    pair={}
    def avatar_factory():
        if pair:raise RuntimeError('bound factory group already assigned')
        avatar=RemoteAvatarEngine(endpoint,session_id,log_config,image_path)
        pair['avatar']=avatar
        return avatar
    def wrapped_media():
        return ConsumptionMediaOutput(media_factory(),pair['avatar'])
    return llm_factory,tts_factory,avatar_factory,wrapped_media
