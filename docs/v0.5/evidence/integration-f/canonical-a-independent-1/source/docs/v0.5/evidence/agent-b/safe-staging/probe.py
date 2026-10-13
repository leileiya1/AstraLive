"""Local unchanged Worker.handle credit diagnostic, with synthetic model/adapter.

Not GPU inference, Runtime, durability, Chrome, RTMP, or audience evidence.
No production source is patched. The control branch/encoder/wire are actual code.
"""
import argparse
import collections
import hashlib
import json
import pathlib
import socket
import subprocess
import tempfile
import threading
import time
import types

import numpy as np

from gpu_worker.model import ResidentModel
from gpu_worker.service import Worker
from gpu_worker.validated.wire import receive, send


class SyntheticAdapter:
    AUDIO_BOUND = 32000

    def __init__(self):
        self.cv = threading.Condition(threading.RLock())
        self.committed = collections.deque(maxlen=9)
        self.video = collections.deque()
        self.pending_samples = 0
        self.error = None
        self.active = None
        self.closed = False

    def begin(self, gid, origin):
        self.active = gid
        self.first_sample = self.next_sample = origin

    def put(self, chunk):
        # Synthetic deterministic images; no inference/pose implementation here.
        with self.cv:
            self.next_sample += chunk.sample_count
            count = (chunk.sample_count * 25 + 15999) // 16000
            for seq in range(count):
                self.video.append(dict(generation_id=self.active, frame_sequence=seq,
                    pts_us=self.first_sample * 1000000 // 16000 + seq * 40000,
                    frame=np.full((512, 512, 3), seq, dtype=np.uint8)))
            self.cv.notify_all()
        return True

    def consume(self, publish, timeout, commit, expected_generation):
        until = time.monotonic() + timeout
        with self.cv:
            while not self.video:
                if self.closed or self.active != expected_generation:
                    return None
                remaining = until - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self.cv.wait(remaining)
            return self.video.popleft()

    def cancel(self, gid):
        with self.cv:
            self.active = None
            self.video.clear()
            self.cv.notify_all()

    def finish(self, gid):
        assert not self.video and self.active == gid
        self.active = None

    def close(self):
        with self.cv:
            self.closed = True
            self.cv.notify_all()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    adapter = SyntheticAdapter()
    events = []
    with tempfile.TemporaryDirectory(prefix='astralive-b-credit-') as temp:
        token = pathlib.Path(temp) / 'token'
        token.write_text('local-probe-only-' + 'x' * 48)
        token.chmod(0o600)
        worker = Worker.__new__(Worker)
        worker.cfg = types.SimpleNamespace(token_file=str(token), mode='simulation',
            avatar_ref='synthetic', asset_sha256='a' * 64)
        worker.metrics = types.SimpleNamespace(epoch='local-probe-epoch',
            event=lambda *a, **k: events.append((a, k)), lock=threading.Lock())
        worker.ready = dict(worker_epoch=worker.metrics.epoch)
        worker.model = types.SimpleNamespace(adapter=lambda: adapter,
            encoder=ResidentModel.encoder, cache_id='synthetic-cache')
        worker.stop = threading.Event()
        worker.highest_generation = -1
        worker.status = lambda: dict(ready=True, active_generation_id=adapter.active, lastError=None)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        server, _ = listener.accept()
        listener.close()
        thread = threading.Thread(target=worker.handle, args=(server,))
        thread.start()
        def command(kind, **fields):
            send(client, dict(type=kind, session_id='local-probe-session',
                worker_epoch=worker.metrics.epoch, **fields))
        def begin(gid, samples):
            command('BeginGeneration', generation_id=gid, cache_id='synthetic-cache',
                sample_rate=16000, channels=1, pcm_format='s16le', first_sample_index=0, output_fps=25)
            assert receive(client)[0]['type'] == 'GenerationBegun'
            header = dict(type='AudioChunk', session_id='local-probe-session',
                worker_epoch=worker.metrics.epoch, generation_id=gid, chunk_sequence=0,
                first_sample_index=0, sample_count=samples, sample_rate=16000,
                channels=1, pcm_format='s16le', final_chunk=True)
            send(client, header, bytes(samples * 2))
        def packets(count):
            out = []
            while len(out) < count:
                header, _ = receive(client)
                if header['type'] == 'VideoPacket':
                    out.append(header['frame_sequence'])
            return out
        try:
            client.settimeout(3)
            send(client, dict(type='Auth', protocol_version=1, internal_version='1.1',
                session_id='local-probe-session', token=token.read_text()))
            assert receive(client)[0]['type'] == 'GPU_WORKER_READY'
            begin(1, 15360)  # 960 ms, 24 frames: a normal semantic segment is longer.
            first = packets(4)
            command('Health', nonce=1)
            health, _ = receive(client)
            assert health['type'] == 'Health'
            client.settimeout(.2)
            blocked = False
            try:
                receive(client)
            except socket.timeout:
                blocked = True
            client.settimeout(3)
            unplayed_pose_before_credit = len(adapter.committed)
            # Deliberately invalid proposed workaround, contained only in this diagnostic.
            for seq in range(9):
                command('Credit', generation_id=1, latest_consumed_sequence=seq)
                assert packets(1) == [seq + 4]
            unplayed_pose_after_credit = len(adapter.committed)
            command('CancelGeneration', generation_id=1)
            assert receive(client)[0]['type'] == 'GenerationCancelled'
            pose_after_cancel = len(adapter.committed)
            begin(2, 2560)  # Even <=4 frames cannot receive GenerationComplete pre-Credit.
            short = packets(4)
            client.settimeout(.2)
            complete_withheld = False
            try:
                receive(client)
            except socket.timeout:
                complete_withheld = True
            client.settimeout(3)
            for seq in range(4):
                command('Credit', generation_id=2, latest_consumed_sequence=seq)
            complete, _ = receive(client)
            assert complete['type'] == 'GenerationComplete'
            checks = dict(four_slot_preplayout_bound=first == [0, 1, 2, 3] and blocked,
                no_credit_no_published_pose=unplayed_pose_before_credit == 0,
                early_credit_mutates_unplayed_pose=unplayed_pose_after_credit == 9,
                cancel_retains_false_pose=pose_after_cancel == 9,
                short_completion_requires_consumption_credit=short == [0, 1, 2, 3] and complete_withheld,
                normal_credit_completes=complete['consumed_frames'] == 4)
            files = ['gpu_worker/service.py', 'gpu_worker/model.py',
                'gpu_worker/validated/adapter.py', 'gpu_worker/validated/wire.py']
            result = dict(status='PASS' if all(checks.values()) else 'FAIL',
                scope='LOCAL_SYNTHETIC_CONTROL_DIAGNOSTIC_NOT_GPU_OR_PLAYBACK', checks=checks,
                productionSourceSHA=subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
                sourceHashes={name: hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in files},
                probeSHA256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                noCreditSentFrames=first, earlyCreditPoseCount=unplayed_pose_after_credit,
                blockedObserveSeconds=.2, realGPU='NOT TESTED', realSinks='NOT TESTED')
            args.output.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
            if not all(checks.values()):
                raise SystemExit(1)
        finally:
            worker.stop.set()
            client.close()
            thread.join(3)
            server.close()
            assert not thread.is_alive(), 'local service failed cleanup'
            if not args.output.exists():
                print(json.dumps({'diagnosticEvents': events}))


if __name__ == '__main__':
    main()
