import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/utils'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-lg border border-border bg-surface p-5 shadow-card', className)} {...props} />
}

/** Title row for a card: heading, optional caption and trailing actions. */
export function CardHeader({ title, description, icon, actions, className, as: Heading = 'h2' }: {
  title: ReactNode; description?: ReactNode; icon?: ReactNode; actions?: ReactNode; className?: string; as?: 'h1' | 'h2' | 'h3'
}) {
  return (
    <div className={cn('mb-4 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-brand-soft text-brand [&_svg]:size-4">{icon}</span>}
        <div className="min-w-0">
          <Heading className="text-title text-fg">{title}</Heading>
          {description && <p className="mt-0.5 text-caption text-fg-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
