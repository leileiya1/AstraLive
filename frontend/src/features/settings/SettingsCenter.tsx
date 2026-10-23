import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { configApi, type ConfigSchemas, type Kind, type Profile } from '../../api/config-client'
import { Bot, Cpu, KeyRound, LogOut, Pencil, Plus, Radio, Save, ShieldCheck, SlidersHorizontal, Trash2, UserRound, Volume2, type LucideIcon } from 'lucide-react'
import { ErrorNotice } from '../../components/feedback'
import { Badge, StatusDot, type Tone } from '../../components/ui/badge'
import { ConfirmDialog } from '../../components/ui/confirm-dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { PageHeader } from '../../components/ui/page-header'
import { ListSkeleton, Skeleton } from '../../components/ui/skeleton'
import { cn } from '../../lib/utils'
import { Button } from '../../components/ui/button'
import { Card, CardHeader } from '../../components/ui/card'
import { Field, Input, Select } from '../../components/ui/input'
import { LoginPanel } from './LoginPanel'
import { WorkerHealth } from './WorkerHealth'
import { integrationApi } from './integration-client'

const labels: Record<Kind, string> = {LLM:'AI 模型', TTS:'TTS 音色', AVATAR:'Avatar', GPU_WORKER:'GPU Worker', LIVE_PLATFORM:'直播平台凭据'}
const providers: Record<Kind, string[]> = {LLM:['deepseek','openai-compatible'],TTS:['xiaoya'],AVATAR:['mock','lightweight','soulx'],GPU_WORKER:['soulx'],LIVE_PLATFORM:['generic']}
function initialConfig(kind: Kind, provider: string): ConfigSchemas['ProviderConfig'] {
  switch(kind) {
    case 'LLM': return {model:'deepseek-flash',maxTokens:256,...(provider === 'openai-compatible' ? {endpoint:'https://api.example.com/v1'} : {})}
    case 'TTS': return {voiceId:'xiao_ya',speed:1,modelRef:'xiaoya-default'}
    case 'AVATAR': return {avatarRef:'avatar-reference'}
    case 'GPU_WORKER': return {workerRef:'worker-reference'}
    case 'LIVE_PLATFORM': return {platform:'generic'}
  }
}
const messages: Record<string,string> = {PROVIDER_AUTH_FAILED:'服务商拒绝密钥（401/403）。请更新密钥后重新测试。',PROVIDER_TEST_UNAVAILABLE:'此 Provider 暂未接入真实探测，配置已保存，不能确认可用。',CONFIG_VERSION_CONFLICT:'配置已改变，请刷新后再操作。',CREDENTIAL_NOT_CONFIGURED:'请先保存 API Key。',ENDPOINT_BLOCKED:'端点不符合安全规则，或尚未由管理员加入允许列表。',CONFIG_NOT_VERIFIED:'请先验证当前模型配置和密钥。',RATE_LIMITED:'请间隔五秒后重试连接。'}
function friendly(error: unknown): Error { return error instanceof ApiError && messages[error.code] ? new ApiError(error.code,messages[error.code],error.requestId,error.status) : error instanceof Error ? error : new Error('配置操作失败') }
export function SettingsCenter() {
  const qc = useQueryClient()
  const me = useQuery({queryKey:['config','me'],queryFn:configApi.me,retry:false})
  const profiles = useQuery({queryKey:['config','profiles'],queryFn:configApi.profiles,enabled:me.isSuccess,retry:false})
  const settings = useQuery({queryKey:['config','settings'],queryFn:configApi.settings,enabled:me.isSuccess,retry:false})
  const [kind,setKind] = useState<Kind>('LLM')
  const workers = useQuery({queryKey:['config','authorized-workers'],queryFn:integrationApi.workers,enabled:me.isSuccess&&(kind==='GPU_WORKER'||kind==='AVATAR'),retry:false,refetchInterval:10000})
  const [selected,setSelected] = useState<Profile|null>(null)
  const [name,setName] = useState('')
  const [provider,setProvider] = useState('deepseek')
  const [config,setConfig] = useState<ConfigSchemas['ProviderConfig']>(initialConfig('LLM','deepseek'))
  const secretRef = useRef<HTMLInputElement>(null)
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState<Error|null>(null)
  const [notice,setNotice] = useState('')
  const [maxQueue,setMaxQueue] = useState(100)
  useEffect(()=>{ if(settings.data) setMaxQueue(settings.data.policy.maxQueue) },[settings.data])
  useEffect(()=>()=>{qc.removeQueries({queryKey:['config']})},[qc])
  function edit(p: Profile|null,nextKind:Kind=kind) {
    setSelected(p); setKind(nextKind); const nextProvider = p?.provider ?? providers[nextKind][0]
    setProvider(nextProvider); setName(p?.name ?? '');setConfig(p?.config ?? initialConfig(nextKind,nextProvider))
    setError(null);setNotice('');if(secretRef.current) secretRef.current.value=''
  }
  async function run(fn:()=>Promise<unknown>,message:string) {
    if(busy)return;setBusy(true);setError(null);setNotice('')
    try { await fn();setNotice(message);await qc.invalidateQueries({queryKey:['config','profiles']});await qc.invalidateQueries({queryKey:['config','settings']});setSelected(null);setName('');setConfig(initialConfig(kind,provider)) }
    catch(e) {setError(friendly(e));await qc.invalidateQueries({queryKey:['config','profiles']})}
    finally {setBusy(false)}
  }
  function save() {
    const secret=secretRef.current?.value ?? '';if(secretRef.current)secretRef.current.value=''
    if(selected && secret){setError(new Error('请单独点击更新密钥；保存配置只更新参数。'));return}
    // No mutation object/query cache receives credentials. Only the transient request carries it.
    void run(async()=>{
      if(selected) {await configApi.update(selected.profileId,{expectedVersion:selected.version,name,config})}
      else await configApi.create({kind,name,provider,config,...(secret?{secret}:{})})
    },'配置已保存；将在后续新 Session 的绑定中生效。')
  }
  function rotate() {
    const secret=secretRef.current?.value ?? '';if(secretRef.current)secretRef.current.value=''
    if(selected) void run(()=>configApi.credential(selected.profileId,{expectedVersion:selected.version,secret}),'密钥已更新，请重新测试并设为默认。')
  }
  function patch(field:string,value:string|number) {setConfig(c=>{const n={...c} as Record<string,unknown>;if(field==='temperature'&&value==='')delete n[field];else n[field]=value;return n as ConfigSchemas['ProviderConfig']})}
  function field(fieldName:string,title:string,type='text') {
    const value=(config as Record<string,string|number>)[fieldName] ?? ''
    return <Field label={title} key={fieldName}><Input aria-label={title} type={type} step={type==='number'?'any':undefined} value={value} onChange={e=>patch(fieldName,type==='number'&&e.target.value!==''?Number(e.target.value):e.target.value )} required={fieldName!=='temperature'}/></Field>
  }
  if(me.isPending)return <div role="status" aria-label="正在读取用户配置…" className="space-y-4"><Skeleton className="h-9 w-48"/><ListSkeleton rows={2}/></div>
  if(me.error && me.error instanceof ApiError && me.error.status===401)return <LoginPanel/>
  if(me.error)return <Card className="mx-auto max-w-lg"><CardHeader as="h1" icon={<ShieldCheck/>} title="配置中心"/><ErrorNotice error={me.error}/><p className="mt-3 text-body text-fg-muted">请通过 AstraLive 登录后访问。可在此使用单操作员账户登录；登录服务不可用时请联系管理员。</p><Button className="mt-4" onClick={()=>void me.refetch()}>重新检查登录</Button></Card>
  const rows=profiles.data?.filter(p=>p.kind===kind)
  return <div className="space-y-6">
    <PageHeader title="配置中心" description="配置版本在新会话绑定时固定。新会话使用此处已验证的默认配置；配置状态与实际会话状态分开显示，管理员须启用正式集成入口。"
      actions={<><Badge className="py-1"><UserRound className="size-3"/>{me.data?.identity.tenantId} / {me.data?.identity.userId}</Badge>
        <ConfirmDialog title="退出登录？" description="退出后需要重新登录才能修改配置，正在进行的直播不受影响。" confirmLabel="登出" tone="default" onConfirm={()=>void run(async()=>{await integrationApi.logout();qc.clear();window.location.reload()},'已登出')}>
          <Button variant="outline" size="sm"><LogOut className="size-3.5"/>登出</Button>
        </ConfirmDialog></>}/>
    <div role="group" aria-label="配置类型" className="flex gap-1 overflow-x-auto rounded-lg border border-border bg-surface p-1 shadow-card">{(Object.keys(labels) as Kind[]).map(k=>{const Icon=kindIcons[k];return <Button key={k} size="sm" variant="ghost" aria-pressed={kind===k} disabled={busy} onClick={()=>edit(null,k)} className={cn('flex-1 whitespace-nowrap',kind===k&&'bg-brand-soft text-brand ring-1 ring-brand/30 hover:bg-brand-soft hover:text-brand')}><Icon className="size-3.5"/>{labels[k]}</Button>})}</div>
    {(error||notice)&&<div className="space-y-2">{error&&<ErrorNotice error={error}/>}{notice&&<p role="status" className="flex items-center gap-2 rounded-md border border-ok/30 bg-ok-soft px-3 py-2.5 text-body text-ok"><ShieldCheck className="size-4 shrink-0"/>{notice}</p>}</div>}
    {profiles.error&&<ErrorNotice error={profiles.error}/>} {profiles.isPending&&<div role="status" aria-label="读取配置…"><ListSkeleton rows={2}/></div>}
    {rows?.length===0&&<EmptyState icon={kindIcons[kind]} title={`未配置 ${labels[kind]}`} description="在下方表单中新增一份配置。"/>}
    <div className="grid gap-3">{rows?.map(p=><Card key={p.profileId} className={cn('p-4 sm:p-5',p.isDefault&&'border-brand/35',selected?.profileId===p.profileId&&'shadow-glow')}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0 space-y-2"><h2 className="text-body font-semibold text-fg">{p.name} · {p.provider}</h2>
      <div className="flex flex-wrap items-center gap-1.5"><Badge className="font-mono">v{p.version}</Badge><Badge tone={p.enabled?'neutral':'danger'}>{p.enabled?'已配置':'已禁用'}</Badge>{p.isDefault?<Badge tone="brand"><StatusDot tone="brand"/>当前启用（后续绑定默认）</Badge>:<Badge>非默认</Badge>}<Badge tone={verificationTone[p.verification]??'neutral'}>{p.verification==='FAILED'?'验证失败':p.verification==='VERIFIED'?'已验证':'未验证'}</Badge></div>
      {(p.kind==='LLM'||p.kind==='LIVE_PLATFORM')&&<p className="text-caption text-fg-muted">凭据：{p.credentialConfigured?'已保存，不可查看':'未配置'}</p>}
      <p className="flex items-center gap-1.5 text-caption text-fg-muted"><StatusDot tone={p.health==='UP'?'ok':p.health==='UNKNOWN'?'neutral':'danger'}/>{p.kind==='LLM'?'最近连接测试':p.kind==='GPU_WORKER'?'Worker 健康':'连接/健康状态'}：{p.health==='UNKNOWN'?'未知 / 未上报':p.health==='UP'?'正常':'异常'}{p.errorCode&&` · ${p.errorCode}`}</p>
      {p.kind==='GPU_WORKER'&&<WorkerHealth profileId={p.profileId}/>}</div>
      <div className="flex flex-wrap items-center gap-2 lg:justify-end"><Button size="sm" variant="outline" disabled={busy} onClick={()=>edit(p)}><Pencil className="size-3.5"/>编辑</Button>
      {p.kind!=='LIVE_PLATFORM'&&<Button size="sm" variant="outline" disabled={busy||!p.enabled} onClick={()=>void run(()=>configApi.action(p,'test'),p.kind==='TTS'?'真实 XiaoYa 合成测试成功。':p.kind==='AVATAR'?'SoulX Avatar 与授权物理 Worker 匹配且 READY；实际渲染以 Session 状态为准。':p.kind==='GPU_WORKER'?'授权物理 GPU Worker 健康检查成功。':'服务端收到有效回复，测试成功。')}>{p.kind==='TTS'?'测试合成':p.kind==='AVATAR'?'检查 Avatar 绑定':p.kind==='GPU_WORKER'?'检查物理 Worker':'测试连接'}</Button>}
      {p.kind!=='LIVE_PLATFORM'&&<Button size="sm" variant="subtle" disabled={busy||!p.enabled||(p.kind==='LLM'&&p.verification!=='VERIFIED')} onClick={()=>void run(()=>configApi.action(p,'default'),'已设为后续绑定默认。')}>设为默认</Button>}
      <Button size="sm" variant="ghost" disabled={busy||!p.enabled} onClick={()=>void run(()=>configApi.action(p,'disable'),'配置已禁用。')}>禁用</Button>
      <ConfirmDialog title={`删除配置「${p.name}」？`} description="删除后不可恢复；已绑定的会话不受影响，后续会话将无法使用此配置。" confirmLabel="删除" onConfirm={()=>void run(()=>configApi.action(p,'delete'),'配置已删除。')}>
        <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" disabled={busy}><Trash2 className="size-3.5"/>删除</Button>
      </ConfirmDialog></div></div>
    </Card>)}</div>
    <Card className={cn(selected&&'border-brand/40')}><CardHeader icon={selected?<Pencil/>:<Plus/>} title={`${selected?'编辑':'新增'} ${labels[kind]} 配置`} description={footnotes[kind]}/>
      <form className="grid gap-4 md:grid-cols-2" onSubmit={e=>{e.preventDefault();save()}}>
        <Field label="配置名称"><Input aria-label="配置名称" value={name} onChange={e=>setName(e.target.value)} required maxLength={128}/></Field>
        <Field label="服务商"><Select aria-label="服务商" disabled={!!selected} value={provider} onChange={e=>{setProvider(e.target.value);setConfig(initialConfig(kind,e.target.value))}}>{providers[kind].map(p=><option key={p}>{p}</option>)}</Select></Field>
        {kind==='LLM'&&<>
          {provider==='deepseek'?<Field label="API URL" hint="固定官方端点；请求路径为 /chat/completions。"><Input aria-label="API URL" value="https://api.deepseek.com" readOnly className="font-mono"/></Field>:field('endpoint','API URL')}
          <Field label="模型选择" hint="也可填写服务商支持的模型 ID；保存后须测试连接。"><Select aria-label="模型选择" value={(config as ConfigSchemas['LLMConfig']).model} onChange={e=>patch('model',e.target.value)}>
            {Array.from(new Set(['deepseek-flash','deepseek-v4-pro',(config as ConfigSchemas['LLMConfig']).model])).map(model=><option key={model} value={model}>{model}</option>)}
          </Select></Field>
          {field('model','模型名称')}{field('maxTokens','最大输出 Token','number')}{field('temperature','Temperature（可选）','number')}
        </>}
        {kind==='TTS'&&<>{field('voiceId','音色 ID')}{field('speed','语速','number')}{field('modelRef','模型逻辑引用')}</>}
        {kind==='AVATAR'&&<>{provider==='soulx'?<Field label="Avatar 逻辑引用"><Select aria-label="Avatar 逻辑引用" required value={(config as ConfigSchemas['AvatarConfig']).avatarRef} onChange={e=>patch('avatarRef',e.target.value)}><option value="">选择已授权 Worker 的 Avatar</option>{workers.data?.filter(w=>w.avatarRef).map(w=><option key={w.workerRef} value={w.avatarRef}>{w.avatarRef} · {w.workerRef} · {w.ready?'READY':'UNAVAILABLE'}</option>)}</Select></Field>:field('avatarRef','Avatar 逻辑引用')}<Field label="Worker 配置"><Select aria-label="Worker 配置" value={(config as ConfigSchemas['AvatarConfig']).workerProfileId??''} onChange={e=>setConfig(c=>{const n={...c} as ConfigSchemas['AvatarConfig'];if(e.target.value)n.workerProfileId=e.target.value;else delete n.workerProfileId;return n})}><option value="">无 Worker</option>{profiles.data?.filter(p=>p.kind==='GPU_WORKER').map(p=><option key={p.profileId} value={p.profileId}>{p.name}</option>)}</Select></Field></>}
        {kind==='GPU_WORKER'&&<Field label="Worker 逻辑引用"><Select aria-label="Worker 逻辑引用" required value={(config as ConfigSchemas['WorkerConfig']).workerRef} onChange={e=>patch('workerRef',e.target.value)}><option value="">选择已授权 Worker</option>{workers.data?.map(w=><option key={w.workerRef} value={w.workerRef}>{w.workerRef} · {w.ready?'READY':'UNAVAILABLE'}</option>)}</Select></Field>}
        {(kind==='GPU_WORKER'||kind==='AVATAR')&&workers.error&&<div className="md:col-span-2"><ErrorNotice error={workers.error}/></div>}
        {kind==='LIVE_PLATFORM'&&field('platform','平台名称')}
        {(kind==='LLM'||kind==='LIVE_PLATFORM')&&<Field label={<span className="inline-flex items-center gap-1.5"><KeyRound className="size-3.5"/>{kind==='LLM'?'API Key':'推流凭据'}</span>} hint="只用于本次提交，保存后无法查看。"><Input ref={secretRef} aria-label={kind==='LLM'?'API Key':'推流凭据'} type="password" autoComplete="off" maxLength={4096} className="font-mono"/></Field>}
        <div className="flex flex-wrap items-end gap-2 md:col-span-2"><Button loading={busy}>{!busy&&<Save className="size-4"/>}{selected?'保存配置（凭据另行更新）':'保存配置'}</Button>{selected&&(kind==='LLM'||kind==='LIVE_PLATFORM')&&<><Button type="button" variant="outline" disabled={busy} onClick={rotate}><KeyRound className="size-4"/>更新密钥</Button>
          <ConfirmDialog title="删除已保存的凭据？" description="删除后此配置将无法连接服务商，需要重新填写密钥并测试。" confirmLabel="删除凭据" onConfirm={()=>void run(()=>configApi.action(selected,'remove-credential'),'凭据已删除。')}><Button type="button" variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" disabled={busy||!selected.credentialConfigured}>删除凭据</Button></ConfirmDialog></>} {selected&&<Button type="button" variant="ghost" disabled={busy} onClick={()=>edit(null)}>取消编辑</Button>}</div>
      </form>
    </Card>
    <Card><CardHeader icon={<SlidersHorizontal/>} title="基础运行策略" description="保存后对后续绑定的会话生效。"/>{settings.error&&<div className="mb-3"><ErrorNotice error={settings.error}/></div>}<form className="flex flex-wrap items-end gap-3" onSubmit={e=>{e.preventDefault();if(settings.data)void run(()=>configApi.saveSettings({expectedVersion:settings.data.version,policy:{maxQueue,failurePolicy:'STOP'}}),'运行策略已保存，后续绑定生效。')}}><Field label="最大队列" className="w-36"><Input aria-label="最大队列" type="number" min={1} max={100} value={maxQueue} onChange={e=>setMaxQueue(Number(e.target.value))}/></Field><p className="flex h-9 items-center gap-2 text-body text-fg-muted">失败策略：<Badge tone="warn">STOP</Badge></p><Button variant="outline" disabled={busy||!settings.data}><Save className="size-4"/>保存策略</Button></form></Card>
  </div>
}
const kindIcons: Record<Kind, LucideIcon> = {LLM:Bot, TTS:Volume2, AVATAR:UserRound, GPU_WORKER:Cpu, LIVE_PLATFORM:Radio}
const verificationTone: Record<string, Tone> = {VERIFIED:'ok', FAILED:'danger'}
const footnotes: Record<Kind, string> = {
  LLM:'连接测试由 Backend 执行；自定义端点必须由管理员加入允许列表。',
  TTS:'XiaoYa 使用本地模型，无 API 凭据；测试合成由正式 Runtime 使用已安装模型生成真实音频。',
  AVATAR:'保存逻辑引用与授权 Worker 选择；正式 Session 启动时校验 SoulX，实际渲染状态见直播控制台。',
  GPU_WORKER:'物理健康由服务端使用私有认证探测；选择默认配置不会启动 GPU。',
  LIVE_PLATFORM:'只保存加密凭据，当前不连接直播平台。',
}
