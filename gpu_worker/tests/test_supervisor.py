import dataclasses
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from gpu_worker.tests import test_service as fixtures

class SupervisorTests(fixtures.ServiceTests):
    # Inherit real-process setup/cleanup, only execute supervisor-specific tests here.
    async def test_retry_exhaustion_no_cloud_or_infinite_restart(self):
        import asyncio
        await asyncio.to_thread(__import__('gpu_worker.cli',fromlist=['stop']).stop,self.cfg)
        await asyncio.to_thread(self.proc.wait,10)
        corrupt=json.loads(self.path.read_text())
        corrupt['asset_sha256']='b'*64
        self.path.write_text(json.dumps(corrupt))
        self.proc=subprocess.Popen([sys.executable,'-m','gpu_worker.supervisor','--config',str(self.path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        await asyncio.to_thread(self.proc.wait,20)
        self.assertEqual(self.proc.returncode,70)
        state=json.loads((self.root/'state/supervisor.json').read_text())
        self.assertEqual(state['status'],'EXHAUSTED')
        self.assertEqual(state['attempt'],1)
        self.assertEqual(json.loads((self.root/'state/worker-last-exit.json').read_text())['lastError'],'AVATAR_SHA256_MISMATCH')
        self.assertFalse((self.root/'state/control.sock').exists())

    async def test_duplicate_supervisor_refused_without_stopping_current_worker(self):
        import asyncio
        first=await self.wait_ready()
        duplicate=subprocess.Popen([sys.executable,'-m','gpu_worker.supervisor','--config',str(self.path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        code=await asyncio.to_thread(duplicate.wait,10)
        self.assertNotEqual(code,0)
        self.assertEqual((await self.wait_ready())['workerEpoch'],first['workerEpoch'])

# Avoid inherited test repetition, while retaining setup/cleanup methods.
for method in [name for name in fixtures.ServiceTests.__dict__ if name.startswith('test_')]:
    setattr(SupervisorTests,method,None)

if __name__=='__main__':unittest.main()
