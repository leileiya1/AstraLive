"""Versioned endpoint/session adapter around the unchanged validated receive/credit logic."""
import asyncio
import json
from pathlib import Path
import socket
import time

from .config import IDENTIFIER, secret
from .validated.async_link import WorkerLink as ValidatedLink
from .validated.prefetch import WorkerUnavailable


class WorkerLink(ValidatedLink):
    def __init__(self, endpoint, session_id, log=lambda *a, **k: None):
        if not IDENTIFIER.fullmatch(session_id):
            raise ValueError('invalid session ID')
        self.endpoint, self.session_id = endpoint, session_id
        super().__init__(endpoint['tokenFile'], log)
        self.retired_epoch = None

    async def _write(self, header, payload=b''):
        if header['type'] != 'Auth':
            header = dict(header, session_id=self.session_id, worker_epoch=self.epoch)
        return await super()._write(header, payload)

    async def _read(self):
        header, payload = await super()._read()
        if self.epoch and header.get('session_id') != self.session_id:
            raise WorkerUnavailable('worker session mismatch')
        return header, payload

    async def receive(self, gid):
        packet = await super().receive(gid)
        if self.ready.get('simulation'):
            packet['source'] = 'CPU_SIMULATION'
        return packet

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', self.endpoint['port']), 1)
            await self._write(dict(type='Auth', protocol_version=1, internal_version='1.1', session_id=self.session_id, token=secret(self.token_file)))
            self.ready, _ = await asyncio.wait_for(self._read(), 5)
            if self.ready.get('type') != 'GPU_WORKER_READY' or self.ready.get('internal_version') != '1.1':
                raise WorkerUnavailable('worker not ready/version mismatch')
            if self.ready.get('simulation') and not self.endpoint.get('allowSimulation', False):
                raise WorkerUnavailable('simulation worker not allowed')
            self.epoch = self.ready['worker_epoch']
            self.rx = asyncio.create_task(self._receive_loop())
            self.health_task = asyncio.create_task(self._health())
            await self._write(dict(type='PrepareAvatar', avatar_id=self.endpoint['avatarRef'], input_asset_sha256=self.endpoint['assetSHA256']))
        except BaseException as exc:
            await self.close()
            if not isinstance(exc, Exception):
                raise
            raise WorkerUnavailable(type(exc).__name__) from exc

    async def close(self):
        writer = self.writer
        try:
            await asyncio.wait_for(super().close(), 2)
        except asyncio.TimeoutError:
            pass
        finally:
            # Bound a transport whose pending write cannot drain after tunnel loss.
            if writer and self.writer is not None:
                writer.transport.abort()
                self.writer = None

    async def reconnect(self, attempts=24, recovery_window_s=300):
        # Caller must first fence/degrade current job. Reconnect admits FUTURE jobs only.
        if self.active is not None:
            raise ValueError('cancel active generation before reconnect')
        if type(attempts) is not int or not 1 <= attempts <= 24 or not 0 < recovery_window_s <= 1800:
            raise ValueError('invalid bounded recovery policy')
        self.retired_epoch = self.epoch
        await self.close()
        deadline = time.monotonic() + recovery_window_s
        for attempt in range(attempts):
            if time.monotonic() >= deadline:
                break
            fresh = type(self)(self.endpoint, self.session_id, self.log)
            try:
                await fresh.connect()
                return fresh
            except WorkerUnavailable:
                if attempt + 1 < attempts:
                    await asyncio.sleep(min(15, .5 * 2**attempt, max(0, deadline-time.monotonic())))
        raise WorkerUnavailable('recovery attempts exhausted')


def resolve_binding(binding, registry_path, scope):
    """Only consume an already authorized immutable Agent 1 binding, never browser IDs."""
    profiles = binding['profiles']
    avatars = [p for p in profiles if p['kind'] == 'AVATAR' and p['provider'] == 'soulx']
    if len(avatars) != 1:
        raise ValueError('one bound SoulX avatar required')
    config = avatars[0]['config']
    workers = [p for p in profiles if p['kind'] == 'GPU_WORKER' and p['provider'] == 'soulx' and p['profileId'] == config.get('workerProfileId')]
    if len(workers) != 1:
        raise ValueError('bound workerProfileId required')
    ref = workers[0]['config']['workerRef']
    entries = json.loads(Path(registry_path).read_text())
    endpoint = entries['workers'].get(ref)
    if entries.get('registryVersion') != '1.0' or not endpoint or endpoint['avatarRef'] != config['avatarRef']:
        raise ValueError('operator worker/avatar reference unavailable')
    if set(endpoint) - {'port', 'tokenFile', 'avatarRef', 'assetSHA256', 'allowSimulation', 'allowedScopes'}:
        raise ValueError('unsupported endpoint fields')
    if set(scope) != {'tenantId', 'userId'} or scope not in endpoint.get('allowedScopes', []):
        raise ValueError('worker reference not authorized for scope')
    if type(endpoint['port']) is not int or not 1 <= endpoint['port'] <= 65535:
        raise ValueError('invalid private port')
    secret(endpoint['tokenFile'])
    return dict(endpoint)
