"""Registry/Fanout diagnostics regressions, not browser or GPU acceptance."""
import asyncio
import os
import unittest
from uuid import UUID
from unittest.mock import patch

from app.media_fanout import FanoutMediaOutput
from app.providers import AudioChunk
from app.webrtc_media import WebRTCMediaOutput, _AudioTrack, _VideoTrack, _Peer


class Connection:
    """Control-plane fixture; production diagnoses the actual RTCConnection."""
    def __init__(self, state):
        self.connectionState = state
        self.iceConnectionState = state
    async def close(self):
        self.connectionState = self.iceConnectionState = 'closed'


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.dict(os.environ, {'ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED':'false',
                                   'ASTRALIVE_MEDIA_TIMELINE_ENABLED':'false'}):
            self.output = WebRTCMediaOutput()
        self.assertFalse(self.output.timeline_v2)
        self.addAsyncCleanup(self.output.stop)

    def peer(self, name, state='connected'):
        peer = _Peer(name, Connection(state), _AudioTrack(), _VideoTrack())
        self.output.peers.add(peer)
        return peer

    async def test_empty_stopped_and_running_snapshots_do_not_invent_peers(self):
        before = self.output.diagnostics()
        self.assertEqual(before['peers'],[])
        self.assertFalse(before['running'])
        self.assertFalse(before['audienceAudible'])
        await self.output.start()
        after = self.output.diagnostics()
        self.assertTrue(after['running'])
        self.assertEqual(after['peers'],[])
        self.assertEqual(self.output.peers,set())

    async def test_fanout_exposes_registered_ids_and_actual_connection_states(self):
        self.peer('connecting-peer','connecting')
        connected = self.peer('connected-peer')
        fanout = FanoutMediaOutput([('webrtc',self.output)])
        await fanout.start()
        try:
            sink = fanout.diagnostics()['webrtc']['sink']
            rows = {row['peerId']:row for row in sink['peers']}
            self.assertEqual(set(rows),{'connecting-peer','connected-peer'})
            self.assertEqual(rows['connecting-peer']['connectionState'],'connecting')
            self.assertEqual([r['peerId'] for r in sink['peers'] if r['connectionState']=='connected'],['connected-peer'])
            connected.connection.connectionState = 'disconnected'
            self.assertEqual(fanout.diagnostics()['webrtc']['sink']['peers'][0]['connectionState'],'disconnected')
        finally:
            await fanout.stop()

    async def test_reading_snapshot_preserves_tracks_counters_and_warnings(self):
        peer = self.peer('consuming')
        await self.output.start()
        await self.output.push_audio(AudioChunk(1,0,b'\x01\x00'*960,48000,1))
        await peer.audio.recv()
        warning={'code':'OWNED_FIXTURE'};self.output.warnings.append(warning)
        first = self.output.diagnostics()
        second = self.output.diagnostics()
        self.assertEqual(first['peers'][0]['audioFramesConsumed'],1)
        self.assertEqual(second['peers'][0]['audioFramesConsumed'],1)
        self.assertEqual(peer.audio.consumed,1)
        self.assertFalse(first['audienceAudible'])
        self.assertEqual(self.output.warnings,[warning])
        first['peers'][0]['audioFramesConsumed']=999
        self.assertEqual(self.output.diagnostics()['peers'][0]['audioFramesConsumed'],1)

    async def test_registry_change_during_diagnostic_walk_uses_owned_snapshot(self):
        self.peer('a');self.peer('b')
        diagnostic = self.output._diagnostic
        removed = tuple(self.output.peers)
        def change_registry(peer):
            self.output.peers.clear()
            return diagnostic(peer)
        try:
            with patch.object(self.output,'_diagnostic',side_effect=change_registry):
                rows = self.output.diagnostics()['peers']
            self.assertEqual([row['peerId'] for row in rows],['a','b'])
            self.assertEqual(self.output.diagnostics()['peers'],[])
        finally:
            # The registry mutation fixture must retain ownership for cleanup.
            self.output.peers.update(removed)

    async def test_peer_close_task_and_snapshot_reads_are_consistent(self):
        peer = self.peer('closing')
        await self.output.start()
        async def close():
            await asyncio.sleep(0)
            await peer.connection.close()
            await asyncio.sleep(0)
            self.output.peers.discard(peer)
        task = asyncio.create_task(close())
        for _ in range(4):
            rows = self.output.diagnostics()['peers']
            self.assertTrue(not rows or rows[0]['peerId']=='closing')
            self.assertTrue(not rows or rows[0]['connectionState'] in ('connected','closed'))
            await asyncio.sleep(0)
        await task
        self.assertEqual(self.output.diagnostics()['peers'],[])
        peer.audio.stop();peer.video.stop()

    async def test_actual_local_rtc_offer_exposes_generated_connected_peer_id(self):
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
        client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        await self.output.start()
        try:
            client.addTransceiver('audio',direction='recvonly')
            client.addTransceiver('video',direction='recvonly')
            await client.setLocalDescription(await client.createOffer())
            answer = await asyncio.wait_for(self.output.create_answer(client.localDescription.sdp),15)
            await client.setRemoteDescription(RTCSessionDescription(sdp=answer,type='answer'))
            for _ in range(100):
                if client.connectionState=='connected':break
                await asyncio.sleep(.05)
            self.assertEqual(client.connectionState,'connected')
            rows = FanoutMediaOutput([('webrtc',self.output)]).diagnostics()['webrtc']['sink']['peers']
            self.assertEqual(len(rows),1)
            peer = next(iter(self.output.peers))
            self.assertEqual(rows[0]['peerId'],peer.peer_id)
            self.assertTrue(rows[0]['peerId'].startswith('peer_'))
            self.assertEqual(UUID(rows[0]['peerId'][5:]).hex,peer.peer_id[5:])
            self.assertEqual(rows[0]['connectionState'],peer.connection.connectionState)
            self.assertEqual(rows[0]['connectionState'],'connected')
            self.assertFalse(self.output.diagnostics()['audienceAudible'])
        finally:
            await client.close()
            await self.output.stop()
        self.assertEqual(self.output.diagnostics()['peers'],[])


if __name__=='__main__':unittest.main()
