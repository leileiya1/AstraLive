import { useQuery } from '@tanstack/react-query'
import { configCall } from '../../api/config-client'
import { ErrorNotice } from '../../components/feedback'
import { Badge, StatusDot } from '../../components/ui/badge'
// Read-only projection of frozen GPU-WORKER-STATUS-CONTRACT 1.0.
type WorkerHealth={workerRef:string;ready:boolean;health:'UP'|'DOWN';mode:'gpu'|'simulation';workerEpoch:string;trueGeneratedFPS:number;lastError:string|null}
export function WorkerHealth({profileId}:{profileId:string}){
 const worker=useQuery({queryKey:['config','worker-status',profileId],queryFn:()=>configCall<WorkerHealth>(`/profiles/${encodeURIComponent(profileId)}/worker-status`),retry:false,refetchInterval:10000})
 const w=worker.data;const ready=!!w&&w.ready&&w.mode==='gpu'
 return <div className="space-y-2 text-caption text-fg-muted"><p className="flex flex-wrap items-center gap-1.5">物理 Worker：{w?<><span className="font-mono text-fg">{w.workerRef}</span><Badge tone={ready?'ok':'warn'}><StatusDot tone={ready?'ok':'warn'} pulse={!ready}/>{ready?'READY':'UNAVAILABLE'}</Badge><Badge tone={w.health==='UP'?'ok':'danger'}>{w.health}</Badge><Badge>{w.mode}</Badge><span className="tabular">{w.trueGeneratedFPS.toFixed(1)} FPS</span></>:'未知'}</p>{worker.error&&<ErrorNotice error={worker.error}/>}</div>
}
