import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Cpu, Radio, ScrollText, Server } from 'lucide-react'
import { api } from '../api/client'
import { Badge, StatusDot, type Tone } from '../components/ui/badge'
import { Card, CardHeader } from '../components/ui/card'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { Skeleton } from '../components/ui/skeleton'
import { ResourceState } from '../components/feedback'
import { lookSession } from '../lib/status'

function StatCard({ icon, label, children, tone = 'neutral', pulse, footer }: { icon: ReactNode; label: string; children: ReactNode; tone?: Tone; pulse?: boolean; footer?: ReactNode }) {
  return (
    <Card className="relative overflow-hidden p-5">
      <span aria-hidden className="pointer-events-none absolute -top-10 -right-10 size-28 rounded-full bg-brand-gradient opacity-[0.07] blur-2xl" />
      <div className="flex items-center justify-between text-caption text-fg-muted">
        <span className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-md bg-surface-3 text-fg-muted [&_svg]:size-3.5">{icon}</span><h2>{label}</h2></span>
        <StatusDot tone={tone} pulse={pulse} />
      </div>
      <div className="mt-4 text-title font-semibold text-fg">{children}</div>
      {footer && <div className="mt-1 text-caption text-fg-subtle">{footer}</div>}
    </Card>
  )
}

export function Dashboard({sessionId}:{sessionId:string|null}) {
 const health=useQuery({queryKey:['health'],queryFn:api.controlHealth,refetchInterval:15000,retry:false})
 const session=useQuery({queryKey:['session',sessionId],queryFn:()=>api.session(sessionId!),enabled:!!sessionId,refetchInterval:10000})
 const healthTone:Tone=health.isPending?'warn':health.isError?'danger':health.data?.status==='UP'?'ok':'warn'
 const look=lookSession(session.data?.status)
 return <div className="space-y-6">
  <PageHeader title="总览" description="控制面健康状况与当前直播会话一览。"/>
  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
   <StatCard icon={<Server/>} label="控制面" tone={healthTone} pulse={health.isPending} footer="每 15 秒自动检查">
    {health.isPending?<Skeleton className="h-6 w-16"/>:health.isError?<span className="text-danger">不可用</span>:<span className={health.data?.status==='UP'?'text-ok':undefined}>{health.data?.status}</span>}
   </StatCard>
   <StatCard icon={<Cpu/>} label="运行时" footer="后端尚未开放"><span className="text-body text-fg-muted">未提供公共健康接口</span></StatCard>
   <StatCard icon={<Activity/>} label="活跃会话" footer="后端尚未开放"><span className="text-body text-fg-muted">未提供聚合接口</span></StatCard>
   <StatCard icon={<Radio/>} label="当前会话" tone={session.data?look.tone:'neutral'} pulse={look.pulse} footer={<span className="block truncate font-mono">{sessionId??'进入直播控制台创建会话'}</span>}>
    {session.data?<Badge tone={look.tone} className="text-body"><StatusDot tone={look.tone} ping={look.ping}/>{look.label}</Badge>:'未选择'}
   </StatCard>
  </div>
  <ResourceState loading={false} error={health.error} retry={()=>void health.refetch()}/>
  <Card>
   <CardHeader icon={<ScrollText/>} title="最近运行错误"/>
   <EmptyState icon={ScrollText} title="暂无可展示的错误" description="进入直播控制台后可查看当前会话的运行事件与错误。"/>
  </Card>
 </div>
}
