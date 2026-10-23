import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Hand, MessageSquareText, PackageOpen, Radio, Sparkles } from "lucide-react";
import { apiUrl, ApiError } from "../../api/client";
import { Card, CardHeader } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Badge, StatusDot } from "../../components/ui/badge";
import { EmptyState } from "../../components/ui/empty-state";
import { ErrorNotice } from "../../components/feedback";
import { cn } from "../../lib/utils";

export type Snapshot = {
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
/** Read-only view of the snapshot InteractionPanel polls; never fetches on its own. */
export function useInteractionSnapshot(sessionId: string | null) {
  return useQuery<Snapshot>({ queryKey: ["interaction", sessionId], queryFn: () => request<Snapshot>(sessionId!), enabled: false }).data;
}
const modes = [
  { mode: "IDLE", label: "恢复自动互动", Icon: Sparkles },
  { mode: "PRODUCT_EXPLAINING", label: "商品讲解模式", Icon: PackageOpen },
  { mode: "OPERATOR_OVERRIDE", label: "操作员接管", Icon: Hand },
] as const;
const modeLabels: Record<string, string> = { IDLE: "自动互动", PRODUCT_EXPLAINING: "商品讲解", OPERATOR_OVERRIDE: "操作员接管" };
function Stat({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0 rounded-md bg-surface-2/70 px-2.5 py-2"><dt className="truncate text-[11px] text-fg-subtle">{label}</dt><dd className="mt-0.5 truncate font-medium tabular text-fg">{children}</dd></div>;
}
export function InteractionPanel({ sessionId, running, speechQueue, className }: { sessionId: string | null; running: boolean; speechQueue: number; className?: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState("有 XL 吗？");
  const key = ["interaction", sessionId];
  // An authentication/authorization refusal will not change by polling: stop
  // and keep the notice until the operator logs in and the panel remounts.
  const refused = (error: unknown) => error instanceof ApiError && (error.status === 401 || error.status === 403);
  const query = useQuery({ queryKey: key, queryFn: () => request<Snapshot>(sessionId!), enabled: !!sessionId && running, refetchInterval: q => running && !refused(q.state.error) ? 1000 : false, retry: false });
  const action = useMutation({ mutationFn: ({ suffix, method, body }: { suffix: string; method: string; body?: unknown }) => request(sessionId!, suffix, method, body), onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); } });
  const send = (suffix: string, method: string, body?: unknown) => action.mutate({ suffix, method, body });
  const data = query.data;
  const feed = useRef<HTMLUListElement>(null);
  const pinned = useRef(true);
  const lastId = data?.recent.at(-1)?.eventId;
  useEffect(() => { const el = feed.current; if (el && pinned.current) el.scrollTop = el.scrollHeight; }, [lastId]);
  const adapter = data?.adapter.state ?? "DISCONNECTED";
  const selected = data?.current?.event.content;
  // The snapshot links the selection by content only; mark the newest matching comment.
  const selectedId = selected ? [...(data?.recent ?? [])].reverse().find(e => e.content === selected)?.eventId : undefined;
  return <Card className={cn("flex min-h-0 flex-col p-4 sm:p-5", className)}>
    <CardHeader
      className="mb-3"
      icon={<MessageSquareText />}
      title="弹幕互动"
      description="来源：Mock 模拟直播间 · 真实平台尚未接入。只有调度选中的评论才创建语音任务。"
      actions={<Badge tone={adapter === "CONNECTED" ? "ok" : running ? "warn" : "neutral"} title="平台适配器状态"><StatusDot tone={adapter === "CONNECTED" ? "ok" : running ? "warn" : "neutral"} pulse={running && adapter !== "CONNECTED"} />{adapter}</Badge>}
    />
    {query.error && <ErrorNotice error={query.error} />}
    {action.error && <ErrorNotice error={action.error} />}
    <div className="grid grid-cols-3 gap-1 rounded-md border border-border bg-surface-2/60 p-1" aria-label="互动模式">
      {modes.map(({ mode, label, Icon }) => {
        const current = data?.mode === mode;
        return <Button key={mode} size="sm" variant="ghost" aria-pressed={current} disabled={!running || action.isPending} onClick={() => send("/mode", "PUT", { mode })}
          className={cn("h-auto min-h-8 px-1.5 py-1.5 text-[12px] whitespace-normal", current && "bg-surface text-fg shadow-card ring-1 ring-brand/30")}>
          <Icon className={cn("size-3.5 shrink-0", current && "text-brand")} />{label}
        </Button>;
      })}
    </div>
    <ul ref={feed} onScroll={e => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24; }}
      aria-label="最近弹幕" className="relative mt-3 h-72 space-y-1.5 overflow-y-auto overscroll-contain rounded-md border border-border bg-bg/40 p-2 xl:h-[22rem]">
      {!data?.recent.length && <li className="list-none"><EmptyState compact icon={Radio} title={running ? "等待弹幕…" : "直播开始后显示弹幕"} /></li>}
      <AnimatePresence initial={false}>
        {data?.recent.map(e => {
          const hit = e.eventId === selectedId;
          return <m.li key={e.eventId} layout="position" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            className={cn("break-words rounded-md px-2.5 py-1.5 text-body", hit ? "border border-brand/40 bg-brand-soft shadow-glow" : "hover:bg-surface-2/70")}>
            <span className={cn("mr-1.5 font-medium", hit ? "text-brand" : "text-info")}>{e.nickname}:</span>
            <span className="text-fg">{e.content}</span>
            {hit && <span className="ml-2 inline-flex items-center gap-1 align-middle text-[11px] font-medium text-brand"><CheckCircle2 className="size-3" />已选中回答</span>}
          </m.li>;
        })}
      </AnimatePresence>
    </ul>
    {data?.current && <p className="mt-3 break-words rounded-md border border-brand/25 bg-brand-soft/60 px-3 py-2 text-caption text-fg-muted">最近选中：<span className="text-fg">{data.current.event.content}</span> · {data.current.topic} · {data.current.audience} 人关注</p>}
    {data?.lastError && <p role="status" className="mt-2 text-caption text-warn">{data.lastError}</p>}
    <dl className="mt-3 grid grid-cols-2 gap-1.5 text-caption sm:grid-cols-3">
      <Stat label="互动模式">{data ? modeLabels[data.mode] ?? data.mode : "—"}</Stat>
      <Stat label="候选 / 峰值">{data?.candidates ?? 0} / {data?.counters.peak ?? 0}</Stat>
      <Stat label="语音队列（SSE）">{speechQueue}</Stat>
      <Stat label="合并 / 去重">{data?.counters.merged ?? 0} / {data?.counters.deduplicated ?? 0}</Stat>
      <Stat label="过滤 / 过期 / 丢弃">{data?.counters.filtered ?? 0} / {data?.counters.expired ?? 0} / {data?.counters.dropped ?? 0}</Stat>
      <Stat label="投递 / 失败">{data?.counters.delivered ?? 0} / {data?.counters.failed ?? 0}</Stat>
      <div className="col-span-2 min-w-0 rounded-md bg-surface-2/70 px-2.5 py-2 sm:col-span-3"><dt className="text-[11px] text-fg-subtle">最近选中 Utterance</dt><dd className="mt-0.5 truncate font-mono text-[11px] text-fg-muted">{data?.utteranceId ?? "—"}</dd></div>
    </dl>
    <p className="mt-3 text-[11px] leading-relaxed text-fg-subtle">评论接收 → 选中：{data && data.latency.samples >= 20 ? `均值 ${data.latency.meanMs.toFixed(0)}ms · P50 ${data.latency.p50Ms.toFixed(0)}ms · P95 ${data.latency.p95Ms.toFixed(0)}ms` : "样本不足（至少 20 个）"} · n={data?.latency.samples ?? 0}。此面板不展示浏览器/RTMP 完整同步回复延迟。</p>
    {import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_EVENTS === "true" && <div className="mt-3 space-y-2 border-t border-dashed border-border-strong pt-3">
      <p className="flex items-center gap-2 text-caption font-medium text-fg-muted"><Badge tone="warn">DEV</Badge>Mock / Replay（受保护开发接口）</p>
      <div className="flex flex-wrap gap-2"><Input aria-label="模拟弹幕内容" value={text} maxLength={512} onChange={e => setText(e.target.value)} className="min-w-40 flex-1" />
        {[1, 10].map(users => <Button key={users} size="sm" variant="outline" disabled={!running || !text.trim() || action.isPending} onClick={() => send("/mock", "POST", { text: text.trim(), users })}>{users === 1 ? "发送单条" : "模拟 10 人"}</Button>)}</div>
      <div className="flex flex-wrap gap-1.5">{[1, 5, 20].map(rate => <Button key={rate} size="sm" variant="subtle" disabled={!running || action.isPending} onClick={() => send("/replay", "POST", { rate, count: 100 })}>{rate} 条/秒</Button>)}
        <Button size="sm" variant="subtle" disabled={!running || action.isPending} onClick={() => send("/replay", "POST", { rate: 0, count: 100 })}>突发 100 条</Button>
        <Button size="sm" variant="ghost" disabled={!running || action.isPending} onClick={() => send("/replay", "DELETE")}>停止 Replay</Button>
      </div>
    </div>}
  </Card>;
}
