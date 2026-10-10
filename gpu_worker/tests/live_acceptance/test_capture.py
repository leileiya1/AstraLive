"""CPU regression for zero-PCM FORCE and async generator cleanup across contexts."""
import asyncio,contextvars,importlib.util,io,pathlib,tempfile,unittest,wave,sys,os
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[3]))
spec=importlib.util.spec_from_file_location('lab_provider',pathlib.Path(__file__).with_name('lab_provider.py'));module=importlib.util.module_from_spec(spec)
with patch.dict(os.environ,{'SOULX_EXPERIMENT_DIR':'/tmp/unused-acceptance-capture-test'}):spec.loader.exec_module(module)
class CaptureTest(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,before_pcm):
        with tempfile.TemporaryDirectory() as temp:
            a=object.__new__(module.RemoteAvatarEngine);a.evidence=pathlib.Path(temp);a.wave_files={};a.capture_scope=contextvars.ContextVar('capture',default=None);a.generation_id=1;a.journal=io.StringIO();a.logfile=SimpleNamespace(info=lambda x:None)
            entered=asyncio.Event();wait=asyncio.Event()
            async def product_stream(self,source,generation):
                self.log('BeginSpeechJob',job_id=101,marker=1,first_sample_index=0);entered.set()
                if before_pcm:await wait.wait()
                yield SimpleNamespace(pcm=bytes(640),generation_id=1)
                await wait.wait()
            with patch.object(module.ProductAvatar,'stream_audio',product_stream):
                g=a.stream_audio(None,1);task=asyncio.create_task(anext(g));await entered.wait()
                if before_pcm:
                    # Header must already be readable while generation has no PCM.
                    with wave.open(str(a.evidence/'speech-101.wav')) as f:self.assertEqual(f.getnframes(),0)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await task
                else:
                    await task
                    # This task has a different Context from the anext() task.
                    await asyncio.create_task(g.aclose())
                self.assertEqual(a.wave_files,{})
                with wave.open(str(a.evidence/'speech-101.wav')) as f:self.assertEqual(f.getnframes(),0 if before_pcm else 320)
    async def test_force_before_first_pcm(self):await self.run_case(True)
    async def test_cross_context_generator_cleanup(self):await self.run_case(False)
if __name__=='__main__':unittest.main(verbosity=2)
