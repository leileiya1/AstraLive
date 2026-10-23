import { useRef,useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { integrationApi } from './integration-client'
import { Button } from '../../components/ui/button'
import { KeyRound, LogIn } from 'lucide-react'
import { Card } from '../../components/ui/card'
import { Field, Input } from '../../components/ui/input'
import { ErrorNotice } from '../../components/feedback'
export function LoginPanel({onSignedIn=()=>window.location.reload()}:{onSignedIn?:()=>void}={}){
 const username=useRef<HTMLInputElement>(null),password=useRef<HTMLInputElement>(null)
 const qc=useQueryClient();const [busy,setBusy]=useState(false);const [error,setError]=useState<unknown>(null)
 async function login(){const name=username.current?.value??'',secret=password.current?.value??'';if(password.current)password.current.value='';setBusy(true);setError(null)
 try{await integrationApi.login(name,secret);qc.clear();onSignedIn()}catch(e){setError(e)}finally{setBusy(false)}}
 return <div className="grid min-h-[70dvh] place-items-center"><Card className="relative w-full max-w-md overflow-hidden p-6 sm:p-8 shadow-raised">
  <span aria-hidden className="pointer-events-none absolute -top-24 -right-20 size-56 rounded-full bg-brand-gradient opacity-20 blur-3xl"/>
  <span className="relative mb-5 grid size-11 place-items-center rounded-xl bg-brand-gradient text-brand-fg shadow-glow"><KeyRound className="size-5"/></span>
  <h1 className="relative text-display tracking-tight">登录 AstraLive</h1>
  <p className="relative mt-2 mb-6 text-body text-fg-muted">单操作员 MVP · 使用管理员预置的账户。登录后进入 AI 模型配置，可填写 API URL、API Key、选择模型，并测试连接。</p>
  <form className="relative grid gap-4" onSubmit={e=>{e.preventDefault();void login()}}><Field label="用户名"><Input ref={username} aria-label="登录用户名" autoComplete="username" required/></Field><Field label="密码" hint="12–72 个字符"><Input ref={password} aria-label="登录密码" type="password" autoComplete="current-password" minLength={12} maxLength={72} required/></Field><Button size="lg" className="mt-1 w-full" loading={busy}>{!busy&&<LogIn className="size-4"/>}登录</Button></form>
  {error!=null&&<div className="relative mt-4"><ErrorNotice error={error}/></div>}
 </Card></div>
}
