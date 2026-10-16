"""Decode the ingest server's read-only recording; never a producer file sink.

Both complete ordered coded-packet sequences and decoded A/V coverage must agree. A
recording with missing head/tail, a decode error, or a missing required sink
cannot become LOCAL_MEDIA_DRAINED. This proves dedicated ingest, not an external
platform's audience. No Runtime-provided receipt is accepted.
"""

import hashlib
import json
from pathlib import Path

import av

from .codec import packet_hash
from .model import Closed


def decode_recordings(paths):
    hashes = {"audio": [], "video": []}
    samples, frames = 0, 0
    for path in paths:
        with av.open(str(path)) as source:
            for stream in source.streams:
                if stream.type in {"audio", "video"}:
                    stream.codec_context.thread_count = 1
            for packet in source.demux():
                kind = packet.stream.type
                if kind not in hashes:
                    continue
                if packet.size:
                    digest = packet_hash(kind, bytes(packet))
                    if digest:
                        hashes[kind].append(digest)
                decoded = list(packet.decode())
                for frame in decoded:
                    if kind == "audio":
                        samples += frame.samples
                    else:
                        frames += 1
    return hashes, samples, frames


def verify_recordings(paths, manifest):
    if (
        not paths
        or len(paths) > 32
        or sum(Path(p).stat().st_size for p in paths) > 256 * 1024 * 1024
    ):
        raise Closed("DRAIN_UNKNOWN")
    hashes, samples, frames = decode_recordings(paths)
    expected = manifest["manifest"]
    if (
        any(not expected[k] or hashes[k] != expected[k] for k in expected)
        or samples < manifest["audioSamples"]
        or frames != len(manifest["videoPTSUS"])
    ):
        raise Closed("DRAIN_UNKNOWN")
    evidence = {
        "observer": "guardian-ingest-recording-decoder-v1",
        "sink": "rtmp",
        "audioSampleRange": [0, manifest["audioSamples"]],
        "videoPTSUS": manifest["videoPTSUS"],
        "decodedAudioSamples": samples,
        "decodedVideoFrames": frames,
        "packetManifestSHA256": hashlib.sha256(
            json.dumps(expected, sort_keys=True).encode()
        ).hexdigest(),
        "recordingSHA256": [
            hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths
        ],
    }
    evidence["evidenceSHA256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True).encode()
    ).hexdigest()
    return evidence


def verify_network(observed, manifest):
    expected = manifest["manifest"]
    if (
        observed.get("decodeError")
        or not observed.get("connected")
        or any(
            not expected[k] or observed["manifest"][k] != expected[k] for k in expected
        )
        or observed["decodedAudioSamples"] < manifest["audioSamples"]
        or observed["decodedVideoFrames"] != len(manifest["videoPTSUS"])
    ):
        raise Closed("DRAIN_UNKNOWN")
    evidence = {
        "observer": "guardian-rtmp-network-decoder-v1",
        "sink": "rtmp",
        "audioSampleRange": [0, manifest["audioSamples"]],
        "videoPTSUS": manifest["videoPTSUS"],
        "decodedAudioSamples": observed["decodedAudioSamples"],
        "decodedVideoFrames": observed["decodedVideoFrames"],
        "packetManifestSHA256": hashlib.sha256(
            json.dumps(expected, sort_keys=True).encode()
        ).hexdigest(),
    }
    evidence["evidenceSHA256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True).encode()
    ).hexdigest()
    return evidence


def verify_combined(paths, observed, manifest):
    # The ingest recorder retains a prefix; a real network decoder can retain a
    # suffix. Only exact ordered coverage with no gap is accepted (no max-PTS or
    # counter union). Duplicate coded frames cannot fill a missing position.
    if observed.get("decodeError"):
        raise Closed("DRAIN_NETWORK_DECODE_ERROR")
    if not paths:
        return verify_network(observed, manifest)
    if (
        len(paths) > 32
        or sum(Path(p).stat().st_size for p in paths) > 256 * 1024 * 1024
    ):
        raise Closed("DRAIN_UNKNOWN")
    prefix, prefix_samples, prefix_frames = decode_recordings(paths)
    expected = manifest["manifest"]
    if not observed.get("connected"):
        return verify_recordings(paths, manifest)
    for kind, packets in expected.items():
        head, tail = prefix[kind], observed["manifest"][kind]
        if (
            not packets
            or head != packets[: len(head)]
            or not tail
            or tail != packets[len(packets) - len(tail) :]
            or len(head) + len(tail) < len(packets)
        ):
            raise Closed(
                f"DRAIN_PACKET_COVERAGE_{kind}_head{len(head)}_tail{len(tail)}_expected{len(packets)}_headmatch{head == packets[: len(head)]}_tailmatch{tail == packets[len(packets) - len(tail) :]}"
            )
    audio_overlap = (
        len(prefix["audio"])
        + len(observed["manifest"]["audio"])
        - len(expected["audio"])
    )
    video_overlap = (
        len(prefix["video"])
        + len(observed["manifest"]["video"])
        - len(expected["video"])
    )
    if prefix_frames + observed["decodedVideoFrames"] - video_overlap != len(
        manifest["videoPTSUS"]
    ):
        raise Closed("DRAIN_VIDEO_RANGE_GAP")
    if (
        prefix_samples + observed["decodedAudioSamples"] - audio_overlap * 1024
        < manifest["audioSamples"]
    ):
        raise Closed("DRAIN_AUDIO_RANGE_GAP")
    evidence = {
        "observer": "guardian-ingest-prefix-network-suffix-decoder-v1",
        "sink": "rtmp",
        "audioSampleRange": [0, manifest["audioSamples"]],
        "videoPTSUS": manifest["videoPTSUS"],
        "decodedAudioSamples": manifest["audioSamples"],
        "decodedVideoFrames": len(manifest["videoPTSUS"]),
        "prefixDecodedAudioSamples": prefix_samples,
        "suffixDecodedAudioSamples": observed["decodedAudioSamples"],
        "prefixDecodedVideoFrames": prefix_frames,
        "suffixDecodedVideoFrames": observed["decodedVideoFrames"],
        "prefixPackets": {k: len(v) for k, v in prefix.items()},
        "suffixPackets": {k: len(v) for k, v in observed["manifest"].items()},
        "packetManifestSHA256": hashlib.sha256(
            json.dumps(expected, sort_keys=True).encode()
        ).hexdigest(),
    }
    evidence["evidenceSHA256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True).encode()
    ).hexdigest()
    return evidence
