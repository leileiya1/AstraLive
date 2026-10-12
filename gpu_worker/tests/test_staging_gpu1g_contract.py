"""CCR-BC-003 capability extension, not a GPU/resource success claim."""
import copy
import hashlib
import json
import pathlib
import unittest
from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import message, produced

# Exact old value inventory, independent of the implementation's new aliases.
OLD_COMMON={'worker_pose_bytes':8388608,'runtime_transient_bytes':25165824,'gpu_incremental_allocated_bytes':536870912,'audio_queue_samples':32000,'native_queue_frames':24,'network_window_frames':4,'lease_ms_max':60000}
EXPECTED_OLD={
 'staging-short-1':{**OLD_COMMON,'limits_revision':'staging-short-1','max_source_samples':30720,'worker_rgb_bytes':50331648,'runtime_artifact_bytes':100663296,'worker_attempt_bytes':268435456},
 'staging-segment-8s-1':{**OLD_COMMON,'limits_revision':'staging-segment-8s-1','max_source_samples':128000,'worker_rgb_bytes':167772160,'runtime_artifact_bytes':201326592,'worker_attempt_bytes':536870912}}
PAIRS=(('staging-short-gpu1g-1','staging-short-1'),('staging-segment-8s-gpu1g-1','staging-segment-8s-1'))

class GPU1GCapabilityTests(unittest.TestCase):
 def test_original_profiles_exact_inventory_preserved(self):
  for name,expected in EXPECTED_OLD.items():self.assertEqual(c.PROFILES[name],expected)
 def test_only_revision_and_gpu_allowance_differ(self):
  for new,old in PAIRS:
   value=copy.deepcopy(c.PROFILES[new]);self.assertEqual(value.pop('limits_revision'),new)
   self.assertEqual(value.pop('gpu_incremental_allocated_bytes'),1073741824)
   expected=copy.deepcopy(EXPECTED_OLD[old]);expected.pop('limits_revision');expected.pop('gpu_incremental_allocated_bytes');self.assertEqual(value,expected)
 def test_new_profiles_are_explicit_auth_capabilities(self):
  for new,old in PAIRS:
   auth=message('Auth');ready=message('GPU_WORKER_READY')
   auth['requested_limits_revision']=new;ready['selected_limits']=c.profile(new,short_gpu_gate=new in c.LONG_PROFILES)
   ready['profile_gate_ref']=None if new in c.SHORT_PROFILES else 'sha256:'+'a'*64
   c.validate_negotiation(auth,ready)
   auth['requested_limits_revision']=old
   with self.assertRaises(c.ContractError):c.validate_negotiation(auth,ready)
 def test_new_gpu_profiles_forbid_simulation(self):
  for new,old in PAIRS:
   ready=message('GPU_WORKER_READY');ready['selected_limits']=c.profile(new,short_gpu_gate=new in c.LONG_PROFILES)
   ready['profile_gate_ref']=None if new in c.SHORT_PROFILES else 'sha256:'+'a'*64;ready['simulation']=True
   with self.assertRaises(c.ContractError):c.validate_message(ready)
 def test_new_descriptor_simulation_forbidden(self):
  for new,_ in PAIRS:
   header=produced();d=header['descriptor'];d['limits']=c.profile(new,short_gpu_gate=new in c.LONG_PROFILES);d['provenance']['source']='CPU_SIMULATION'
   for k in d['resources']:
    if k.startswith('gpu_'):d['resources'][k]=None
   header['descriptor_sha256']=c.descriptor_hash(d)
   with self.assertRaises(c.ContractError):c.validate_message(header)
 def test_new_short_null_gate_new_long_real_gate_reference(self):
  for new,old in PAIRS:
   gate=None if new in c.SHORT_PROFILES else 'sha256:'+'a'*64
   value={'soulxStagingEnabled':True,'soulxStagingLimitsRevision':new,'soulxStagingShortGateSHA256':gate};c.validate_capture(value)
   value['soulxStagingShortGateSHA256']='sha256:'+'b'*64 if gate is None else None
   with self.assertRaises(c.ContractError):c.validate_capture(value)
  with self.assertRaises(c.ContractError):c.profile('staging-segment-8s-gpu1g-1')
 def test_new_names_schema_present_no_default_change(self):
  self.assertEqual(c.REVISION,'staging-contract-1');self.assertEqual(c.CAPABILITY,'immutable_segment_staging_v1')
  schema=json.dumps(c.SCHEMA)
  for new,_ in PAIRS:self.assertIn(new,schema)
  self.assertEqual(message('Auth')['requested_limits_revision'],'staging-short-1')
 def test_old_hash_vectors_unchanged(self):
  root=pathlib.Path(__file__).resolve().parents[2]
  # The immutable old vectors' hash is checked against F57a9 by the owner gate.
  for value in json.loads((root/'docs/v0.5/staging-canonical-vectors.json').read_text()):
   self.assertEqual(c.digest(value['projection']),value['sha256'])
