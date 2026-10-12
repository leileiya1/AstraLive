"""Opt-in TCP1.2 staging lease. No business authority or model algorithm.

Native RGB stays private until all required sinks prove consumption. Socket
writing and safe cleanup are separate from control dispatch/inference.
"""
import collections
import copy
import hashlib
import queue
import struct
import threading
import time

import av

from .staging_contract import (CAPABILITY, REVISION, ContractError, LeaseBudget,
    bytes_digest, canonical_bytes, decode_header, descriptor_hash, digest,
    negotiation_watermark, profile, validate_message, validate_negotiation,
    validate_pose_consumed)
from .validated.adapter import AudioChunk
from .validated.wire import MAX_HEADER, MAX_PAYLOAD, read_exact, send


def milliseconds():
    return time.monotonic_ns() // 1000000


class StagingDiagnosticFault(ContractError):
    """Local diagnostic only; wire errors and frozen limits are unchanged."""
    def __init__(self, reason_code, resources=None):
        super().__init__(reason_code)
        self.reason_code, self.resources = reason_code, resources


class StagingConnection:
    def __init__(self, worker, sock, auth):
        self.worker, self.sock, self.auth = worker, sock, auth
        self.session, self.epoch = auth['session_id'], worker.metrics.epoch
        self.limits = profile(worker.cfg.staging_profile,
            short_gpu_gate=worker.cfg.staging_short_gate_sha256 is not None)
        if auth['requested_limits_revision'] != self.limits['limits_revision']:
            raise ContractError('operator profile mismatch')
        if worker.cfg.mode == 'simulation' and self.limits['limits_revision'] != 'staging-short-1':
            raise ContractError('simulation cannot enable long GPU profile')
        self.adapter = None
        self.lock = threading.RLock()
        self.cv = threading.Condition(self.lock)
        self.done = threading.Event()
        self.outbound = queue.PriorityQueue(64)
        self.order = 0
        self.queued_video = self.wire_bytes = 0
        self.writer_busy = self.encoder_busy = False
        self.stage = None
        self.fenced = threading.Event()
        self.replay = collections.OrderedDict()
        self.threads = []
        self.releasing = False

    def common(self, name, identity=None):
        return dict(type=name, contract_revision=REVISION, session_id=self.session,
            worker_epoch=self.epoch, identity=copy.deepcopy(identity or self.stage['identity']))

    def reply(self, header, payload=b''):
        validate_message(header, payload)
        with self.lock:
            self.order += 1
            video = header['type'] == 'StageVideo'
            if video:
                self.queued_video += 1
                self.wire_bytes += len(payload)
            try:
                self.outbound.put_nowait((1 if video else 0, self.order, header, payload))
            except queue.Full:
                if video:
                    self.queued_video -= 1
                    self.wire_bytes -= len(payload)
                self.done.set()
                if self.stage:
                    self.worker.staging_unknown = True
                raise ContractError('bounded writer queue exhausted')

    def writer(self):
        try:
            while not self.done.is_set():
                try:
                    _, _, header, payload = self.outbound.get(timeout=.05)
                except queue.Empty:
                    continue
                with self.lock:
                    video = header['type'] == 'StageVideo'
                    if video:
                        self.queued_video -= 1
                        self.wire_bytes -= len(payload)
                    stale = (header['type'] in {'StageVideo', 'StageProduced'} and
                        (self.fenced.is_set() or not self.stage or header['identity'] != self.stage['identity']))
                    self.writer_busy = not stale
                try:
                    if not stale:
                        # The write was admitted before a concurrent fence;
                        # already transmitted TCP bytes cannot be withdrawn.
                        send(self.sock, header, payload)
                finally:
                    with self.cv:
                        self.writer_busy = False
                        self.cv.notify_all()
                    self.outbound.task_done()
        except Exception:
            if self.stage:
                self.worker.staging_unknown = True
            self.done.set()
            try:
                self.sock.shutdown(2)
            except OSError:
                pass

    def read(self):
        header_size, size = struct.unpack('!II', read_exact(self.sock, 8))
        if header_size > MAX_HEADER or size > MAX_PAYLOAD:
            raise ContractError('wire budget exceeded')
        return decode_header(read_exact(self.sock, header_size)), read_exact(self.sock, size)

    def pose_digest(self):
        with self.adapter.cv:
            return bytes_digest(b''.join(frame.tobytes() for frame in self.adapter.committed))

    def counters(self):
        with self.adapter.cv:
            return dict(audio_credit_samples=self.adapter.AUDIO_BOUND - self.adapter.pending_samples,
                native_queue_frames=len(self.adapter.video),
                network_inflight_frames=0 if not self.stage else max(0, len(self.stage['frames']) - self.stage['received'] - 1))

    def provenance(self, identity):
        ready = self.worker.ready
        return dict(workerRef=self.worker.cfg.worker_ref, workerEpoch=self.epoch,
            model_source_revision=self.worker.cfg.model_revision,
            weights_manifest_sha256='sha256:' + self.worker.cfg.manifest_sha256,
            avatar_sha256='sha256:' + self.worker.cfg.asset_sha256,
            input_asset_sha256='sha256:' + self.worker.cfg.asset_sha256,
            cache_id=self.worker.model.cache_id, preprocessing_version='soulx-lite-512-seed42-v1',
            capability=CAPABILITY, source='GPU_INFERENCE' if self.worker.cfg.mode == 'gpu' else 'CPU_SIMULATION')

    def error(self, header, code):
        result = self.common('StageError', header['identity'])
        result.update(code=code, operation_id=header.get('control_id') or header.get('pose_ack_id'),
            publication_fenced=self.fenced.is_set(), state=self.stage['state'] if self.stage else 'RETIRED')
        self.reply(result)

    def fence(self):
        self.fenced.set()
        if self.stage and self.stage['state'] != 'RELEASED':
            self.stage['state'] = 'FENCED'
            self.stage['lease'].fence()
            self.adapter.cancel(self.stage['identity']['workerGenerationId'])
        with self.cv:
            self.cv.notify_all()

    def remember(self, key, request, response):
        fingerprint = digest(request)
        if len(self.replay) >= 1024:
            self.fence()
            raise ContractError('attempt replay capacity exceeded')
        self.replay[key] = (fingerprint, copy.deepcopy(response))
        return response

    def cached(self, key, request):
        prior = self.replay.get(key)
        if prior:
            if prior[0] != digest(request):
                raise ContractError('same operation conflicts')
            self.reply(copy.deepcopy(prior[1]))
            return True
        return False

    def begin(self, h):
        identity = h['identity']
        key = ('StageBegin', identity['stageId'])
        if self.cached(key, h):
            return
        if (self.worker.staging_unknown or self.stage and self.stage['state'] != 'RELEASED' or
                identity['workerGenerationId'] <= self.worker.highest_generation or
                identity['stageId'] in self.worker.staging_terminals):
            self.error(h, 'STAGING_RETIRED')
            return
        if identity['workerRef'] != self.worker.cfg.worker_ref or h['cache_id'] != self.worker.model.cache_id:
            raise ContractError('worker/cache identity mismatch')
        if h['limits_revision'] != self.limits['limits_revision']:
            raise ContractError('operator limits mismatch')
        if self.adapter.native_busy_generation is not None:
            self.error(h, 'STAGING_CLEANUP_PENDING')
            return
        self.replay.clear()
        self.fenced.clear()
        gpu = self.worker.model.gpu()
        if self.worker.cfg.mode == 'gpu':
            import torch
            torch.cuda.reset_peak_memory_stats()
        self.stage = dict(identity=copy.deepcopy(identity), begin=copy.deepcopy(h), state='STAGING',
            lease=LeaseBudget(h, milliseconds()), samples=0, chunk_sequence=0, eof=False,
            frames={}, received=-1, pose=-1, pose_fingerprint=None, descriptor=None,
            descriptor_hash=None, commit=None, slots=4, pcm_hash=hashlib.sha256(),
            native_hash=hashlib.sha256(), video_hash=hashlib.sha256(), video_bytes=0,
            rgb_bytes=0, rgb_peak=0, host_peak=0, gpu_baseline=gpu.get('gpuAllocatedBytes'),
            gpu_reserved_baseline=gpu.get('gpuReservedBytes'), started_ns=time.monotonic_ns(),
            disposition=None, reusable=False, cancel=None)
        self.worker.highest_generation = identity['workerGenerationId']
        self.worker.active = identity['workerGenerationId']
        self.adapter.begin(identity['workerGenerationId'], 0)
        reply = self.common('StageBegun')
        reply.update(request_fingerprint=h['request_fingerprint'], audio_credit_samples=32000,
            limits=copy.deepcopy(self.limits), pose_history_sha256=self.pose_digest())
        self.remember(key, h, reply)
        self.reply(reply)
        self.cv.notify_all()

    def audio(self, h, payload):
        s = self.stage
        key = ('StageAudio', h['chunk_sequence'])
        if self.cached(key, h):
            return
        if (s['eof'] or h['chunk_sequence'] != s['chunk_sequence'] or
                h['first_sample_index'] != s['samples'] or
                s['samples'] + h['sample_count'] > s['begin']['source_samples']):
            raise ContractError('PCM sequence/count mismatch')
        end = s['samples'] + h['sample_count']
        if h['final_chunk'] != (end == s['begin']['source_samples']):
            raise ContractError('exact final chunk required')
        pad_offset = max(0, s['begin']['original_samples'] - s['samples']) * 2
        if end > s['begin']['original_samples'] and any(payload[pad_offset:]):
            raise ContractError('declared pad is not silent')
        candidate = s['pcm_hash'].copy()
        candidate.update(payload)
        if h['final_chunk'] and 'sha256:' + candidate.hexdigest() != s['begin']['pcm_sha256']:
            raise ContractError('PCM final digest mismatch')
        with self.adapter.cv:
            if self.adapter.pending_samples + h['sample_count'] > self.adapter.AUDIO_BOUND:
                self.error(h, 'STAGING_BUDGET_EXCEEDED')
                return
            accepted = self.adapter.put(AudioChunk(16000, 1, 's16le', h['chunk_sequence'],
                h['first_sample_index'], h['sample_count'], s['identity']['workerGenerationId'],
                h['final_chunk'], payload))
        if not accepted:
            raise ContractError('native admission fenced')
        s['pcm_hash'], s['samples'], s['eof'] = candidate, end, h['final_chunk']
        s['chunk_sequence'] += 1
        reply = self.common('StageAudioAccepted')
        reply.update(chunk_sequence=h['chunk_sequence'], chunk_sha256=h['chunk_sha256'],
            accepted=True, audio_credit_samples=self.counters()['audio_credit_samples'])
        self.remember(key, h, reply)
        self.reply(reply)

    def received(self, h):
        s = self.stage
        seq = h['frame_sequence']
        key = ('StageReceived', seq)
        if self.cached(key, h):
            return
        frame = s['frames'].get(seq)
        if not frame or seq != s['received'] + 1 or any(h[k] != frame[k] for k in ('payload_sha256', 'native_rgb_sha256')):
            raise ContractError('frame storage proof mismatch')
        s['received'] = seq
        s['slots'] += 1
        if s['slots'] > 4:
            raise ContractError('window overflow')
        reply = self.common('StageReceivedAck')
        reply.update(**{k:h[k] for k in ('frame_sequence', 'payload_sha256', 'native_rgb_sha256', 'storage_receipt_id')})
        self.remember(key, h, reply)
        self.reply(reply)
        self.cv.notify_all()

    def commit(self, h):
        s = self.stage
        key = ('StageCommit', 0)
        if self.cached(key, h):
            return
        proof = h['commit_proof']
        if s['state'] != 'PRODUCED' or proof['descriptor_sha256'] != s['descriptor_hash'] or proof['output']['sourceSamples'] != s['samples']:
            raise ContractError('commit is not the produced artifact')
        s['commit'] = copy.deepcopy(h)
        s['state'] = 'COMMIT_ARMED'
        reply = self.common('StageCommitAck')
        reply.update(descriptor_sha256=s['descriptor_hash'], commit_proof_fingerprint=h['commit_proof_fingerprint'], state='COMMIT_ARMED')
        self.remember(key, h, reply)
        self.reply(reply)

    def pose(self, h):
        s = self.stage
        proof = h['pose_proof']
        key = ('StagePoseConsumed', proof['pose_ack_id'])
        if self.cached(key, h):
            return
        if s['state'] != 'COMMIT_ARMED':
            raise ContractError('pose before arm')
        validate_pose_consumed(h, s['commit'])
        latest = proof['latest_consumed_sequence']
        if latest <= s['pose'] or latest > s['received']:
            raise ContractError('nonadvancing/future pose')
        for seq in range(s['pose'] + 1, latest + 1):
            item = s['frames'][seq]
            if item['rgb'] is None or bytes_digest(item['rgb'].tobytes()) != item['native_rgb_sha256']:
                raise ContractError('native pose storage corrupted')
        with self.adapter.cv:
            for seq in range(s['pose'] + 1, latest + 1):
                item = s['frames'][seq]
                self.adapter.committed.append(item['rgb'].copy())
                s['rgb_bytes'] -= item['rgb'].nbytes
                item['rgb'] = None
        s['pose'], s['pose_fingerprint'] = latest, h['pose_proof_fingerprint']
        reply = self.common('StagePoseConsumedAck')
        reply.update(pose_ack_id=proof['pose_ack_id'], pose_proof_fingerprint=h['pose_proof_fingerprint'],
            latest_consumed_sequence=latest, pose_history_sha256=self.pose_digest())
        self.remember(key, h, reply)
        self.reply(reply)

    def cancel(self, h):
        identity = h['identity']
        if self.stage is None or identity != self.stage['identity']:
            if self.stage and self.stage['state'] != 'RELEASED':
                self.error(h, 'STAGING_IDENTITY_MISMATCH')
                return
            if identity['workerGenerationId'] <= self.worker.highest_generation:
                prior = self.worker.staging_terminals.get(identity['stageId'])
                if prior and prior['cancel'] == h:
                    self.reply(copy.deepcopy(prior['fenced']))
                else:
                    self.error(h, 'STAGING_RETIRED')
                return
            self.prune_terminals()
            if len(self.worker.staging_terminals) >= 64:
                raise ContractError('tombstone capacity exhausted')
            self.worker.highest_generation = identity['workerGenerationId']
            reply = self.common('StageFenced', identity)
            reply.update(control_id=h['control_id'], publication_fenced=True,
                latest_consumed_sequence=-1, pose_history_sha256=self.pose_digest())
            self.worker.staging_terminals[identity['stageId']] = dict(cancel=copy.deepcopy(h), fenced=copy.deepcopy(reply), released=None, at=milliseconds())
            self.reply(reply)
            return
        key = ('StageCancel', h['control_id'])
        if self.cached(key, h):
            return
        if self.stage['cancel'] and self.stage['cancel'] != h:
            raise ContractError('cancel control conflicts')
        self.stage['cancel'] = copy.deepcopy(h)
        self.fence()
        reply = self.common('StageFenced')
        reply.update(control_id=h['control_id'], publication_fenced=True,
            latest_consumed_sequence=self.stage['pose'], pose_history_sha256=self.pose_digest())
        self.remember(key, h, reply)
        self.reply(reply)

    def prune_terminals(self):
        now = milliseconds()
        for key, value in list(self.worker.staging_terminals.items()):
            if now - value['at'] >= 300000:
                del self.worker.staging_terminals[key]
        if len(canonical_bytes(self.worker.staging_terminals)) > 2 * 1048576:
            raise ContractError('terminal byte budget exhausted')

    def release(self, h):
        identity = h['identity']
        prior = self.worker.staging_terminals.get(identity['stageId'])
        if self.stage is None or identity != self.stage['identity']:
            if prior and prior.get('cancel') and prior['cancel']['identity'] == identity and h['reason'] == 'CANCELLED' and h['control_id'] == prior['cancel']['control_id']:
                if (h['descriptor_sha256'] is not None or h['commit_proof_fingerprint'] is not None or
                        h['pose_proof_fingerprint'] is not None or h['latest_consumed_sequence'] != -1 or
                        prior.get('release_request') and prior['release_request'] != h):
                    raise ContractError('prebegin release conflicts')
                prior['release_request'] = copy.deepcopy(h)
                if not prior['released']:
                    reply = self.common('StageReleased', identity)
                    reply.update(control_id=h['control_id'], native_safe_boundary=True, retained_artifact_bytes=0,
                        latest_consumed_sequence=-1, pose_history_sha256=self.pose_digest(),
                        terminal_disposition='PROVEN_CANCELLED', reusable=True)
                    prior['released'] = reply
                self.reply(copy.deepcopy(prior['released']))
            else:
                self.error(h, 'STAGING_RETIRED')
            return
        s = self.stage
        key = ('StageRelease', h['control_id'])
        if self.cached(key, h):
            return
        if s.get('release_request') and s['release_request'] != h:
            raise ContractError('release control conflicts')
        if h['latest_consumed_sequence'] != s['pose'] or h['descriptor_sha256'] != s['descriptor_hash']:
            raise ContractError('release descriptor/prefix mismatch')
        if h['commit_proof_fingerprint'] != (s['commit']['commit_proof_fingerprint'] if s['commit'] else None) or h['pose_proof_fingerprint'] != s['pose_fingerprint']:
            raise ContractError('release proof mismatch')
        if h['reason'] == 'COMPLETE':
            if s['state'] != 'COMMIT_ARMED' or s['pose'] != s['samples'] // 640 - 1:
                raise ContractError('complete release lacks final pose')
        elif not self.fenced.is_set() or not s['cancel'] or h['control_id'] != s['cancel']['control_id']:
            raise ContractError('cancel release lacks matching fence')
        s['release_request'] = copy.deepcopy(h)
        if self.releasing:
            return
        self.releasing = True
        self.threads[:] = [thread for thread in self.threads if thread.is_alive()]
        thread = threading.Thread(target=self.cleanup_release, args=(s, h, key), daemon=True)
        self.threads.append(thread)
        thread.start()

    def cleanup_release(self, s, h, key):
        try:
            while not self.done.is_set():
                with self.cv:
                    status = self.adapter.native_status(s['identity']['workerGenerationId'])
                    if status['safe'] and not self.encoder_busy and not self.writer_busy and self.queued_video == 0:
                        if h['reason'] == 'COMPLETE':
                            self.adapter.finish(s['identity']['workerGenerationId'])
                            disposition = 'PROVEN_COMPLETE'
                        else:
                            disposition = 'UNKNOWN' if s['commit'] is not None else 'PROVEN_CANCELLED'
                        s['frames'].clear()
                        s['rgb_bytes'] = 0
                        self.fenced.set()
                        s['state'], s['disposition'], s['reusable'] = 'RELEASED', disposition, disposition != 'UNKNOWN'
                        if disposition == 'UNKNOWN':
                            self.worker.staging_unknown = True
                        self.worker.active = None
                        reply = self.common('StageReleased', s['identity'])
                        reply.update(control_id=h['control_id'], native_safe_boundary=True, retained_artifact_bytes=0,
                            latest_consumed_sequence=s['pose'], pose_history_sha256=self.pose_digest(),
                            terminal_disposition=disposition, reusable=s['reusable'])
                        self.remember(key, h, reply)
                        self.prune_terminals()
                        if len(self.worker.staging_terminals) >= 64:
                            raise ContractError('terminal count exhausted')
                        self.worker.staging_terminals[s['identity']['stageId']] = dict(cancel=s['cancel'], fenced=None, released=copy.deepcopy(reply), at=milliseconds())
                        self.reply(reply)
                        self.releasing = False
                        return
                time.sleep(.01)
        except Exception:
            self.worker.staging_unknown = True
            self.done.set()

    def resources(self):
        s = self.stage
        native = self.adapter.native_status(s['identity']['workerGenerationId'])
        with self.adapter.cv:
            pipeline = len(self.adapter.video) * 512 * 512 * 3 + self.adapter.pending_samples * 2
        # A conservative accounted upper bound; process/model RSS is separately
        # sampled by the external gate, never misreported as this buffer counter.
        owned = s['rgb_bytes'] + pipeline + self.wire_bytes + native['cpu_peak_bytes']
        s['host_peak'] = max(s['host_peak'], owned)
        allocated = reserved = None
        if self.worker.cfg.mode == 'gpu':
            import torch
            allocated = max(0, torch.cuda.max_memory_allocated() - s['gpu_baseline'])
            reserved = max(0, torch.cuda.max_memory_reserved() - s['gpu_reserved_baseline'])
        return dict(worker_rgb_peak_bytes=s['rgb_peak'], worker_attempt_peak_bytes=s['host_peak'],
            gpu_baseline_allocated_bytes=s['gpu_baseline'], gpu_incremental_allocated_peak_bytes=allocated,
            gpu_incremental_reserved_peak_bytes=reserved,
            inference_elapsed_us=native['inference_elapsed_us'])

    def failure_diagnostic(self, phase, exc):
        """Bounded counters only: never log exception text or private media."""
        s = self.stage
        if not s:
            return
        resource_snapshot = getattr(exc, 'resources', None)
        observation_error = None
        if resource_snapshot is None:
            try:
                resource_snapshot = self.resources()
            except Exception as observation_exc:
                observation_error = type(observation_exc).__name__[:80]
        data = dict(phase=phase, exception_type=type(exc).__name__[:80],
            reason_code=(exc.reason_code if isinstance(exc, StagingDiagnosticFault) else phase),
            resources=resource_snapshot, resource_observation_error_type=observation_error,
            limits=copy.deepcopy(self.limits), stage_state=s['state'],
            source_samples=s['samples'], stored_frames=len(s['frames']),
            received_sequence=s['received'], consumed_sequence=s['pose'],
            queued_video=self.queued_video, network_wire_bytes=self.wire_bytes)
        # Observe before fencing/cancel drains native queues. Diagnostics must
        # not prevent the existing fence/error path if telemetry itself fails.
        try:
            with self.adapter.cv:
                data.update(native_queue_frames=len(self.adapter.video),
                    pending_audio_samples=self.adapter.pending_samples)
            self.worker.metrics.event('StagingFailure', s['identity']['workerGenerationId'], **data)
        except Exception:
            pass

    def enforce_resources(self, resources):
        for measured, cap, reason in (
            ('worker_rgb_peak_bytes', 'worker_rgb_bytes', 'WORKER_RGB_CAP'),
            ('worker_attempt_peak_bytes', 'worker_attempt_bytes', 'WORKER_HOST_CAP'),
            ('gpu_incremental_allocated_peak_bytes', 'gpu_incremental_allocated_bytes', 'GPU_ALLOCATED_CAP')):
            if (resources[measured] or 0) > self.limits[cap]:
                raise StagingDiagnosticFault(reason, resources)

    def produced(self):
        s = self.stage
        if not s or s['state'] != 'STAGING' or not s['eof'] or self.fenced.is_set():
            return
        native = self.adapter.native_status(s['identity']['workerGenerationId'])
        count = s['samples'] // 640
        if (not native['final'] or native['frames'] != count or not native['safe'] or
                self.encoder_busy or len(s['frames']) != count or s['received'] != count - 1):
            return
        d = dict(descriptor_revision='staging-descriptor-1', identity=copy.deepcopy(s['identity']),
            request_fingerprint=s['begin']['request_fingerprint'], source_format=copy.deepcopy(s['begin']['source_format']),
            original_samples=s['begin']['original_samples'], pad_samples=s['begin']['pad_samples'],
            source_samples=s['samples'], pcm_sha256=s['begin']['pcm_sha256'], frame_count=count,
            first_sequence=0, last_sequence=count-1, first_pts_us=0, last_pts_us=(count-1)*40000,
            video_bytes=s['video_bytes'], video_stream_sha256='sha256:' + s['video_hash'].hexdigest(),
            native_rgb_stream_sha256='sha256:' + s['native_hash'].hexdigest(), eof=True,
            final_marker=True, native_final=True, limits=copy.deepcopy(self.limits),
            provenance=self.provenance(s['identity']), resources=self.resources())
        reply = self.common('StageProduced')
        reply.update(descriptor=d, descriptor_sha256=descriptor_hash(d))
        validate_message(reply)
        s['descriptor'], s['descriptor_hash'], s['state'] = d, reply['descriptor_sha256'], 'PRODUCED'
        self.reply(reply)

    def sender(self):
        ctx = generation = None
        phase = 'NATIVE_CONSUME'
        try:
            while not self.done.is_set():
                with self.cv:
                    s = self.stage
                    if not s or s['state'] != 'STAGING' or self.fenced.is_set() or s['slots'] == 0:
                        self.cv.wait(.02)
                        continue
                    gid = s['identity']['workerGenerationId']
                try:
                    phase = 'NATIVE_CONSUME'
                    packet = self.adapter.consume(lambda p: None, timeout=.1, commit=False, expected_generation=gid)
                except TimeoutError:
                    continue
                if packet is None:
                    continue
                with self.lock:
                    if s is not self.stage or self.fenced.is_set():
                        continue
                    self.encoder_busy = True
                try:
                    phase = 'ENCODER_INITIALIZATION'
                    if generation != gid:
                        ctx, generation = self.worker.model.encoder(), gid
                    phase = 'FRAME_CONVERSION'
                    frame = av.VideoFrame.from_ndarray(packet['frame'], format='rgb24')
                    frame.pts = packet['frame_sequence']
                    phase = 'H264_ENCODE'
                    encoded = ctx.encode(frame)
                    if len(encoded) != 1:
                        raise StagingDiagnosticFault('ENCODER_REORDER_OR_FLUSH')
                    phase = 'FRAME_ACCOUNTING'
                    payload = bytes(encoded[0])
                    rgb = packet['frame'].copy()
                    with self.cv:
                        if s is not self.stage or self.fenced.is_set():
                            continue
                        seq = packet['frame_sequence']
                        if seq != len(s['frames']) or seq >= s['begin']['source_samples'] // 640:
                            raise StagingDiagnosticFault('NATIVE_FRAME_SEQUENCE')
                        header = self.common('StageVideo')
                        header.update(frame_sequence=seq, pts_us=seq*40000, duration_us=40000,
                            sample_start=seq*640, sample_end=(seq+1)*640, codec='h264', width=512, height=512,
                            keyframe=encoded[0].is_keyframe, payload_sha256=bytes_digest(payload),
                            native_rgb_sha256=bytes_digest(rgb.tobytes()), provenance=self.provenance(s['identity']))
                        if seq == 0 and not header['keyframe']:
                            raise StagingDiagnosticFault('FIRST_FRAME_NOT_IDR')
                        s['frames'][seq] = dict(rgb=rgb, **{k:header[k] for k in ('payload_sha256','native_rgb_sha256')})
                        s['rgb_bytes'] += rgb.nbytes
                        s['rgb_peak'] = max(s['rgb_peak'], s['rgb_bytes'])
                        s['native_hash'].update(rgb.tobytes())
                        s['video_hash'].update(struct.pack('!Q', len(payload)) + payload)
                        s['video_bytes'] += len(payload)
                        s['slots'] -= 1
                        phase = 'RESOURCE_OBSERVATION'
                        resources = self.resources()
                        phase = 'RESOURCE_CAP_CHECK'
                        self.enforce_resources(resources)
                        phase = 'VIDEO_VALIDATION_OR_ENQUEUE'
                        self.reply(header, payload)
                finally:
                    with self.cv:
                        self.encoder_busy = False
                        self.cv.notify_all()
        except Exception as exc:
            with self.lock:
                if self.stage:
                    self.failure_diagnostic(phase, exc)
                    self.fence()
                    self.error(self.stage['begin'], 'STAGING_BUDGET_EXCEEDED')

    def watcher(self):
        while not self.done.wait(.01):
            with self.lock:
                s = self.stage
                if not s or s['state'] in {'FENCED','RELEASED'}:
                    continue
                if milliseconds() >= s['lease'].deadline or milliseconds() >= s['lease'].started + 60000:
                    self.fence()
                    self.error(s['begin'], 'STAGING_LEASE_EXPIRED')
                else:
                    try:
                        self.produced()
                    except ContractError as exc:
                        self.failure_diagnostic('PRODUCED_DESCRIPTOR_VALIDATION', exc)
                        self.fence()
                        self.error(s['begin'], 'STAGING_BUDGET_EXCEEDED')

    def dispatch(self, h, payload):
        validate_message(h, payload)
        if h['session_id'] != self.session or h['worker_epoch'] != self.epoch:
            raise ContractError('foreign connection')
        if 'identity' in h and h['identity']['workerRef'] != self.worker.cfg.worker_ref:
            raise ContractError('foreign Worker reference')
        with self.lock:
            if h['type'] == 'StageHealth':
                reply = {k:copy.deepcopy(v) for k,v in h.items()}
                reply['type'] = 'StageHealthAck'
                reply.update(self.counters())
                self.reply(reply)
                return
            if h['type'] == 'StageCancel':
                self.cancel(h)
                return
            if h['type'] == 'StageRelease':
                self.release(h)
                return
            if h['type'] == 'StageBegin':
                self.begin(h)
                return
            if not self.stage or h['identity'] != self.stage['identity']:
                self.error(h, 'STAGING_IDENTITY_MISMATCH')
                return
            if h['type'] == 'StageStatus':
                s = self.stage
                reply = self.common('StageStatusResult')
                reply.update(nonce=h['nonce'], **self.counters(), state=s['state'],
                    descriptor_sha256=s['descriptor_hash'], received_sequence=s['received'],
                    latest_consumed_sequence=s['pose'], retained_artifact_bytes=s['rgb_bytes'],
                    lease_age_ms=milliseconds()-s['lease'].started, publication_fenced=self.fenced.is_set(),
                    native_safe_boundary=self.adapter.native_status(s['identity']['workerGenerationId'])['safe'],
                    terminal_disposition=s['disposition'], reusable=s['reusable'])
                self.reply(reply)
                return
            if self.fenced.is_set() or self.stage['state'] == 'RELEASED' or milliseconds() >= self.stage['lease'].deadline:
                self.fence()
                self.error(h, 'STAGING_RETIRED')
                return
            name = h['type']
            if name == 'StageAudio':
                self.audio(h, payload)
            elif name == 'StageReceived':
                self.received(h)
            elif name == 'StageCommit':
                self.commit(h)
            elif name == 'StagePoseConsumed':
                self.pose(h)
            elif name == 'StageRenew':
                self.reply(self.stage['lease'].renew(h, milliseconds()))
            else:
                raise ContractError('unexpected client operation')

    def run(self):
        ready = self.worker.ready
        response = dict(type='GPU_WORKER_READY', status='GPU_WORKER_READY', contract_revision=REVISION,
            internal_version='1.2', session_id=self.session, worker_epoch=self.epoch,
            cache_id=ready['cache_id'], input_asset_sha256='sha256:' + ready['input_asset_sha256'],
            model_revision=ready['model_revision'], model_load_count=ready['model_load_count'],
            codec='h264', av_version=str(ready['av_version']), torch_version=str(ready['torch_version']),
            weights_manifest_sha256='sha256:' + ready['weights_manifest_sha256'], simulation=ready['simulation'],
            selected_capabilities=[CAPABILITY], highest_generation_id=negotiation_watermark(self.worker.highest_generation),
            selected_limits=copy.deepcopy(self.limits), profile_gate_ref=self.worker.cfg.staging_short_gate_sha256)
        validate_negotiation(self.auth, response)
        send(self.sock, response)
        self.sock.settimeout(5)
        self.adapter = self.worker.adapter = self.worker.model.adapter()
        for name, target in [('staging-writer',self.writer), ('staging-encoder',self.sender), ('staging-watchdog',self.watcher)]:
            thread = threading.Thread(target=target, name=name, daemon=True)
            self.threads.append(thread)
            thread.start()
        try:
            while not self.done.is_set() and not self.worker.stop.is_set():
                h, payload = self.read()
                try:
                    self.dispatch(h, payload)
                except ContractError:
                    with self.lock:
                        self.fence()
                        if 'identity' in h:
                            self.error(h, 'STAGING_CONFLICT')
                        else:
                            raise
        except (OSError, EOFError, ContractError):
            if self.stage and self.stage['state'] != 'RELEASED':
                self.worker.staging_unknown = True
        finally:
            self.done.set()
            with self.cv:
                self.fence()
                self.cv.notify_all()
            self.adapter.close()
            try:
                self.sock.shutdown(2)
            except OSError:
                pass
            for thread in self.threads:
                thread.join(5)
            self.worker.adapter = self.worker.active = None
            if any(thread.is_alive() for thread in self.threads) or self.adapter.error:
                raise RuntimeError('WORKER_RESTART_REQUIRED')
