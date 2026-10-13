"""Numerical acceptance-oracle tests; synthetic arrays are never live evidence."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np

path=Path(__file__).resolve().parents[1]/'observer_audit.py'
spec=importlib.util.spec_from_file_location('waveform_numeric_oracle',path)
oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)


class WaveformNumericalTests(unittest.TestCase):
    def test_exact_silence_cannot_amplify_fft_residuals_into_match(self):
        reference=np.random.default_rng(15).normal(0,.1,8000)
        result=oracle.match(reference,np.zeros(100000),4)
        self.assertEqual(result['status'],'MISSING_OR_SILENT_RECORDING')

    def test_microscopic_copy_after_loud_prefix_is_not_speech_match(self):
        rng=np.random.default_rng(7)
        reference=rng.normal(0,.1,8000)
        observed=np.concatenate((rng.normal(0,.1,16000),np.zeros(40000),reference*1e-9,np.zeros(8000)))
        result=oracle.match(reference,observed,7)
        self.assertEqual(result['status'],'UNRESOLVED')
        self.assertLessEqual(abs(result['correlation']),1)
        self.assertNotAlmostEqual(result['referenceStartSeconds'],7,places=2)

    def test_real_energy_prefix_after_long_silence_has_bounded_score_and_correct_time(self):
        reference=np.random.default_rng(19).normal(0,.1,8000)
        observed=np.concatenate((np.zeros(80000),reference,np.zeros(40000)))
        result=oracle.match(reference,observed,10)
        self.assertEqual(result['status'],'MATCHED')
        self.assertLessEqual(result['correlation'],1)
        self.assertAlmostEqual(result['referenceStartSeconds'],10,places=4)

    def test_two_true_prefixes_remain_ambiguous(self):
        reference=np.random.default_rng(41).normal(0,.1,8000)
        observed=np.concatenate((np.zeros(8000),reference,np.zeros(8000),reference,np.zeros(8000)))
        self.assertEqual(oracle.match(reference,observed,1)['status'],'AMBIGUOUS')

    def test_second_fft_peak_must_agree_with_independent_dot(self):
        reference=np.random.default_rng(41).normal(0,.1,8000)
        observed=np.concatenate((np.zeros(8000),reference,np.zeros(8000),reference,np.zeros(8000)))
        original=np.fft.irfft
        def corrupt_second(*args,**kwargs):
            values=original(*args,**kwargs)
            values[24000+len(reference)-1]*=.999
            return values
        with patch.object(np.fft,'irfft',side_effect=corrupt_second):
            self.assertEqual(oracle.match(reference,observed,1)['status'],'NUMERICAL_UNCERTAINTY')


if __name__=='__main__':unittest.main()
