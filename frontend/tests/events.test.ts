import { describe,expect,it } from 'vitest'
import { initialEventState,parseEvent,reduceEvent } from '../src/features/live-console/events'
const event=(id:string,utteranceId:string|null,payload:Record<string,unknown>={})=>({schemaVersion:'1.0' as const,eventId:id,eventType:'UTTERANCE_QUEUED',sessionId:'s_1',utteranceId,traceId:'t_1',occurredAt:'2026-10-06T00:00:00Z',source:'AI_RUNTIME' as const,payload})
describe('SSE reducer',()=>{
 it('maps lifecycle and deduplicates events',()=>{const ready=reduceEvent(initialEventState,'session.ready',event('e1',null));expect(ready.sessionStatus).toBe('READY');expect(reduceEvent(ready,'session.ready',event('e1',null))).toBe(ready)})
 it('updates the utterance timeline only when facts arrive',()=>{const queued=reduceEvent(initialEventState,'utterance.queued',event('e1','u_1',{text:'你好',priority:100}));const playing=reduceEvent(queued,'utterance.playing',event('e2','u_1'));expect(playing.timeline).toEqual([{utteranceId:'u_1',status:'PLAYING',text:'你好',priority:100,occurredAt:'2026-10-06T00:00:00Z'}]);const interrupted=reduceEvent(playing,'utterance.interrupted',event('e3','u_1'));expect(interrupted.timeline[0].status).toBe('INTERRUPTED')})
 it('surfaces runtime errors and rejects malformed data',()=>{const state=reduceEvent(initialEventState,'runtime.error',event('e1',null,{message:'TTS failed'}));expect(state.errors).toHaveLength(1);expect(parseEvent({bad:true})).toBeNull()})
})
