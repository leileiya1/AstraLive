import { useQuery } from '@tanstack/react-query'
import { configCall } from '../../api/config-client'
import { ErrorNotice } from '../../components/feedback'
// Read-only projection of frozen GPU-WORKER-STATUS-CONTRACT 1.0.
type WorkerHealth={workerRef:string;ready:boolean;health:'UP'|'DOWN';mode:'gpu'|'simulation';workerEpoch:string;trueGeneratedFPS:number;lastError:string|null}
export function WorkerHealth({profileId}:{profileId:string}){
 const worker=useQuery({queryKey:['config','worker-status',profileId],queryFn:()=>configCall<WorkerHealth>(`/profiles/${encodeURIComponent(profileId)}/worker-status`),retry:false,refetchInterval:10000})
 return <div className="mt-2 text-sm"><p>物理 Worker：{worker.data?`${worker.data.workerRef} · ${worker.data.ready&&worker.data.mode==='gpu'?'READY':'UNAVAILABLE'} · ${worker.data.health} · ${worker.data.mode} · ${worker.data.trueGeneratedFPS.toFixed(1)} FPS`:'未知'}</p>{worker.error&&<ErrorNotice error={worker.error}/>}</div>
}
