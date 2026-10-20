import { z } from 'zod'
import type { components } from './generated'

type S = components['schemas']
const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const envelope = z.object({ code: z.literal('OK'), message: z.string(), requestId: z.string(), timestamp: z.string(), data: z.unknown() })
const failure = z.object({ code: z.string(), message: z.string(), requestId: z.string().optional() })
export class ApiError extends Error {
  constructor(public code: string, message: string, public requestId?: string, public status?: number) { super(message) }
}
export const apiUrl = (path: string) => `${base}${path}`
const enc = encodeURIComponent
export const key = () => crypto.randomUUID()
async function call<T>(path: string, method = 'GET', body?: unknown, idempotencyKey?: string, expectedStatus?: number): Promise<T> {
  const response = await fetch(apiUrl(path), { method, headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) })
  let json: unknown
  try { json = await response.json() } catch { throw new ApiError('INTERNAL_ERROR', `Invalid API response (${response.status})`, undefined, response.status) }
  if (!response.ok) {
    const parsed = failure.safeParse(json)
    throw new ApiError(parsed.success ? parsed.data.code : 'INTERNAL_ERROR', parsed.success ? parsed.data.message : `Request failed (${response.status})`, parsed.success ? parsed.data.requestId : undefined, response.status)
  }
  if (expectedStatus !== undefined && response.status !== expectedStatus) throw new ApiError('INTERNAL_ERROR', `Unexpected API status (${response.status})`, undefined, response.status)
  const parsed = envelope.safeParse(json)
  if (!parsed.success || parsed.data.data === undefined) throw new ApiError('INTERNAL_ERROR', 'Invalid API envelope', undefined, response.status)
  return parsed.data.data as T
}
export const api = {
  durableSession: (id: string) => call<DurableSession>(`/api/v0.5/durable-live/sessions/${enc(id)}`),
  resolveDurable: (runId: string, decision: DurableDecision) => call<{ decisionId: string; action: string; mediaAuthorized: false }>(`/api/v0.5/durable-live/runs/${enc(runId)}/decisions`, 'POST', decision),
  stopDurable: (runId: string, decisionId: string) => call<unknown>(`/api/v0.5/durable-live/runs/${enc(runId)}/stop`, 'POST', { decisionId }),
  controlHealth: async (): Promise<S['Health']> => { const response = await fetch(apiUrl('/health/ready')); const data: unknown = await response.json(); if (!response.ok) { const error = failure.safeParse(data); throw new ApiError(error.success ? error.data.code : 'INTERNAL_ERROR', error.success ? error.data.message : 'Health check failed', error.success ? error.data.requestId : undefined, response.status) } const parsed = z.object({ status: z.string() }).safeParse(data); if (!parsed.success) throw new ApiError('INTERNAL_ERROR', 'Invalid health response'); return parsed.data },
  avatars: () => call<S['Avatar'][]>('/api/v1/avatars'),
  createAvatar: (body: S['CreateAvatarRequest']) => call<S['Avatar']>('/api/v1/avatars', 'POST', body),
  prepareAvatar: (id: string) => call<S['Job']>(`/api/v1/avatars/${enc(id)}/prepare`, 'POST', undefined, key()),
  deleteAvatar: (id: string) => call<Record<string, never>>(`/api/v1/avatars/${enc(id)}`, 'DELETE'),
  voices: () => call<S['Voice'][]>('/api/v1/voices'),
  createVoice: (body: S['CreateVoiceRequest']) => call<S['Voice']>('/api/v1/voices', 'POST', body),
  deleteVoice: (id: string) => call<Record<string, never>>(`/api/v1/voices/${enc(id)}`, 'DELETE'),
  products: () => call<S['Product'][]>('/api/v1/products'),
  createProduct: (body: S['ProductInput']) => call<S['Product']>('/api/v1/products', 'POST', body),
  updateProduct: (id: string, body: S['ProductInput']) => call<S['Product']>(`/api/v1/products/${enc(id)}`, 'PUT', body),
  createKnowledgeBase: (body: S['KnowledgeBaseInput']) => call<S['KnowledgeBase']>('/api/v1/knowledge-bases', 'POST', body),
  indexKnowledgeBase: (id: string) => call<S['Job']>(`/api/v1/knowledge-bases/${enc(id)}/index`, 'POST', undefined, key()),
  job: (id: string) => call<S['Job']>(`/api/v1/jobs/${enc(id)}`),
  rooms: () => call<S['LiveRoom'][]>('/api/v1/live-rooms'),
  createRoom: (body: S['LiveRoomInput']) => call<S['LiveRoom']>('/api/v1/live-rooms', 'POST', body),
  updateRoom: (id: string, body: S['LiveRoomInput']) => call<S['LiveRoom']>(`/api/v1/live-rooms/${enc(id)}`, 'PUT', body),
  createSession: (body: S['CreateLiveSessionRequest']) => call<S['LiveSession']>('/api/v1/live-sessions', 'POST', body),
  session: (id: string) => call<S['LiveSession']>(`/api/v1/live-sessions/${enc(id)}`),
  startSession: (id: string) => call<S['Operation'] & {status: S['LiveSessionStatus']}>(`/api/v1/live-sessions/${enc(id)}/start`, 'POST', undefined, key()),
  stopSession: (id: string) => call<S['Operation']>(`/api/v1/live-sessions/${enc(id)}/stop`, 'POST', undefined, key()),
  speak: (id: string, body: S['CreateUtteranceRequest']) => call<S['Utterance']>(`/api/v1/live-sessions/${enc(id)}/utterances`, 'POST', body, key()),
  interrupt: (id: string, body: S['InterruptRequest']) => call<S['Operation']>(`/api/v1/live-sessions/${enc(id)}/interrupt`, 'POST', body),
  exchangeWebRTCOffer: (id: string, body: S['WebRTCOffer']) => call<S['WebRTCAnswer']>(`/api/v1/live-sessions/${enc(id)}/webrtc/offer`, 'POST', body, undefined, 200),
  devEvent: (body: S['PlatformEvent']) => call<S['Utterance']>('/api/v1/dev/platform-events', 'POST', body, undefined, 202),
}
export type { S as ApiSchemas }

export type DurableDecision = { decisionId: string; attemptId: string; expectedRevision: number; action: 'WAIT_FOR_EVIDENCE' | 'SKIP_WITH_GAP' | 'CREATE_NEW_TURN'; reason: string; createdAt: string }
export type DurableSession = { managed: false } | {
  managed: true;
  snapshot: {
    run: { runId: string; revision: number; status: string; desiredState: string; stopRevision: number };
    completedPrefix: number; resumeSequence: number;
    bundle: { plan: { planId: string; revision: number; productId: string }; segments: { sequence: number; segmentId: string; content: string; state: string }[] } | null;
    unresolvedAttempts: { attemptId: string; lastCheckpoint: string; commandId: string }[];
    decisions: { decisionId: string; action: string; reason: string }[];
  };
  choice: { state: import('../features/live-console/TurnManagerPanel').TurnManagerView['state']; source: string; pending: number; reason?: string };
  releaseGate: string;
}
