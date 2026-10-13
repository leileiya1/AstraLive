import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { InteractionPanel } from '../src/features/live-console/InteractionPanel'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const snapshot = { platform: 'mock', mode: 'IDLE', candidates: 2, stopped: false, adapter: {state: 'CONNECTED'}, counters: {input:10,merged:5,filtered:1,expired:1,dropped:1,deduplicated:1,delivered:1,failed:0,peak:3}, recent:[{eventId:'e',nickname:'模拟观众',content:'<script>alert(1)</script>'}], latency:{samples:1,meanMs:100,p50Ms:100,p95Ms:100,maxMs:100} }
function show(running=true) { return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><InteractionPanel sessionId="session-test" running={running} speechQueue={1}/></QueryClientProvider>) }
test('labels Mock and does not present partial latency as synchronized playback', async () => {
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({code:'OK',data:snapshot})}))
 show();await screen.findByText('CONNECTED')
 expect(screen.getByText(/真实平台尚未接入/)).toBeInTheDocument()
 expect(screen.getByText(/样本不足/)).toBeInTheDocument()
 expect(screen.getByText(/此面板不展示浏览器\/RTMP 完整同步回复延迟/)).toBeInTheDocument()
 expect(screen.getByText(/<script>alert/)).toBeInTheDocument()
 expect(document.querySelector('script')).toBeNull()
})
test('operator mode mutation stays on owned Go endpoint',async()=>{
 const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({code:'OK',data:snapshot})});vi.stubGlobal('fetch',fetch)
 show();await screen.findByText('CONNECTED');fireEvent.click(screen.getByRole('button',{name:'操作员接管'}))
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/v0.4/interaction/session-test/mode',expect.objectContaining({method:'PUT',body:JSON.stringify({mode:'OPERATOR_OVERRIDE'})})))
})
test('no polling/mutation after Session Stop',()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);show(false)
 expect(fetch).not.toHaveBeenCalled();expect(screen.getByRole('button',{name:'恢复自动互动'})).toBeDisabled()
})
