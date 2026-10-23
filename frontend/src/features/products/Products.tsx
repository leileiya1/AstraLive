import { useState } from 'react'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import { BookOpen, Boxes, PackagePlus, Pencil, Save } from 'lucide-react'
import type { ApiSchemas } from '../../api/client'
import { api } from '../../api/client'
import { ErrorNotice,ResourceState } from '../../components/feedback'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardHeader } from '../../components/ui/card'
import { Field, Input,Textarea } from '../../components/ui/input'
import { PageHeader } from '../../components/ui/page-header'
import { ResourceItem, ResourceList } from '../../components/ui/resource-list'
import { toast } from '../../components/ui/toast'
import { cn } from '../../lib/utils'
type ProductInput=ApiSchemas['ProductInput']
const blank:ProductInput={name:'',description:'',price:0,currency:'CNY',stock:0,sizes:[]}
export function Products(){const qc=useQueryClient();const q=useQuery({queryKey:['products'],queryFn:api.products});const [editId,setEditId]=useState<string|null>(null);const [form,setForm]=useState<ProductInput>(blank);const save=useMutation({mutationFn:()=>editId?api.updateProduct(editId,form):api.createProduct(form),onSuccess:()=>{toast.success(editId?'商品已更新':'商品已创建',form.name);setEditId(null);setForm(blank);void qc.invalidateQueries({queryKey:['products']})}})
 return <div className="space-y-6">
  <PageHeader title="商品" description="直播讲解与观众问答所依据的商品资料。"/>
  <Card className={cn(editId&&'border-brand/40 shadow-glow')}>
   <CardHeader icon={editId?<Pencil/>:<PackagePlus/>} title={editId?'修改商品':'创建商品'} description={editId?'保存后新的直播回答会使用更新后的资料。':undefined}/>
   <form className="grid gap-3 md:grid-cols-2" onSubmit={e=>{e.preventDefault();save.mutate()}}>
    <Field label="商品名称"><Input aria-label="商品名称" placeholder="例如：纯棉宽松卫衣" value={form.name} onChange={e=>setForm({...form,name:e.target.value})} required/></Field>
    <div className="grid grid-cols-3 gap-3">
     <Field label="价格"><Input aria-label="价格" type="number" min="0" step="0.01" value={form.price} onChange={e=>setForm({...form,price:Number(e.target.value)})} required/></Field>
     <Field label="货币"><Input aria-label="货币" value={form.currency} onChange={e=>setForm({...form,currency:e.target.value})} required/></Field>
     <Field label="库存"><Input aria-label="库存" type="number" min="0" step="1" value={form.stock} onChange={e=>setForm({...form,stock:Number(e.target.value)})} required/></Field>
    </div>
    <Field label="尺码" hint="用逗号分隔，例如 S, M, L"><Input aria-label="尺码" placeholder="尺码，用逗号分隔" value={form.sizes.join(', ')} onChange={e=>setForm({...form,sizes:e.target.value.split(',').map(s=>s.trim()).filter(Boolean)})}/></Field>
    <Field label="描述"><Textarea aria-label="描述" placeholder="面料、版型、卖点…" value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/></Field>
    <div className="flex gap-2 md:col-span-2"><Button loading={save.isPending}>{!save.isPending&&<Save className="size-4"/>}保存</Button>{editId&&<Button type="button" variant="outline" onClick={()=>{setEditId(null);setForm(blank)}}>取消</Button>}</div>
   </form>
   {save.error&&<div className="mt-3"><ErrorNotice error={save.error}/></div>}
  </Card>
  <ResourceState loading={q.isPending} error={q.error} retry={()=>void q.refetch()} empty={q.data?.length===0} emptyIcon={Boxes} emptyTitle="还没有商品" emptyDescription="创建商品后可在直播间中设为当前讲解商品。"/>
  <ResourceList className="lg:grid-cols-2">{q.data?.map(p=><ResourceItem key={p.productId} id={p.productId} glyph={<Boxes/>} title={p.name} className={cn(editId===p.productId&&'border-brand/50')}
   meta={<><span className="text-body font-semibold tabular text-fg">{p.price} <span className="text-caption font-normal text-fg-muted">{p.currency}</span></span><Badge tone={p.stock>0?'ok':'danger'}>库存 {p.stock}</Badge>{p.sizes.map(s=><Badge key={s}>{s}</Badge>)}</>}
   description={p.description&&<p className="line-clamp-2">{p.description}</p>}
   actions={<Button size="sm" variant="outline" onClick={()=>{setEditId(p.productId);setForm({name:p.name,description:p.description,price:p.price,currency:p.currency,stock:p.stock,sizes:p.sizes});window.scrollTo({top:0,behavior:'smooth'})}}><Pencil className="size-3.5"/>编辑</Button>}/>)}</ResourceList>
  <Card className="flex items-start gap-3 border-dashed bg-surface/60 p-4">
   <span className="grid size-9 shrink-0 place-items-center rounded-md bg-info-soft text-info"><BookOpen className="size-4"/></span>
   <div><h2 className="text-body font-medium">知识库</h2><p className="mt-1 text-caption text-fg-muted">契约尚未定义创建字段与查询接口。已知知识库 ID 可在「直播间」中填写。</p></div>
  </Card>
 </div>
}
