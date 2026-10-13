"""Isolated bounded PCM adapter. No AstraLive Runtime imports or file audio input."""
import collections
import dataclasses
import threading
import time
import numpy as np

def restore_published_pose(pipeline, committed):
    import torch
    with torch.no_grad():
        if len(committed) == 9:
            pose = torch.from_numpy(np.stack(committed)).to(pipeline.device, dtype=pipeline.param_dtype)
            pose = (pose.permute(3,0,1,2)[None] / 255 - .5) * 2
            pipeline.latent_motion_frames = pipeline.vae.encode(pose)
        else:
            pipeline.reset_person_name()

@dataclasses.dataclass(frozen=True)
class AudioChunk:
    sample_rate: int
    channels: int
    pcm_format: str
    chunk_sequence: int
    first_sample_index: int
    sample_count: int
    generation_id: int
    final_chunk: bool
    pcm: bytes

class StreamingAdapter:
    SR = 16000
    FPS = 25
    STEP = 15360
    AUDIO_BOUND = 32000  # two seconds, sample budget (not message count)
    VIDEO_BOUND = 24     # one generated block, 960 ms

    def __init__(self, pipeline, embedding, inference, log):
        self.p = pipeline
        self.embedding = embedding
        self.inference = inference
        self.log = log
        self.cv = threading.Condition(threading.RLock())
        self.audio = collections.deque()
        self.video = collections.deque()
        self.pending_samples = 0
        self.active = None
        self.last_generation_id = -1
        self.closed = False
        self.error = None
        self.committed = collections.deque(maxlen=9)
        self.inference_started = threading.Event()
        # Opt-in staging observes these signals; legacy media/credit is unchanged.
        # Only the inference thread sets/clears busy and emits final after EOF.
        self.native_busy_generation = None
        self.native_final_generation = None
        self.native_final_frames = 0
        self.native_cpu_peak_bytes = 0
        self.native_elapsed_us = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def begin(self, generation_id, first_sample_index=0):
        with self.cv:
            if generation_id <= self.last_generation_id or first_sample_index < 0:
                raise ValueError('generation IDs must increase; sample index must be nonnegative')
            if self.active is not None:
                raise ValueError('cancel/complete active generation before begin')
            self.last_generation_id = generation_id
            self.active = generation_id
            self.sequence = 0
            self.next_sample = first_sample_index
            self.first_sample = first_sample_index
            self.eof = False
            self.audio.clear(); self.video.clear(); self.pending_samples = 0
            self.log('BeginGeneration', generation_id, first_sample_index=first_sample_index)
            self.cv.notify_all()

    def put(self, chunk):
        if (chunk.sample_rate, chunk.channels, chunk.pcm_format) != (16000, 1, 's16le'):
            raise ValueError('PoC supports 16000 Hz mono s16le only')
        if chunk.sample_count < 0 or len(chunk.pcm) != chunk.sample_count * 2:
            raise ValueError('PCM length mismatch')
        if chunk.sample_count > self.AUDIO_BOUND:
            raise ValueError('chunk exceeds sample budget')
        with self.cv:
            while self.pending_samples + chunk.sample_count > self.AUDIO_BOUND:
                if chunk.generation_id != self.active or self.closed:
                    return False
                self.cv.wait(.05)
            if chunk.generation_id != self.active or self.closed:
                self.log('stale_audio_rejected', chunk.generation_id)
                return False
            if self.eof or chunk.chunk_sequence != self.sequence or chunk.first_sample_index != self.next_sample:
                raise ValueError('non-contiguous sequence/sample index or audio after EOF')
            self.sequence += 1
            self.next_sample += chunk.sample_count
            self.eof = chunk.final_chunk
            self.audio.append(chunk); self.pending_samples += chunk.sample_count
            self.log('PCM_Arrival', chunk.generation_id, sequence=chunk.chunk_sequence,
                     first_sample_index=chunk.first_sample_index, sample_count=chunk.sample_count,
                     pts_us=chunk.first_sample_index * 1000000 // self.SR,
                     final_chunk=chunk.final_chunk, audio_queue_ms=self.pending_samples / 16)
            self.cv.notify_all()
            return True

    def cancel(self, generation_id):
        with self.cv:
            if self.active != generation_id:
                return
            self.active = None
            n = len(self.video)
            a = self.pending_samples
            self.audio.clear(); self.video.clear(); self.pending_samples = 0
            self.log('CancelGeneration', generation_id, discarded_frames=n,
                     discarded_audio_samples=a, committed_pose_frames=len(self.committed))
            self.cv.notify_all()

    def consume(self, publish, timeout=20, commit=True, expected_generation=None):
        # Caller publishes under the same lock as cancellation: no post-cancel callback.
        until = time.monotonic() + timeout
        with self.cv:
            while not self.video:
                if expected_generation is not None and self.active != expected_generation:
                    return None
                if self.error:
                    raise RuntimeError(self.error)
                if self.closed:
                    return None
                remaining = until - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('video consumer timeout')
                self.cv.wait(min(.05, remaining))
            if expected_generation is not None and self.active != expected_generation:
                return None
            packet = self.video.popleft()
            if packet['generation_id'] != self.active:
                raise RuntimeError('generation fence violated')
            publish(packet)
            if commit:
                self.committed.append(packet['frame'].copy())
            self.log('FrameConsumed', packet['generation_id'], frame_sequence=packet['frame_sequence'],
                     pts_us=packet['pts_us'], video_queue_ms=len(self.video) * 40)
            self.cv.notify_all()
            return packet

    def finish(self, generation_id):
        with self.cv:
            if self.video or self.audio or self.pending_samples:
                raise RuntimeError('finish before drain')
            if self.active != generation_id:
                raise RuntimeError('wrong generation')
            self.active = None
            self.cv.notify_all()

    def close(self):
        with self.cv:
            self.closed = True; self.active = None
            self.audio.clear(); self.video.clear(); self.cv.notify_all()
        self.thread.join(30)
        if self.thread.is_alive():
            raise RuntimeError('GPU thread did not reach safe boundary')

    def native_status(self, generation_id):
        with self.cv:
            return dict(safe=self.native_busy_generation != generation_id and not self.error,
                        final=self.native_final_generation == generation_id,
                        frames=self.native_final_frames if self.native_final_generation == generation_id else 0,
                        cpu_peak_bytes=self.native_cpu_peak_bytes,
                        inference_elapsed_us=self.native_elapsed_us)

    def _run(self):
        import torch
        try:
            current = None
            while True:
                with self.cv:
                    self.native_busy_generation = None
                    self.cv.notify_all()
                    while not self.audio and not self.closed:
                        self.cv.wait(.05)
                    if self.closed:
                        return
                    c = self.audio.popleft(); self.pending_samples -= c.sample_count
                    self.cv.notify_all()
                    if c.generation_id != self.active:
                        continue
                    self.native_busy_generation = c.generation_id
                    if current != c.generation_id:
                        current = c.generation_id
                        pending = np.empty(0, dtype=np.float32)
                        history = np.zeros(128000, dtype=np.float32)
                        emitted = 0
                        origin = self.first_sample
                        committed = list(self.committed)
                        self.native_cpu_peak_bytes = 0
                        self.native_elapsed_us = 0
                    else:
                        committed = None
                # Only GPU thread mutates model state. Restore from last PUBLISHED pose.
                if committed is not None:
                    self.log('PoseRestoreStart', current)
                    restore_published_pose(self.p, committed)
                    self.log('PoseCommitted', current, source='last_9_consumed_frames' if len(committed)==9 else 'cached_portrait')
                pending = np.concatenate((pending, np.frombuffer(c.pcm, dtype='<i2').astype(np.float32) / 32768))
                while len(pending) >= self.STEP or (c.final_chunk and len(pending)):
                    with self.cv:
                        if current != self.active or self.closed:
                            pending = np.empty(0, dtype=np.float32)
                            break
                    valid_samples = min(self.STEP, len(pending))
                    block = np.pad(pending[:valid_samples], (0,self.STEP-valid_samples))
                    pending = pending[valid_samples:]
                    history = np.concatenate((history[self.STEP:], block))
                    self.log('AudioBlockReady', current, output_frame_start=emitted,
                             valid_samples=valid_samples, buffered_samples=len(pending),
                             feature_window_samples=len(history))
                    t = time.monotonic()
                    emb = self.embedding(self.p, history, 167, 200)
                    torch.cuda.synchronize()
                    self.log('AudioFeatureReady', current, elapsed_ms=(time.monotonic()-t)*1000)
                    self.log('GPUInferenceStart', current, output_frame_start=emitted)
                    self.inference_started.set()
                    t = time.monotonic()
                    native_t = time.monotonic_ns()
                    output = self.inference(self.p, emb)[9:]
                    torch.cuda.synchronize()
                    with self.cv:
                        self.native_elapsed_us += (time.monotonic_ns() - native_t) // 1000
                    self.log('GPUOutput', current, output_frame_start=emitted,
                             elapsed_ms=(time.monotonic()-t)*1000, generated_frames=len(output))
                    # Account the existing CPU readback/cast peak without retaining
                    # another tensor or changing the native model invocation.
                    with self.cv:
                        self.native_cpu_peak_bytes = max(self.native_cpu_peak_bytes,
                            output.numel() * output.element_size() + output.numel() + history.nbytes + pending.nbytes)
                    frames = output.cpu().numpy().astype(np.uint8)
                    valid_frames = (valid_samples * self.FPS + self.SR-1)//self.SR
                    with self.cv:
                        if current != self.active or self.closed:
                            self.log('stale_gpu_output_rejected', current, frames=len(frames))
                            break
                    for frame in frames[:valid_frames]:
                        with self.cv:
                            while len(self.video) >= self.VIDEO_BOUND and current == self.active and not self.closed:
                                self.cv.wait(.05)
                            if current != self.active or self.closed:
                                break
                            packet = dict(generation_id=current, frame_sequence=emitted,
                                          pts_us=origin*1000000//self.SR + emitted*40000,
                                          duration_us=40000, source='GPU_INFERENCE', frame=frame)
                            self.video.append(packet); emitted += 1
                            self.log('FrameQueued', current, frame_sequence=emitted-1,
                                     pts_us=packet['pts_us'], video_queue_ms=len(self.video)*40)
                            self.cv.notify_all()
                with self.cv:
                    if c.final_chunk and current == self.active and not len(pending):
                        self.native_final_generation = current
                        self.native_final_frames = emitted
                    self.native_busy_generation = None
                    self.cv.notify_all()
        except Exception:
            import traceback
            with self.cv:
                self.error = traceback.format_exc(); self.cv.notify_all()
            self.log('WorkerError', current, error=self.error)
