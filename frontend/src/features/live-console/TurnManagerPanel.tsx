import { Card } from "../../components/ui/card";
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
  return <Card>
    <h2 className="font-semibold">自动场控</h2>
    <p role="status" className="mt-2 text-sm">{labels[view.state]}</p>
    <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
      <dt>当前计划</dt><dd className="break-all">{view.plan ? `${view.plan.planId} · v${view.plan.revision}` : "尚无计划"}</dd>
      <dt>当前商品</dt><dd>{view.plan?.productId ?? "—"}</dd>
      <dt>讲话来源</dt><dd>{({ SCRIPT: "商品讲解", COMMENT: "观众问题", OPERATOR: "操作员", SYSTEM: "系统" } as Record<string, string>)[view.source] ?? "空闲"}</dd>
      <dt>已确认进度</dt><dd>连续完成 {view.completedPrefix} 段</dd>
      <dt>待回复弹幕</dt><dd>{view.pendingComments}</dd>
      <dt>当前段</dt><dd>{view.currentSegment ? `${view.currentSegment.sequence} · ${view.currentSegment.content}` : "—"}</dd>
      <dt>下一段</dt><dd>{view.nextSegment ? `${view.nextSegment.sequence} · ${view.nextSegment.content}` : "—"}</dd>
    </dl>
    {view.hasUnknown && <p role="alert" className="mt-3 text-sm text-amber-700">部分内容是否播放完成尚不确定，已暂停续讲。请先检查证据并选择恢复方式。</p>}
    {view.reason && <p className="mt-2 break-words text-sm text-amber-700">场控提示：{view.reason}</p>}
    {needsReview && <Button className="mt-3" disabled={busy || view.state === "STOPPED"} onClick={onReviewRecovery}>检查并人工恢复</Button>}
  </Card>;
}
