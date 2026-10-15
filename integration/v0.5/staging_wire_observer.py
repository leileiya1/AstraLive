#!/usr/bin/env python3
"""Opt-in loopback acceptance observer. Forwards original framed TCP bytes.

Records a strict whitelist of validated control metadata, never Auth, audio,
video, grants or arbitrary payloads. A wire ACK is not Runtime acceptance,
durable completion or audible speech. This extra local hop is test topology.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gpu_worker import staging_contract as contract

CAPTURE = frozenset(("StageBegin", "StageBegun", "StageProduced", "StageCommit",
                     "StageCommitAck", "StageCancel", "StageFenced", "StageRelease",
                     "StageReleased", "StageError"))
FIELDS = ("control_id", "request_fingerprint", "descriptor_sha256",
          "commit_proof_fingerprint", "pose_proof_fingerprint", "reason", "state",
          "publication_fenced", "native_safe_boundary", "retained_artifact_bytes",
          "latest_consumed_sequence", "terminal_disposition", "reusable", "code")


def metadata(raw, payload, direction, connection):
    header = contract.decode_header(raw)
    name = header.get("type")
    if name not in CAPTURE:
        return None
    contract.validate_message(header, payload)
    before = time.monotonic_ns()
    utc = time.time_ns()
    after = time.monotonic_ns()
    row = {"scope": "VALIDATED_WIRE_METADATA_NOT_RUNTIME_ACCEPTANCE_OR_AUDIBLE",
           "direction": direction, "connection": connection, "type": name,
           "monotonicBeforeNs": before, "utcNs": utc, "monotonicAfterNs": after,
           "sessionId": header["session_id"], "workerEpoch": header["worker_epoch"],
           "identity": {k: header["identity"][k] for k in contract.IDENTITY_FIELDS}}
    row.update({k: header[k] for k in FIELDS if k in header})
    if name == "StageProduced":
        d = header["descriptor"]
        row["produced"] = {"frameCount": d["frame_count"],
                           "sourceSamples": d["source_samples"],
                           "provenanceSource": d["provenance"]["source"],
                           "resources": d["resources"]}
    return row


async def forward(reader, writer, direction, connection, emit):
    while True:
        try:
            prefix = await reader.readexactly(8)
        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                raise ValueError("TRUNCATED_FRAME_PREFIX") from None
            return
        size, payload_size = struct.unpack("!II", prefix)
        # Same per-frame limits as the production staging reader.
        if not 1 <= size <= 16384 or payload_size > 2097152:
            raise ValueError("FRAME_BUDGET_EXCEEDED")
        raw = await reader.readexactly(size)
        payload = await reader.readexactly(payload_size)
        writer.write(prefix + raw + payload)
        await writer.drain()
        try:
            row = metadata(raw, payload, direction, connection)
        except (contract.ContractError, ValueError, TypeError, KeyError):
            row = {"scope": "OBSERVER_INVALID_HEADER_NOT_PROOF", "connection": connection,
                   "direction": direction, "code": "HEADER_REJECTED"}
        if row is not None:
            emit(row)


class Observer:
    def __init__(self, upstream_port, emit):
        self.upstream_port, self.emit = upstream_port, emit
        self.connections = 0
        self.tasks = set()

    async def handle(self, reader, writer):
        self.connections += 1
        connection = self.connections
        upstream_writer = None
        tasks = []
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", self.upstream_port)
            tasks = [asyncio.create_task(forward(reader, upstream_writer,
                         "runtime_to_worker", connection, self.emit)),
                     asyncio.create_task(forward(upstream_reader, writer,
                         "worker_to_runtime", connection, self.emit))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                completed.result()
        except (OSError, ValueError, asyncio.IncompleteReadError):
            self.emit({"scope": "OBSERVER_CONNECTION_ERROR_NOT_PROOF",
                       "connection": connection, "code": "FORWARDING_STOPPED"})
        finally:
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            for stream in (writer, upstream_writer):
                if stream is not None:
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except OSError:
                        pass
            self.tasks.discard(task)


async def main(args):
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as output:
        def emit(row):
            output.write(json.dumps(row, separators=(",", ":"), allow_nan=False)+"\n")
            output.flush()
        observer = Observer(args.upstream_port, emit)
        server = await asyncio.start_server(observer.handle, "127.0.0.1", args.listen_port)
        ready = {"scope": "ACCEPTANCE_ONLY_EXTRA_LOOPBACK_HOP",
                 "listenPort": server.sockets[0].getsockname()[1],
                 "upstreamPort": args.upstream_port, "pid": os.getpid(),
                 "rawPayloadsRecorded": False, "audienceAudible": False}
        ready_fd = os.open(args.ready_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(ready_fd, "w") as ready_out:
            json.dump(ready, ready_out)
        try:
            async with server:
                await server.serve_forever()
        finally:
            for pending in tuple(observer.tasks):
                pending.cancel()
            if observer.tasks:
                await asyncio.gather(*tuple(observer.tasks), return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--listen-port", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.upstream_port <= 65535 or not 0 <= args.listen_port <= 65535:
        parser.error("invalid loopback port")
    asyncio.run(main(args))
