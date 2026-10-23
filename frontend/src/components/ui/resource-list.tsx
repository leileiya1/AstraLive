import type { ReactNode } from 'react'
import { AnimatePresence } from 'motion/react'
import * as m from 'motion/react-m'
import { cn } from '../../lib/utils'

/** Animated list wrapper: items fade/slide in and collapse out. */
export function ResourceList({ children, className }: { children: ReactNode; className?: string }) {
  return <ul className={cn('grid gap-3', className)}><AnimatePresence initial={false}>{children}</AnimatePresence></ul>
}

/** One resource card: leading glyph, title, badges/meta, trailing actions. */
export function ResourceItem({ id, glyph, title, meta, description, actions, className }: {
  id: string; glyph?: ReactNode; title: ReactNode; meta?: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string
}) {
  return (
    <m.li
      key={id}
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
      className={cn('group flex flex-col gap-4 rounded-lg border border-border bg-surface p-4 shadow-card transition-colors hover:border-border-strong sm:flex-row sm:items-center sm:p-5', className)}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3.5">
        {glyph && <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand ring-1 ring-brand/20 [&_svg]:size-5">{glyph}</span>}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-body font-semibold text-fg">{title}</h2>
          {meta && <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-caption text-fg-muted">{meta}</div>}
          {description && <div className="mt-1.5 text-caption text-fg-muted">{description}</div>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">{actions}</div>}
    </m.li>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="max-w-full truncate font-mono text-[11px] text-fg-subtle">{children}</span>
}
