import { z } from 'zod'
import type { ApiSchemas } from '../../api/client'
const names=['session.preparing','session.ready','session.live','session.degraded','session.ended','session.failed','utterance.queued','utterance.generating','utterance.synthesizing','utterance.rendering','utterance.playing','utterance.completed','utterance.interrupted','utterance.failed','media.ready','runtime.warning','runtime.error'] as const
export const eventNames=names
export type EventName=typeof names[number]
const runtimeEventSchema=z.object({schemaVersion:z.literal('1.0'),eventId:z.string(),eventType:z.string(),sessionId:z.string(),utteranceId:z.string().nullable(),traceId:z.string(),occurredAt:z.string(),source:z.enum(['AI_RUNTIME','CONTROL_PLANE']),payload:z.record(z.string(),z.unknown())})
export type RuntimeEvent=z.infer<typeof runtimeEventSchema>
export type TimelineItem={utteranceId:string;status:ApiSchemas['UtteranceStatus'];text?:string;priority?:number;occurredAt:string}
export type EventState={sessionStatus:ApiSchemas['LiveSessionStatus']|null;timeline:TimelineItem[];events:{name:EventName;event:RuntimeEvent}[];errors:RuntimeEvent[];mediaReady:boolean}
export const initialEventState:EventState={sessionStatus:null,timeline:[],events:[],errors:[],mediaReady:false}
const statuses:Partial<Record<EventName,ApiSchemas['LiveSessionStatus']>>={'session.preparing':'PREPARING','session.ready':'READY','session.live':'LIVE','session.degraded':'DEGRADED','session.ended':'ENDED','session.failed':'FAILED'}
const utteranceStatuses:Partial<Record<EventName,ApiSchemas['UtteranceStatus']>>={'utterance.queued':'QUEUED','utterance.generating':'GENERATING','utterance.synthesizing':'SYNTHESIZING','utterance.rendering':'RENDERING','utterance.playing':'PLAYING','utterance.completed':'COMPLETED','utterance.interrupted':'INTERRUPTED','utterance.failed':'FAILED'}
export function parseEvent(value:unknown):RuntimeEvent|null {const parsed=runtimeEventSchema.safeParse(value);return parsed.success?parsed.data:null}
export function reduceEvent(state:EventState,name:EventName,event:RuntimeEvent):EventState {
 if(state.events.some(e=>e.event.eventId===event.eventId))return state
 const status=utteranceStatuses[name];const id=event.utteranceId;let timeline=state.timeline
 if(status&&id){const prev=timeline.find(t=>t.utteranceId===id);const payload=event.payload;const item:TimelineItem={utteranceId:id,status,text:typeof payload.text==='string'?payload.text:prev?.text,priority:typeof payload.priority==='number'?payload.priority:prev?.priority,occurredAt:event.occurredAt};timeline=prev?timeline.map(t=>t.utteranceId===id?item:t):[item,...timeline]}
 return {sessionStatus:statuses[name]??state.sessionStatus,timeline,events:[{name,event},...state.events].slice(0,100),errors:name==='runtime.error'||name==='session.failed'?[event,...state.errors].slice(0,10):state.errors,mediaReady:name==='media.ready'?true:state.mediaReady}
}
