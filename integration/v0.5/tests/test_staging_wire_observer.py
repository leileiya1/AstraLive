"""Local TCP observer tests; no real GPU/physical-audibility evidence."""
import asyncio
import importlib.util
import json
from pathlib import Path
import struct
import unittest

path = Path(__file__).resolve().parents[1] / "staging_wire_observer.py"
spec = importlib.util.spec_from_file_location("wire_observer", path)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
from gpu_worker.tests.test_staging_contract import message


def frame(header, payload=b""):
    raw = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack("!II", len(raw), len(payload)) + raw + payload


def released():
    header = message("StageReleased")
    header.update(native_safe_boundary=True, retained_artifact_bytes=0,
                  terminal_disposition="UNKNOWN", reusable=False)
    return header


class WireObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_loopback_preserves_auth_and_binary_bytes_without_logging_them(self):
        rows, received = [], []
        auth = frame({"type": "Auth", "token": "private-fake-token-do-not-record"})
        binary = frame({"type": "StageVideo"}, b"\x00private-binary-\xff\x00")
        reply = frame(released())

        async def worker(reader, writer):
            received.append(await reader.readexactly(len(auth + binary)))
            writer.write(reply)
            await writer.drain()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        upstream = await asyncio.start_server(worker, "127.0.0.1", 0)
        proxy = observer.Observer(upstream.sockets[0].getsockname()[1], rows.append)
        server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
            writer.write(auth + binary)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(reply)), 2), reply)
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(asyncio.gather(*tuple(proxy.tasks)), 2)
        finally:
            server.close(); upstream.close()
            await server.wait_closed(); await upstream.wait_closed()
        self.assertEqual(received, [auth + binary])
        self.assertFalse(proxy.tasks)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["type"], "StageReleased")
        self.assertEqual(row["terminal_disposition"], "UNKNOWN")
        self.assertFalse(row["reusable"])
        self.assertEqual(row["retained_artifact_bytes"], 0)
        self.assertLessEqual(row["monotonicBeforeNs"], row["monotonicAfterNs"])
        self.assertGreater(row["utcNs"], 0)
        self.assertIn("NOT_RUNTIME_ACCEPTANCE_OR_AUDIBLE", row["scope"])
        self.assertNotIn("private-", json.dumps(rows))

    async def forward_bytes(self, data):
        reader = asyncio.StreamReader()
        reader.feed_data(data); reader.feed_eof()
        class Writer:
            output = b""
            def write(self, value): self.output += value
            async def drain(self): pass
        writer, rows = Writer(), []
        error = None
        try:
            await observer.forward(reader, writer, "worker_to_runtime", 1, rows.append)
        except (ValueError, asyncio.IncompleteReadError) as exc:
            error = exc
        return writer.output, rows, error

    async def test_invalid_safe_boundary_retained_bytes_and_extra_field_never_become_proof(self):
        for change in ({"native_safe_boundary": False}, {"retained_artifact_bytes": 1},
                       {"secret": "private-secret"}, {"reusable": True}):
            with self.subTest(change=change):
                packet = frame(dict(released(), **change))
                output, rows, error = await self.forward_bytes(packet)
                self.assertEqual(output, packet)
                self.assertIsNone(error)
                self.assertEqual(rows, [{"scope": "OBSERVER_INVALID_HEADER_NOT_PROOF",
                                        "connection": 1, "direction": "worker_to_runtime",
                                        "code": "HEADER_REJECTED"}])

    async def test_partial_prefix_or_payload_never_forges_release(self):
        for data in (b"\x00\x00", frame(released())[:-1], struct.pack("!II", 1, 2) + b"{" + b"x"):
            output, rows, error = await self.forward_bytes(data)
            self.assertEqual(output, b"")
            self.assertEqual(rows, [])
            self.assertIsNotNone(error)

    async def test_production_frame_limits_fail_before_allocation_or_forwarding(self):
        for header_size, payload_size in ((0, 0), (16385, 0), (1, 2097153)):
            output, rows, error = await self.forward_bytes(struct.pack("!II", header_size, payload_size))
            self.assertEqual(output, b"")
            self.assertEqual(rows, [])
            self.assertEqual(str(error), "FRAME_BUDGET_EXCEEDED")

    async def test_identity_mismatch_is_forwarded_but_rejected_as_observer_proof(self):
        header = released(); header["identity"]["sessionId"] = "foreign"
        packet = frame(header)
        output, rows, error = await self.forward_bytes(packet)
        self.assertEqual(output, packet)
        self.assertIsNone(error)
        self.assertEqual(rows[0]["scope"], "OBSERVER_INVALID_HEADER_NOT_PROOF")

    async def test_clean_disconnect_emits_no_terminal_ack(self):
        output, rows, error = await self.forward_bytes(b"")
        self.assertEqual((output, rows, error), (b"", [], None))


if __name__ == "__main__":
    unittest.main()
