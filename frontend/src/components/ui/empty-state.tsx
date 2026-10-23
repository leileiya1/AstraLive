import { Inbox, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export function EmptyState({ icon: Icon = Inbox, title, description, action, compact = false, className }: {
  icon?: LucideIcon; title: ReactNode; description?: ReactNode; action?: ReactNode; compact?: boolean; className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'gap-2 py-6' : 'gap-3 rounded-lg border border-dashed border-border-strong py-12', className)}>
      <span className={cn('relative grid place-items-center rounded-full bg-brand-soft text-brand', compact ? 'size-9' : 'size-14')}>
        <span aria-hidden className="absolute inset-0 rounded-full bg-brand-gradient opacity-15 blur-md" />
        <Icon aria-hidden className={compact ? 'size-4' : 'size-6'} />
      </span>
      <p className={cn('font-medium text-fg', compact ? 'text-body' : 'text-title')}>{title}</p>
      {description && <p className="max-w-sm text-caption text-fg-muted">{description}</p>}
      {action}
    </div>
  )
}
