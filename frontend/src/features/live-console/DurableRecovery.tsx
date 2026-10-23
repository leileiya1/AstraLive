import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, key, type DurableDecision } from "../../api/client";
import { ErrorNotice } from "../../components/feedback";
import { Button } from "../../components/ui/button";
import { Card, CardHeader } from "../../components/ui/card";
import { Field, Input, Select } from "../../components/ui/input";
import { TurnManagerPanel } from "./TurnManagerPanel";

// Recovery controls are independent of LIVE admission. They use the existing
// authenticated cookie API and never receive an internal service credential.
export function DurableRecovery({ sessionId }: { sessionId: string }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["durable", sessionId], queryFn: () => api.durableSession(sessionId), refetchInterval: 2000, retry: false });
  const [review, setReview] = useState(false);
  const [attemptId, setAttempt] = useState("");
  const [action, setAction] = useState<DurableDecision["action"]>("WAIT_FOR_EVIDENCE");
  const [reason, setReason] = useState("");
  const draft = useRef<DurableDecision | null>(null);
  const stopId = useRef<string | null>(null);
  const data = query.data?.managed ? query.data : null;
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["durable", sessionId] }); };
  const resolve = useMutation({
    mutationFn: () => {
      if (!data) throw new Error("Recovery state unavailable");
      // Keep the entire original decision on an ambiguous HTTP error. A retry
      // cannot silently choose a new identity, revision or creation timestamp.
      draft.current ??= { decisionId: key(), attemptId, expectedRevision: data.snapshot.run.revision, action, reason, createdAt: new Date().toISOString() };
      return api.resolveDurable(data.snapshot.run.runId, draft.current);
    },
    onSuccess: refresh,
  });
  const stop = useMutation({ mutationFn: () => { stopId.current ??= key(); return api.stopDurable(data!.snapshot.run.runId, stopId.current); }, onSuccess: refresh });
  if (query.error) return <ErrorNotice error={query.error} />;
  if (!data) return null;
  const s = data.snapshot;
  const stopped = s.run.stopRevision > 0 || ["STOPPING", "STOPPED", "FAILED"].includes(s.run.status);
  const unknown = s.unresolvedAttempts.filter(a => a.lastCheckpoint === "UNKNOWN");
  const current = s.bundle?.segments.find(segment => segment.state === "ACTIVE");
  const next = s.bundle?.segments.find(segment => segment.sequence === s.resumeSequence && segment.state === "READY");
  const changed = () => { draft.current = null; resolve.reset(); };
  return <>
    <TurnManagerPanel view={{ state: data.choice.state, source: data.choice.source, plan: s.bundle?.plan ?? null, completedPrefix: s.completedPrefix, pendingComments: data.choice.pending, currentSegment: current ?? null, nextSegment: next ?? null, hasUnknown: unknown.length > 0, reason: data.choice.reason }} onReviewRecovery={() => setReview(true)} />
    {review && <Card className="space-y-3 p-4">
      <CardHeader as="h3" className="mb-0" title="人工处理播放状态" />
      <p className="text-caption text-fg-muted">跳过会留下未播放确认的缺口，不计为成功播出。登记新话轮意图后仍须独立授权，系统不会自动重播。</p>
      <p className="text-caption text-fg-subtle">当前自动开播与恢复开播尚未开放。</p>
      <Field label="待处理任务"><Select aria-label="待处理任务" value={attemptId} disabled={stopped || resolve.isPending} onChange={e => { setAttempt(e.target.value); changed(); }}>
        <option value="">请选择不确定任务</option>{unknown.map(a => <option key={a.attemptId} value={a.attemptId}>{a.attemptId}</option>)}
      </Select></Field>
      <Field label="处理方式"><Select aria-label="处理方式" value={action} disabled={stopped || resolve.isPending} onChange={e => { setAction(e.target.value as DurableDecision["action"]); changed(); }}>
        <option value="WAIT_FOR_EVIDENCE">等待证据</option><option value="SKIP_WITH_GAP">跳过并记录缺口</option><option value="CREATE_NEW_TURN">登记新话轮意图</option>
      </Select></Field>
      <Field label="处理原因"><Input aria-label="处理原因" maxLength={2000} value={reason} disabled={stopped || resolve.isPending} onChange={e => { setReason(e.target.value); changed(); }} /></Field>
      <Button disabled={stopped || !attemptId || !reason.trim() || resolve.isPending || resolve.isSuccess} onClick={() => resolve.mutate()}>提交处理决定</Button>
      <Button variant="danger" className="ml-2" disabled={stopped || stop.isPending} onClick={() => stop.mutate()}>停止此直播计划</Button>
      {resolve.isSuccess && <p role="status" className="text-caption text-ok">决定已记录，未授权新的口播。</p>}
      {resolve.error && <ErrorNotice error={resolve.error} />}{stop.error && <ErrorNotice error={stop.error} />}
      {s.decisions.length > 0 && <ul className="space-y-1 text-caption text-fg-muted">{s.decisions.map(d => <li key={d.decisionId}>{d.action} · {d.reason}</li>)}</ul>}
    </Card>}
  </>;
}
