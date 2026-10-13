import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { getWebRTCConfiguration } from '../config/webrtc'
import { AudioRouteGuard, PlayoutWatchdog, type PlayoutStat } from '../lib/previewAudioHealth'

export type PreviewStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'recovering' | 'failed'

export function waitForIceGathering(peer: RTCPeerConnection, signal: AbortSignal): Promise<void> {
  if (peer.iceGatheringState === 'complete') return Promise.resolve()
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      peer.removeEventListener('icegatheringstatechange', check)
      signal.removeEventListener('abort', abort)
    }
    const check = () => { if (peer.iceGatheringState === 'complete') { cleanup(); resolve() } }
    const abort = () => { cleanup(); reject(new DOMException('Preview closed', 'AbortError')) }
    peer.addEventListener('icegatheringstatechange', check)
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
    else check()
  })
}

export function useLivePreview(sessionId: string | null) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [status, setStatus] = useState<PreviewStatus>('idle')
  const [error, setError] = useState<unknown>(null)
  const [epoch, setEpoch] = useState(0)
  const restartTimes = useRef<number[]>([])
  const route = useRef<AudioRouteGuard | null>(null)
  const currentSession = useRef(sessionId)
  currentSession.current = sessionId
  const picker = (navigator.mediaDevices as MediaDevices & { selectAudioOutput?: () => Promise<MediaDeviceInfo> } | undefined)?.selectAudioOutput
  const chooseOutput = useCallback(async () => {
    if (!picker || !videoRef.current) return
    const owner = currentSession.current
    try {
      const selected = await picker.call(navigator.mediaDevices)
      if (!videoRef.current || owner !== currentSession.current) return
      route.current?.dispose()
      route.current = new AudioRouteGuard(videoRef.current, { log: (event) => {
        if (event === 'AudioOutputUnavailable') setError(new Error('音频设备已断开，请重新选择音频输出'))
      } })
      await route.current.pin(selected.deviceId)
      if (owner === currentSession.current) setError(null)
    } catch (cause) { if (owner === currentSession.current) setError(cause) }
  }, [picker])
  useEffect(() => {
    restartTimes.current = []
    return () => { route.current?.dispose(); route.current = null }
  }, [sessionId])
  useEffect(() => {
    if (!sessionId) { setStatus('idle'); setError(null); return }
    const abort = new AbortController()
    let peer: RTCPeerConnection
    try {
      peer = new RTCPeerConnection(getWebRTCConfiguration())
    } catch {
      console.warn('Invalid WebRTC ICE configuration; using the default peer configuration')
      try {
        peer = new RTCPeerConnection({})
      } catch (cause) {
        setError(cause)
        setStatus('failed')
        return
      }
    }
    let inboundStream: MediaStream | null = null
    setStatus('connecting')
    setError(null)
    peer.addTransceiver('video', { direction: 'recvonly' })
    peer.addTransceiver('audio', { direction: 'recvonly' })
    peer.ontrack = event => {
      if (abort.signal.aborted) return
      inboundStream ??= new MediaStream()
      if (!inboundStream.getTracks().includes(event.track)) inboundStream.addTrack(event.track)
      if (videoRef.current) videoRef.current.srcObject = inboundStream
    }
    peer.onconnectionstatechange = () => {
      if (abort.signal.aborted) return
      if (peer.connectionState === 'connected' || peer.connectionState === 'disconnected' || peer.connectionState === 'failed') setStatus(peer.connectionState)
    }
    // Use actual native audio playout, not received RTP or an AudioContext clock.
    const watch = new PlayoutWatchdog()
    let polling = false
    let stalledAt: number | null = null
    let restarting = false
    const healthTimer = setInterval(() => {
      if (polling || restarting || abort.signal.aborted || peer.connectionState !== 'connected') return
      const element = videoRef.current
      if (!element || element.muted || element.paused) { watch.reset(); stalledAt = null; return }
      polling = true
      void peer.getStats().then(stats => {
        if (abort.signal.aborted) return
        const rows: PlayoutStat[] = []
        stats.forEach(row => rows.push(row))
        const now = performance.now() / 1000
        const event = watch.sample(now, rows)
        if (event?.state === 'stalled') { stalledAt = now; setStatus('recovering') }
        if (stalledAt === null) return
        if (now - stalledAt > 8) {
          restarting = true
          setError(new Error('音频设备未恢复播放，请检查音频输出后重新连接预览'))
          setStatus('failed')
          return
        }
        if (!watch.readyToRestart) return
        // Wait for the output device to render again before negotiating a new clock.
        const recent = restartTimes.current.filter(t => now - t < 60)
        if (recent.length >= 2) {
          restarting = true
          setError(new Error('音频设备反复中断，请检查音频输出'))
          setStatus('failed')
          return
        }
        restartTimes.current = [...recent, now]
        restarting = true
        setEpoch(value => value + 1)
      }).catch(cause => {
        if (!abort.signal.aborted) { setError(cause); setStatus('failed'); restarting = true }
      }).finally(() => { polling = false })
    }, 250)
    void (async () => {
      try {
        const offer = await peer.createOffer()
        if (abort.signal.aborted) return
        await peer.setLocalDescription(offer)
        await waitForIceGathering(peer, abort.signal)
        if (abort.signal.aborted) return
        const sdp = peer.localDescription?.sdp
        if (!sdp) throw new Error('WebRTC offer has no SDP')
        const answer = await api.exchangeWebRTCOffer(sessionId, { type: 'offer', sdp })
        if (abort.signal.aborted) return
        if (answer.type !== 'answer' || !answer.sdp) throw new Error('Invalid WebRTC answer')
        await peer.setRemoteDescription(answer)
      } catch (cause) {
        if (!abort.signal.aborted) { setError(cause); setStatus('failed') }
      }
    })()
    return () => {
      abort.abort()
      clearInterval(healthTimer)
      peer.close()
      if (videoRef.current && videoRef.current.srcObject === inboundStream) videoRef.current.srcObject = null
    }
  }, [sessionId, epoch])
  const reconnect = () => { restartTimes.current = []; setEpoch(value => value + 1) }
  return { videoRef, status, error, chooseOutput, canChooseOutput: !!picker, reconnect }
}
