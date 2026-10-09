import { useEffect,useReducer,useState } from 'react'
import { apiUrl } from '../api/client'
import { eventNames,initialEventState,parseEvent,reduceEvent,type EventName } from '../features/live-console/events'
type Action={name:EventName;event:NonNullable<ReturnType<typeof parseEvent>>}|{name:'reset'}
export function useLiveSessionEvents(sessionId:string|null){const [state,dispatch]=useReducer((s:typeof initialEventState,a:Action)=>a.name==='reset'?initialEventState:reduceEvent(s,a.name,a.event),initialEventState);const [connection,setConnection]=useState<'idle'|'connecting'|'connected'|'reconnecting'>('idle')
 useEffect(()=>{dispatch({name:'reset'});if(!sessionId){setConnection('idle');return}let source:EventSource|null=null;let timer:ReturnType<typeof setTimeout>|undefined;let retry:ReturnType<typeof setTimeout>|undefined;let closed=false;let attempts=0
 const cleanup=()=>{source?.close();if(timer)clearTimeout(timer);if(retry)clearTimeout(retry)}
 const reconnect=()=>{if(closed)return;cleanup();setConnection('reconnecting');retry=setTimeout(connect,Math.min(1000*2**attempts++,10000))}
 const heartbeat=()=>{if(timer)clearTimeout(timer);timer=setTimeout(reconnect,45000)}
 const connect=()=>{if(closed)return;setConnection(attempts?'reconnecting':'connecting');source=new EventSource(apiUrl(`/api/v1/live-sessions/${encodeURIComponent(sessionId)}/events`));source.onopen=()=>{attempts=0;setConnection('connected');heartbeat()};source.onerror=reconnect;source.onmessage=heartbeat;source.addEventListener('heartbeat',heartbeat);source.addEventListener('snapshot',heartbeat);for(const name of eventNames)source.addEventListener(name,(raw)=>{heartbeat();try{const event=parseEvent(JSON.parse((raw as MessageEvent).data));if(event&&event.sessionId===sessionId)dispatch({name,event})}catch{/* malformed event ignored */}})}
 connect();return()=>{closed=true;cleanup();setConnection('idle')}
 },[sessionId]);return {state,connection}
}
