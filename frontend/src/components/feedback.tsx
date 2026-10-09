import { ApiError } from '../api/client'
import { Button } from './ui/button'
export function ErrorNotice({error,retry}:{error:unknown;retry?:()=>void}) {
  const e = error instanceof ApiError ? error : null
  return <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"><span>{e?.message ?? '请求失败，请重试'}</span>{import.meta.env.DEV && e && <small className="ml-2">{e.code} {e.requestId}</small>}{retry && <Button type="button" variant="ghost" onClick={retry}>重试</Button>}</div>
}
export function ResourceState({loading,error,retry,empty}:{loading:boolean;error:unknown;retry:()=>void;empty?:boolean}) { if(loading)return <p role="status">加载中…</p>;if(error)return <ErrorNotice error={error} retry={retry}/>;if(empty)return <p className="py-10 text-center text-slate-500">暂无内容</p>;return null }
