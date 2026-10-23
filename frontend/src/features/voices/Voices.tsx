import { useState } from 'react'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import { AudioLines, Plus, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import { ErrorNotice,ResourceState } from '../../components/feedback'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader } from '../../components/ui/card'
import { ConfirmDialog } from '../../components/ui/confirm-dialog'
import { Field, Input } from '../../components/ui/input'
import { PageHeader } from '../../components/ui/page-header'
import { Mono, ResourceItem, ResourceList } from '../../components/ui/resource-list'
import { toast } from '../../components/ui/toast'
export function Voices(){const qc=useQueryClient();const q=useQuery({queryKey:['voices'],queryFn:api.voices});const [name,setName]=useState('');const [provider,setProvider]=useState('MOCK');const [providerVoiceId,setId]=useState('');const create=useMutation({mutationFn:api.createVoice,onSuccess:(v)=>{setName('');setId('');void qc.invalidateQueries({queryKey:['voices']});toast.success('音色已创建',v.name)}});const remove=useMutation({mutationFn:api.deleteVoice,onSuccess:()=>{void qc.invalidateQueries({queryKey:['voices']});toast.success('音色已删除')}})
 return <div className="space-y-6">
  <PageHeader title="音色" description="预置 TTS 音色，直播间按音色合成主播语音。"/>
  <Card>
   <CardHeader icon={<Plus/>} title="新增预置音色"/>
   <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_10rem_minmax(0,1fr)_auto] lg:items-end" onSubmit={e=>{e.preventDefault();create.mutate({name:name.trim(),provider:provider.trim(),providerVoiceId:providerVoiceId.trim()})}}>
    <Field label="名称"><Input aria-label="名称" placeholder="例如：小雅 温柔女声" value={name} onChange={e=>setName(e.target.value)} required/></Field>
    <Field label="服务商"><Input aria-label="服务商" value={provider} onChange={e=>setProvider(e.target.value)} required className="font-mono"/></Field>
    <Field label="服务商音色 ID"><Input aria-label="服务商音色 ID" placeholder="例如：xiao_ya" value={providerVoiceId} onChange={e=>setId(e.target.value)} required className="font-mono"/></Field>
    <Button loading={create.isPending}>{!create.isPending&&<Plus className="size-4"/>}创建</Button>
   </form>
   {create.error&&<div className="mt-3"><ErrorNotice error={create.error}/></div>}
  </Card>
  <ResourceState loading={q.isPending} error={q.error} retry={()=>void q.refetch()} empty={q.data?.length===0} emptyIcon={AudioLines} emptyTitle="还没有音色" emptyDescription="新增一个预置音色后即可在直播间中选择。"/>
  <ResourceList className="lg:grid-cols-2">{q.data?.map(v=><ResourceItem key={v.voiceId} id={v.voiceId} glyph={<AudioLines/>} title={v.name}
   meta={<><Badge tone="info">{v.provider}</Badge><Badge className="font-mono">{v.providerVoiceId}</Badge><Mono>{v.voiceId}</Mono></>}
   actions={<ConfirmDialog title={`删除音色「${v.name}」？`} description="删除后使用该音色的直播间需要重新选择音色，此操作不能撤销。" confirmLabel="删除" onConfirm={()=>remove.mutate(v.voiceId)}>
    <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" disabled={remove.isPending}><Trash2 className="size-3.5"/>删除</Button>
   </ConfirmDialog>}/>)}</ResourceList>
  {remove.error&&<ErrorNotice error={remove.error}/>}
 </div>
}
