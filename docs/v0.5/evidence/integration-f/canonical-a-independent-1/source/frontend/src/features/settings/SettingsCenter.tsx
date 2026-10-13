import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { configApi, type ConfigSchemas, type Kind, type Profile } from '../../api/config-client'
import { ErrorNotice } from '../../components/feedback'
import { Button } from '../../components/ui/button'
import { Card } from '../../components/ui/card'
import { Input } from '../../components/ui/input'
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
    return <label className="grid gap-1 text-sm" key={fieldName}>{title}<Input aria-label={title} type={type} step={type==='number'?'any':undefined} value={value} onChange={e=>patch(fieldName,type==='number'&&e.target.value!==''?Number(e.target.value):e.target.value )} required={fieldName!=='temperature'}/></label>
  }
  if(me.isPending)return <p>正在读取用户配置…</p>
  if(me.error && me.error instanceof ApiError && me.error.status===401)return <LoginPanel/>
  if(me.error)return <Card><h1 className="mb-3 text-xl font-semibold">用户配置中心</h1><ErrorNotice error={me.error}/><p className="mt-3 text-sm">请通过 AstraLive 登录后访问。可在此使用单操作员账户登录；登录服务不可用时请联系管理员。</p><Button className="mt-3" onClick={()=>void me.refetch()}>重新检查登录</Button></Card>
  return <div className="space-y-5"><h1 className="text-2xl font-semibold">用户配置中心</h1>
    <p className="text-sm text-slate-600">{me.data?.identity.tenantId} / {me.data?.identity.userId} · 配置版本在新 Session 绑定时固定。新 Session 使用此处已验证的默认配置。配置状态与实际 Session 状态分开显示；管理员须启用正式集成入口。</p>
    <Button variant="outline" onClick={()=>void run(async()=>{await integrationApi.logout();qc.clear();window.location.reload()},'已登出')}>登出</Button>
    <div className="flex flex-wrap gap-2">{(Object.keys(labels) as Kind[]).map(k=><Button key={k} variant={kind===k?'default':'outline'} disabled={busy} onClick={()=>edit(null,k)}>{labels[k]}</Button>)}</div>
    {error&&<ErrorNotice error={error}/>} {notice&&<p role="status" className="rounded bg-sky-50 p-3">{notice}</p>}
    {profiles.error&&<ErrorNotice error={profiles.error}/>} {profiles.isPending&&<p>读取配置…</p>}
    {profiles.data?.filter(p=>p.kind===kind).length===0&&<p>未配置 {labels[kind]}</p>}
    <div className="grid gap-3">{profiles.data?.filter(p=>p.kind===kind).map(p=><Card key={p.profileId}>
      <div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-semibold">{p.name} · {p.provider}</h2><p className="text-sm">v{p.version} · {p.enabled?'已配置':'已禁用'} · {p.isDefault?'当前启用（后续绑定默认）':'非默认'} · {p.verification==='FAILED'?'验证失败':p.verification==='VERIFIED'?'已验证':'未验证'}</p>
      {(p.kind==='LLM'||p.kind==='LIVE_PLATFORM')&&<p className="text-sm">凭据：{p.credentialConfigured?'已保存，不可查看':'未配置'}</p>}
      <p className="text-sm">{p.kind==='LLM'?'最近连接测试':p.kind==='GPU_WORKER'?'Worker 健康':'连接/健康状态'}：{p.health==='UNKNOWN'?'未知 / 未上报':p.health==='UP'?'正常':'异常'}{p.errorCode&&` · ${p.errorCode}`}</p></div>
      {p.kind==='GPU_WORKER'&&<WorkerHealth profileId={p.profileId}/>}
      <div className="flex flex-wrap items-center gap-2"><Button variant="outline" disabled={busy} onClick={()=>edit(p)}>编辑</Button>
      {p.kind!=='LIVE_PLATFORM'&&<Button variant="outline" disabled={busy||!p.enabled} onClick={()=>void run(()=>configApi.action(p,'test'),p.kind==='TTS'?'真实 XiaoYa 合成测试成功。':p.kind==='AVATAR'?'SoulX Avatar 与授权物理 Worker 匹配且 READY；实际渲染以 Session 状态为准。':p.kind==='GPU_WORKER'?'授权物理 GPU Worker 健康检查成功。':'服务端收到有效回复，测试成功。')}>{p.kind==='TTS'?'测试合成':p.kind==='AVATAR'?'检查 Avatar 绑定':p.kind==='GPU_WORKER'?'检查物理 Worker':'测试连接'}</Button>}
      {p.kind!=='LIVE_PLATFORM'&&<Button disabled={busy||!p.enabled||(p.kind==='LLM'&&p.verification!=='VERIFIED')} onClick={()=>void run(()=>configApi.action(p,'default'),'已设为后续绑定默认。')}>设为默认</Button>}
      <Button variant="outline" disabled={busy||!p.enabled} onClick={()=>void run(()=>configApi.action(p,'disable'),'配置已禁用。')}>禁用</Button>
      <Button variant="danger" disabled={busy} onClick={()=>void run(()=>configApi.action(p,'delete'),'配置已删除。')}>删除</Button></div></div>
    </Card>)}</div>
    <Card><h2 className="mb-3 font-semibold">{selected?'编辑':'新增'} {labels[kind]} 配置</h2>
      <form className="grid gap-3 md:grid-cols-2" onSubmit={e=>{e.preventDefault();save()}}>
        <label className="grid gap-1 text-sm">配置名称<Input aria-label="配置名称" value={name} onChange={e=>setName(e.target.value)} required maxLength={128}/></label>
        <label className="grid gap-1 text-sm">服务商<select aria-label="服务商" className="rounded border p-2" disabled={!!selected} value={provider} onChange={e=>{setProvider(e.target.value);setConfig(initialConfig(kind,e.target.value))}}>{providers[kind].map(p=><option key={p}>{p}</option>)}</select></label>
        {kind==='LLM'&&<>
          {provider==='deepseek'?<label className="grid gap-1 text-sm">API URL<Input aria-label="API URL" value="https://api.deepseek.com" readOnly/><span className="text-xs text-slate-500">固定官方端点；请求路径为 /chat/completions。</span></label>:field('endpoint','API URL')}
          <label className="grid gap-1 text-sm">模型选择<select aria-label="模型选择" className="rounded border p-2" value={(config as ConfigSchemas['LLMConfig']).model} onChange={e=>patch('model',e.target.value)}>
            {Array.from(new Set(['deepseek-flash','deepseek-v4-pro',(config as ConfigSchemas['LLMConfig']).model])).map(model=><option key={model} value={model}>{model}</option>)}
          </select><span className="text-xs text-slate-500">也可填写服务商支持的模型 ID；保存后须测试连接。</span></label>
          {field('model','模型名称')}{field('maxTokens','最大输出 Token','number')}{field('temperature','Temperature（可选）','number')}
        </>}
        {kind==='TTS'&&<>{field('voiceId','音色 ID')}{field('speed','语速','number')}{field('modelRef','模型逻辑引用')}</>}
        {kind==='AVATAR'&&<>{provider==='soulx'?<label className="grid gap-1 text-sm">Avatar 逻辑引用<select aria-label="Avatar 逻辑引用" className="rounded border p-2" required value={(config as ConfigSchemas['AvatarConfig']).avatarRef} onChange={e=>patch('avatarRef',e.target.value)}><option value="">选择已授权 Worker 的 Avatar</option>{workers.data?.filter(w=>w.avatarRef).map(w=><option key={w.workerRef} value={w.avatarRef}>{w.avatarRef} · {w.workerRef} · {w.ready?'READY':'UNAVAILABLE'}</option>)}</select></label>:field('avatarRef','Avatar 逻辑引用')}<label className="grid gap-1 text-sm">Worker 配置<select aria-label="Worker 配置" className="rounded border p-2" value={(config as ConfigSchemas['AvatarConfig']).workerProfileId??''} onChange={e=>setConfig(c=>{const n={...c} as ConfigSchemas['AvatarConfig'];if(e.target.value)n.workerProfileId=e.target.value;else delete n.workerProfileId;return n})}><option value="">无 Worker</option>{profiles.data?.filter(p=>p.kind==='GPU_WORKER').map(p=><option key={p.profileId} value={p.profileId}>{p.name}</option>)}</select></label></>}
        {kind==='GPU_WORKER'&&<label className="grid gap-1 text-sm">Worker 逻辑引用<select aria-label="Worker 逻辑引用" className="rounded border p-2" required value={(config as ConfigSchemas['WorkerConfig']).workerRef} onChange={e=>patch('workerRef',e.target.value)}><option value="">选择已授权 Worker</option>{workers.data?.map(w=><option key={w.workerRef} value={w.workerRef}>{w.workerRef} · {w.ready?'READY':'UNAVAILABLE'}</option>)}</select></label>}
        {(kind==='GPU_WORKER'||kind==='AVATAR')&&workers.error&&<ErrorNotice error={workers.error}/>}
        {kind==='LIVE_PLATFORM'&&field('platform','平台名称')}
        {(kind==='LLM'||kind==='LIVE_PLATFORM')&&<label className="grid gap-1 text-sm">{kind==='LLM'?'API Key':'推流凭据'}<Input ref={secretRef} aria-label={kind==='LLM'?'API Key':'推流凭据'} type="password" autoComplete="off" maxLength={4096}/><span className="text-xs text-slate-500">只用于本次提交，保存后无法查看。</span></label>}
        <div className="flex flex-wrap items-end gap-2"><Button disabled={busy}>{selected?'保存配置（凭据另行更新）':'保存配置'}</Button>{selected&&(kind==='LLM'||kind==='LIVE_PLATFORM')&&<><Button type="button" variant="outline" disabled={busy} onClick={rotate}>更新密钥</Button><Button type="button" variant="danger" disabled={busy||!selected.credentialConfigured} onClick={()=>void run(()=>configApi.action(selected,'remove-credential'),'凭据已删除。')}>删除凭据</Button></>} {selected&&<Button type="button" variant="outline" disabled={busy} onClick={()=>edit(null)}>取消编辑</Button>}</div>
      </form>
      <p className="mt-3 text-sm text-slate-500">{kind==='TTS'?'XiaoYa 使用本地模型，无 API 凭据；测试合成由正式 Runtime 使用已安装模型生成真实音频。':kind==='GPU_WORKER'?'物理健康由服务端使用私有认证探测；选择默认配置不会启动 GPU。':kind==='LIVE_PLATFORM'?'只保存加密凭据，当前不连接直播平台。':kind==='AVATAR'?'保存逻辑引用与授权 Worker 选择；正式 Session 启动时校验 SoulX，实际渲染状态见直播控制台。':'连接测试由 Backend 执行；自定义端点必须由管理员加入允许列表。'}</p>
    </Card>
    <Card><h2 className="mb-3 font-semibold">基础运行策略</h2>{settings.error&&<ErrorNotice error={settings.error}/>}<form className="flex flex-wrap items-end gap-3" onSubmit={e=>{e.preventDefault();if(settings.data)void run(()=>configApi.saveSettings({expectedVersion:settings.data.version,policy:{maxQueue,failurePolicy:'STOP'}}),'运行策略已保存，后续绑定生效。')}}><label className="grid gap-1 text-sm">最大队列<Input aria-label="最大队列" type="number" min={1} max={100} value={maxQueue} onChange={e=>setMaxQueue(Number(e.target.value))}/></label><p className="text-sm">失败策略：STOP</p><Button disabled={busy||!settings.data}>保存策略</Button></form></Card>
  </div>
}
