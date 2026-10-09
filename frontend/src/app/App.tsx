import { useState } from 'react'
import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { Activity, AudioLines, Boxes, LayoutDashboard, Menu, MonitorPlay, Radio, UserRound } from 'lucide-react'
import { Dashboard } from '../pages/Dashboard'
import { Avatars } from '../features/avatars/Avatars'
import { Voices } from '../features/voices/Voices'
import { Products } from '../features/products/Products'
import { Rooms } from '../features/rooms/Rooms'
import { LiveConsole } from '../features/live-console/LiveConsole'
import { useUi } from '../stores/ui'
import { Button } from '../components/ui/button'
const queryClient=new QueryClient({defaultOptions:{queries:{retry:1,staleTime:10000}}})
type Page='dashboard'|'avatars'|'voices'|'products'|'rooms'|'console'
const nav=[['dashboard','Dashboard',LayoutDashboard],['avatars','Avatars',UserRound],['voices','Voices',AudioLines],['products','Products',Boxes],['rooms','Live Rooms',Radio],['console','Live Console',MonitorPlay]] as const
function Shell(){const [page,setPage]=useState<Page>('dashboard');const [sessionId,setSessionId]=useState<string|null>(null);const roomId=useUi(s=>s.selectedRoomId);const setRoom=useUi(s=>s.setSelectedRoomId);const open=useUi(s=>s.sidebarOpen);const setOpen=useUi(s=>s.setSidebarOpen);return <div className="min-h-screen md:flex"><aside className={`${open?'block':'hidden'} border-r border-slate-200 bg-white p-4 md:min-h-screen md:w-56`}><div className="mb-8 flex items-center gap-2 text-lg font-bold text-sky-700"><Activity size={22}/> AstraLive</div><nav aria-label="Main navigation" className="space-y-1">{nav.map(([id,label,Icon])=><button key={id} onClick={()=>setPage(id)} className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${page===id?'bg-sky-50 font-semibold text-sky-700':'text-slate-600 hover:bg-slate-100'}`}><Icon size={18}/>{label}</button>)}</nav></aside><main className="min-w-0 flex-1"><header className="flex h-16 items-center gap-3 border-b border-slate-200 bg-white px-5"><Button variant="ghost" aria-label="Toggle sidebar" onClick={()=>setOpen(!open)}><Menu size={18}/></Button><span className="font-semibold">AstraLive Control</span><span className="ml-auto text-xs text-slate-500">Go Control Plane</span></header><div className="mx-auto max-w-7xl p-5 md:p-8">{page==='dashboard'&&<Dashboard sessionId={sessionId}/>} {page==='avatars'&&<Avatars/>} {page==='voices'&&<Voices/>} {page==='products'&&<Products/>} {page==='rooms'&&<Rooms onConsole={id=>{setRoom(id);setSessionId(null);setPage('console')}}/>} {page==='console'&&<LiveConsole roomId={roomId} sessionId={sessionId} onSession={setSessionId}/>}</div></main></div>}
export function App(){return <QueryClientProvider client={queryClient}><Shell/></QueryClientProvider>}
