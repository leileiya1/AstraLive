import * as T from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

export const TooltipProvider = T.Provider

export function Tooltip({ content, children, side = 'right', disabled = false }: { content: ReactNode; children: ReactNode; side?: T.TooltipContentProps['side']; disabled?: boolean }) {
  if (disabled) return <>{children}</>
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={8} className="z-50 rounded-md border border-border bg-surface-3 px-2 py-1 text-caption text-fg shadow-raised">
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}
