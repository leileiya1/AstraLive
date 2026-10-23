import { useState } from 'react'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import { Cog, Plus, Trash2, UserRound, Wand2 } from 'lucide-react'
import { api } from '../../api/client'
import { ErrorNotice, ResourceState } from '../../components/feedback'
import { Badge, StatusDot, type Tone } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader } from '../../components/ui/card'
import { ConfirmDialog } from '../../components/ui/confirm-dialog'
import { Field, Input } from '../../components/ui/input'
import { PageHeader } from '../../components/ui/page-header'
import { Mono, ResourceItem, ResourceList } from '../../components/ui/resource-list'
import { toast } from '../../components/ui/toast'
const statusTone=(s:string):Tone=>s==='READY'||s==='COMPLETED'?'ok':s==='FAILED'||s==='CANCELLED'?'danger':s==='CREATED'||s==='PENDING'?'neutral':'warn'
const jobLabels:Record<string,string>={PENDING:'排队中',RUNNING:'处理中',COMPLETED:'已完成',FAILED:'失败',CANCELLED:'已取消'}
export function Avatars(){const qc=useQueryClient();const q=useQuery({queryKey:['avatars'],queryFn:api.avatars});const [name,setName]=useState('');const [engine,setEngine]=useState('MOCK');const [jobId,setJobId]=useState<string|null>(null)
 const job=useQuery({queryKey:['job',jobId],queryFn:()=>api.job(jobId!),enabled:!!jobId,refetchInterval:(query)=>['COMPLETED','FAILED','CANCELLED'].includes(query.state.data?.status??'')?false:1500})
 const create=useMutation({mutationFn:api.createAvatar,onSuccess:(a)=>{setName('');void qc.invalidateQueries({queryKey:['avatars']});toast.success('数字人已创建',a.name)}})
 const prepare=useMutation({mutationFn:api.prepareAvatar,onSuccess:(data)=>{setJobId(data.jobId);void qc.invalidateQueries({queryKey:['avatars']});toast.info('预处理任务已提交')}})
 const remove=useMutation({mutationFn:api.deleteAvatar,onSuccess:()=>{void qc.invalidateQueries({queryKey:['avatars']});toast.success('数字人已删除')}})
 const jobStatus=job.data?.status
 return <div className="space-y-6">
  <PageHeader title="数字人" description="管理直播使用的数字人形象，创建后需完成预处理才能开播。"/>
  <Card>
   <CardHeader icon={<Plus/>} title="创建数字人" description="引擎默认 MOCK，本地开发无需 GPU。"/>
   <form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto] sm:items-end" onSubmit={e=>{e.preventDefault();if(name.trim())create.mutate({name:name.trim(),engine:engine.trim()||'MOCK'})}}>
    <Field label="名称"><Input aria-label="名称" placeholder="例如：小雅 · 主播" value={name} onChange={e=>setName(e.target.value)} required/></Field>
    <Field label="引擎"><Input aria-label="引擎" value={engine} onChange={e=>setEngine(e.target.value)} required className="font-mono"/></Field>
    <Button loading={create.isPending}>{!create.isPending&&<Plus className="size-4"/>}创建</Button>
   </form>
   {create.error && <div className="mt-3"><ErrorNotice error={create.error}/></div>}
  </Card>
  {jobId && <Card className="flex flex-wrap items-center gap-3 p-4">
   <span className="grid size-9 place-items-center rounded-md bg-brand-soft text-brand"><Cog className={jobStatus&&!['COMPLETED','FAILED','CANCELLED'].includes(jobStatus)?'size-4 motion-safe:animate-spin':'size-4'}/></span>
   <div className="min-w-0 flex-1"><h2 className="text-body font-medium">预处理任务</h2><Mono>{jobId}</Mono></div>
   <Badge tone={jobStatus?statusTone(jobStatus):'neutral'}><StatusDot tone={jobStatus?statusTone(jobStatus):'neutral'} pulse={!jobStatus||!['COMPLETED','FAILED','CANCELLED'].includes(jobStatus)}/>{jobStatus?jobLabels[jobStatus]??jobStatus:'查询中'}</Badge>
   {job.error && <div className="w-full"><ErrorNotice error={job.error} retry={()=>void job.refetch()}/></div>}
  </Card>}
  <ResourceState loading={q.isPending} error={q.error} retry={()=>void q.refetch()} empty={q.data?.length===0} emptyIcon={UserRound} emptyTitle="还没有数字人" emptyDescription="在上方创建第一个数字人形象。"/>
  <ResourceList className="lg:grid-cols-2">{q.data?.map(a=><ResourceItem key={a.avatarId} id={a.avatarId} glyph={<UserRound/>} title={a.name}
   meta={<><Badge tone={statusTone(a.status)}><StatusDot tone={statusTone(a.status)}/>{a.status}</Badge><Badge>{a.engine}</Badge><Mono>{a.avatarId}</Mono></>}
   actions={<><Button size="sm" variant="outline" disabled={prepare.isPending} onClick={()=>prepare.mutate(a.avatarId)}><Wand2 className="size-3.5"/>预处理</Button>
    <ConfirmDialog title={`删除数字人「${a.name}」？`} description="删除后使用该数字人的直播间将无法开播，此操作不能撤销。" confirmLabel="删除" onConfirm={()=>remove.mutate(a.avatarId)}>
     <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" disabled={remove.isPending}><Trash2 className="size-3.5"/>删除</Button>
    </ConfirmDialog></>}/>)}</ResourceList>
  {prepare.error&&<ErrorNotice error={prepare.error}/>} {remove.error&&<ErrorNotice error={remove.error}/>}
 </div>
}
