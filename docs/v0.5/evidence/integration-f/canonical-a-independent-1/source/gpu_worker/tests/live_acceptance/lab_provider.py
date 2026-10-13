"""Acceptance-only wiring and source capture; no production default or public API changes."""
import importlib, json, os, pathlib, sys, types, wave, contextvars
# The isolated uvicorn package is app; preserve class identity for validated adapters.
import app
runtime = types.ModuleType('runtime'); runtime.app = app; runtime.__path__ = []
sys.modules['runtime'] = runtime; sys.modules['runtime.app'] = app
for name in ('providers','lightweight_avatar','rtmp_media'):
    sys.modules['runtime.app.'+name] = importlib.import_module('app.'+name)
from gpu_worker.runtime_adapter import RemoteAvatarEngine as ProductAvatar
from gpu_worker.validated.runtime_avatar import ConsumptionMediaOutput
from gpu_worker.client import resolve_binding
from gpu_worker.config import Config

ROOT=pathlib.Path(os.environ['SOULX_EXPERIMENT_DIR'])
class RemoteAvatarEngine(ProductAvatar):
    def __init__(self):
        cfg=Config(**json.loads((ROOT/'.private/log-config.json').read_text()))
        fixture=json.loads((ROOT/'.private/binding-fixture.json').read_text())
        endpoint=resolve_binding(fixture['binding'],ROOT/'.private/registry.json',fixture['scope'])
        super().__init__(endpoint,'acceptance-pending',cfg,os.environ['AVATAR_IMAGE_PATH'])
        self.evidence=ROOT/'integration';self.journal=(self.evidence/'avatar-events.jsonl').open('a',buffering=1)
        self.wave_files={};self.capture_scope=contextvars.ContextVar('acceptance_pcm_capture',default=None)
    def set_session_id(self,sid):self.session_id=sid
    def log(self,event,**kw):
        super().log(event,**kw)
        safe={k:v for k,v in kw.items() if k not in {'reason','traceback','error'}}
        self.journal.write(json.dumps(dict(event=event,monotonic_s=__import__('time').monotonic(),business_generation_id=self.generation_id,**safe))+'\n')
        if event=='BeginSpeechJob':
            raw=(self.evidence/f"speech-{kw['job_id']}.wav").open('wb',buffering=0);f=wave.open(raw,'wb');f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'');self.wave_files[kw['job_id']]=(f,raw)
            scope=self.capture_scope.get()
            if scope is not None:scope.append(kw['job_id'])
    async def stream_audio(self,source,generation_id):
        scope=[];self.capture_scope.set(scope)
        try:
            async for chunk in super().stream_audio(source,generation_id):
                if scope and scope[-1] in self.wave_files:self.wave_files[scope[-1]][0].writeframes(chunk.pcm)
                yield chunk
        finally:
            for job in scope:
                pair=self.wave_files.pop(job,None)
                if pair:pair[0].close();pair[1].close()
            self.capture_scope.set(None)
    async def stop(self):
        await super().stop()
        for f,raw in self.wave_files.values():f.close();raw.close()
        self.wave_files.clear();self.journal.close()
