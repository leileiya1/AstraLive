import * as A from '@radix-ui/react-alert-dialog'
import { AlertTriangle } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Button } from './button'

/**
 * Replaces window.confirm. Wrap the trigger; `onConfirm` runs only after the
 * operator presses the confirm button. Keyboard: Esc cancels, focus starts on cancel.
 */
export function ConfirmDialog({ title, description, confirmLabel = '确认', cancelLabel = '取消', tone = 'danger', onConfirm, children }: {
  title: ReactNode; description?: ReactNode; confirmLabel?: string; cancelLabel?: string; tone?: 'danger' | 'default'; onConfirm: () => void; children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <A.Root open={open} onOpenChange={setOpen}>
      <A.Trigger asChild>{children}</A.Trigger>
      <A.Portal>
        <A.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm data-[state=open]:motion-safe:animate-[fade-in_180ms_ease-out]" />
        <A.Content className="fixed top-1/2 left-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border-strong bg-surface p-5 shadow-raised data-[state=open]:motion-safe:animate-[dialog-in_200ms_cubic-bezier(.2,.8,.2,1)]">
          <div className="flex gap-4">
            <span className={tone === 'danger' ? 'grid size-10 shrink-0 place-items-center rounded-full bg-danger-soft text-danger' : 'grid size-10 shrink-0 place-items-center rounded-full bg-brand-soft text-brand'}>
              <AlertTriangle className="size-5" />
            </span>
            <div className="min-w-0">
              <A.Title className="text-title text-fg">{title}</A.Title>
              {description && <A.Description className="mt-1.5 text-body text-fg-muted">{description}</A.Description>}
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <A.Cancel asChild><Button variant="outline">{cancelLabel}</Button></A.Cancel>
            <A.Action asChild><Button variant={tone === 'danger' ? 'danger' : 'default'} onClick={onConfirm}>{confirmLabel}</Button></A.Action>
          </div>
        </A.Content>
      </A.Portal>
    </A.Root>
  )
}
