"""RTMP Observer tap: chunk parser and ledger invariants (no network).

Bytes are produced by the Guardian's own Publisher framing, so the parser is
tested against exactly what the owned child writes, split at every boundary.
"""

import asyncio
import hashlib

import pytest

from output_guardian.v2.rtmp import CHUNK, Publisher
from runtime.app.receiver1.rtmp_observer import HANDSHAKE, ChunkParser, Ledger, TapFault


class Wire:
    def __init__(self):
        self.data = bytearray()

    def sendall(self, data):
        self.data += data


def publisher():
    p = Publisher.__new__(Publisher)
    p.sock, p.stream_id = Wire(), 1
    p._send(2, 1, 0, 0, CHUNK.to_bytes(4, "big"))  # Set Chunk Size, as open() does
    return p


def stream(units=5, samples=640, big=False):
    p = publisher()
    pcm = []
    for i in range(units):
        a = bytes((i * 7 + k) % 251 for k in range(samples * 2))
        pcm.append(a)
        p.audio((i * samples * 1000 + 8000) // 16000, a)
        p.video(i * 40, i == 0, 1, b"\x00\x00\x00\x02\x65\x88" * (900 if big else 1))
    return bytes(HANDSHAKE * b"\x00") + bytes(p.sock.data), b"".join(pcm)


def parse(data, step=None):
    ledger = Ledger(16000)
    parser = ChunkParser(ledger)
    if step is None:
        parser.feed(data)
    else:
        for at in range(0, len(data), step):
            parser.feed(data[at : at + step])
    return ledger


@pytest.mark.parametrize("step", [None, 1, 3, 4096])
def test_parser_is_split_invariant_and_bit_exact(step):
    data, pcm = stream(big=True)  # video tags span several chunks
    ledger = parse(data, step)
    assert bytes(ledger.pcm) == pcm
    assert [ts for ts, _ in ledger.video] == [0, 40, 80, 120, 160]


def test_audio_gap_overlap_or_format_change_faults():
    p = publisher()
    p.audio(0, bytes(1280))
    p.audio(80, bytes(1280))  # 40ms of samples missing on the pipe
    with pytest.raises(TapFault):
        parse(HANDSHAKE * b"\x00" + bytes(p.sock.data))
    p = publisher()
    p._send(4, 8, 0, 1, b"\xaf\x01" + bytes(10))  # AAC, not the proven PCM
    with pytest.raises(TapFault):
        parse(HANDSHAKE * b"\x00" + bytes(p.sock.data))


def test_video_retime_or_non_avc_faults():
    p = publisher()
    p.video(40, True, 1, b"\x00\x00\x00\x01\x65")
    p.video(40, False, 1, b"\x00\x00\x00\x01\x41")  # same timestamp twice
    with pytest.raises(TapFault):
        parse(HANDSHAKE * b"\x00" + bytes(p.sock.data))
    p = publisher()
    p._send(6, 9, 0, 1, b"\x12" + bytes(8))  # codec id 2 (Sorenson)
    with pytest.raises(TapFault):
        parse(HANDSHAKE * b"\x00" + bytes(p.sock.data))


def test_aggregate_and_orphan_continuation_fault():
    p = publisher()
    p._send(4, 22, 0, 1, bytes(20))
    with pytest.raises(TapFault):
        parse(HANDSHAKE * b"\x00" + bytes(p.sock.data))
    with pytest.raises(TapFault):
        parse(HANDSHAKE * b"\x00" + b"\xc9" + bytes(10))  # fmt 3 on an unknown csid


def test_extended_timestamp_round_trips():
    p = publisher()
    ts = 0xFFFFFF + 40  # ~4.6 hours into a Session
    p.video(ts, True, 1, b"\x00\x00\x00\x02\x65\x88" * 900)
    ledger = parse(HANDSHAKE * b"\x00" + bytes(p.sock.data), 7)
    assert [t for t, _ in ledger.video] == [ts]


def test_prove_waits_for_tail_then_checks_hash():
    from runtime.app.receiver1.rtmp_observer import RTMPObserver

    async def run():
        data, pcm = stream()
        o = RTMPObserver(sink_id="s", upstream=None, audio_origin=1000,
                         sample_rate=16000, guardian=None, settle=0.3)
        request = dict(audioStart=1000 + 640, audioEnd=1000 + 3 * 640,
                       audioHash=hashlib.sha256(pcm[1280 : 3 * 1280]).hexdigest(),
                       videoPts=[62500 + 40000, 62500 + 80000], finalVideoFrame=2,
                       generationId="g", evidenceRef="r")
        half = len(data) // 3
        o.parser.feed(data[:half])
        pending = asyncio.create_task(o.prove(request))
        await asyncio.sleep(0.05)
        assert not pending.done()  # tail not on the pipe yet: no evidence
        o.parser.feed(data[half:])
        o.ledger.notify()
        evidence = await pending
        proof = evidence["sinkProofs"][0]
        assert proof["kind"] == "RTMP_PIPE_WRITE"
        assert (proof["firstAudioSample"], proof["finalAudioSampleExclusive"]) == (1640, 2920)
        with pytest.raises(TapFault) as wrong:
            await o.prove(dict(request, audioHash="0" * 64))
        assert wrong.value.code == "EVIDENCE_CONFLICT"
        with pytest.raises(TapFault) as early:
            await o.prove(dict(request, audioStart=999))
        assert early.value.code == "INVALID_ARGUMENT"

    asyncio.run(run())
