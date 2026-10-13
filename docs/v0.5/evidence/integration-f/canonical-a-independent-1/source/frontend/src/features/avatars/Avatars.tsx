import { useState } from 'react'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { ErrorNotice, ResourceState } from '../../components/feedback'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
export function Avatars(){const qc=useQueryClient();const q=useQuery({queryKey:['avatars'],queryFn:api.avatars});const [name,setName]=useState('');const [engine,setEngine]=useState('MOCK');const [jobId,setJobId]=useState<string|null>(null)
 const job=useQuery({queryKey:['job',jobId],queryFn:()=>api.job(jobId!),enabled:!!jobId,refetchInterval:(query)=>['COMPLETED','FAILED','CANCELLED'].includes(query.state.data?.status??'')?false:1500})
 const create=useMutation({mutationFn:api.createAvatar,onSuccess:()=>{setName('');void qc.invalidateQueries({queryKey:['avatars']})}})
 const prepare=useMutation({mutationFn:api.prepareAvatar,onSuccess:(data)=>{setJobId(data.jobId);void qc.invalidateQueries({queryKey:['avatars']})}})
 const remove=useMutation({mutationFn:api.deleteAvatar,onSuccess:()=>void qc.invalidateQueries({queryKey:['avatars']})})
 return <div className="space-y-5"><h1 className="text-2xl font-semibold">Avatars</h1><Card><h2 className="mb-3 font-semibold">创建数字人</h2><form className="flex flex-wrap gap-2" onSubmit={e=>{e.preventDefault();if(name.trim())create.mutate({name:name.trim(),engine:engine.trim()||'MOCK'})}}><Input aria-label="名称" placeholder="名称" value={name} onChange={e=>setName(e.target.value)} required className="max-w-xs"/><Input aria-label="Engine" value={engine} onChange={e=>setEngine(e.target.value)} required className="max-w-40"/><Button disabled={create.isPending}>创建</Button></form>{create.error && <ErrorNotice error={create.error}/>}</Card>{jobId && <Card><h2 className="font-semibold">Prepare Job</h2><p>{jobId}: {job.data?.status??'查询中'}</p>{job.error && <ErrorNotice error={job.error} retry={()=>void job.refetch()}/>}</Card>}<ResourceState loading={q.isPending} error={q.error} retry={()=>void q.refetch()} empty={q.data?.length===0}/><div className="grid gap-3">{q.data?.map(a=><Card key={a.avatarId} className="flex items-center justify-between gap-3"><div><h2 className="font-semibold">{a.name}</h2><p className="text-sm text-slate-500">{a.avatarId} · {a.engine} · {a.status}</p></div><div className="flex gap-2"><Button variant="outline" disabled={prepare.isPending} onClick={()=>prepare.mutate(a.avatarId)}>Prepare</Button><Button variant="danger" disabled={remove.isPending} onClick={()=>remove.mutate(a.avatarId)}>删除</Button></div></Card>)}</div>{prepare.error&&<ErrorNotice error={prepare.error}/>} {remove.error&&<ErrorNotice error={remove.error}/>}</div>
}
