import unittest
import numpy as np
from prefetch import PCM
from resample import PCMResampler

class Tests(unittest.TestCase):
    def convert(self,rate,data,pattern):
        r=PCMResampler(1);out=[];index=seq=0
        while index<len(data):
            count=min(pattern[seq%len(pattern)],len(data)-index)
            out.extend(r.push(PCM(1,data[index:index+count].tobytes(),rate,1)))
            self.assertLess(len(r.tail),640)
            index+=count;seq+=1
        out.extend(r.finish());raw=b''.join(c.pcm for c in out)
        self.assertEqual(len(raw)//2,r.output_samples)
        self.assertLessEqual(abs(r.output_samples-len(data)*16000/rate),1)
        self.assertTrue(all(len(c.pcm)==640 for c in out[:-1]))
        return raw
    def test_incremental_matches_whole_resampling_and_sample_clock(self):
        for rate in (16000,22050,24000,48000):
            n=rate*10+127; t=np.arange(n)/rate
            data=(np.sin(2*np.pi*233*t)*10000+np.sin(2*np.pi*1799*t)*3000).astype('<i2')
            whole=self.convert(rate,data,[n])
            for pattern in ([rate//50],[rate//25],[rate//10],[rate//50,rate//25,rate//10,123]):
                self.assertEqual(self.convert(rate,data,pattern),whole,(rate,pattern))
    def test_generation_and_format_changes_rejected(self):
        r=PCMResampler(1);r.push(PCM(1,bytes(640),22050))
        with self.assertRaises(ValueError):r.push(PCM(2,bytes(640),22050))
        with self.assertRaises(ValueError):r.push(PCM(1,bytes(640),16000))
        r.finish()
        with self.assertRaises(ValueError):r.finish()

if __name__=='__main__':unittest.main(verbosity=2)
