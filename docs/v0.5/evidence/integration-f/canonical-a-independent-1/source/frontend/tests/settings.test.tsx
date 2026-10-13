import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsCenter } from '../src/features/settings/SettingsCenter'
import { configApi, type Profile } from '../src/api/config-client'

const ok=(data:unknown,status=200)=>new Response(JSON.stringify({code:'OK',message:'success',data,requestId:'test',timestamp:'2026-10-09T00:00:00Z'}),{status})
const fail=(code:string,status:number)=>new Response(JSON.stringify({code,message:'safe failure',requestId:'test'}),{status})
const profile:Profile={profileId:'profile-a',kind:'LLM',name:'My DeepSeek',provider:'deepseek',config:{model:'deepseek-flash',maxTokens:256},version:1,enabled:true,isDefault:false,credentialConfigured:true,verification:'UNTESTED',errorCode:'',health:'UNKNOWN',updatedAt:'2026-10-09T00:00:00Z'}
let rows:Profile[]
let requests:{path:string;method:string;body:unknown}[]
function mount(){const qc=new QueryClient({defaultOptions:{queries:{retry:false}}});render(<QueryClientProvider client={qc}><SettingsCenter/></QueryClientProvider>);return qc}
beforeEach(()=>{
 rows=[];requests=[]
 vi.spyOn(globalThis,'fetch').mockImplementation(async(path,init)=>{
  const p=String(path);const method=init?.method??'GET';const body=init?.body?JSON.parse(String(init.body)):undefined
  requests.push({path:p,method,body})
  if(p.endsWith('/me'))return ok({identity:{tenantId:'tenant-a',userId:'user-a'},contractVersion:'0.3.0'})
  if(p.endsWith('/settings'))return ok({version:0,policy:{maxQueue:100,failurePolicy:'STOP'},effect:'NEXT_SESSION'})
  if(p.endsWith('/profiles')&&method==='POST'){rows=[{...profile,name:body.name,credentialConfigured:!!body.secret}];return ok(rows[0],201)}
  if(p.endsWith('/profiles'))return ok(rows)
  if(p.endsWith('/credential')){rows=[{...rows[0],version:2,verification:'UNTESTED'}];return ok(rows[0])}
  if(p.endsWith('/test')){rows=[{...rows[0],verification:'FAILED',errorCode:'PROVIDER_AUTH_FAILED',health:'DOWN'}];return fail('PROVIDER_AUTH_FAILED',502)}
  return fail('INTERNAL_ERROR',500)
 })
})
afterEach(()=>{cleanup();vi.restoreAllMocks()})
describe('configuration center',()=>{
 it('connects URL, key and model selection to the existing profile API',async()=>{
  mount();await screen.findByText('未配置 AI 模型')
  expect(screen.getByLabelText('API URL')).toHaveValue('https://api.deepseek.com')
  expect(screen.getByLabelText('API URL')).toHaveAttribute('readonly')
  fireEvent.change(screen.getByLabelText('模型选择'),{target:{value:'deepseek-v4-pro'}})
  expect(screen.getByLabelText('模型名称')).toHaveValue('deepseek-v4-pro')
  fireEvent.change(screen.getByLabelText('配置名称'),{target:{value:'Selected model'}})
  fireEvent.change(screen.getByLabelText('API Key'),{target:{value:'synthetic-key'}})
  fireEvent.click(screen.getByRole('button',{name:'保存配置'}))
  await waitFor(()=>expect(requests.some(r=>r.method==='POST')).toBe(true))
  expect(requests.find(r=>r.method==='POST')?.body).toMatchObject({provider:'deepseek',config:{model:'deepseek-v4-pro'},secret:'synthetic-key'})
  fireEvent.change(screen.getByLabelText('服务商'),{target:{value:'openai-compatible'}})
  expect(screen.getByLabelText('API URL')).not.toHaveAttribute('readonly')
 })
 it('requires authenticated identity',async()=>{
  vi.mocked(fetch).mockResolvedValue(fail('UNAUTHENTICATED',401));mount()
  expect(await screen.findByRole('heading',{name:'登录 AstraLive'})).toBeInTheDocument();expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument()
  expect(requests.some(r=>r.path.endsWith('/profiles'))).toBe(false)
 })
 it('shows saved metadata after refresh without a readable key',async()=>{
  rows=[{...profile,verification:'VERIFIED',isDefault:true}];mount()
  expect(await screen.findByText('凭据：已保存，不可查看')).toBeInTheDocument()
  expect(screen.getByText(/当前启用（后续绑定默认）/)).toBeInTheDocument()
  expect(screen.getByLabelText('API Key')).toHaveValue('')
 })
 it('clears submitted key and never places it in query/mutation caches or localStorage',async()=>{
  const storage=vi.spyOn(Storage.prototype,'setItem');const qc=mount()
  await screen.findByText('未配置 AI 模型')
  fireEvent.change(screen.getByLabelText('配置名称'),{target:{value:'Personal DeepSeek'}})
  fireEvent.change(screen.getByLabelText('API Key'),{target:{value:'ui-synthetic-private-key'}})
  fireEvent.click(screen.getByRole('button',{name:'保存配置'}))
  expect(screen.getByLabelText('API Key')).toHaveValue('')
  await screen.findByText('凭据：已保存，不可查看')
  const saved=requests.find(r=>r.method==='POST'&&r.path.endsWith('/profiles'))
  expect(saved?.body).toMatchObject({secret:'ui-synthetic-private-key'})
  expect(JSON.stringify(qc.getQueryCache().getAll().map(q=>q.state))).not.toContain('ui-synthetic-private-key')
  expect(qc.getMutationCache().getAll()).toHaveLength(0);expect(storage).not.toHaveBeenCalled()
 })
 it('renders provider 401 as failure and disables selecting the failed profile',async()=>{
  rows=[profile];mount();await screen.findByText('My DeepSeek · deepseek')
  fireEvent.click(screen.getByRole('button',{name:'测试连接'}))
  expect(await screen.findByText(/服务商拒绝密钥/)).toBeInTheDocument()
  await waitFor(()=>expect(screen.getByText(/验证失败/)).toBeInTheDocument())
  expect(screen.getByRole('button',{name:'设为默认'})).toBeDisabled()
  expect(screen.queryByText('服务端收到有效回复，测试成功。')).not.toBeInTheDocument()
 })
 it('updates credentials through the dedicated endpoint using expected version',async()=>{
  rows=[profile];mount();await screen.findByText('My DeepSeek · deepseek')
  fireEvent.click(screen.getByRole('button',{name:'编辑'}));fireEvent.change(screen.getByLabelText('API Key'),{target:{value:'rotated-ui-synthetic-key'}})
  fireEvent.click(screen.getByRole('button',{name:'更新密钥'}))
  expect(screen.getByLabelText('API Key')).toHaveValue('')
  await waitFor(()=>expect(requests.some(r=>r.path.endsWith('/credential'))).toBe(true))
  expect(requests.find(r=>r.path.endsWith('/credential'))?.body).toEqual({expectedVersion:1,secret:'rotated-ui-synthetic-key'})
 })
 it('does not invent a remote credential field for local XiaoYa',async()=>{
  mount();await screen.findByText('未配置 AI 模型');fireEvent.click(screen.getByRole('button',{name:'TTS 音色'}))
  expect(screen.getByLabelText('音色 ID')).toHaveValue('xiao_ya');expect(screen.getByLabelText('语速')).toHaveValue(1)
  expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument();expect(screen.getByText(/生成真实音频/)).toBeInTheDocument()
 })
 it('requires an OK envelope even for a 200 response',async()=>{
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({code:'PROVIDER_TEST_FAILED',message:'failed'}),{status:200}))
  await expect(configApi.profiles()).rejects.toMatchObject({code:'PROVIDER_TEST_FAILED'})
 })
})
