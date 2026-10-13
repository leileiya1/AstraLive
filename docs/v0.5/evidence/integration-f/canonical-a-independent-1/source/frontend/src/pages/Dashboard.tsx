import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card } from '../components/ui/card'
import { ResourceState } from '../components/feedback'
export function Dashboard({sessionId}:{sessionId:string|null}) {
 const health=useQuery({queryKey:['health'],queryFn:api.controlHealth,refetchInterval:15000,retry:false})
 const session=useQuery({queryKey:['session',sessionId],queryFn:()=>api.session(sessionId!),enabled:!!sessionId,refetchInterval:10000})
 return <div className="space-y-5"><h1 className="text-2xl font-semibold">Dashboard</h1><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"><Card><h2 className="text-sm text-slate-500">Control Plane</h2><p className="mt-2 text-xl font-semibold">{health.isPending?'检查中':health.isError?'不可用':health.data?.status}</p></Card><Card><h2 className="text-sm text-slate-500">Runtime</h2><p className="mt-2 text-xl font-semibold">未提供公共健康接口</p></Card><Card><h2 className="text-sm text-slate-500">Active Sessions</h2><p className="mt-2 text-xl font-semibold">未提供聚合接口</p></Card><Card><h2 className="text-sm text-slate-500">Current Session</h2><p className="mt-2 text-xl font-semibold">{session.data?.status ?? '未选择'}</p><p className="break-all text-xs text-slate-500">{sessionId}</p></Card></div><ResourceState loading={false} error={health.error} retry={()=>void health.refetch()}/><Card><h2 className="font-semibold">Recent Runtime Errors</h2><p className="mt-2 text-sm text-slate-500">进入 Live Console 后可查看当前会话的 Runtime 事件。</p></Card></div>
}
