import threading,time,unittest
import numpy as np
import torch
from adapter import AudioChunk,StreamingAdapter

class Pipeline:
    device='cpu';param_dtype=torch.float32
    class VAE:
        def encode(self,x):return x
    vae=VAE()
    def reset_person_name(self):self.latent_motion_frames=None

class AdapterTests(unittest.TestCase):
    def make(self,block=None):
        events=[]
        def inference(p,e):
            if block and not block.is_set():block.wait(5)
            return torch.zeros((33,2,2,3))
        a=StreamingAdapter(Pipeline(),lambda *args:None,inference,lambda name,gid=None,**kw:events.append((name,gid,kw)))
        self.addCleanup(a.close)
        return a,events
    def chunk(self,gid,n=15360,seq=0,index=0,final=True):
        return AudioChunk(16000,1,'s16le',seq,index,n,gid,final,bytes(n*2))
    def test_cancel_inflight_and_begin_new_before_kernel_finishes(self):
        release=threading.Event();a,events=self.make(release)
        a.begin(100);a.put(self.chunk(100))
        self.assertTrue(a.inference_started.wait(3))
        a.cancel(100);a.begin(101);a.put(self.chunk(101,n=320,final=True))
        release.set();published=[]
        p=a.consume(lambda p:published.append(p['generation_id']))
        self.assertEqual(p['generation_id'],101)
        self.assertEqual(published,[101])
        self.assertTrue(any(e[0]=='stale_gpu_output_rejected' and e[1]==100 for e in events))
        self.assertFalse(a.put(self.chunk(100)))
    def test_sample_index_pts_partial_and_empty_eof(self):
        a,_=self.make();a.begin(1,16000)
        a.put(self.chunk(1,n=240,index=16000,final=False))
        a.put(self.chunk(1,n=0,seq=1,index=16240,final=True))
        p=a.consume(lambda p:None)
        self.assertEqual(p['pts_us'],1000000)
        self.assertEqual(p['frame_sequence'],0)
        self.assertEqual(len(a.video),0)
        a.finish(1)
    def test_generation_reuse_is_rejected(self):
        a,_=self.make();a.begin(100);a.cancel(100)
        with self.assertRaises(ValueError):a.begin(100)
        with self.assertRaises(ValueError):a.begin(101,-1)
        a.begin(101)

    def test_invalid_pcm_gap_and_duplicate(self):
        a,_=self.make();a.begin(1)
        with self.assertRaises(ValueError):a.put(self.chunk(1,index=320))
        with self.assertRaises(ValueError):a.put(AudioChunk(16000,1,'s16le',0,0,320,1,False,b'bad'))
        a.put(self.chunk(1,n=320,final=False))
        with self.assertRaises(ValueError):a.put(self.chunk(1,n=320,final=False))
    def test_bounded_audio_backpressure_unblocks_on_cancel(self):
        release=threading.Event();a,_=self.make(release)
        a.begin(1);a.put(self.chunk(1,final=False))
        self.assertTrue(a.inference_started.wait(3))
        results=[]
        def producer():
            for i in range(1,30):
                results.append(a.put(self.chunk(1,n=1600,seq=i,index=15360+(i-1)*1600,final=False)))
                if not results[-1]:break
        t=threading.Thread(target=producer);t.start();time.sleep(.1)
        self.assertTrue(t.is_alive());self.assertLessEqual(a.pending_samples,32000)
        a.cancel(1);release.set();t.join(2)
        self.assertFalse(t.is_alive());self.assertFalse(results[-1]);self.assertEqual(a.pending_samples,0)

if __name__=='__main__':unittest.main(verbosity=2)
