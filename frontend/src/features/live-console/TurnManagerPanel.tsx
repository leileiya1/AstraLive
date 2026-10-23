import { Bot } from "lucide-react";
import { Card, CardHeader } from "../../components/ui/card";
import { Button } from "../../components/ui/button";

export type TurnManagerView = {
  state: "IDLE" | "EXPLAINING" | "YIELD_PENDING" | "ANSWERING" | "RESUMING" | "OPERATOR_OVERRIDE" | "RECOVERING" | "STOPPED";
  plan: { planId: string; revision: number; productId: string } | null;
  currentSegment: { sequence: number; content: string } | null;
  nextSegment: { sequence: number; content: string } | null;
  source: string;
  pendingComments: number;
  completedPrefix: number;
  reason?: string;
  hasUnknown: boolean;
};

// Agent 4 mounts this in the existing authenticated Session console after its
// authorized server projection is wired. No browser-facing internal RPC/token,
// Runtime queue control, speculative API route, or local progress authority.
export function TurnManagerPanel({ view, onReviewRecovery, busy = false }: {
  view: TurnManagerView;
  onReviewRecovery: () => void;
  busy?: boolean;
}) {
  const labels: Record<TurnManagerView["state"], string> = {
    IDLE: "等待有效任务", EXPLAINING: "商品讲解中", YIELD_PENDING: "等待当前段自然结束",
    ANSWERING: "回答观众", RESUMING: "正在续讲", OPERATOR_OVERRIDE: "操作员接管",
    RECOVERING: "等待恢复确认", STOPPED: "已停止自动讲解",
  };
  const needsReview = view.hasUnknown || view.state === "RECOVERING" || view.state === "OPERATOR_OVERRIDE";
  return <Card className="p-4">
    <CardHeader as="h3" className="mb-3" icon={<Bot />} title="自动场控" actions={<p role="status" className="rounded-full border border-brand/25 bg-brand-soft px-2 py-0.5 text-caption font-medium text-brand">{labels[view.state]}</p>} />
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-caption [&_dt]:text-fg-subtle [&_dd]:text-fg">
      <dt>当前计划</dt><dd className="break-all">{view.plan ? `${view.plan.planId} · v${view.plan.revision}` : "尚无计划"}</dd>
      <dt>当前商品</dt><dd>{view.plan?.productId ?? "—"}</dd>
      <dt>讲话来源</dt><dd>{({ SCRIPT: "商品讲解", COMMENT: "观众问题", OPERATOR: "操作员", SYSTEM: "系统" } as Record<string, string>)[view.source] ?? "空闲"}</dd>
      <dt>已确认进度</dt><dd>连续完成 {view.completedPrefix} 段</dd>
      <dt>待回复弹幕</dt><dd>{view.pendingComments}</dd>
      <dt>当前段</dt><dd>{view.currentSegment ? `${view.currentSegment.sequence} · ${view.currentSegment.content}` : "—"}</dd>
      <dt>下一段</dt><dd>{view.nextSegment ? `${view.nextSegment.sequence} · ${view.nextSegment.content}` : "—"}</dd>
    </dl>
    {view.hasUnknown && <p role="alert" className="mt-3 rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-caption text-warn">部分内容是否播放完成尚不确定，已暂停续讲。请先检查证据并选择恢复方式。</p>}
    {view.reason && <p className="mt-2 break-words text-caption text-warn">场控提示：{view.reason}</p>}
    {needsReview && <Button className="mt-3" variant="outline" disabled={busy || view.state === "STOPPED"} onClick={onReviewRecovery}>检查并人工恢复</Button>}
  </Card>;
}
