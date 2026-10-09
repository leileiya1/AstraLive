// Run with: bun tests/browser_connected_soak.ts [duration seconds]
// Chrome is instrumented only to observe the peer created by the real Live Console hook.
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'

const base = 'http://127.0.0.1:18080'
const port = 19222
const duration = Number(process.argv[2] ?? 1800)
const evidenceTag = process.argv[3] ?? (duration >= 3600 ? '60m' : 'preflight-5m')
const evidenceDir = process.env.ASTRALIVE_EVIDENCE_DIR ?? 'integration/evidence'
const output = `${evidenceDir}/browser-connected-soak-${evidenceTag}.json`
const runtimeOutput = `${evidenceDir}/browser-connected-runtime-${evidenceTag}.json`
const browserPath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const remoteHost = process.env.ASTRALIVE_REMOTE_HOST ?? 'ubuntu-server'
const finalRtmp = process.env.ASTRALIVE_FINAL_RTMP === '1'
const remoteEvidenceDir = '$HOME/AstraLive/integration/evidence/rtmp-final'
const chrome = Bun.spawn([browserPath, '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--autoplay-policy=no-user-gesture-required', `--remote-debugging-port=${port}`, `--user-data-dir=/private/tmp/astralive-browser-soak-profile-${process.pid}`, 'about:blank'], { stdout: 'ignore', stderr: Bun.file('/private/tmp/astralive-browser-chrome.log') })
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
const result: Record<string, unknown> = { duration_requested_s: duration, samples: [], errors: [] }
let sessionId = ''
let cdp: WebSocket | undefined

function remoteWrite(path: string, data: string, append = false) {
  if (!finalRtmp) return
  const redirect = append ? '>>' : '>'
  const child = Bun.spawnSync(['ssh', '-o', 'BatchMode=yes', remoteHost,
    `umask 077; mkdir -p ${remoteEvidenceDir}; ${append ? 'cat' : 'cat'} ${redirect} ${remoteEvidenceDir}/${path}`],
    { stdin: Buffer.from(data), stdout: 'pipe', stderr: 'pipe' })
  if (child.exitCode !== 0) throw new Error(`Remote evidence write failed: ${child.stderr.toString()}`)
}

function remoteRtmpReady() {
  const code = `set -euo pipefail
ffmpeg_pid=$(pgrep -o -f '[f]fmpeg .* -f flv rtmp://' || true)
test -n "$ffmpeg_pid"
docker logs --since 30s astralive-rtmp-test-mediamtx-1 2>&1 | grep -F "is publishing to path 'live/astralive-test'" >/dev/null
jq -n --arg boot "$(cat /proc/sys/kernel/random/boot_id)" --argjson ffmpegPid "$ffmpeg_pid" '{boot_id:$boot,ffmpeg_pid:$ffmpegPid,publisher_ready:true}'`
  const child = Bun.spawnSync(['ssh', '-o', 'BatchMode=yes', remoteHost, code], { stdout: 'pipe', stderr: 'pipe' })
  if (child.exitCode !== 0) throw new Error(`RTMP publisher not ready: ${child.stderr.toString()}`)
  return JSON.parse(child.stdout.toString())
}

async function request(path: string, method = 'GET', data?: unknown) {
  const response = await fetch(base + path, { method, headers: { 'Content-Type': 'application/json', ...(method === 'POST' ? { 'Idempotency-Key': `browser-soak-${crypto.randomUUID()}` } : {}) }, body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(30000) })
  const body = await response.json() as { data: Record<string, unknown>; code: string }
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${body.code}`)
  return body.data
}

async function main() {
  mkdirSync(evidenceDir, { recursive: true })
  if (existsSync(output) || existsSync(runtimeOutput)) throw new Error(`Refusing to overwrite existing evidence: ${output} or ${runtimeOutput}`)
  let targets: Array<{ id: string; type: string; url: string; webSocketDebuggerUrl: string }> = []
  for (let i = 0; i < 50; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json() as typeof targets; if (targets.length) break } catch { /* Chrome starting */ }
    await sleep(100)
  }
  if (!targets.length) throw new Error(`Chrome CDP unavailable (Chrome exit code ${chrome.exitCode}; see /private/tmp/astralive-browser-chrome.log)`)
  const target = targets.find(t => t.type === 'page' && t.url === 'about:blank') ?? targets.find(t => t.type === 'page' && t.webSocketDebuggerUrl)
  if (!target) throw new Error(`No Chrome page target: ${JSON.stringify(targets.map(t => ({ type: t.type, url: t.url })))}`)
  let nextId = 1
  const pending = new Map<number, (value: any) => void>()
  const browserErrors: string[] = []
  cdp = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise<void>((resolve, reject) => { cdp!.onopen = () => resolve(); cdp!.onerror = reject })
  cdp.onmessage = event => { const message = JSON.parse(String(event.data)); if (message.id && pending.has(message.id)) { pending.get(message.id)!(message); pending.delete(message.id) } else if (message.method === 'Runtime.exceptionThrown') browserErrors.push(message.params?.exceptionDetails?.exception?.description ?? message.params?.exceptionDetails?.text ?? 'Browser exception') }
  const call = async (method: string, params: Record<string, unknown> = {}) => {
    const id = nextId++
    const response = await new Promise<any>(resolve => { pending.set(id, resolve); cdp!.send(JSON.stringify({ id, method, params })) })
    if (response.error) throw new Error(`${method}: ${response.error.message}`)
    return response.result
  }
  const evalJs = async (expression: string) => {
    const r = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(`Browser evaluation: ${r.exceptionDetails.text}`)
    return r.result.value
  }
  const until = async (expression: string, timeoutMs = 30000) => {
    const end = Date.now() + timeoutMs
    while (Date.now() < end) { const v = await evalJs(expression); if (v) return v; await sleep(200) }
    const diagnostic = await evalJs(`JSON.stringify({url:location.href,readyState:document.readyState,body:document.body.innerText.slice(0,800),peer:window.__astralivePeer&&{ice:window.__astralivePeer.iceConnectionState,gather:window.__astralivePeer.iceGatheringState,connection:window.__astralivePeer.connectionState,local:!!window.__astralivePeer.localDescription,answerAudio:window.__astralivePeer.remoteDescription?.sdp?.split('m=audio')[1]?.split('m=video')[0]?.slice(0,1200)},config:window.__astraliveIceConfig})`).catch(() => 'unavailable')
    const media = await evalJs(`(async()=>{const p=window.__astralivePeer;if(!p)return null;let a=0,e=0,v=0,tracks=[],codecs=[];for(const s of (await p.getStats()).values()){if(s.type==='codec')codecs.push({id:s.id,mimeType:s.mimeType,payloadType:s.payloadType});if(s.type==='inbound-rtp'){tracks.push({kind:s.kind,codecId:s.codecId,packets:s.packetsReceived,bytes:s.bytesReceived,frames:s.framesDecoded,energy:s.totalAudioEnergy,audioLevel:s.audioLevel,totalSamplesReceived:s.totalSamplesReceived,concealedSamples:s.concealedSamples,silentConcealedSamples:s.silentConcealedSamples,jitterBufferEmittedCount:s.jitterBufferEmittedCount});if(s.kind==='audio'){a+=s.packetsReceived||0;e+=s.totalAudioEnergy||0}if(s.kind==='video')v+=s.framesDecoded||0}}const el=document.querySelector('video');return {a,e,v,tracks,codecs,receivers:p.getReceivers().map(r=>({kind:r.track?.kind,muted:r.track?.muted,readyState:r.track?.readyState})),element:el&&{paused:el.paused,muted:el.muted,volume:el.volume,readyState:el.readyState,error:el.error?.message,tracks:el.srcObject?.getTracks().map(t=>t.kind)}}})()`).catch(() => null)
    throw new Error(`Browser timeout: ${expression}; ${diagnostic}; media=${JSON.stringify(media)}; exceptions=${JSON.stringify(browserErrors)}`)
  }
  await call('Page.enable')
  await call('Runtime.enable')
  await call('Page.addScriptToEvaluateOnNewDocument', { source: `(() => { const Native = window.RTCPeerConnection; window.RTCPeerConnection = class extends Native { constructor(config) { super(config); window.__astralivePeer = this; window.__astraliveIceConfig = config; } }; })();` })

  const suffix = crypto.randomUUID().slice(0, 8)
  const avatar = await request('/api/v1/avatars', 'POST', { name: `browser-soak-${suffix}`, engine: 'MOCK' })
  const voice = await request('/api/v1/voices', 'POST', { name: `browser-soak-${suffix}`, provider: 'MOCK', providerVoiceId: 'mock-female-01' })
  const product = await request('/api/v1/products', 'POST', { name: '卫衣', description: 'Browser stability acceptance', price: 129, currency: 'CNY', stock: 27, sizes: ['M', 'L', 'XL'] })
  const room = await request('/api/v1/live-rooms', 'POST', { name: `browser-soak-${suffix}`, avatarId: avatar.avatarId, voiceId: voice.voiceId, activeProductId: product.productId, systemPrompt: '你是一名简洁自然的服装主播。' })
  const roomId = String(room.roomId)
  result.room_id = roomId
  result.product_id = product.productId
  await call('Page.navigate', { url: 'http://127.0.0.1:18081/' })
  await until(`document.querySelector('nav')?.textContent?.includes('Live Rooms')`)
  await evalJs(`Array.from(document.querySelectorAll('nav button')).find(b => b.textContent?.includes('Live Rooms'))?.click()`)
  await until(`Array.from(document.querySelectorAll('h2')).some(h => h.textContent === 'browser-soak-${suffix}')`)
  await evalJs(`Array.from(document.querySelectorAll('h2')).find(h => h.textContent === 'browser-soak-${suffix}')?.parentElement?.parentElement?.querySelector('button:last-child')?.click()`)
  await until(`document.querySelector('h1')?.textContent === 'Live Console'`)
  result.playback_volume = await evalJs(`(()=>{const video=document.querySelector('video');video.volume=0.01;return video.volume})()`)
  await evalJs(`Array.from(document.querySelectorAll('button')).find(b => b.textContent === '创建 Session')?.click()`)
  sessionId = String(await until(`Array.from(document.querySelectorAll('dt')).find(d => d.textContent === 'Session')?.nextElementSibling?.textContent?.match(/^session_[a-z0-9]+$/)?.[0]`))
  result.session_id = sessionId
  await until(`Array.from(document.querySelectorAll('button')).some(b => b.textContent === 'Start Live' && !b.disabled)`)
  await evalJs(`Array.from(document.querySelectorAll('button')).find(b => b.textContent === 'Start Live')?.click()`)
  await until(`window.__astralivePeer?.connectionState === 'connected' && ['connected','completed'].includes(window.__astralivePeer?.iceConnectionState)`, 45000)
  const config = await evalJs(`window.__astraliveIceConfig`)
  if (!config?.iceServers?.some((server: { urls: string[] }) => server.urls.includes('stun:stun.l.google.com:19302'))) throw new Error(`Production frontend STUN missing: ${JSON.stringify(config)}`)
  result.ice_configuration = config
  result.connected_at = new Date().toISOString()

  const stats = async () => await evalJs(`(async()=>{ const pc=window.__astralivePeer; const data={at:new Date().toISOString(),ice:pc?.iceConnectionState,connection:pc?.connectionState,audioPackets:0,audioBytes:0,audioEnergy:0,videoPackets:0,framesDecoded:0,framesDropped:0,jitter:0,packetsLost:0}; for(const s of (await pc.getStats()).values()) if(s.type==='inbound-rtp'){ if(s.kind==='audio'){data.audioPackets+=s.packetsReceived||0;data.audioBytes+=s.bytesReceived||0;data.audioEnergy+=s.totalAudioEnergy||0}else if(s.kind==='video'){data.videoPackets+=s.packetsReceived||0;data.framesDecoded+=s.framesDecoded||0;data.framesDropped+=s.framesDropped||0}data.jitter+=s.jitter||0;data.packetsLost+=s.packetsLost||0} return data;})()`)
  const initial = await stats()
  await request(`/api/v1/live-sessions/${sessionId}/utterances`, 'POST', { text: '欢迎大家进入直播间，今天向大家介绍这件衣服。', priority: 100, interruptPolicy: 'NONE', source: 'OPERATOR' })
  await until(`(async()=>{let a=0,v=0;for(const s of (await window.__astralivePeer.getStats()).values())if(s.type==='inbound-rtp'){if(s.kind==='audio')a+=s.packetsReceived||0;if(s.kind==='video')v+=s.framesDecoded||0}return a>${initial.audioPackets}&&v>${initial.framesDecoded}})()`, 30000)
  result.initial_media = await stats()
  console.log(`Cross-host frontend PASS: ${sessionId}, ICE ${result.initial_media && (result.initial_media as any).ice}, audio/video received`)
  if (finalRtmp) {
    result.rtmp_ready = remoteRtmpReady()
    remoteWrite('timer-start.json', JSON.stringify({ at: new Date().toISOString(), session_id: sessionId,
      browser: result.initial_media, rtmp: result.rtmp_ready }, null, 2) + '\n')
    remoteWrite('browser-monitor.jsonl', JSON.stringify({ phase: 'timer-start', ...(result.initial_media as object) }) + '\n')
  }
  const started = Date.now()
  writeFileSync('/private/tmp/astralive-browser-soak-driver.log', '')
  writeFileSync('/private/tmp/astralive-browser-soak-driver.err.log', '')
  const ackPath = '/private/tmp/astralive-browser-soak-cycle-ack.txt'
  writeFileSync(ackPath, '0')
  const forceBurst = process.env.ASTRALIVE_FORCE_BURST ?? '0'
  const idleSeconds = process.env.ASTRALIVE_IDLE_SECONDS ?? '0'
  const py = Bun.spawn(['runtime/.venv/bin/python', 'tests/gpu_partial_soak.py', '--duration', String(duration), '--room-id', roomId, '--session-id', sessionId, '--already-started', '--browser-ack-file', ackPath, '--force-burst', forceBurst, '--idle-seconds', idleSeconds, '--output', runtimeOutput], { stdout: Bun.file('/private/tmp/astralive-browser-soak-driver.log'), stderr: Bun.file('/private/tmp/astralive-browser-soak-driver.err.log') })
  let previous = await stats()
  let previousCycle = previous
  let lastCycle = 0
  let stagnant = 0
  let lastPeriodic = started
  result.cycle_media = []
  while (py.exitCode === null) {
    await sleep(5000)
    if (py.exitCode !== null) break
    const lines = readFileSync('/private/tmp/astralive-browser-soak-driver.log', 'utf8').split('\n').filter(Boolean)
    const cycles = lines.map(line => { try { return JSON.parse(line) } catch { return null } }).filter(row => row?.cycle > lastCycle)
    for (const cycle of cycles) {
      const media = await stats()
      ;(result.cycle_media as any[]).push({ cycle: cycle.cycle, runtime_elapsed_s: cycle.elapsed_s, runtime_sample: cycle.sample, browser_media: media })
      if (media.connection !== 'connected' || !['connected', 'completed'].includes(media.ice)) (result.errors as string[]).push(`Cycle ${cycle.cycle}: disconnected`)
      if (media.audioPackets <= previousCycle.audioPackets || media.framesDecoded <= previousCycle.framesDecoded) (result.errors as string[]).push(`Cycle ${cycle.cycle}: media counters did not grow`)
      if ((result.errors as string[]).length === 0) writeFileSync(ackPath, String(cycle.cycle))
      previousCycle = media
      lastCycle = cycle.cycle
    }
    if (Date.now() - lastPeriodic >= 30000) {
      const sample = await stats()
      ;(result.samples as any[]).push(sample)
      if (finalRtmp) remoteWrite('browser-monitor.jsonl', JSON.stringify({ elapsed_s: Math.round((Date.now() - started) / 1000), ...sample }) + '\n', true)
      if (sample.connection !== 'connected' || !['connected', 'completed'].includes(sample.ice)) (result.errors as string[]).push(`Disconnected at ${sample.at}: ${sample.connection}/${sample.ice}`)
      if (sample.audioPackets <= previous.audioPackets || sample.framesDecoded <= previous.framesDecoded) stagnant++
      else stagnant = 0
      if (stagnant >= 3) (result.errors as string[]).push(`Media counters stagnant for ${stagnant} samples at ${sample.at}`)
      previous = sample
      lastPeriodic = Date.now()
      console.log(JSON.stringify({ elapsed_s: Math.round((Date.now() - started) / 1000), ...sample }))
    }
    if ((result.errors as string[]).length) { py.kill(); break }
  }
  result.actual_connected_monitor_s = Math.round((Date.now() - started) / 1000)
  result.driver_exit_code = await py.exited
  result.final_media = await stats().catch(() => null)
  if (finalRtmp && result.final_media) remoteWrite('browser-monitor.jsonl', JSON.stringify({ phase: 'final', elapsed_s: Math.round((Date.now() - started) / 1000), ...(result.final_media as object) }) + '\n', true)
  const runtimeRun = existsSync(runtimeOutput)
    ? JSON.parse(readFileSync(runtimeOutput, 'utf8'))
    : null
  if (!runtimeRun) (result.errors as string[]).push('Runtime driver did not write a final summary')
  else if (runtimeRun.cycles !== (result.cycle_media as any[]).length) (result.errors as string[]).push(`Only ${(result.cycle_media as any[]).length}/${runtimeRun.cycles} cycles have browser media samples`)
  if (!(result.cycle_media as any[]).some(row => row.browser_media.audioEnergy > 0)) (result.errors as string[]).push('Browser decoded no non-silent audio during the soak')
  if (runtimeRun && (runtimeRun.stop !== 'PASS' || runtimeRun.errors.length)) (result.errors as string[]).push('Runtime run or Session Stop failed')
  if (result.driver_exit_code !== 0) (result.errors as string[]).push('Runtime driver failed')
  if ((result.actual_connected_monitor_s as number) < duration) (result.errors as string[]).push('Browser monitor ended before requested duration')
  if ((result.errors as string[]).length) throw new Error((result.errors as string[]).join('; '))
  result.verdict = 'PASS'
}

try { await main() } catch (error) { (result.errors as string[]).push(String(error)); result.verdict = 'FAIL'; console.error(error) } finally {
  if (sessionId) await request(`/api/v1/live-sessions/${sessionId}/stop`, 'POST').catch(() => {})
  result.ended_at = new Date().toISOString()
  mkdirSync(evidenceDir, { recursive: true })
  if (!existsSync(output)) writeFileSync(output, JSON.stringify(result, null, 2) + '\n')
  if (finalRtmp && existsSync(output)) remoteWrite('browser-stats.json', readFileSync(output, 'utf8'))
  if (finalRtmp && existsSync(runtimeOutput)) remoteWrite('runtime-driver.json', readFileSync(runtimeOutput, 'utf8'))
  cdp?.close()
  chrome.kill()
}
if (result.verdict !== 'PASS') process.exitCode = 1
