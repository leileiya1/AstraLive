import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, Bug, Hand, ListTree, Mic, Play, Plus, ScrollText, Square } from "lucide-react";
import { api, ApiError } from "../../api/client";
import { ErrorNotice } from "../../components/feedback";
import { Badge, StatusDot } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardHeader } from "../../components/ui/card";
import { CollapsibleCard } from "../../components/ui/collapsible";
import { ConfirmDialog } from "../../components/ui/confirm-dialog";
import { Field, Input, Select, Textarea } from "../../components/ui/input";
import { PageHeader } from "../../components/ui/page-header";
import { useLiveSessionEvents } from "../../hooks/useLiveSessionEvents";
import { useLivePreview } from "../../hooks/useLivePreview";
import { eventsLook, lookSession, utteranceLook } from "../../lib/status";
import { TurnManagerPanel, type TurnManagerView } from "./TurnManagerPanel";
import { DurableRecovery } from "./DurableRecovery";
import { InteractionPanel, useInteractionSnapshot } from "./InteractionPanel";
import { ProviderStatus } from "./ProviderStatus";
import { EventFeed, MetricsStrip, UtteranceTimeline, VideoStage } from "./Cockpit";
import { useUi } from "../../stores/ui";
function PreviewError({ error }: { error: unknown }) {
  if (error instanceof ApiError) return <ErrorNotice error={error} />;
  return (
    <p
      role="alert"
      className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 text-body text-danger"
    >
      浏览器预览连接失败。请检查浏览器是否允许
      WebRTC、网络及音频输出，再重新连接预览。服务端 ready
      事件不代表浏览器已开始播放。
    </p>
  );
}
const ended = ["COMPLETED", "INTERRUPTED", "CANCELLED", "FAILED"];
// Desktop: two independent columns (video, metrics, composer, timeline | session,
// danmaku, side panels). Below xl the wrappers become `contents` and `order`
// interleaves the same blocks into one reading-order column.
const col = "contents xl:flex xl:min-w-0 xl:flex-col xl:gap-5";
export function LiveConsole({
  roomId,
  sessionId,
  onSession,
  turnManager,
}: {
  roomId: string | null;
  sessionId: string | null;
  onSession: (id: string) => void;
  turnManager?: { view: TurnManagerView; onReviewRecovery: () => void; busy?: boolean };
}) {
  const qc = useQueryClient();
  const room = useQuery({
    queryKey: ["room-list"],
    queryFn: api.rooms,
    enabled: !!roomId,
  });
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.session(sessionId!),
    enabled: !!sessionId,
    refetchInterval: 10000,
  });
  const { state, connection } = useLiveSessionEvents(sessionId);
  const muted = useUi((s) => s.muted);
  const setMuted = useUi((s) => s.setMuted);
  const setLiveStatus = useUi((s) => s.setLiveStatus);
  const [text, setText] = useState("");
  const [priority, setPriority] = useState(100);
  const [policy, setPolicy] = useState<
    "NONE" | "INTERRUPT_LOWER_PRIORITY" | "FORCE"
  >("NONE");
  const [comment, setComment] = useState("");
  const [nickname, setNickname] = useState("测试用户");
  const [pendingStart, setPendingStart] = useState(false);
  const [fit, setFit] = useState<"cover" | "contain">("cover");
  const create = useMutation({
    mutationFn: () => api.createSession({ roomId: roomId! }),
    onSuccess: (s) => {
      onSession(s.sessionId);
      void qc.invalidateQueries({ queryKey: ["session", s.sessionId] });
    },
  });
  const start = useMutation({
    mutationFn: () => api.startSession(sessionId!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["session", sessionId] });
    },
    onError: () => setPendingStart(false),
  });
  const stop = useMutation({
    mutationFn: () => api.stopSession(sessionId!),
    onSuccess: () =>
      void qc.invalidateQueries({ queryKey: ["session", sessionId] }),
  });
  const speak = useMutation({
    mutationFn: () =>
      api.speak(sessionId!, {
        text: text.trim(),
        priority,
        interruptPolicy: policy,
        source: "OPERATOR",
      }),
    onSuccess: () => setText(""),
  });
  const interrupt = useMutation({
    mutationFn: () =>
      api.interrupt(sessionId!, { reason: "OPERATOR_INTERRUPT" }),
  });
  const dev = useMutation({
    mutationFn: () =>
      api.devEvent({
        eventType: "COMMENT",
        roomId: roomId!,
        user: { externalId: "mock-user-01", nickname: nickname.trim() },
        payload: { text: comment.trim() },
      }),
    onSuccess: () => setComment(""),
  });
  const shownStatus =
    state.sessionStatus ??
    (pendingStart ? "PREPARING" : (session.data?.status ?? null));
  const {
    videoRef,
    status: previewStatus,
    error: previewError,
    chooseOutput,
    canChooseOutput,
    reconnect,
  } = useLivePreview(
    ["LIVE", "DEGRADED"].includes(shownStatus ?? "") ? sessionId : null,
  );
  useEffect(() => {
    if (["LIVE", "FAILED", "ENDED"].includes(state.sessionStatus ?? ""))
      setPendingStart(false);
  }, [state.sessionStatus]);
  useEffect(() => {
    if (sessionId && shownStatus) setLiveStatus({ sessionId, status: shownStatus });
  }, [sessionId, shownStatus, setLiveStatus]);
  const active = state.timeline.find(
    (t) =>
      !["COMPLETED", "INTERRUPTED", "CANCELLED", "FAILED"].includes(t.status),
  );
  const roomData = room.data?.find((r) => r.roomId === roomId);
  const running = ["LIVE", "DEGRADED"].includes(shownStatus ?? "");
  const speechQueue = state.timeline.filter(t => !ended.includes(t.status)).length;
  const snapshot = useInteractionSnapshot(sessionId);
  const look = lookSession(shownStatus);
  const events = eventsLook[connection] ?? eventsLook.idle;
  return (
    <div className="space-y-5">
      <PageHeader
        title="直播控制台"
        description={roomData?.name ?? roomId ?? "未选择直播间，请先在「直播间」中进入控制台"}
        actions={<>
          {!sessionId && (
            <Button
              size="lg"
              disabled={!roomId || create.isPending}
              loading={create.isPending}
              onClick={() => create.mutate()}
            >
              {!create.isPending && <Plus className="size-4" />}创建会话
            </Button>
          )}
          {sessionId && (
            <Button
              size="lg"
              disabled={
                start.isPending ||
                pendingStart ||
                !["CREATED", "READY"].includes(shownStatus ?? "")
              }
              loading={start.isPending || pendingStart}
              onClick={() => {
                setPendingStart(true);
                start.mutate();
              }}
            >
              {!(start.isPending || pendingStart) && <Play className="size-4" />}开始直播
            </Button>
          )}
          <ConfirmDialog
            title="停止当前直播？"
            description="数字人会停止输出画面和语音，观众端会断开。此操作不能撤销，需要重新创建会话才能再次开播。"
            confirmLabel="停止直播"
            onConfirm={() => stop.mutate()}
          >
            <Button
              size="lg"
              variant="danger"
              disabled={
                !sessionId ||
                stop.isPending ||
                !["LIVE", "DEGRADED"].includes(shownStatus ?? "")
              }
              loading={stop.isPending}
            >
              {!stop.isPending && <Square className="size-3.5 fill-current" />}停止直播
            </Button>
          </ConfirmDialog>
        </>}
      />
      {[create.error, start.error, stop.error].filter(Boolean).map((e, i) => (
        <ErrorNotice key={i} error={e} />
      ))}
      <div className="flex flex-col gap-4 xl:grid xl:grid-cols-[minmax(0,1fr)_minmax(340px,400px)] xl:items-start xl:gap-5">
        <div className={col}>
        <div className="order-1 min-w-0 space-y-3">
          <VideoStage
            videoRef={videoRef}
            muted={muted}
            fit={fit}
            status={shownStatus}
            previewStatus={previewStatus}
            mediaReady={state.mediaReady}
            canChooseOutput={canChooseOutput}
            onReconnect={reconnect}
            onChooseOutput={() => void chooseOutput()}
            onToggleFit={() => setFit(fit === "cover" ? "contain" : "cover")}
            onToggleMute={() => setMuted(!muted)}
          />
          {previewError != null && <PreviewError error={previewError} />}
        </div>
        <div className="order-2 min-w-0">
          <MetricsStrip snapshot={snapshot} speechQueue={speechQueue} completed={state.timeline.filter(t => t.status === "COMPLETED").length} />
        </div>
        <Card className="order-5 min-w-0">
          <CardHeader icon={<Mic />} title="运营发言" description="以操作员身份插入一条口播，按优先级和打断策略进入语音队列。" />
          <form
            className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem_13rem]"
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim()) speak.mutate();
            }}
          >
            <Field label="发言内容" className="sm:col-span-3">
              <Textarea
                aria-label="发言内容"
                placeholder="欢迎大家来到直播间"
                value={text}
                onChange={(e) => setText(e.target.value)}
                required
                className="min-h-16"
              />
            </Field>
            <Field label="优先级" className="sm:col-start-2">
              <Input
                aria-label="优先级"
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
              />
            </Field>
            <Field label="打断策略">
              <Select
                aria-label="打断策略"
                value={policy}
                onChange={(e) => setPolicy(e.target.value as typeof policy)}
              >
                <option value="NONE">不打断</option>
                <option value="INTERRUPT_LOWER_PRIORITY">
                  打断低优先级
                </option>
                <option value="FORCE">强制打断</option>
              </Select>
            </Field>
            <div className="flex flex-wrap items-center gap-2 sm:row-start-2 sm:col-start-1 sm:self-end">
              <Button
                disabled={
                  !sessionId ||
                  speak.isPending ||
                  !["LIVE", "DEGRADED"].includes(shownStatus ?? "")
                }
                loading={speak.isPending}
              >
                发言
              </Button>
              <Button
                type="button"
                variant="outline"
                className="hover:border-danger/50 hover:text-danger"
                disabled={!sessionId || interrupt.isPending || !active}
                onClick={() => interrupt.mutate()}
              >
                <Hand className="size-4" />打断当前发言
              </Button>
            </div>
          </form>
          <p className="mt-3 flex min-w-0 flex-wrap items-center gap-2 text-caption text-fg-subtle">
            当前：
            {active
              ? <><Badge tone={utteranceLook[active.status].tone}>{utteranceLook[active.status].label}</Badge><span className="truncate font-mono">{`${active.utteranceId} · priority ${active.priority ?? "—"} · ${active.status}`}</span></>
              : "—"}
          </p>
          {(speak.error || interrupt.error) && <div className="mt-3 space-y-2">
            {speak.error && <ErrorNotice error={speak.error} />}
            {interrupt.error && <ErrorNotice error={interrupt.error} />}
          </div>}
        </Card>
        <Card className="order-6 min-w-0">
          <CardHeader icon={<ListTree />} title="发言时间线" description="排队 → 生成 → 合成 → 渲染 → 播放 → 完成"
            actions={speechQueue > 0 ? <Badge tone="live"><StatusDot tone="live" ping />进行中 {speechQueue}</Badge> : undefined} />
          <UtteranceTimeline items={state.timeline} />
        </Card>
        </div>
        <div className={col}>
        <Card className="order-3 min-w-0 p-4 sm:p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="text-caption text-fg-muted">会话状态</span>
            </div>
            <Badge tone={events.tone} title="Runtime 事件流（SSE）"><StatusDot tone={events.tone} pulse={events.pulse} />事件流 · {events.label}</Badge>
          </div>
          <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-body">
            <dt className="text-fg-subtle">状态</dt>
            <dd data-testid="session-status" data-status={shownStatus ?? ""} className="flex flex-wrap items-center gap-2">
              <Badge tone={shownStatus ? look.tone : "neutral"}><StatusDot tone={shownStatus ? look.tone : "neutral"} pulse={look.pulse} ping={look.ping} />{shownStatus ? look.label : "未创建"}</Badge>
              <span className="font-mono text-[11px] text-fg-subtle">{shownStatus ?? "—"}</span>
            </dd>
            <dt className="text-fg-subtle">会话</dt>
            <dd className="truncate font-mono text-caption text-fg-muted" title={sessionId ?? undefined}>{sessionId ?? "—"}</dd>
            <dt className="text-fg-subtle">数字人</dt>
            <dd className="truncate font-mono text-caption text-fg-muted">{roomData?.avatarId ?? "—"}</dd>
            <dt className="text-fg-subtle">音色</dt>
            <dd className="truncate font-mono text-caption text-fg-muted">{roomData?.voiceId ?? "—"}</dd>
            <dt className="text-fg-subtle">帧率 / 延迟</dt>
            <dd className="text-caption text-fg-subtle">未提供指标</dd>
          </dl>
          {session.error && (
            <div className="mt-3">
              <ErrorNotice
                error={session.error}
                retry={() => void session.refetch()}
              />
            </div>
          )}
        </Card>
        <InteractionPanel className="order-4" sessionId={sessionId} running={running} speechQueue={speechQueue} />
        <div className="order-7 min-w-0 space-y-4">
          <CollapsibleCard
            defaultOpen
            icon={<AlertOctagon />}
            title="运行错误"
            meta={<Badge tone={state.errors.length ? "danger" : "neutral"}>{state.errors.length}</Badge>}
          >
            {state.errors.length === 0 ? (
              <p className="py-1 text-caption text-fg-subtle">暂无错误</p>
            ) : (
              <div className="space-y-2">
                {state.errors.map((e) => (
                  <p
                    key={e.eventId}
                    role="alert"
                    className="break-words rounded-md border border-danger/25 bg-danger-soft px-3 py-2 text-caption text-danger"
                  >
                    {typeof e.payload.message === "string"
                      ? e.payload.message
                      : e.eventType}{" "}
                    · <span className="font-mono opacity-75">{e.traceId}</span>
                  </p>
                ))}
              </div>
            )}
          </CollapsibleCard>
          <CollapsibleCard icon={<ScrollText />} title="事件流" meta={<span className="text-caption tabular text-fg-subtle">{state.events.length}</span>}>
            <EventFeed events={state.events} />
          </CollapsibleCard>
          <ProviderStatus sessionId={sessionId} />
          {turnManager && <TurnManagerPanel {...turnManager} />}
          {sessionId && import.meta.env.VITE_DURABLE_RECOVERY_ENABLED === "true" && <DurableRecovery sessionId={sessionId} />}
          {import.meta.env.DEV &&
            import.meta.env.VITE_ENABLE_DEV_PLATFORM_EVENTS === "true" && (
              <Card className="border-dashed p-4">
                <CardHeader as="h3" icon={<Bug />} className="mb-3" title="开发面板 · 模拟弹幕" description="经 /dev/platform-events 投递 COMMENT 事件" />
                <form
                  className="flex flex-wrap gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (roomId && comment.trim()) dev.mutate();
                  }}
                >
                  <Input
                    aria-label="昵称"
                    value={nickname}
                    onChange={(e) => setNickname(e.target.value)}
                    required
                    className="max-w-28"
                  />
                  <Input
                    aria-label="模拟弹幕"
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    required
                    placeholder="有 XL 吗？"
                    className="min-w-32 flex-1"
                  />
                  <Button disabled={!roomId || dev.isPending} loading={dev.isPending}>发送</Button>
                </form>
                {dev.isSuccess && dev.data && (
                  <p role="status" className="mt-2 break-all text-caption text-ok">
                    COMMENT 已接受 · {dev.data.utteranceId} · {dev.data.status}
                    ；等待 SSE 更新
                  </p>
                )}
                {dev.error && <div className="mt-2"><ErrorNotice error={dev.error} /></div>}
              </Card>
            )}
        </div>
        </div>
      </div>
    </div>
  );
}
