"""Single lease per logical worker. Media algorithm copied from pinned worker_final."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import struct
import threading
import time
import uuid

from .config import Config, IDENTIFIER, secret
from .model import ResidentModel
from .resources import GPUResources
from .telemetry import Metrics, atomic_json
from .validated.adapter import AudioChunk
from .validated.wire import send, receive, read_exact, MAX_HEADER, MAX_PAYLOAD


class Worker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.metrics = Metrics(cfg, uuid.uuid4().hex)
        self.model = ResidentModel(cfg, self.metrics)
        self.ready = None
        self.adapter = None
        self.active = None
        self.highest_generation = -1
        self.stop = threading.Event()
        self.connection = None
        self.listener = None
        self.resources = GPUResources(cfg.mode)
        switch = os.getenv('ASTRALIVE_WORKER_STAGING_ENABLED')
        if switch is not None and switch.lower() not in {'true', 'false', '1', '0'}:
            raise ValueError('invalid staging switch')
        self.staging_enabled = cfg.staging_enabled if switch is None else switch.lower() in {'true', '1'}
        self.staging_unknown = False
        self.staging_terminals = {}

    def status(self):
        return dict(self.metrics.snapshot(self.adapter, self.active, self.model.gpu if self.ready else None), **self.resources.snapshot(), processPid=os.getpid())

    def shutdown(self, *_):
        self.metrics.ready = False
        self.stop.set()
        if self.listener:
            self.listener.close()
        if self.connection:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def handle(self, sock):
        import av
        sock.settimeout(5)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        # Preserve legacy JSON parsing; only 1.2 gets strict raw duplicate-key,
        # UTF-8 and integer validation before information can be discarded.
        header_size, payload_size = struct.unpack('!II', read_exact(sock, 8))
        if header_size > MAX_HEADER or payload_size > MAX_PAYLOAD:
            raise ValueError('oversize packet')
        raw_header = read_exact(sock, header_size)
        h, payload = json.loads(raw_header), read_exact(sock, payload_size)
        if not isinstance(h, dict):
            raise ValueError('invalid header')
        if isinstance(h, dict) and h.get('internal_version') == '1.2':
            from .staging_contract import decode_header, validate_message
            from .staging_service import StagingConnection
            h = decode_header(raw_header)
            validate_message(h, payload)
            if (not self.staging_enabled or not IDENTIFIER.fullmatch(h['session_id']) or
                    not hmac.compare_digest(h['token'], secret(self.cfg.token_file))):
                self.metrics.event('AuthenticationRejected')
                return
            return StagingConnection(self, sock, h).run()
        session = h.get('session_id', '')
        if (h.get('type') != 'Auth' or h.get('protocol_version') != 1 or h.get('internal_version') != '1.1'
                or not isinstance(session, str) or not IDENTIFIER.fullmatch(session)
                or not hmac.compare_digest(str(h.get('token', '')), secret(self.cfg.token_file)) or payload):
            self.metrics.event('AuthenticationRejected')
            return
        send(sock, dict(type='GPU_WORKER_READY', **self.ready))
        sock.settimeout(15)
        adapter = self.adapter = self.model.adapter()
        state = threading.Condition()
        sendlock = threading.Lock()
        stopped = threading.Event()
        active = None
        slots = 0
        ack = last_sent = -1
        target = None
        outstanding = {}

        def reply(header, payload=b''):
            with sendlock:
                send(sock, dict(worker_epoch=self.metrics.epoch, session_id=session, **header), payload)

        def sender():
            nonlocal slots, last_sent
            ctx = ctxgid = None
            try:
                while not stopped.is_set():
                    with state:
                        if active is None or slots == 0:
                            state.wait(.05)
                            continue
                        gid = active
                    try:
                        packet = adapter.consume(lambda p: None, timeout=.1, commit=False, expected_generation=gid)
                    except TimeoutError:
                        continue
                    if packet is None:
                        continue
                    if ctxgid != gid:
                        ctx, ctxgid = self.model.encoder(), gid
                    t = time.monotonic()
                    f = av.VideoFrame.from_ndarray(packet['frame'], format='rgb24')
                    f.pts = packet['frame_sequence']
                    encoded = ctx.encode(f)
                    elapsed = (time.monotonic() - t) * 1000
                    if len(encoded) != 1:
                        raise RuntimeError('encoder buffered/reordered frame')
                    encoded = encoded[0]
                    with state:
                        if active != gid or packet['generation_id'] != gid:
                            self.metrics.event('stale_encoded_frame_rejected', gid)
                            continue
                        slots -= 1
                        last_sent = packet['frame_sequence']
                        outstanding[last_sent] = packet['frame']
                        if len(outstanding) > 4:
                            raise RuntimeError('credit bound exceeded')
                    reply(dict(type='VideoPacket', source='GPU_INFERENCE' if self.cfg.mode == 'gpu' else 'CPU_SIMULATION',
                               generation_id=gid, frame_sequence=packet['frame_sequence'], pts_us=packet['pts_us'],
                               duration_us=40000, codec='h264', width=512, height=512, keyframe_flag=encoded.is_keyframe,
                               encode_latency_ms=elapsed, audio_queue_ms=adapter.pending_samples / 16,
                               video_queue_ms=len(adapter.video) * 40), bytes(encoded))
                    self.metrics.event('VideoPacketPublished', gid, frame_sequence=packet['frame_sequence'])
            except Exception as exc:
                self.metrics.event('TransportSenderError', error_type=type(exc).__name__)
                stopped.set()
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        thread = threading.Thread(target=sender, name='video-sender', daemon=True)
        thread.start()
        try:
            while not stopped.is_set() and not self.stop.is_set():
                h, payload = receive(sock)
                kind = h['type']
                if h.get('session_id') != session or h.get('worker_epoch') != self.metrics.epoch:
                    raise ValueError('session/epoch mismatch')
                if kind != 'AudioChunk' and payload:
                    raise ValueError('unexpected payload')
                if kind == 'PrepareAvatar':
                    if h['avatar_id'] != self.cfg.avatar_ref or h['input_asset_sha256'] != self.cfg.asset_sha256:
                        raise ValueError('unauthorized avatar')
                    reply(dict(type='AvatarPrepared', cache_id=self.model.cache_id))
                elif kind == 'BeginGeneration':
                    if getattr(self, 'staging_unknown', False):
                        raise ValueError('staging UNKNOWN requires Worker retirement')
                    gid = h['generation_id']
                    if type(gid) is not int or not 0 <= gid < 2**63 or gid <= self.highest_generation or h['cache_id'] != self.model.cache_id:
                        raise ValueError('generation/cache mismatch')
                    if type(h['first_sample_index']) is not int or not 0 <= h['first_sample_index'] < 2**63:
                        raise ValueError('invalid sample origin')
                    if (h['sample_rate'], h['channels'], h['pcm_format'], h['output_fps']) != (16000, 1, 's16le', 25):
                        raise ValueError('unsupported PCM/FPS')
                    with state:
                        if active is not None:
                            raise ValueError('generation already active')
                        adapter.begin(gid, h['first_sample_index'])
                        self.highest_generation = gid
                        active = self.active = gid
                        slots, ack, last_sent, target = 4, -1, -1, None
                        outstanding.clear()
                        state.notify_all()
                    reply(dict(type='GenerationBegun', generation_id=gid, audio_credit_samples=32000))
                elif kind == 'AudioChunk':
                    for field in ('generation_id', 'chunk_sequence', 'first_sample_index', 'sample_count'):
                        if type(h[field]) is not int or not 0 <= h[field] < 2**63:
                            raise ValueError('invalid PCM metadata')
                    if type(h['final_chunk']) is not bool:
                        raise ValueError('invalid EOF')
                    c = AudioChunk(h['sample_rate'], h['channels'], h['pcm_format'], h['chunk_sequence'], h['first_sample_index'], h['sample_count'], h['generation_id'], h['final_chunk'], payload)
                    # Reject overflow synchronously: controls never queue behind PCM admission.
                    with adapter.cv:
                        if adapter.pending_samples + c.sample_count > adapter.AUDIO_BOUND:
                            raise ValueError('audio credit exhausted')
                        accepted = adapter.put(c)
                        if accepted and c.final_chunk:
                            target = ((adapter.next_sample - adapter.first_sample) * 25 + 15999) // 16000
                    if target == 0 and active == c.generation_id:
                        adapter.finish(active)
                        reply(dict(type='GenerationComplete', generation_id=active, consumed_frames=0))
                        active = self.active = None
                        slots = 0
                    reply(dict(type='AudioAccepted', generation_id=c.generation_id, chunk_sequence=c.chunk_sequence, audio_credit_samples=adapter.AUDIO_BOUND-adapter.pending_samples, accepted=accepted))
                elif kind == 'Credit':
                    with state:
                        if h['generation_id'] != active:
                            continue
                        latest = h['latest_consumed_sequence']
                        if latest != ack + 1 or latest > last_sent:
                            raise ValueError('invalid video acknowledgment')
                        with adapter.cv:
                            adapter.committed.append(outstanding.pop(latest).copy())
                        ack, slots = latest, slots + 1
                        if slots > 4:
                            raise ValueError('credit overflow')
                        if target is not None and ack + 1 == target:
                            adapter.finish(active)
                            reply(dict(type='GenerationComplete', generation_id=active, consumed_frames=target))
                            active = self.active = None
                            slots = 0
                        state.notify_all()
                elif kind == 'CancelGeneration':
                    with state:
                        if active == h['generation_id']:
                            adapter.cancel(active)
                            active = self.active = None
                            slots = 0
                            outstanding.clear()
                            state.notify_all()
                        with self.metrics.lock:
                            self.metrics.cancel = {'generationId': h['generation_id'], 'status': 'PUBLICATION_FENCED'}
                    reply(dict(type='GenerationCancelled', generation_id=h['generation_id']))
                elif kind == 'Health':
                    status = self.status()
                    reply(dict(type='Health', nonce=h['nonce'], ready=status['ready'], active_generation_id=active,
                               last_completed_frame=last_sent, audio_queue_ms=adapter.pending_samples/16,
                               video_queue_ms=len(adapter.video)*40, error=status['lastError']))
                else:
                    raise ValueError('unknown message')
        except Exception as exc:
            self.metrics.event('TransportReceiverClosed', error_type=type(exc).__name__)
        finally:
            stopped.set()
            with state:
                state.notify_all()
            # Same safe-boundary cleanup; never reuse a model behind a stuck inference thread.
            adapter.close()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            thread.join(20)
            self.adapter = self.active = None
            self.metrics.event('ConnectionCleaned', sender_stopped=not thread.is_alive())
            if thread.is_alive() or adapter.error:
                raise RuntimeError('WORKER_RESTART_REQUIRED')

    def run(self):
        worker = self
        token = secret(self.cfg.management_token_file)
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'
            def log_message(self, *_):
                pass
            def do_GET(self):
                if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                    self.send_error(401)
                    return
                if self.path not in {'/v1/status', '/livez', '/readyz'}:
                    self.send_error(404)
                    return
                status = worker.status()
                body = json.dumps(status).encode()
                self.send_response(200 if self.path != '/readyz' or status['ready'] else 503)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            def setup(self):
                super().setup()
                self.connection.settimeout(2)
        management = HTTPServer(('127.0.0.1', self.cfg.management_port), Handler)
        mt = threading.Thread(target=management.serve_forever, daemon=True)
        mt.start()
        self.resources.start()
        try:
            self.ready = self.model.load()
            self.listener = socket.socket()
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(('127.0.0.1', self.cfg.port))
            self.listener.listen(1)
            self.listener.settimeout(.5)
            self.metrics.ready = not self.stop.is_set()
            if self.metrics.ready:
                self.metrics.event('GPU_WORKER_READY', model_load_count=self.model.load_count)
            while not self.stop.is_set():
                try:
                    conn, _ = self.listener.accept()
                except socket.timeout:
                    continue
                with conn:
                    self.connection = conn
                    try:
                        self.handle(conn)
                    except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
                        self.metrics.event('ConnectionRejected', error_type=type(exc).__name__)
                self.connection = None
        finally:
            self.shutdown()
            management.shutdown()
            management.server_close()
            mt.join(3)
            self.resources.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    cfg = Config.load(args.config)
    Path(cfg.state_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    worker = Worker(cfg)
    signal.signal(signal.SIGTERM, worker.shutdown)
    signal.signal(signal.SIGINT, worker.shutdown)
    try:
        worker.run()
    except Exception as exc:
        codes = {'AVATAR_SHA256_MISMATCH', 'MANIFEST_SHA256_MISMATCH', 'WEIGHT_SHA256_MISMATCH',
                 'PINNED_ENVIRONMENT_MISMATCH', 'MODEL_SOURCE_REVISION_MISMATCH', 'MODEL_SOURCE_DIRTY',
                 'ENCODER_READY_GATE_FAILED', 'WORKER_RESTART_REQUIRED',
                 'GPU_UNAVAILABLE', 'GPU_ARCHITECTURE_UNSUPPORTED'}
        code = str(exc) if str(exc) in codes else ('DEPENDENCY_OR_ASSET_MISSING' if isinstance(exc, (ImportError, FileNotFoundError)) else 'WORKER_START_OR_RUNTIME_FAILED')
        atomic_json(Path(cfg.state_dir) / 'worker-last-exit.json', dict(lastError=code, workerEpoch=worker.metrics.epoch))
        worker.metrics.event('WorkerExited', error_type=type(exc).__name__, last_error_code=code)
        return 70
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
