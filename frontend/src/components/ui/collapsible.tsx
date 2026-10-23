import { useId, useState, type ReactNode } from 'react'
import { AnimatePresence } from 'motion/react'
import * as m from 'motion/react-m'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'

/** Card-styled disclosure section. Content unmounts when closed. */
export function CollapsibleCard({ title, icon, meta, defaultOpen = false, children, className }: {
  title: ReactNode; icon?: ReactNode; meta?: ReactNode; defaultOpen?: boolean; children: ReactNode; className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  return (
    <section className={cn('overflow-hidden rounded-lg border border-border bg-surface shadow-card', className)}>
      <h2>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2"
        >
          {icon && <span className="grid size-7 shrink-0 place-items-center rounded-md bg-surface-3 text-fg-muted [&_svg]:size-3.5">{icon}</span>}
          <span className="min-w-0 flex-1 truncate text-body font-medium text-fg">{title}</span>
          {meta}
          <ChevronDown aria-hidden className={cn('size-4 shrink-0 text-fg-subtle transition-transform duration-200', open && 'rotate-180')} />
        </button>
      </h2>
      <AnimatePresence initial={false}>
        {open && (
          <m.div
            id={id}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="border-t border-border px-4 py-3">{children}</div>
          </m.div>
        )}
      </AnimatePresence>
    </section>
  )
}
