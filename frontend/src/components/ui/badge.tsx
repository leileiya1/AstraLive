import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

export type Tone = 'neutral' | 'brand' | 'live' | 'warn' | 'ok' | 'danger' | 'info'
const tones: Record<Tone, string> = {
  neutral: 'bg-surface-3 text-fg-muted border-border',
  brand: 'bg-brand-soft text-brand border-brand/25',
  live: 'bg-live-soft text-live border-live/30',
  warn: 'bg-warn-soft text-warn border-warn/30',
  ok: 'bg-ok-soft text-ok border-ok/30',
  danger: 'bg-danger-soft text-danger border-danger/30',
  info: 'bg-info-soft text-info border-info/30',
}
const dots: Record<Tone, string> = {
  neutral: 'bg-fg-subtle', brand: 'bg-brand', live: 'bg-live', warn: 'bg-warn', ok: 'bg-ok', danger: 'bg-danger', info: 'bg-info',
}

export function Badge({ tone = 'neutral', className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-caption font-medium whitespace-nowrap', tones[tone], className)} {...props} />
}

/** Small status light. `pulse` = breathing (in progress), `ping` = LIVE ripple. Both stop under reduced motion. */
export function StatusDot({ tone = 'neutral', pulse = false, ping = false, className }: { tone?: Tone; pulse?: boolean; ping?: boolean; className?: string }) {
  return (
    <span aria-hidden className={cn('relative inline-flex size-2 shrink-0 rounded-full', dots[tone], pulse && 'motion-safe:animate-breathe', ping && 'motion-safe:animate-live-pulse', className)} />
  )
}
