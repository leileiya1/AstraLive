"""One Room per independent guardian, authenticated Unix IPC, closed on any doubt."""

import asyncio
import base64
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .model import Attempt, Binding, Closed, identifier, integer
from .observe import verify_combined
from .process import Publisher
from .rtmp_proxy import PublishingSocket


class Guardian:
    def __init__(
        self,
        authority,
        ingest,
        state_dir,
        recording_dir,
        *,
        rtmp_url,
        path,
        width=256,
        height=256,
        fps=25,
        sample_rate=16000,
        webrtc=False,
    ):
        if (
            width % 2
            or height % 2
            or not 2 <= width <= 1920
            or not 2 <= height <= 1920
            or width * height > 1920 * 1080
        ):
            raise ValueError("invalid dimensions")
        if not 1 <= fps <= 60 or sample_rate not in {16000, 24000, 48000}:
            raise ValueError("invalid media configuration")
        target = urlsplit(rtmp_url)
        if (
            target.scheme != "rtmp"
            or target.hostname not in {"127.0.0.1", "::1"}
            or target.path not in {"", "/"}
            or target.query
            or target.fragment
            or target.username
        ):
            raise ValueError("dedicated loopback RTMP target required")
        self.authority, self.ingest = authority, ingest
        self.api_secret = secrets.token_urlsafe(32)
        self.ingest.api_secret = self.api_secret
        self.state_dir, self.recording_dir = Path(state_dir), Path(recording_dir)
        self.path, self.rtmp_url = identifier(path), rtmp_url.rstrip("/")
        self.media_config = dict(
            width=width, height=height, fps=fps, sample_rate=sample_rate
        )
        self.publisher = Publisher(state_dir)
        self.receiver = Publisher(state_dir, "receiver")
        self.publishing_socket = None
        self.observer_started = False
        self.binding = self.attempt = self.right = None
        self.secret = self.read_secret = self.publisher_id = None
        self.publisher_seen = False
        self.barrier, self.generation = 0, 0
        self.failed, self.started, self.finishing = True, False, False
        self.operations, self.closing = asyncio.Lock(), asyncio.Lock()
        self.audio_sequence, self.video_pts = 0, -1
        self.audio_samples, self.video_frames = 0, 0
        self.stopped = set()
        self.used_attempts = set()
        self.webrtc_enabled, self.web = webrtc, None
        self.watchdog = self.poller = self.lock_file = None
        self.last_fault = None
        self.records_before = set()

    def persist_stops(self):
        target = self.state_dir / "stopped.json"
        temp = target.with_suffix(".tmp")
        with temp.open("w") as f:
            json.dump(sorted(self.stopped), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        fd = os.open(self.state_dir, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    async def start(self):
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (
            self.state_dir.is_symlink()
            or self.state_dir.stat().st_uid != os.geteuid()
            or self.state_dir.stat().st_mode & 0o077
        ):
            raise Closed()
        self.lock_file = (self.state_dir / "room.lock").open("a")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Closed() from None
        target = self.state_dir / "stopped.json"
        if target.exists():
            try:
                stored = json.loads(target.read_text())
                if not isinstance(stored, list) or len(stored) != len(set(stored)):
                    raise Closed()
                self.stopped = set(stored)
                for run in self.stopped:
                    identifier(run)
            except Exception:
                raise Closed() from None
        # Authentication is still closed. Do not restore an old permit/secret.
        self.publisher.recover()
        self.receiver.recover()
        await self.authority.start()
        await self.ingest.start()
        for retry in range(40):
            try:
                await self.ingest.isolate()
                break
            except Closed:
                if retry == 39:
                    raise
                await asyncio.sleep(0.05)
        self.started, self.failed = True, False
        self.watchdog = asyncio.create_task(self._watch(), name="guardian-expiry")
        self.poller = asyncio.create_task(self._poll(), name="guardian-authority")

    def invalidate(self, *, fatal=False):
        self.barrier += 1
        self.right = None
        self.secret = self.read_secret = None
        self.publisher_id = None
        self.publisher_seen = False
        self.failed |= fatal

    def check(self, attempt=None):
        if (
            self.failed
            or not self.started
            or self.binding is None
            or self.attempt is None
            or self.binding.runId in self.stopped
            or self.right is None
        ):
            raise Closed()
        self.right.check()
        if attempt is not None and attempt != self.attempt:
            raise Closed("STALE_RUN_EPOCH")

    async def close_resources(self):
        async with self.closing:
            await self.publisher.abort()
            await self.receiver.abort()
            if self.publishing_socket:
                socket, self.publishing_socket = self.publishing_socket, None
                await socket.close()
            if self.web:
                # stop() cancels sender tracks and closes actual DTLS/SRTP sockets.
                output, self.web = self.web, None
                await asyncio.wait_for(output.stop(), 0.5)
            await self.ingest.isolate()

    async def retire(self, fatal=False):
        self.invalidate(fatal=fatal)
        try:
            await self.close_resources()
        except BaseException:
            self.failed = True
            raise Closed() from None

    async def install(self, binding):
        async with self.operations:
            if self.failed or not self.started or binding.runId in self.stopped:
                raise Closed()
            self.authority.scope_check(binding)
            if (
                self.binding
                and binding.outputBindingVersion <= self.binding.outputBindingVersion
            ):
                raise Closed("STALE_RUN_EPOCH")
            await self.retire()
            barrier = self.barrier
            await self.authority.pending(binding)
            if barrier != self.barrier or binding.runId in self.stopped:
                raise Closed()
            # A second ingest observation follows SQL; Runtime cannot assert this.
            await self.ingest.isolate()
            if barrier != self.barrier or binding.runId in self.stopped:
                raise Closed()
            self.binding, self.attempt, self.generation = binding, None, 0
            receipt = {
                "proofRef": "guardian_" + uuid.uuid4().hex,
                "binding": binding.json(),
                "barrier": barrier,
                "state": "CLOSED_FENCED",
            }
            target = self.state_dir / "fence.json"
            with target.with_suffix(".tmp").open("w") as f:
                json.dump(receipt, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(target.with_suffix(".tmp"), target)
            fd = os.open(self.state_dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            return receipt

    async def bind(self, attempt, permit_id):
        async with self.operations:
            if (
                self.failed
                or attempt.binding != self.binding
                or attempt.generation <= self.generation
                or attempt.binding.runId in self.stopped
                or attempt.attemptId in self.used_attempts
            ):
                raise Closed("STALE_RUN_EPOCH")
            await self.retire()
            barrier = self.barrier
            right = await self.authority.permit(attempt, permit_id)
            right.check()
            if (
                barrier != self.barrier
                or self.failed
                or attempt.binding.runId in self.stopped
            ):
                raise Closed()
            self.used_attempts.add(attempt.attemptId)
            self.attempt, self.right, self.generation = (
                attempt,
                right,
                attempt.generation,
            )
            self.audio_sequence, self.video_pts = 0, -1
            self.audio_samples, self.video_frames = 0, 0
            self.finishing = False
            self.observer_started = False
            self.secret = secrets.token_urlsafe(32)
            self.read_secret = secrets.token_urlsafe(32)
            self.records_before = set(self.recording_dir.rglob("*.mp4"))

            # No URL or credential is ever placed in argv, logs, state or replies.
            def check_socket():
                self.check(attempt)
                if self.barrier != barrier:
                    raise Closed()

            target = urlsplit(self.rtmp_url)
            self.publishing_socket = PublishingSocket(
                check_socket, target.hostname, target.port or 1935
            )
            port = await self.publishing_socket.start()
            config = self.media_config | {
                "url": f"rtmp://127.0.0.1:{port}/{self.path}?user=guardian&pass={self.secret}",
                "deadline": right.deadline,
                "monotonic_deadline": right.monotonic_deadline,
                "identity": attempt.json(),
            }
            try:
                await self.publisher.start(config)
                if self.webrtc_enabled:
                    from .webrtc import GuardianWebRTCOutput

                    def check_peer():
                        self.check(attempt)
                        if self.barrier != barrier:
                            raise Closed()

                    self.web = GuardianWebRTCOutput(
                        check_peer, fps=self.media_config["fps"]
                    )
                    await self.web.start()
                    await self.web.interrupt(attempt.generation)
                self.check(attempt)
                if barrier != self.barrier:
                    raise Closed()
            except BaseException:
                await self.retire()
                raise
            return {"state": "AUTHORIZED", "barrier": self.barrier}

    async def renew(self, attempt, permit_id):
        self.check(attempt)
        barrier, old_right = self.barrier, self.right
        try:
            right = await self.authority.permit(attempt, permit_id)
            # A late renewal may never revive an expired local authorization.
            old_right.check()
            self.check(attempt)
            if barrier != self.barrier:
                raise Closed()
            right.check()
            await self.publisher.call(
                {
                    "op": "permit",
                    "deadline": right.deadline,
                    "monotonic_deadline": right.monotonic_deadline,
                }
            )
            old_right.check()
            if barrier != self.barrier:
                raise Closed()
            self.right = right
        except BaseException:
            await self.retire()
            raise Closed("LEASE_LOST") from None
        return {"state": "AUTHORIZED"}

    async def media(self, attempt, packet):
        self.check(attempt)
        if self.finishing:
            raise Closed("STATE_CONFLICT")
        barrier = self.barrier
        kind, payload = packet["kind"], packet["payload"]
        from runtime.app.providers import AudioChunk, VideoFrame

        if kind == "audio":
            sequence = integer(packet["sequence"])
            if (
                sequence != self.audio_sequence
                or not payload
                or len(payload) % 2
                or len(payload) > self.media_config["sample_rate"] * 2 // 5
            ):
                raise Closed("INVALID_ARGUMENT")
            if (
                self.audio_samples + len(payload) // 2
                > self.media_config["sample_rate"] * 6
            ):
                raise Closed("INVALID_ARGUMENT")
            self.audio_samples += len(payload) // 2
            self.audio_sequence += 1
            item = AudioChunk(
                attempt.generation,
                sequence,
                payload,
                self.media_config["sample_rate"],
                1,
            )
            message = {"op": "audio", "payload": payload}
        elif kind == "video":
            pts = integer(packet["pts_us"])
            if (
                pts <= self.video_pts
                or len(payload)
                != self.media_config["width"] * self.media_config["height"] * 3
            ):
                raise Closed("INVALID_ARGUMENT")
            if self.video_frames >= self.media_config["fps"] * 6:
                raise Closed("INVALID_ARGUMENT")
            if self.video_frames == 0 and pts != 0:
                await self.retire()
                raise Closed("OUTPUT_FENCE_UNPROVEN")
            self.video_frames += 1
            self.video_pts = pts
            item = VideoFrame(
                attempt.generation,
                pts,
                self.media_config["width"],
                self.media_config["height"],
                payload,
            )
            message = {"op": "video", "payload": payload, "pts_us": pts}
        else:
            raise Closed("INVALID_ARGUMENT")
        try:
            await self.publisher.call(message)
            self.check(attempt)
            if barrier != self.barrier:
                raise Closed()
            if self.web:
                await asyncio.wait_for(getattr(self.web, "push_" + kind)(item), 0.1)
            self.check(attempt)
        except BaseException:
            await self.retire()
            raise Closed("MEDIA_DELIVERY_FAILED") from None
        return {"accepted": True}  # Explicitly NOT a drain/checkpoint or GPU credit.

    async def offer(self, attempt, sdp):
        self.check(attempt)
        output = self.web
        if output is None:
            raise Closed()
        barrier = self.barrier
        answer = await output.create_answer(sdp)
        self.check(attempt)
        if barrier != self.barrier:
            raise Closed()
        return {"sdp": answer, "type": "answer"}

    async def finish(self, attempt):
        async with self.operations:
            self.check(attempt)
            if self.finishing:
                raise Closed("STATE_CONFLICT")
            self.finishing = True
            barrier = self.barrier
            try:
                response = await self.publisher.call({"op": "finish"}, timeout=0.25)
                manifest = response
                # Observe the real RTMP reader before closing the publisher;
                # recorder teardown is permitted to lose its final partial part.
                for _ in range(100):
                    self.check(attempt)
                    try:
                        observed = await self.receiver.call({"op": "status"})
                        paths = sorted(
                            set(self.recording_dir.rglob("*.mp4")) - self.records_before
                        )
                        evidence = await asyncio.to_thread(
                            verify_combined, paths, observed, manifest
                        )
                        evidence["attempt"] = attempt.json()
                        evidence["guardianId"] = self.authority.guardian_id
                        evidence["barrier"] = barrier
                        evidence.pop("evidenceSHA256", None)
                        evidence["evidenceSHA256"] = hashlib.sha256(
                            json.dumps(evidence, sort_keys=True).encode()
                        ).hexdigest()
                        break
                    except Exception as exc:
                        self.last_drain_stats = {
                            "connected": observed.get("connected"),
                            "openErrorType": observed.get("openErrorType"),
                            "openErrorNumber": observed.get("openErrorNumber"),
                            "packets": {
                                k: len(v)
                                for k, v in observed.get("manifest", {}).items()
                            },
                            "decodeError": observed.get("decodeError"),
                            "transportEnded": observed.get("transportEnded"),
                            "recordings": len(paths),
                        }
                        self.last_drain_fault = getattr(exc, "code", type(exc).__name__)
                        await asyncio.sleep(0.01)
                else:
                    raise Closed("DRAIN_UNKNOWN")
                self.check(attempt)
                if barrier != self.barrier:
                    raise Closed("DRAIN_UNKNOWN")
                if self.webrtc_enabled:
                    # Existing aiortc track consumption is NOT a decoded-peer
                    # proof. Agent 4 must install the trusted receiver adapter.
                    raise Closed("DRAIN_UNKNOWN")
                await self.publisher.abort()
                await self.receiver.abort()
                await self.publishing_socket.close()
                self.publishing_socket = None
                self.secret, self.publisher_id = None, None
                await self.ingest.isolate()
                self.invalidate()
                return {
                    "state": "LOCAL_MEDIA_DRAINED",
                    "attempt": attempt.json(),
                    "requiredSinks": ["rtmp"],
                    "evidence": [evidence],
                }
            except BaseException:
                await self.retire()
                raise Closed("DRAIN_UNKNOWN") from None

    async def stop(self, run_id):
        identifier(run_id)
        # Synchronous tombstone/barrier precedes every await and defeats an
        # already in-flight install/renewal. No permit/lease needed for Stop.
        self.stopped.add(run_id)
        self.persist_stops()
        if not self.binding or self.binding.runId == run_id:
            await self.retire()
        return {"state": "CLOSED_FENCED", "runId": run_id}

    async def _watch(self):
        while self.started:
            await asyncio.sleep(0.005)
            if self.right is not None:
                try:
                    self.check()
                except Closed as exc:
                    self.last_fault = exc.code
                    try:
                        await self.retire()
                    except Closed:
                        pass

    async def _poll(self):
        last_poll = 0
        while self.started:
            await asyncio.sleep(0.05)
            if self.right is None:
                continue
            try:
                self.check()
                if time.monotonic() - last_poll >= 0.1:
                    last_poll = time.monotonic()
                    attempt, right, barrier = self.attempt, self.right, self.barrier
                    checked = await self.authority.permit(attempt, right.permit_id)
                    if barrier != self.barrier:
                        continue
                    self.check(attempt)
                    # Polling the SAME permit can only shorten its deadline.
                    if checked.deadline < self.right.deadline:
                        self.right = checked
                    if not self.observer_started and await self.ingest.ready():
                        self.check(attempt)
                        if self.barrier != barrier:
                            continue
                        self.observer_started = True
                        await self.receiver.start(
                            {
                                "url": f"{self.rtmp_url}/{self.path}?user=observer&pass={self.read_secret}"
                            }
                        )
                        self.check(attempt)
                        if self.barrier != barrier:
                            continue
                    if not self.finishing:
                        publishers = await self.ingest.publishers()
                        if len(publishers) > 1:
                            raise Closed()
                        if publishers:
                            if self.publisher_id is None:
                                # Only a publish auth callback may supply the ID.
                                raise Closed()
                            await self.ingest.exclusive(self.publisher_id)
                            self.publisher_seen = True
                        elif self.publisher_seen:
                            raise Closed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_fault = getattr(exc, "code", type(exc).__name__)
                try:
                    await self.retire()
                except Closed:
                    pass

    async def auth(self, packet):
        # Called only on the private MediaMTX loopback listener. No Runtime route.
        action = packet.get("action")
        if action == "api":
            return (
                packet.get("ip") in {"127.0.0.1", "::1"}
                and packet.get("user") == "guardian-api"
                and hmac.compare_digest(
                    str(packet.get("password", "")), self.api_secret
                )
            )
        if (
            action not in {"publish", "read"}
            or packet.get("protocol") != "rtmp"
            or packet.get("path") != self.path
        ):
            return False
        try:
            self.check()
        except Closed:
            return False
        if (
            not self.secret
            or packet.get("user") != ("guardian" if action == "publish" else "observer")
            or not hmac.compare_digest(
                str(packet.get("password", "")),
                self.secret if action == "publish" else self.read_secret,
            )
        ):
            return False
        if action == "read":
            return True
        connection_id = packet.get("id")
        if not connection_id or (
            self.publisher_id is not None and connection_id != self.publisher_id
        ):
            return False
        self.publisher_id = connection_id
        return True

    async def close(self):
        if not self.started and self.lock_file is None:
            return
        self.started = False
        tasks = [t for t in (self.watchdog, self.poller) if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self.retire()
        finally:
            await self.authority.close()
            await self.ingest.close()
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None


def ipc_app(guardian, control_token, producers):
    if (
        len(control_token) < 32
        or not producers
        or any(len(t) < 32 or t == control_token for t in producers)
    ):
        raise ValueError("distinct registered tokens required")

    @web.middleware
    async def errors(request, handler):
        try:
            return await handler(request)
        except Closed as exc:
            status = {
                "FORBIDDEN": 403,
                "INVALID_ARGUMENT": 422,
                "DEPENDENCY_UNAVAILABLE": 503,
                "MEDIA_DELIVERY_FAILED": 502,
            }.get(exc.code, 409)
            return web.json_response({"code": exc.code}, status=status)
        except (ValueError, KeyError, TypeError):
            return web.json_response({"code": "INVALID_ARGUMENT"}, status=422)
        except Exception:
            return web.json_response({"code": "DEPENDENCY_UNAVAILABLE"}, status=503)

    app = web.Application(client_max_size=9 * 1024 * 1024, middlewares=[errors])

    async def handle(request):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        control = hmac.compare_digest(token, control_token)
        producer = next(
            (p for t, p in producers.items() if hmac.compare_digest(token, t)), None
        )
        if not control and producer is None:
            raise Closed("FORBIDDEN")
        data = await request.json(loads=lambda s: strict_json(s))
        op = request.match_info["op"]
        if op in {"install", "bind", "stop"} and not control:
            raise Closed("FORBIDDEN")
        if op == "install" and set(data) == {"binding"}:
            result = await guardian.install(Binding.parse(data["binding"]))
        elif op == "stop" and set(data) == {"runId"}:
            result = await guardian.stop(data["runId"])
        elif op in {"bind", "renew"} and set(data) == {"attempt", "permitId"}:
            attempt = Attempt.parse(data["attempt"])
            if not control and attempt.binding.producerIncarnation != producer:
                raise Closed("FORBIDDEN")
            result = await getattr(guardian, op)(attempt, identifier(data["permitId"]))
        elif op in {"media", "offer", "finish"}:
            attempt = Attempt.parse(data["attempt"])
            if not control and attempt.binding.producerIncarnation != producer:
                raise Closed("FORBIDDEN")
            if (
                op == "media"
                and set(data) == {"attempt", "kind", "payload", "sequence"}
                and data["kind"] == "audio"
            ):
                result = await guardian.media(
                    attempt,
                    data
                    | {"payload": base64.b64decode(data["payload"], validate=True)},
                )
            elif (
                op == "media"
                and set(data) == {"attempt", "kind", "payload", "pts_us"}
                and data["kind"] == "video"
            ):
                result = await guardian.media(
                    attempt,
                    data
                    | {"payload": base64.b64decode(data["payload"], validate=True)},
                )
            elif (
                op == "offer"
                and set(data) == {"attempt", "sdp"}
                and isinstance(data["sdp"], str)
                and len(data["sdp"]) <= 65536
            ):
                result = await guardian.offer(attempt, data["sdp"])
            elif op == "finish" and set(data) == {"attempt"}:
                try:
                    result = await asyncio.wait_for(guardian.finish(attempt), 2)
                except asyncio.TimeoutError:
                    await guardian.retire()
                    raise Closed("DRAIN_UNKNOWN") from None
            else:
                raise Closed("INVALID_ARGUMENT")
        else:
            raise Closed("INVALID_ARGUMENT")
        return web.json_response(result)

    app.router.add_post("/guardian/v1/{op}", handle)
    return app


def strict_json(value):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError("duplicate key")
            out[k] = v
        return out

    return json.loads(
        value,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )


def auth_app(guardian):
    app = web.Application(client_max_size=16384)

    async def auth(request):
        return web.Response(
            status=200 if await guardian.auth(await request.json()) else 401
        )

    app.router.add_post("/auth", auth)
    return app
