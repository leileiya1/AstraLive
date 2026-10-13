import dataclasses
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from gpu_worker.config import Config
from gpu_worker.doctor import inspect
from gpu_worker.hardware import validate_gpu
from gpu_worker.install import install, verify_bundle
from gpu_worker.release import build


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root/'bundle'
        self.release = build(self.bundle)
        self.install_root = self.root/'installed'

    def tearDown(self):
        self.temp.cleanup()

    def setup_install(self):
        return install(self.bundle, self.install_root, mode='simulation', python=sys.executable, port=port(), management_port=port())

    def command(self, action):
        return subprocess.run([str(self.install_root/'bin/astralive-worker'), action], capture_output=True, text=True, timeout=45)

    def test_install_preserves_secrets_config_and_rejects_tamper(self):
        first = self.setup_install()
        config = self.install_root/'config/worker.json'
        token = self.install_root/'secrets/worker-token'
        before = (config.read_bytes(), token.read_bytes())
        install(self.bundle, self.install_root)
        self.assertEqual(before, (config.read_bytes(), token.read_bytes()))
        self.assertEqual(token.stat().st_mode & 0o777, 0o600)
        self.assertFalse(first['ready'])
        self.assertFalse(first['modelLoaded'])
        self.assertFalse((self.bundle/'gpu_worker/tests').exists())
        self.assertFalse((self.bundle/'gpu_worker/evidence').exists())
        with (self.bundle/'gpu_worker/service.py').open('a') as f:
            f.write('\n# corrupted\n')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            verify_bundle(self.bundle)

    def test_one_command_ready_restart_upgrade_and_stop(self):
        self.setup_install()
        self.assertEqual(self.command('doctor').returncode, 0)
        try:
            start = self.command('start')
            self.assertEqual(start.returncode, 0, start.stdout+start.stderr)
            first = json.loads(self.command('status').stdout)
            self.assertTrue(first['ready'])
            with self.assertRaisesRegex(ValueError, 'STOP_WORKER'):
                install(self.bundle, self.install_root)
            result = self.command('restart')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            second = json.loads(self.command('status').stdout)
            self.assertNotEqual(first['workerEpoch'], second['workerEpoch'])
            self.assertEqual(first['avatarCacheStatus']['cacheId'], second['avatarCacheStatus']['cacheId'])
            self.assertTrue(second['avatarCacheStatus']['metadataRestored'])
        finally:
            self.assertEqual(self.command('stop').returncode, 0)
        self.assertFalse((self.install_root/'state/control.sock').exists())
        # Changed code installs atomically and retains previous release; config unchanged.
        (self.bundle/'gpu_worker/__init__.py').write_text('# upgraded\n')
        manifest = json.loads((self.bundle/'MANIFEST.json').read_text())
        manifest['files']['gpu_worker/__init__.py'] = hashlib.sha256((self.bundle/'gpu_worker/__init__.py').read_bytes()).hexdigest()
        manifest['releaseId'] = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        (self.bundle/'MANIFEST.json').write_text(json.dumps(manifest))
        cfg = (self.install_root/'config/worker.json').read_bytes()
        install(self.bundle, self.install_root)
        self.assertEqual((self.install_root/'previous').resolve().name, self.release)
        self.assertEqual((self.install_root/'current').resolve().name, manifest['releaseId'])
        self.assertEqual((self.install_root/'config/worker.json').read_bytes(), cfg)

    def test_reboot_stale_socket_does_not_block_start_or_stop(self):
        self.setup_install()
        state = self.install_root/'state'
        state.mkdir(exist_ok=True)
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(str(state/'control.sock'))
        (state/'supervisor.json').write_text(json.dumps({'status': 'READY', 'supervisorPid': 99999999}))
        # No PID signals: a stale socket and old READY snapshot are not liveness.
        before = (self.install_root/'config/worker.json').read_bytes()
        install(self.bundle, self.install_root)
        self.assertEqual((self.install_root/'config/worker.json').read_bytes(), before)
        stopped = self.command('stop')
        self.assertEqual(stopped.returncode, 0, stopped.stdout+stopped.stderr)
        try:
            started = self.command('start')
            self.assertEqual(started.returncode, 0, started.stdout+started.stderr)
            again = self.command('start')
            self.assertNotEqual(again.returncode, 0)
            self.assertIn('ALREADY_RUNNING', again.stdout)
            self.assertTrue(json.loads(self.command('status').stdout)['ready'])
        finally:
            self.command('stop')

    def test_gpu_preflight_missing_assets_never_starts_worker(self):
        install(self.bundle, self.install_root, python=sys.executable, lab_root=str(self.root/'empty-lab'))
        result = self.command('start')
        self.assertEqual(result.returncode, 78)
        self.assertFalse((self.install_root/'state/control.sock').exists())
        self.assertFalse((self.install_root/'state/supervisor.json').exists())
        self.assertFalse(json.loads(result.stdout)['preflightPassed'])

    def test_pinned_architecture_gate(self):
        for available, capability, error in ((False, (0, 0), 'GPU_UNAVAILABLE'), (True, (7, 5), 'GPU_ARCHITECTURE_UNSUPPORTED'), (True, (10, 0), 'GPU_ARCHITECTURE_UNSUPPORTED')):
            fake = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available, get_device_capability=lambda: capability))
            with self.assertRaisesRegex(RuntimeError, error):
                validate_gpu(fake)
        for major in (8, 9):
            validate_gpu(SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_capability=lambda: (major, 0))))

    def test_build_release_from_installed_code_retains_sample(self):
        self.setup_install()
        target = self.root/'rebuilt'
        proc = subprocess.run([sys.executable, '-B', '-m', 'gpu_worker.release', '--out', str(target)],
                              cwd=self.install_root/'current', capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        self.assertTrue((target/'sample-avatar.png').is_file())
        verify_bundle(target)


if __name__ == '__main__':
    unittest.main()
