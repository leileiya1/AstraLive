import { useRef,useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { integrationApi } from './integration-client'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
import { ErrorNotice } from '../../components/feedback'
export function LoginPanel({onSignedIn=()=>window.location.reload()}:{onSignedIn?:()=>void}={}){
 const username=useRef<HTMLInputElement>(null),password=useRef<HTMLInputElement>(null)
 const qc=useQueryClient();const [busy,setBusy]=useState(false);const [error,setError]=useState<unknown>(null)
 async function login(){const name=username.current?.value??'',secret=password.current?.value??'';if(password.current)password.current.value='';setBusy(true);setError(null)
 try{await integrationApi.login(name,secret);qc.clear();onSignedIn()}catch(e){setError(e)}finally{setBusy(false)}}
 return <Card><h1 className="mb-3 text-xl font-semibold">登录 AstraLive</h1><p className="mb-3 text-sm text-slate-600">单操作员 MVP · 使用管理员预置的账户。登录后进入 AI 模型配置，可填写 API URL、API Key、选择模型，并测试连接。</p><form className="grid max-w-md gap-3" onSubmit={e=>{e.preventDefault();void login()}}><label>用户名<Input ref={username} aria-label="登录用户名" autoComplete="username" required/></label><label>密码<Input ref={password} aria-label="登录密码" type="password" autoComplete="current-password" minLength={12} maxLength={72} required/></label><Button disabled={busy}>登录</Button></form>{error!=null&&<ErrorNotice error={error}/>}</Card>
}
