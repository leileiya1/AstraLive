import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from gpu_worker.config import secret,digest
from gpu_worker.client import resolve_binding
from gpu_worker.telemetry import logger

class Tests(unittest.TestCase):
    def test_secret_permissions_and_registry_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); token=root/'token'; token.write_text('x'*64);token.chmod(0o600)
            self.assertEqual(secret(token),'x'*64)
            scope={'tenantId':'tenant-a','userId':'user-a'}
            endpoint={'port':17087,'tokenFile':str(token),'avatarRef':'portrait','assetSHA256':'a'*64,'allowedScopes':[scope]}
            registry=root/'registry.json';registry.write_text(json.dumps({'registryVersion':'1.0','workers':{'w':endpoint}}))
            binding={'profiles':[{'kind':'AVATAR','provider':'soulx','profileId':'a','config':{'avatarRef':'portrait','workerProfileId':'p'}},{'kind':'GPU_WORKER','provider':'soulx','profileId':'p','config':{'workerRef':'w'}}]}
            self.assertEqual(resolve_binding(binding,registry,scope),endpoint)
            with self.assertRaises(ValueError):resolve_binding(binding,registry,{'tenantId':'tenant-a','userId':'user-b'})
            binding['profiles'][0]['config']['workerProfileId']='foreign'
            with self.assertRaises(ValueError):resolve_binding(binding,registry,scope)
            token.chmod(0o644)
            with self.assertRaises(ValueError):secret(token)

    def test_pinned_manifest_and_all_weight_sha256_before_model_import(self):
        import dataclasses,sys
        from gpu_worker.config import Config
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'reports').mkdir()
            image=root/'portrait.png';image.write_bytes(b'test-only-asset')
            weights=root/'models/soulx/SoulX-FlashHead-1_3B';weights.mkdir(parents=True)
            records=[]
            for i in range(7):
                file=weights/f'test-{i}.json';file.write_bytes(b'test-only-weight-placeholder')
                records.append(dict(repo='Soul-AILab/SoulX-FlashHead-1_3B',file=file.name,sha256=digest(file)))
            manifest=root/'reports/soulx-weight-manifest.json';manifest.write_text(json.dumps(records))
            inference=root/'inference-token';management=root/'management-token'
            inference.write_text('i'*64);management.write_text('m'*64)
            inference.chmod(0o600);management.chmod(0o600)
            cfg=Config(worker_ref='w',avatar_ref='a',asset_path=str(image),asset_sha256=digest(image),lab_root=str(root),state_dir=str(root/'state'),token_file=str(inference),manifest_sha256=digest(manifest),python=sys.executable,management_token_file=str(management))
            cfg.validate();self.assertEqual(cfg.verify_assets(),digest(manifest))
            (weights/'test-3.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'WEIGHT_SHA256_MISMATCH'):cfg.verify_assets()
            with self.assertRaisesRegex(ValueError,'MANIFEST_SHA256_MISMATCH'):dataclasses.replace(cfg,manifest_sha256='a'*64).verify_assets()

    def test_rotated_logs_redact_and_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=SimpleNamespace(state_dir=tmp,log_bytes=256,log_backups=2)
            log=logger(cfg,'redaction',('sensitive-test-token',))
            for _ in range(50):log.info('sensitive-test-token https://example.test/path?key=secret Bearer xyz sk-abc')
            files=list(Path(tmp).glob('redaction.log*'))
            self.assertLessEqual(len(files),3)
            for f in files:
                text=f.read_text()
                for s in ('sensitive-test-token','example.test','Bearer xyz','sk-abc'):self.assertNotIn(s,text)
            for h in log.handlers[:]:log.removeHandler(h);h.close()

    def test_validated_algorithm_copies(self):
        root=Path(__file__).resolve().parents[2]
        for name in ('adapter.py','wire.py','prefetch.py'):
            self.assertEqual((root/'gpu_worker/validated'/name).read_bytes(),(root/'astralive-avatar-lab/streaming'/name).read_bytes())
        a=(root/'gpu_worker/validated/async_link.py').read_text().replace('from .prefetch import','from prefetch import').replace('from .wire import','from wire import')
        self.assertEqual(a,(root/'astralive-avatar-lab/streaming/async_link.py').read_text())
        a=(root/'gpu_worker/validated/resample.py').read_text().replace('from .prefetch import','from prefetch import')
        self.assertEqual(a,(root/'astralive-avatar-lab/streaming/resample.py').read_text())

if __name__=='__main__':unittest.main()

class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_readiness_closes_socket_without_orphan_tasks(self):
        import asyncio,struct
        from gpu_worker.client import WorkerLink
        with tempfile.TemporaryDirectory() as tmp:
            token=Path(tmp)/'token';token.write_text('x'*64);token.chmod(0o600)
            authenticated=asyncio.Event();closed=asyncio.Event()
            async def hold_ready(reader,writer):
                try:
                    header,payload=struct.unpack('!II',await reader.readexactly(8))
                    await reader.readexactly(header+payload)
                    authenticated.set()
                    self.assertEqual(await reader.read(),b'')
                    closed.set()
                finally:
                    writer.close();await writer.wait_closed()
            server=await asyncio.start_server(hold_ready,'127.0.0.1',0)
            port=server.sockets[0].getsockname()[1]
            link=WorkerLink(dict(port=port,tokenFile=str(token),avatarRef='a',assetSHA256='a'*64),'session-a')
            task=asyncio.create_task(link.connect())
            try:
                await asyncio.wait_for(authenticated.wait(),2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                await asyncio.wait_for(closed.wait(),2)
                self.assertIsNone(link.writer)
                self.assertIsNone(link.rx)
                self.assertIsNone(link.health_task)
            finally:
                await link.close()
                server.close();await server.wait_closed()
