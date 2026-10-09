import { afterEach, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useLiveSessionEvents } from '../src/hooks/useLiveSessionEvents'
class Source {
  static instances: Source[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: (() => void) | null = null
  listeners = new Map<string, (event: MessageEvent) => void>()
  close = vi.fn()
  constructor(public url: string) { Source.instances.push(this) }
  addEventListener(name: string, callback: EventListenerOrEventListenerObject) { this.listeners.set(name, callback as (event: MessageEvent) => void) }
  emit(name: string, data: unknown) { this.listeners.get(name)?.(new MessageEvent(name, { data: JSON.stringify(data) })) }
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); Source.instances = [] })
it('resets the 45 second timeout on heartbeat without entering the timeline', () => {
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', Source)
  const { result, unmount } = renderHook(() => useLiveSessionEvents('s_1'))
  const source = Source.instances[0]
  act(() => source.onopen?.())
  act(() => vi.advanceTimersByTime(30000))
  act(() => source.emit('heartbeat', { timestamp: '2026-10-06T00:00:30Z' }))
  expect(result.current.state.events).toHaveLength(0)
  expect(result.current.state.timeline).toHaveLength(0)
  act(() => vi.advanceTimersByTime(44000))
  expect(source.close).not.toHaveBeenCalled()
  expect(result.current.connection).toBe('connected')
  act(() => vi.advanceTimersByTime(1000))
  expect(source.close).toHaveBeenCalled()
  expect(result.current.connection).toBe('reconnecting')
  unmount()
})
