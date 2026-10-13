import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, render, renderHook, waitFor } from '@testing-library/react'
import { useLivePreview } from '../src/hooks/useLivePreview'
import { api } from '../src/api/client'

vi.mock('../src/api/client', () => ({ api: { exchangeWebRTCOffer: vi.fn() } }))
class Peer {
  static latest: Peer
  static configurations: (RTCConfiguration | undefined)[] = []
  static rejectConfigured = false
  iceGatheringState: RTCIceGatheringState = 'gathering'
  connectionState: RTCPeerConnectionState = 'new'
  localDescription: RTCSessionDescriptionInit | null = null
  listeners = new Map<string, () => void>()
  ontrack: ((event: RTCTrackEvent) => void) | null = null
  onconnectionstatechange: (() => void) | null = null
  getStats = vi.fn(async (): Promise<Map<string, Record<string, unknown>>> => new Map())
  close = vi.fn()
  addTransceiver = vi.fn()
  createOffer = vi.fn(async () => ({ type: 'offer' as const, sdp: 'initial-offer' }))
  setLocalDescription = vi.fn(async () => { this.localDescription = { type: 'offer', sdp: 'complete-offer-with-candidates' } })
  setRemoteDescription = vi.fn(async () => {})
  addEventListener(name: string, callback: () => void) { this.listeners.set(name, callback) }
  removeEventListener(name: string) { this.listeners.delete(name) }
  finishIce() { this.iceGatheringState = 'complete'; this.listeners.get('icegatheringstatechange')?.() }
  constructor(configuration?: RTCConfiguration) {
    Peer.configurations.push(configuration)
    if (Peer.rejectConfigured && configuration?.iceServers?.length) throw new TypeError('Invalid ICE server')
    Peer.latest = this
  }
}
beforeEach(() => { Peer.configurations = []; Peer.rejectConfigured = false; vi.stubGlobal('RTCPeerConnection', Peer) })
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })
it('uses an empty configuration when no ICE servers are configured', () => {
  const { unmount } = renderHook(() => useLivePreview('s_1'))
  expect(Peer.configurations).toEqual([{}])
  unmount()
})
it('uses configured STUN URLs', () => {
  vi.stubEnv('VITE_WEBRTC_STUN_URLS', 'stun:one.example:3478, stun:two.example:3478')
  const { unmount } = renderHook(() => useLivePreview('s_1'))
  expect(Peer.configurations).toEqual([{ iceServers: [{ urls: ['stun:one.example:3478', 'stun:two.example:3478'] }] }])
  unmount()
})
it('uses configured TURN URLs and credentials', () => {
  vi.stubEnv('VITE_WEBRTC_TURN_URLS', 'turn:relay.example:3478?transport=udp, turns:relay.example:5349?transport=tcp')
  vi.stubEnv('VITE_WEBRTC_TURN_USERNAME', 'alice')
  vi.stubEnv('VITE_WEBRTC_TURN_CREDENTIAL', 'test-credential')
  const { unmount } = renderHook(() => useLivePreview('s_1'))
  expect(Peer.configurations).toEqual([{ iceServers: [{ urls: ['turn:relay.example:3478?transport=udp', 'turns:relay.example:5349?transport=tcp'], username: 'alice', credential: 'test-credential' }] }])
  unmount()
})
it('ignores invalid ICE entries and incomplete TURN credentials without crashing', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.stubEnv('VITE_WEBRTC_STUN_URLS', 'invalid, stun:valid.example:3478, stun:bad host')
  vi.stubEnv('VITE_WEBRTC_TURN_URLS', 'turn:relay.example:3478')
  vi.stubEnv('VITE_WEBRTC_TURN_USERNAME', 'alice')
  const { unmount } = renderHook(() => useLivePreview('s_1'))
  expect(Peer.configurations).toEqual([{ iceServers: [{ urls: ['stun:valid.example:3478'] }] }])
  expect(warn).toHaveBeenCalled()
  unmount()
})
it('falls back to a default peer if the browser rejects an ICE URL', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.stubEnv('VITE_WEBRTC_STUN_URLS', 'stun:browser-rejected.example:3478')
  Peer.rejectConfigured = true
  const { unmount } = renderHook(() => useLivePreview('s_1'))
  expect(Peer.configurations).toEqual([
    { iceServers: [{ urls: ['stun:browser-rejected.example:3478'] }] },
    {},
  ])
  expect(warn).toHaveBeenCalled()
  unmount()
})
it('keeps audio and video tracks together in the preview element', () => {
  class Stream {
    tracks: MediaStreamTrack[] = []
    getTracks() { return this.tracks }
    addTrack(track: MediaStreamTrack) { this.tracks.push(track) }
  }
  vi.stubGlobal('MediaStream', Stream)
  function Preview() { const { videoRef } = useLivePreview('s_1'); return <video ref={videoRef} data-testid="preview" /> }
  const { getByTestId, unmount } = render(<Preview />)
  const audio = { kind: 'audio' } as MediaStreamTrack
  const video = { kind: 'video' } as MediaStreamTrack
  Peer.latest.ontrack?.({ track: audio } as RTCTrackEvent)
  Peer.latest.ontrack?.({ track: video } as RTCTrackEvent)
  expect(((getByTestId('preview') as HTMLVideoElement).srcObject as MediaStream).getTracks()).toEqual([audio, video])
  unmount()
})
it('waits for complete ICE, exchanges SDP through Go, and closes the peer', async () => {
  vi.mocked(api.exchangeWebRTCOffer).mockResolvedValue({ type: 'answer', sdp: 'answer' })
  const { unmount } = renderHook(() => useLivePreview('s_1'))
  await waitFor(() => expect(Peer.latest.setLocalDescription).toHaveBeenCalled())
  expect(api.exchangeWebRTCOffer).not.toHaveBeenCalled()
  Peer.latest.finishIce()
  await waitFor(() => expect(Peer.latest.setRemoteDescription).toHaveBeenCalledWith({ type: 'answer', sdp: 'answer' }))
  expect(api.exchangeWebRTCOffer).toHaveBeenCalledWith('s_1', { type: 'offer', sdp: 'complete-offer-with-candidates' })
  expect(Peer.latest.addTransceiver).toHaveBeenCalledWith('video', { direction: 'recvonly' })
  expect(Peer.latest.addTransceiver).toHaveBeenCalledWith('audio', { direction: 'recvonly' })
  unmount()
  expect(Peer.latest.close).toHaveBeenCalled()
})
it('surfaces signaling errors and closes the peer on cleanup', async () => {
  vi.mocked(api.exchangeWebRTCOffer).mockRejectedValue(Object.assign(new Error('Peer negotiation failed'), { code: 'WEBRTC_FAILED', requestId: 'req_1', status: 503 }))
  const { result, unmount } = renderHook(() => useLivePreview('s_1'))
  await waitFor(() => expect(Peer.latest.setLocalDescription).toHaveBeenCalled())
  Peer.latest.finishIce()
  await waitFor(() => expect(result.current.status).toBe('failed'))
  expect(result.current.error).toMatchObject({ code: 'WEBRTC_FAILED', requestId: 'req_1' })
  expect(Peer.latest.setRemoteDescription).not.toHaveBeenCalled()
  unmount()
  expect(Peer.latest.close).toHaveBeenCalled()
})

it('waits for actual output return, then renegotiates only the same session preview', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
  try {
    vi.mocked(api.exchangeWebRTCOffer).mockResolvedValue({ type: 'answer', sdp: 'answer' })
    const { result, unmount } = renderHook(() => useLivePreview('same-business-session'))
    result.current.videoRef.current = { muted: false, paused: false, srcObject: null } as HTMLVideoElement
    const old = Peer.latest
    old.iceGatheringState = 'complete'; old.connectionState = 'connected'
    let playing = true, packets = 0, video = 0, played = 0
    old.getStats = vi.fn(async () => {
      packets += 12; video += 6; if (playing) played += .25
      return new Map([
        ['a', { type: 'inbound-rtp', kind: 'audio', packetsReceived: packets, totalSamplesReceived: packets * 960 }],
        ['v', { type: 'inbound-rtp', kind: 'video', framesDecoded: video }],
        ['p', { type: 'media-playout', kind: 'audio', totalSamplesDuration: played }],
      ])
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })
    playing = false
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(result.current.status).toBe('recovering')
    expect(Peer.latest).toBe(old)
    expect(old.close).not.toHaveBeenCalled()
    playing = true
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })
    const fresh = Peer.latest
    expect(fresh).not.toBe(old)
    expect(old.close).toHaveBeenCalledOnce()
    await act(async () => { fresh.finishIce(); await Promise.resolve() })
    expect(api.exchangeWebRTCOffer).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.exchangeWebRTCOffer).mock.calls.every(call => call[0] === 'same-business-session')).toBe(true)
    old.ontrack?.({ track: { kind: 'audio' } } as RTCTrackEvent)
    expect(result.current.videoRef.current.srcObject).toBeNull()
    unmount()
    expect(fresh.close).toHaveBeenCalledOnce()
  } finally { vi.useRealTimers() }
})

it('does not reconnect without actual playout statistics', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
  try {
    const { result, unmount } = renderHook(() => useLivePreview('s_1'))
    result.current.videoRef.current = { muted: false, paused: false, srcObject: null } as HTMLVideoElement
    const peer = Peer.latest; peer.connectionState = 'connected'
    let n = 0
    peer.getStats = vi.fn(async () => new Map([
      ['a', { type: 'inbound-rtp', kind: 'audio', packetsReceived: ++n, totalSamplesReceived: 0 }],
      ['v', { type: 'inbound-rtp', kind: 'video', framesDecoded: n }],
    ]))
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(Peer.latest).toBe(peer)
    expect(peer.close).not.toHaveBeenCalled()
    unmount()
  } finally { vi.useRealTimers() }
})

it('stops automatic retries when the audio device never resumes', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
  try {
    const { result, unmount } = renderHook(() => useLivePreview('s_1'))
    result.current.videoRef.current = { muted: false, paused: false, srcObject: null } as HTMLVideoElement
    const peer = Peer.latest; peer.connectionState = 'connected'
    let n = 0
    peer.getStats = vi.fn(async () => new Map([
      ['a', { type: 'inbound-rtp', kind: 'audio', packetsReceived: ++n }],
      ['v', { type: 'inbound-rtp', kind: 'video', framesDecoded: n }],
      ['p', { type: 'media-playout', kind: 'audio', totalSamplesDuration: 0 }],
    ]))
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(result.current.status).toBe('failed')
    expect(result.current.error).toBeInstanceOf(Error)
    expect(Peer.latest).toBe(peer)
    expect(api.exchangeWebRTCOffer).not.toHaveBeenCalled()
    unmount()
  } finally { vi.useRealTimers() }
})
