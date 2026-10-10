"""Run original lab tests on CPU; CUDA barriers are explicitly mocked, no GPU claim."""
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
LAB=ROOT/'astralive-avatar-lab/streaming'
sys.path.insert(0,str(LAB))
sys.path.insert(0,str(LAB/'runtime-experiment'))
modules=('test_adapter','test_async_link','test_prefetch','test_resample','test_degradation_regression','test_final_regression','test_paired_rtmp','test_sync_cadence')
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)) for name in modules)
with patch('torch.cuda.synchronize',lambda:None):
    result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
