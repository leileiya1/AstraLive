import type { ReactNode, RefObject } from "react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { Activity, Clock3, Gauge, ListOrdered, Loader2, Maximize2, Minimize2, MonitorPlay, RefreshCw, Send, Speaker, Volume2, VolumeX, Zap } from "lucide-react";
import type { RuntimeEvent, EventName, TimelineItem } from "./events";
import { AnimatedNumber } from "../../components/ui/animated-number";
import { Badge, StatusDot, type Tone } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { EmptyState } from "../../components/ui/empty-state";
import { lookSession, previewLook, utteranceLook, utteranceSteps } from "../../lib/status";
import { cn } from "../../lib/utils";
import type { Snapshot } from "./InteractionPanel";

// Presentation pieces of the Live Console. They only render props; all session,
// media and SSE behaviour stays in LiveConsole / useLivePreview / useLiveSessionEvents.

const glass = "border border-white/15 bg-black/45 text-white backdrop-blur-md";

export function VideoStage({ videoRef, muted, fit, status, previewStatus, mediaReady, canChooseOutput, onReconnect, onChooseOutput, onToggleFit, onToggleMute }: {
  videoRef: RefObject<HTMLVideoElement | null>; muted: boolean; fit: "cover" | "contain"; status: string | null; previewStatus: string; mediaReady: boolean; canChooseOutput: boolean;
  onReconnect: () => void; onChooseOutput: () => void; onToggleFit: () => void; onToggleMute: () => void;
}) {
  const live = status === "LIVE" || status === "DEGRADED";
  const session = lookSession(status);
  const media = previewLook[previewStatus] ?? { label: previewStatus, tone: "neutral" as Tone };
  const busy = previewStatus === "connecting" || previewStatus === "recovering";
  return (
    <div className={cn("group relative aspect-video w-full overflow-hidden rounded-xl border bg-[#07080d] shadow-raised", live ? "border-live/35" : "border-border")}>
      <video ref={videoRef} autoPlay playsInline muted={muted} aria-label="WebRTC 实时画面"
        className={cn("absolute inset-0 h-full w-full object-center", fit === "cover" ? "object-cover" : "object-contain")} />
      {previewStatus === "idle" && (
        <div className="absolute inset-0 grid place-items-center bg-[radial-gradient(60%_60%_at_50%_40%,color-mix(in_oklab,var(--brand)_22%,transparent),transparent)]">
          <div className="flex flex-col items-center gap-3 text-center text-white/80">
            <span className="grid size-14 place-items-center rounded-full border border-white/10 bg-white/5"><MonitorPlay className="size-6" /></span>
            <span className="text-title text-white">等待直播开始</span>
            <span className="text-caption text-white/55">开播后此处显示数字人实时画面</span>
          </div>
        </div>
      )}
      {busy && (
        <div className="absolute inset-0 grid place-items-center bg-black/35">
          <span className={cn("flex items-center gap-2 rounded-full px-3 py-1.5 text-caption", glass)}><Loader2 className="size-3.5 animate-spin" />{previewStatus === "recovering" ? "音频恢复中…" : "正在建立 WebRTC 连接…"}</span>
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-2 bg-gradient-to-b from-black/55 to-transparent p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-2">
          {live ? (
            <span className="flex items-center gap-1.5 rounded-md bg-live-solid px-2 py-1 text-[11px] font-bold tracking-wider text-white shadow-[0_0_24px_-4px_var(--live)]">
              <StatusDot tone="neutral" ping className="bg-white" />LIVE
            </span>
          ) : (
            <span className={cn("flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium", glass)}><StatusDot tone={status ? session.tone : "neutral"} pulse={session.pulse} />{status ? session.label : "未开播"}</span>
          )}
          {status === "DEGRADED" && <span className={cn("rounded-md px-2 py-1 text-[11px] text-warn", glass)}>降级运行</span>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className={cn("flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px]", glass)} title="浏览器 WebRTC 预览连接">
            <StatusDot tone={media.tone} pulse={media.pulse} />画面 · {media.label}
          </span>
          {mediaReady && <span className={cn("hidden rounded-md px-2 py-1 text-[11px] text-white/80 sm:inline", glass)}>已收到 ready 事件</span>}
        </div>
      </div>
      <div className="absolute inset-x-0 bottom-0 flex flex-wrap items-center justify-end gap-1.5 bg-gradient-to-t from-black/60 to-transparent p-3 opacity-100 transition-opacity duration-200 sm:p-4 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
        {previewStatus === "failed" && <Button size="sm" className={glass} variant="ghost" onClick={onReconnect}><RefreshCw className="size-3.5" />重新连接预览</Button>}
        {canChooseOutput && <Button size="sm" className={glass} variant="ghost" onClick={onChooseOutput}><Speaker className="size-3.5" />音频输出</Button>}
        <Button size="sm" className={glass} variant="ghost" aria-pressed={fit === "cover"} onClick={onToggleFit}>
          {fit === "cover" ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}{fit === "cover" ? "完整画面" : "铺满画面"}
        </Button>
        <Button size="sm" className={glass} variant="ghost" onClick={onToggleMute}>{muted ? <VolumeX className="size-3.5" /> : <Volume2 className="size-3.5" />}{muted ? "取消静音" : "静音"}</Button>
      </div>
    </div>
  );
}

function MetricCard({ icon, label, value, unit, hint, tone = "brand" }: { icon: ReactNode; label: string; value: number | null; unit?: string; hint?: ReactNode; tone?: "brand" | "live" | "ok" | "info" | "warn" }) {
  const tones = { brand: "text-brand bg-brand-soft", live: "text-live bg-live-soft", ok: "text-ok bg-ok-soft", info: "text-info bg-info-soft", warn: "text-warn bg-warn-soft" };
  return (
    <div className="relative min-w-0 overflow-hidden rounded-lg border border-border bg-surface p-3.5 shadow-card">
      <div className="flex items-center gap-2 text-caption text-fg-muted">
        <span className={cn("grid size-6 place-items-center rounded-md [&_svg]:size-3.5", tones[tone])}>{icon}</span>
        <span className="truncate">{label}</span>
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        {value === null ? <span className="text-title text-fg-subtle">—</span> : <AnimatedNumber value={value} className="text-[1.625rem] leading-8 font-semibold tracking-tight tabular text-fg" />}
        {unit && value !== null && <span className="text-caption text-fg-subtle">{unit}</span>}
      </div>
      {hint && <p className="mt-0.5 truncate text-[11px] text-fg-subtle">{hint}</p>}
    </div>
  );
}

/** Metric strip. Latency is the scheduler's comment→selection boundary only, never end-to-end speech latency. */
export function MetricsStrip({ snapshot, speechQueue, completed }: { snapshot: Snapshot | undefined; speechQueue: number; completed: number }) {
  const enough = !!snapshot && snapshot.latency.samples >= 20;
  const n = snapshot?.latency.samples ?? 0;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(7.25rem,1fr))]">
      <MetricCard icon={<Zap />} label="选中 P50" value={enough ? snapshot.latency.p50Ms : null} unit="ms" hint={enough ? `评论→选中 · 均值 ${snapshot.latency.meanMs.toFixed(0)}ms` : `样本不足 · n=${n}`} />
      <MetricCard icon={<Gauge />} label="选中 P95" value={enough ? snapshot.latency.p95Ms : null} unit="ms" tone="info" hint={enough ? `最大 ${snapshot.latency.maxMs.toFixed(0)}ms · n=${n}` : "至少 20 个样本"} />
      <MetricCard icon={<ListOrdered />} label="语音队列" value={speechQueue} tone={speechQueue > 0 ? "live" : "ok"} hint="未结束发言" />
      <MetricCard icon={<Activity />} label="候选弹幕" value={snapshot ? snapshot.candidates : null} tone="warn" hint={snapshot ? `峰值 ${snapshot.counters.peak}` : "直播后统计"} />
      <MetricCard icon={<Send />} label="已完成发言" value={completed} tone="ok" hint={snapshot ? `投递 ${snapshot.counters.delivered} · 失败 ${snapshot.counters.failed}` : "本次会话"} />
    </div>
  );
}

const terminal = ["COMPLETED", "INTERRUPTED", "CANCELLED", "FAILED"];
function Stepper({ status }: { status: TimelineItem["status"] }) {
  const index = utteranceSteps.findIndex(s => s.key === status);
  const broken = index < 0;
  return (
    <ol className="mt-2.5 flex items-center gap-1" aria-label="状态流转">
      {utteranceSteps.map((step, i) => {
        const done = !broken && i < index;
        const current = !broken && i === index;
        const finished = current && status === "COMPLETED";
        return (
          <li key={step.key} className="flex min-w-0 flex-1 flex-col gap-1" aria-current={current ? "step" : undefined}>
            <span className={cn(
              "h-1 rounded-full transition-colors duration-300",
              broken ? "bg-surface-3" : done || finished ? "bg-ok/80" : current ? (status === "PLAYING" ? "bg-live" : "bg-brand") : "bg-surface-3",
              current && !finished && "motion-safe:animate-breathe",
            )} />
            <span className={cn("truncate text-[10px]", current ? "font-medium text-fg" : done ? "text-fg-muted" : "text-fg-subtle")}>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function UtteranceTimeline({ items }: { items: TimelineItem[] }) {
  if (items.length === 0) return <EmptyState compact icon={Clock3} title="暂无发言事件" description="弹幕被选中或手动发言后，每条发言的状态会在这里流转。" />;
  return (
    <ol className="space-y-2">
      <AnimatePresence initial={false}>
        {items.map(t => {
          const look = utteranceLook[t.status];
          const active = !terminal.includes(t.status);
          return (
            <m.li key={t.utteranceId} layout="position" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.22 }}
              className={cn("rounded-lg border p-3 transition-colors", active ? "border-brand/30 bg-brand-soft/40" : "border-border bg-surface-2/40")}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0 flex-1 break-words text-body text-fg">{t.text ?? t.utteranceId}</p>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={look.tone}><StatusDot tone={look.tone} pulse={look.pulse} ping={look.ping} />{look.label}</Badge>
                </div>
              </div>
              <Stepper status={t.status} />
              <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-fg-subtle">
                <span className="font-mono text-fg-muted">{t.status}</span>
                <span>{new Date(t.occurredAt).toLocaleTimeString()}</span>
                {t.priority !== undefined && <span>优先级 {t.priority}</span>}
                <span className="truncate font-mono">{t.utteranceId}</span>
              </p>
            </m.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}

const eventLabels: Record<EventName, string> = {
  "session.preparing": "会话准备中", "session.ready": "会话就绪", "session.live": "进入直播", "session.degraded": "降级运行", "session.ended": "会话结束", "session.failed": "会话失败",
  "utterance.queued": "发言排队", "utterance.generating": "生成回答", "utterance.synthesizing": "合成语音", "utterance.rendering": "渲染画面", "utterance.playing": "开始播放",
  "utterance.completed": "播放完成", "utterance.interrupted": "发言被打断", "utterance.failed": "发言失败", "media.ready": "媒体就绪", "runtime.warning": "运行告警", "runtime.error": "运行错误",
};
function eventTone(name: EventName): Tone {
  if (name === "runtime.error" || name.endsWith(".failed")) return "danger";
  if (name === "runtime.warning" || name === "session.degraded" || name === "utterance.interrupted") return "warn";
  if (name === "session.live" || name === "utterance.playing") return "live";
  if (name === "utterance.completed" || name === "media.ready" || name === "session.ready") return "ok";
  return "neutral";
}
export function EventFeed({ events }: { events: { name: EventName; event: RuntimeEvent }[] }) {
  if (events.length === 0) return <p className="py-2 text-caption text-fg-subtle">暂无事件</p>;
  return (
    <ol className="max-h-72 space-y-0.5 overflow-y-auto pr-1">
      {events.map(({ name, event }) => (
        <li key={event.eventId} className="flex items-center gap-2.5 rounded-md px-1.5 py-1.5 text-caption hover:bg-surface-2">
          <StatusDot tone={eventTone(name)} />
          <span className="min-w-0 flex-1 truncate text-fg">{eventLabels[name]}<span className="ml-2 font-mono text-[11px] text-fg-subtle">{name}</span></span>
          <time className="shrink-0 tabular text-fg-subtle">{new Date(event.occurredAt).toLocaleTimeString()}</time>
        </li>
      ))}
    </ol>
  );
}
