import { useState } from 'react'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import { AudioLines, Boxes, BookOpen, MonitorPlay, Pencil, Radio, Save, Sparkles, UserRound } from 'lucide-react'
import type { ApiSchemas } from '../../api/client'
import { api } from '../../api/client'
import { ErrorNotice,ResourceState } from '../../components/feedback'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader } from '../../components/ui/card'
import { Field, Input,Select,Textarea } from '../../components/ui/input'
import { PageHeader } from '../../components/ui/page-header'
import { ResourceItem, ResourceList } from '../../components/ui/resource-list'
import { toast } from '../../components/ui/toast'
import { cn } from '../../lib/utils'
type RoomInput=ApiSchemas['LiveRoomInput']
const blank:RoomInput={name:'',avatarId:'',voiceId:'',systemPrompt:''}
export function Rooms({onConsole}:{onConsole:(id:string)=>void}) {const qc=useQueryClient();const rooms=useQuery({queryKey:['rooms'],queryFn:api.rooms});const avatars=useQuery({queryKey:['avatars'],queryFn:api.avatars});const voices=useQuery({queryKey:['voices'],queryFn:api.voices});const products=useQuery({queryKey:['products'],queryFn:api.products});const [editId,setEditId]=useState<string|null>(null);const [form,setForm]=useState<RoomInput>(blank);const save=useMutation({mutationFn:()=>editId?api.updateRoom(editId,form):api.createRoom(form),onSuccess:()=>{toast.success(editId?'直播间已更新':'直播间已创建',form.name);setEditId(null);setForm(blank);void qc.invalidateQueries({queryKey:['rooms']})}})
 const avatarName=(id:string)=>avatars.data?.find(a=>a.avatarId===id)?.name??id
 const voiceName=(id:string)=>voices.data?.find(v=>v.voiceId===id)?.name??id
 return <div className="space-y-6">
  <PageHeader title="直播间" description="组合数字人、音色、商品与提示词；进入控制台后创建会话并开播。"/>
  <Card className={cn(editId&&'border-brand/40 shadow-glow')}>
   <CardHeader icon={editId?<Pencil/>:<Sparkles/>} title={editId?'修改直播间':'创建直播间'}/>
   <form className="grid gap-3 md:grid-cols-2" onSubmit={e=>{e.preventDefault();save.mutate()}}>
    <Field label="直播间名称"><Input aria-label="直播间名称" placeholder="例如：秋冬新品专场" required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></Field>
    <Field label="数字人"><Select aria-label="数字人" required value={form.avatarId} onChange={e=>setForm({...form,avatarId:e.target.value})}><option value="">选择数字人</option>{avatars.data?.map(a=><option key={a.avatarId} value={a.avatarId}>{a.name} ({a.status})</option>)}</Select></Field>
    <Field label="音色"><Select aria-label="音色" required value={form.voiceId} onChange={e=>setForm({...form,voiceId:e.target.value})}><option value="">选择音色</option>{voices.data?.map(v=><option key={v.voiceId} value={v.voiceId}>{v.name} ({v.provider})</option>)}</Select></Field>
    <Field label="当前直播商品"><Select aria-label="当前直播商品" value={form.activeProductId??''} onChange={e=>setForm({...form,activeProductId:e.target.value||undefined})}><option value="">不选择商品</option>{products.data?.map(p=><option key={p.productId} value={p.productId}>{p.name}</option>)}</Select></Field>
    <Field label="知识库 ID" hint="可选"><Input aria-label="知识库 ID" placeholder="知识库 ID（可选）" value={form.knowledgeBaseId??''} onChange={e=>setForm({...form,knowledgeBaseId:e.target.value||undefined})} className="font-mono"/></Field>
    <Field label="系统提示词" className="md:row-span-2"><Textarea aria-label="系统提示词" placeholder="设定主播人设、语气与回答规则" required value={form.systemPrompt} onChange={e=>setForm({...form,systemPrompt:e.target.value})} className="min-h-24"/></Field>
    <div className="flex items-end gap-2"><Button loading={save.isPending}>{!save.isPending&&<Save className="size-4"/>}保存</Button>{editId&&<Button type="button" variant="outline" onClick={()=>{setEditId(null);setForm(blank)}}>取消</Button>}</div>
   </form>
   <div className="mt-3 space-y-2 empty:hidden">{save.error&&<ErrorNotice error={save.error}/>}{avatars.error&&<ErrorNotice error={avatars.error} retry={()=>void avatars.refetch()}/>}{voices.error&&<ErrorNotice error={voices.error} retry={()=>void voices.refetch()}/>}{products.error&&<ErrorNotice error={products.error} retry={()=>void products.refetch()}/>}</div>
  </Card>
  <ResourceState loading={rooms.isPending} error={rooms.error} retry={()=>void rooms.refetch()} empty={rooms.data?.length===0} emptyIcon={Radio} emptyTitle="还没有直播间" emptyDescription="先准备好数字人和音色，再创建直播间。"/>
  <ResourceList>{rooms.data?.map(r=><ResourceItem key={r.roomId} id={r.roomId} glyph={<Radio/>} title={r.name} className={cn(editId===r.roomId&&'border-brand/50')}
   meta={<><Badge><UserRound className="size-3"/>{avatarName(r.avatarId)}</Badge><Badge><AudioLines className="size-3"/>{voiceName(r.voiceId)}</Badge>{r.activeProductId&&<Badge tone="brand"><Boxes className="size-3"/>{products.data?.find(p=>p.productId===r.activeProductId)?.name??r.activeProductId}</Badge>}{r.knowledgeBaseId&&<Badge tone="info"><BookOpen className="size-3"/>{r.knowledgeBaseId}</Badge>}</>}
   description={<p className="line-clamp-1">{r.systemPrompt}</p>}
   actions={<><Button size="sm" variant="outline" onClick={()=>{setEditId(r.roomId);setForm({name:r.name,avatarId:r.avatarId,voiceId:r.voiceId,activeProductId:r.activeProductId,knowledgeBaseId:r.knowledgeBaseId,systemPrompt:r.systemPrompt});window.scrollTo({top:0,behavior:'smooth'})}}><Pencil className="size-3.5"/>编辑</Button><Button size="sm" onClick={()=>onConsole(r.roomId)}><MonitorPlay className="size-3.5"/>控制台</Button></>}/>)}</ResourceList>
 </div>
}
