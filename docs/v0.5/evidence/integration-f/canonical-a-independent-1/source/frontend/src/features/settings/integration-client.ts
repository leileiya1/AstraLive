import { apiUrl, ApiError } from '../../api/client'
import type { components } from './integration-generated'
export type IntegrationIdentity = components['schemas']['Identity']
export type SessionProviders = components['schemas']['SessionProviders']
export type WorkerChoice = components['schemas']['WorkerChoice']
export async function integrationCall<T>(path:string, method='GET', body?:unknown):Promise<T>{
 const response=await fetch(apiUrl('/api/v0.4'+path),{method,credentials:'same-origin',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
 let data:{code?:string;message?:string;data?:T;requestId?:string}
 try{data=await response.json()}catch{throw new ApiError('INTERNAL_ERROR','服务响应无效',undefined,response.status)}
 if(!response.ok||data.code!=='OK'||data.data===undefined)throw new ApiError(data.code??'INTERNAL_ERROR',data.message??'请求失败',data.requestId,response.status)
 return data.data
}
export const integrationApi={
 me:()=>integrationCall<IntegrationIdentity>('/auth/me'),
 login:(username:string,password:string)=>integrationCall<IntegrationIdentity>('/auth/login','POST',{username,password}),
 logout:()=>integrationCall<Record<string,never>>('/auth/logout','POST',{}),
 providers:(id:string)=>integrationCall<SessionProviders>(`/sessions/${encodeURIComponent(id)}/providers`),
 workers:()=>integrationCall<WorkerChoice[]>('/workers/'),
}
