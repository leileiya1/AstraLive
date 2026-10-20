"""Lifecycle-only layer over the protected, unchanged v1 ``rig`` fixture.

An asyncpg connection admits one operation at a time. Lifecycle tests run
``renew_forever()`` concurrently with their own setup writes on the same
test-only ``rig.db``, so every statement through it is serialized here.
Production PostgresAuthority keeps its own connection and query lock; no
deadline, Grant lifetime or Guardian behaviour is changed by this fixture.

Import ``rig`` from this module to override the fixture in a lifecycle module.
It is deliberately not a ``conftest.py``: protected v1 tests import the
top-level ``conftest`` module by name, which a nested conftest would shadow.
"""

import asyncio

import pytest_asyncio

SERIALIZED = frozenset({"execute", "executemany", "fetch", "fetchrow", "fetchval"})


class SerialConnection:
    def __init__(self, connection):
        self._connection = connection
        self._lock = asyncio.Lock()

    def __getattr__(self, name):
        attr = getattr(self._connection, name)
        if name not in SERIALIZED:
            return attr

        async def serialized(*args, **kwargs):
            async with self._lock:
                return await attr(*args, **kwargs)

        return serialized


@pytest_asyncio.fixture(name="rig")
async def serial_rig(rig):
    rig.db = SerialConnection(rig.db)
    yield rig
