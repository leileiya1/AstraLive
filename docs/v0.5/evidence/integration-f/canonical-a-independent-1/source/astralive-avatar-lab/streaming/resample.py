"""Stateful utterance resampling; bounded 20 ms output coalescing."""
from fractions import Fraction
import av
import numpy as np
from prefetch import PCM

class PCMResampler:
    def __init__(self,generation_id):
        self.generation=generation_id;self.converter=av.AudioResampler(format='s16',layout='mono',rate=16000)
        self.source_rate=None;self.source_samples=0;self.output_samples=0;self.tail=bytearray();self.finished=False
    def _collect(self,frames):
        out=[]
        for frame in frames:
            raw=bytes(frame.planes[0])[:frame.samples*2]
            # Only the incomplete 20 ms tail is retained across converter outputs.
            for offset in range(0,len(raw),640):
                self.tail.extend(raw[offset:offset+640])
                while len(self.tail)>=640:
                    out.append(PCM(self.generation,bytes(self.tail[:640])))
                    del self.tail[:640];self.output_samples+=320
        return out
    def push(self,chunk):
        if self.finished:raise ValueError('resampler already at EOF')
        if chunk.generation_id!=self.generation:raise ValueError('stale resampler generation')
        if chunk.channels!=1 or len(chunk.pcm)%2:raise ValueError('mono s16le PCM required')
        if self.source_rate is None:self.source_rate=chunk.sample_rate
        if self.source_rate!=chunk.sample_rate:raise ValueError('sample rate changed within utterance')
        data=np.frombuffer(chunk.pcm,dtype='<i2').reshape(1,-1)
        if not data.size:return []
        frame=av.AudioFrame.from_ndarray(data,format='s16',layout='mono');frame.sample_rate=self.source_rate
        frame.pts=self.source_samples;frame.time_base=Fraction(1,self.source_rate);self.source_samples+=data.size
        return self._collect(self.converter.resample(frame))
    def finish(self):
        if self.finished:raise ValueError('duplicate resampler EOF')
        self.finished=True;out=self._collect(self.converter.resample(None))
        if self.tail:
            out.append(PCM(self.generation,bytes(self.tail)));self.output_samples+=len(self.tail)//2;self.tail.clear()
        return out

async def resampled(source,generation_id):
    converter=PCMResampler(generation_id)
    async for chunk in source:
        for converted in converter.push(chunk):yield converted
    for converted in converter.finish():yield converted
