import * as T from '@radix-ui/react-toast'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { create } from 'zustand'
import { cn } from '../../lib/utils'

type Kind = 'success' | 'error' | 'info'
type Item = { id: number; kind: Kind; title: string; description?: string }
let next = 0
const useToasts = create<{ items: Item[]; push: (i: Omit<Item, 'id'>) => void; remove: (id: number) => void }>(set => ({
  items: [],
  push: item => set(s => ({ items: [...s.items.slice(-3), { ...item, id: ++next }] })),
  remove: id => set(s => ({ items: s.items.filter(i => i.id !== id) })),
}))

/** Fire-and-forget notifications. Without a mounted <Toaster/> (unit tests) they are simply kept in memory. */
export const toast = {
  success: (title: string, description?: string) => useToasts.getState().push({ kind: 'success', title, description }),
  error: (title: string, description?: string) => useToasts.getState().push({ kind: 'error', title, description }),
  info: (title: string, description?: string) => useToasts.getState().push({ kind: 'info', title, description }),
}

const icons = { success: CheckCircle2, error: XCircle, info: Info }
const tones = { success: 'text-ok', error: 'text-danger', info: 'text-brand' }

export function Toaster() {
  const items = useToasts(s => s.items)
  const remove = useToasts(s => s.remove)
  return (
    <T.Provider swipeDirection="right" duration={3500}>
      {items.map(item => {
        const Icon = icons[item.kind]
        return (
          <T.Root
            key={item.id}
            onOpenChange={open => { if (!open) remove(item.id) }}
            className={cn(
              'flex items-start gap-3 rounded-lg border border-border-strong bg-surface/95 p-3.5 pr-9 shadow-raised backdrop-blur-xl',
              'data-[state=open]:motion-safe:animate-[slide-up_220ms_cubic-bezier(.2,.8,.2,1)] data-[state=closed]:opacity-0 data-[state=closed]:transition-opacity',
              'data-[swipe=move]:translate-x-(--radix-toast-swipe-move-x) data-[swipe=end]:translate-x-(--radix-toast-swipe-end-x)',
            )}
          >
            <Icon className={cn('mt-0.5 size-4 shrink-0', tones[item.kind])} />
            <div className="min-w-0">
              <T.Title className="text-body font-medium text-fg">{item.title}</T.Title>
              {item.description && <T.Description className="mt-0.5 text-caption text-fg-muted">{item.description}</T.Description>}
            </div>
            <T.Close aria-label="关闭通知" className="absolute top-3 right-3 rounded-sm text-fg-subtle hover:text-fg"><X className="size-3.5" /></T.Close>
          </T.Root>
        )
      })}
      <T.Viewport className="fixed right-0 bottom-0 z-[60] flex w-full max-w-sm flex-col gap-2 p-4 outline-none sm:right-2 sm:bottom-2" />
    </T.Provider>
  )
}
