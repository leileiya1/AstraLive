import { apiUrl, ApiError } from './client'
import type { components } from './config-generated'
export type ConfigSchemas = components['schemas']
export type Profile = ConfigSchemas['Profile']
export type Kind = ConfigSchemas['Kind']
export async function configCall<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(apiUrl('/api/v0.3/config' + path), {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let payload: {code?: string; message?: string; data?: T; requestId?: string}
  try { payload = await response.json() } catch { throw new ApiError('INTERNAL_ERROR', '配置服务响应无效', undefined, response.status) }
  if (!response.ok || payload.code !== 'OK' || payload.data === undefined) {
    throw new ApiError(payload.code ?? 'INTERNAL_ERROR', payload.message ?? '配置请求失败', payload.requestId, response.status)
  }
  return payload.data
}
export const configApi = {
  me: () => configCall<ConfigSchemas['Me']>('/me'),
  profiles: () => configCall<Profile[]>('/profiles'),
  create: (input: ConfigSchemas['CreateProfile']) => configCall<Profile>('/profiles', 'POST', input),
  update: (id: string, input: ConfigSchemas['UpdateProfile']) => configCall<Profile>(`/profiles/${encodeURIComponent(id)}`, 'PUT', input),
  credential: (id: string, input: ConfigSchemas['CredentialInput']) => configCall<Profile>(`/profiles/${encodeURIComponent(id)}/credential`, 'PUT', input),
  action: (p: Profile, action: 'test'|'default'|'disable'|'delete'|'remove-credential') => configCall<Profile | Record<string, never>>(
    `/profiles/${encodeURIComponent(p.profileId)}${action === 'delete' ? '' : action === 'remove-credential' ? '/credential' : '/' + action}`,
    action === 'delete' || action === 'remove-credential' ? 'DELETE' : 'POST', {expectedVersion: p.version}),
  settings: () => configCall<ConfigSchemas['Settings']>('/settings'),
  saveSettings: (input: ConfigSchemas['SettingsInput']) => configCall<ConfigSchemas['Settings']>('/settings', 'PUT', input),
}
