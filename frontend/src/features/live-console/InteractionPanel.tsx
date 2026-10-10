import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiUrl, ApiError } from "../../api/client";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { ErrorNotice } from "../../components/feedback";

type Snapshot = {
  platform: string; mode: string; candidates: number; stopped: boolean;
  adapter: { state: string; received: number; reconnects: number };
  counters: { input: number; deduplicated: number; merged: number; expired: number; dropped: number; filtered: number; delivered: number; failed: number; peak: number };
  recent: { eventId: string; nickname: string; content: string }[];
  current?: { topic: string; audience: number; event: { content: string; traceId: string } };
  utteranceId?: string; lastError?: string;
  latency: { samples: number; meanMs: number; p50Ms: number; p95Ms: number; maxMs: number; boundary: string };
};
async function request<T>(sid: string, suffix = "/", method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(`/api/v0.4/interaction/${encodeURIComponent(sid)}${suffix}`), {
    method, credentials: "same-origin", headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const packet = await response.json();
  if (!response.ok || packet.code !== "OK") throw new ApiError(packet.code ?? "INTERNAL_ERROR", packet.message ?? "Interaction unavailable", packet.requestId, response.status);
  return packet.data as T;
}
export function InteractionPanel({ sessionId, running, speechQueue }: { sessionId: string | null; running: boolean; speechQueue: number }) {
  const qc = useQueryClient();
  const [text, setText] = useState("有 XL 吗？");
  const key = ["interaction", sessionId];
  const query = useQuery({ queryKey: key, queryFn: () => request<Snapshot>(sessionId!), enabled: !!sessionId && running, refetchInterval: running ? 1000 : false, retry: false });
  const action = useMutation({ mutationFn: ({ suffix, method, body }: { suffix: string; method: string; body?: unknown }) => request(sessionId!, suffix, method, body), onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); } });
  const send = (suffix: string, method: string, body?: unknown) => action.mutate({ suffix, method, body });
  const data = query.data;
  return <Card>
    <h2 className="font-semibold">弹幕智能互动</h2>
    <p className="mt-2 text-sm text-slate-500">来源：Mock 模拟直播间 · 真实平台尚未接入。只有调度选中的评论才创建语音任务。</p>
    {query.error && <ErrorNotice error={query.error} />}
    {action.error && <ErrorNotice error={action.error} />}
    <div className="mt-3 flex flex-wrap gap-2">
      {(["IDLE", "PRODUCT_EXPLAINING", "OPERATOR_OVERRIDE"] as const).map(mode => <Button key={mode} variant="ghost" disabled={!running || action.isPending} onClick={() => send("/mode", "PUT", { mode })}>{mode === "IDLE" ? "恢复自动互动" : mode === "PRODUCT_EXPLAINING" ? "商品讲解模式" : "操作员接管"}</Button>)}
    </div>
    <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
      <dt>互动模式</dt><dd>{data?.mode ?? "—"}</dd>
      <dt>Adapter</dt><dd>{data?.adapter.state ?? "DISCONNECTED"}</dd>
      <dt>候选 / 峰值</dt><dd>{data?.candidates ?? 0} / {data?.counters.peak ?? 0}</dd>
      <dt>语音队列（SSE）</dt><dd>{speechQueue}</dd>
      <dt>合并 / 去重</dt><dd>{data?.counters.merged ?? 0} / {data?.counters.deduplicated ?? 0}</dd>
      <dt>过滤 / 过期 / 丢弃</dt><dd>{data?.counters.filtered ?? 0} / {data?.counters.expired ?? 0} / {data?.counters.dropped ?? 0}</dd>
      <dt>投递 / 失败</dt><dd>{data?.counters.delivered ?? 0} / {data?.counters.failed ?? 0}</dd>
      <dt>最近选中 Utterance</dt><dd className="break-all">{data?.utteranceId ?? "—"}</dd>
    </dl>
    {data?.current && <p className="mt-3 break-words text-sm">最近选中：{data.current.event.content} · {data.current.topic} · {data.current.audience} 人关注</p>}
    {data?.lastError && <p role="status" className="mt-2 text-sm text-amber-700">{data.lastError}</p>}
    <p className="mt-3 text-sm text-slate-500">评论接收 → 选中：{data && data.latency.samples >= 20 ? `均值 ${data.latency.meanMs.toFixed(0)}ms · P50 ${data.latency.p50Ms.toFixed(0)}ms · P95 ${data.latency.p95Ms.toFixed(0)}ms` : "样本不足（至少 20 个）"} · n={data?.latency.samples ?? 0}。浏览器/RTMP 完整同步回复延迟尚未测量。</p>
    <ul className="mt-3 max-h-40 space-y-1 overflow-auto text-sm">{data?.recent.map(e => <li key={e.eventId} className="break-words">{e.nickname}: {e.content}</li>)}</ul>
    {import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_EVENTS === "true" && <div className="mt-4 space-y-2 border-t border-slate-200 pt-3">
      <p className="text-sm font-medium">Mock / Replay（受保护开发接口）</p>
      <div className="flex flex-wrap gap-2"><Input aria-label="Scheduler mock comment" value={text} maxLength={512} onChange={e => setText(e.target.value)} className="min-w-40 flex-1" />
        {[1, 10].map(users => <Button key={users} disabled={!running || !text.trim() || action.isPending} onClick={() => send("/mock", "POST", { text: text.trim(), users })}>{users === 1 ? "发送单条" : "模拟 10 人"}</Button>)}</div>
      <div className="flex flex-wrap gap-2">{[1, 5, 20].map(rate => <Button key={rate} disabled={!running || action.isPending} onClick={() => send("/replay", "POST", { rate, count: 100 })}>{rate} 条/秒</Button>)}
        <Button disabled={!running || action.isPending} onClick={() => send("/replay", "POST", { rate: 0, count: 100 })}>突发 100 条</Button>
        <Button variant="ghost" disabled={!running || action.isPending} onClick={() => send("/replay", "DELETE")}>停止 Replay</Button>
      </div>
    </div>}
  </Card>;
}
