"""CCR-BC-003 config/negotiation gates; no native GPU execution."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

from gpu_worker.config import Config
from gpu_worker.staging_contract import ContractError, PROFILES
from gpu_worker.staging_service import StagingConnection


SHORT = ('staging-short-1', 'staging-short-gpu1g-1')
LONG = ('staging-segment-8s-1', 'staging-segment-8s-gpu1g-1')
GPU_ONLY = (SHORT[1], LONG[1])
GATE = 'sha256:'+'a'*64


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in (('token', 'i'*64), ('management', 'm'*64)):
            path = self.root/name
            path.write_text(value)
            path.chmod(0o600)

    def config(self, profile='staging-short-1', mode='gpu', gate=None):
        return Config(worker_ref='w', avatar_ref='a', asset_path=str(self.root/'portrait.png'),
            asset_sha256='a'*64, lab_root=str(self.root/'lab'), state_dir=str(self.root/'state'),
            token_file=str(self.root/'token'), management_token_file=str(self.root/'management'),
            manifest_sha256='a'*64, python=sys.executable, mode=mode,
            staging_profile=profile, staging_short_gate_sha256=gate)

    def connection(self, cfg, requested=None):
        worker = types.SimpleNamespace(cfg=cfg, metrics=types.SimpleNamespace(epoch='test-epoch'))
        return StagingConnection(worker, None, dict(session_id='profile-test',
            requested_limits_revision=requested or cfg.staging_profile))

    def test_existing_default_off_configuration_is_preserved(self):
        cfg = self.config(mode='simulation')
        cfg.validate()
        self.assertFalse(cfg.staging_enabled)
        self.assertEqual(cfg.staging_profile, 'staging-short-1')
        self.assertEqual(self.connection(cfg).limits, PROFILES['staging-short-1'])

    def test_short_profiles_need_no_gate_and_reject_any_gate(self):
        for name in SHORT:
            with self.subTest(profile=name):
                self.config(name).validate()
                for invalid in (GATE, '', 1):
                    with self.assertRaises(ValueError):
                        self.config(name, gate=invalid).validate()

    def test_long_profiles_require_explicit_well_formed_gate(self):
        for name in LONG:
            with self.subTest(profile=name):
                self.config(name, gate=GATE).validate()
                for invalid in (None, '', 'a'*64, 'sha256:'+'A'*64, 1):
                    with self.assertRaises(ValueError):
                        self.config(name, gate=invalid).validate()

    def test_new_profiles_reject_simulation_even_when_switch_is_off(self):
        for name in GPU_ONLY:
            cfg = self.config(name, mode='simulation', gate=GATE if name in LONG else None)
            self.assertFalse(cfg.staging_enabled)
            with self.assertRaises(ValueError):
                cfg.validate()
            with self.assertRaises(ContractError):
                self.connection(cfg)

    def test_only_original_short_profile_is_allowed_for_simulation(self):
        for name in LONG:
            with self.assertRaises(ValueError):
                self.config(name, mode='simulation', gate=GATE).validate()

    def test_controller_limits_are_exact_contract_selected_profile(self):
        for name in SHORT+LONG:
            cfg = self.config(name, gate=GATE if name in LONG else None)
            cfg.validate()
            connection = self.connection(cfg)
            self.assertEqual(connection.limits, PROFILES[name])
            self.assertIsNot(connection.limits, PROFILES[name])

    def test_no_automatic_profile_fallback_on_auth_mismatch(self):
        for name in SHORT+LONG:
            cfg = self.config(name, gate=GATE if name in LONG else None)
            with self.assertRaises(ContractError):
                self.connection(cfg, 'staging-short-1' if name != 'staging-short-1' else SHORT[1])

    def test_unknown_or_free_growth_profiles_are_rejected(self):
        cfg = self.config('staging-short-gpu2g-1')
        with self.assertRaises(ValueError):
            cfg.validate()
        with self.assertRaises(ContractError):
            self.connection(cfg)


if __name__ == '__main__':
    unittest.main()
