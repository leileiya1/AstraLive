import type { ApiSchemas } from '../api/client'
import type { Tone } from '../components/ui/badge'

// Presentation only: Chinese labels and tones for backend status codes. The raw
// code stays the source of truth and is still rendered (data-status / title).
type Look = { label: string; tone: Tone; pulse?: boolean; ping?: boolean }

export const sessionLook: Record<ApiSchemas['LiveSessionStatus'], Look> = {
  CREATED: { label: '已创建', tone: 'neutral' },
  PREPARING: { label: '准备中', tone: 'warn', pulse: true },
  READY: { label: '待开播', tone: 'info' },
  STARTING: { label: '开播中', tone: 'warn', pulse: true },
  LIVE: { label: '直播中', tone: 'live', ping: true },
  DEGRADED: { label: '降级直播', tone: 'warn', pulse: true },
  STOPPING: { label: '停止中', tone: 'warn', pulse: true },
  ENDED: { label: '已结束', tone: 'neutral' },
  FAILED: { label: '失败', tone: 'danger' },
}
export function lookSession(status: string | null | undefined): Look {
  return (status && sessionLook[status as ApiSchemas['LiveSessionStatus']]) || { label: status ?? '未开播', tone: 'neutral' }
}

export const utteranceLook: Record<ApiSchemas['UtteranceStatus'], Look> = {
  QUEUED: { label: '排队中', tone: 'neutral', pulse: true },
  GENERATING: { label: '生成中', tone: 'brand', pulse: true },
  SYNTHESIZING: { label: '合成语音', tone: 'brand', pulse: true },
  RENDERING: { label: '渲染画面', tone: 'info', pulse: true },
  PLAYING: { label: '播放中', tone: 'live', ping: true },
  COMPLETED: { label: '已完成', tone: 'ok' },
  INTERRUPTED: { label: '已打断', tone: 'warn' },
  CANCELLED: { label: '已取消', tone: 'neutral' },
  FAILED: { label: '失败', tone: 'danger' },
}
/** Ordered happy path for the utterance stepper. */
export const utteranceSteps = [
  { key: 'QUEUED', label: '排队' },
  { key: 'GENERATING', label: '生成' },
  { key: 'SYNTHESIZING', label: '合成' },
  { key: 'RENDERING', label: '渲染' },
  { key: 'PLAYING', label: '播放' },
  { key: 'COMPLETED', label: '完成' },
] as const

export const previewLook: Record<string, Look> = {
  idle: { label: '等待开播', tone: 'neutral' },
  connecting: { label: '连接中', tone: 'warn', pulse: true },
  connected: { label: '已连接', tone: 'ok' },
  disconnected: { label: '连接中断', tone: 'warn', pulse: true },
  recovering: { label: '恢复中', tone: 'warn', pulse: true },
  failed: { label: '连接失败', tone: 'danger' },
}
export const eventsLook: Record<string, Look> = {
  idle: { label: '未订阅', tone: 'neutral' },
  connecting: { label: '连接中', tone: 'warn', pulse: true },
  connected: { label: '实时', tone: 'ok' },
  reconnecting: { label: '重连中', tone: 'warn', pulse: true },
}
