"""Packet fingerprints survive FLV -> fMP4 remux by the trusted ingest server."""

import hashlib
import re


def packet_hash(kind, data):
    if kind == "video":
        # Compare coded pictures, not container-specific SPS/PPS/AUD packaging.
        if data.startswith((b"\0\0\0\1", b"\0\0\1")):
            units = re.split(b"\x00\x00(?:\x00)?\x01", data)[1:]
        else:
            units, offset = [], 0
            while offset + 4 <= len(data):
                size = int.from_bytes(data[offset : offset + 4], "big")
                offset += 4
                if size < 1 or offset + size > len(data):
                    raise ValueError("invalid AVC packet")
                units.append(data[offset : offset + size])
                offset += size
            if offset != len(data):
                raise ValueError("truncated AVC packet")
        units = [u for u in units if u and u[0] & 31 in {1, 5}]
        if not units:
            return None
        data = b"".join(len(u).to_bytes(4, "big") + u for u in units)
    return hashlib.sha256(data).hexdigest()
