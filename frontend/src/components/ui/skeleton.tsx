import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        'rounded-md bg-surface-3 bg-[linear-gradient(90deg,transparent,color-mix(in_oklab,var(--fg)_6%,transparent),transparent)] bg-size-[200%_100%] motion-safe:animate-shimmer',
        className,
      )}
      {...props}
    />
  )
}

/** Placeholder for a list of resource cards while the first page loads. */
export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid gap-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 rounded-lg border border-border bg-surface p-5">
          <Skeleton className="size-10 rounded-md" />
          <div className="flex-1 space-y-2"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-3 w-2/3" /></div>
          <Skeleton className="h-8 w-20" />
        </div>
      ))}
    </div>
  )
}
