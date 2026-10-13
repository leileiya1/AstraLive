import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {QueryClient,QueryClientProvider} from '@tanstack/react-query'
import {LoginPanel} from '../src/features/settings/LoginPanel'
import {ProviderStatus} from '../src/features/live-console/ProviderStatus'
afterEach(()=>{cleanup();vi.restoreAllMocks()})
const ok=(data:unknown)=>new Response(JSON.stringify({code:'OK',data}),{status:200})
it('uses genuine login endpoint and clears password and cached data',async()=>{
 const qc=new QueryClient({defaultOptions:{queries:{retry:false}}});qc.setQueryData(['old-owner-room'],{roomId:'old'})
 const seen:unknown[]=[];vi.spyOn(globalThis,'fetch').mockImplementation(async(_,init)=>{seen.push(JSON.parse(String(init?.body)));return ok({identity:{tenantId:'operator',userId:'operator'},mode:'SINGLE_OPERATOR'})})
 const signedIn=vi.fn();render(<QueryClientProvider client={qc}><LoginPanel onSignedIn={signedIn}/></QueryClientProvider>);fireEvent.change(screen.getByLabelText('登录用户名'),{target:{value:'operator'}});fireEvent.change(screen.getByLabelText('登录密码'),{target:{value:'synthetic-login-password'}});fireEvent.click(screen.getByRole('button',{name:'登录'}))
 expect(screen.getByLabelText('登录密码')).toHaveValue('');await waitFor(()=>expect(signedIn).toHaveBeenCalledOnce());expect(qc.getQueryCache().getAll()).toHaveLength(0);expect(seen).toEqual([{username:'operator',password:'synthetic-login-password'}])
})
it('separates latest defaults from pinned Session and displays degradation',async()=>{
 vi.spyOn(globalThis,'fetch').mockImplementation(async path=>{
  const url=String(path);if(url.endsWith('/me'))return ok({identity:{tenantId:'t',userId:'u'}})
  if(url.endsWith('/profiles'))return ok([{kind:'LLM',provider:'deepseek',version:2,isDefault:true}])
  return ok({integrationVersion:'0.4.0',sessionId:'s',bindingId:'b',capturedAt:'2026-10-10T00:00:00Z',expiresAt:'2026-10-11T00:00:00Z',profiles:[{kind:'LLM',provider:'deepseek',version:1}],mode:'DEGRADED',errorCode:'WORKER_DISCONNECTED',workerEpoch:''})
 })
 const qc=new QueryClient({defaultOptions:{queries:{retry:false}}});render(<QueryClientProvider client={qc}><ProviderStatus sessionId="s"/></QueryClientProvider>)
 expect(await screen.findByTestId('provider-mode')).toHaveTextContent('DEGRADED · WORKER_DISCONNECTED');expect(screen.getByText(/后续 Session 默认/)).toHaveTextContent('v2');expect(screen.getByText(/本次绑定/)).toHaveTextContent('v1')
})
