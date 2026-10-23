import { AlertTriangle, RotateCw } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { ApiError } from '../api/client'
import { Button } from './ui/button'
import { EmptyState } from './ui/empty-state'
import { ListSkeleton } from './ui/skeleton'

export function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null
  const message = e?.message ?? '请求失败，请重试'
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 text-body text-danger">
      <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1 break-words">
        <span>{message}</span>
        {import.meta.env.DEV && e && <small className="ml-2 font-mono text-caption opacity-70">{e.code} {e.requestId}</small>}
      </div>
      {retry && <Button type="button" size="sm" variant="ghost" className="-my-1 text-danger hover:text-danger" onClick={retry}><RotateCw className="size-3.5" />重试</Button>}
    </div>
  )
}

export function ResourceState({ loading, error, retry, empty, emptyTitle = '暂无内容', emptyDescription, emptyIcon }: {
  loading: boolean; error: unknown; retry: () => void; empty?: boolean; emptyTitle?: string; emptyDescription?: string; emptyIcon?: LucideIcon
}) {
  if (loading) return <div role="status" aria-label="加载中"><ListSkeleton /></div>
  if (error) return <ErrorNotice error={error} retry={retry} />
  if (empty) return <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
  return null
}
