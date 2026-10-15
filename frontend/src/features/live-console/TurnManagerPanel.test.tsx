import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TurnManagerPanel, type TurnManagerView } from "./TurnManagerPanel";
afterEach(cleanup);
const view: TurnManagerView = {
  state: "YIELD_PENDING", plan: { planId: "plan-1", revision: 1, productId: "product-1" },
  currentSegment: { sequence: 1, content: "采用纯棉面料。" }, nextSegment: { sequence: 2, content: "穿着舒适。" },
  source: "SCRIPT", pendingComments: 2, completedPrefix: 0, hasUnknown: false,
};
describe("TurnManagerPanel", () => {
  it("shows a natural boundary wait and both segments", () => {
    render(<TurnManagerPanel view={view} onReviewRecovery={vi.fn()} />);
    expect(screen.getByText("等待当前段自然结束")).toBeInTheDocument();
    expect(screen.getByText("1 · 采用纯棉面料。")).toBeInTheDocument();
    expect(screen.getByText("2 · 穿着舒适。")).toBeInTheDocument();
  });
  it("requires explicit review of unknown content", () => {
    const review = vi.fn();
    render(<TurnManagerPanel view={{ ...view, state: "RECOVERING", hasUnknown: true }} onReviewRecovery={review} />);
    expect(screen.getByRole("alert")).toHaveTextContent("暂停续讲");
    fireEvent.click(screen.getByRole("button", { name: "检查并人工恢复" }));
    expect(review).toHaveBeenCalledTimes(1);
  });
  it("cannot resume a stopped run", () => {
    const review = vi.fn();
    render(<TurnManagerPanel view={{ ...view, state: "STOPPED", hasUnknown: true }} onReviewRecovery={review} />);
    expect(screen.getByRole("button", { name: "检查并人工恢复" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button")); expect(review).not.toHaveBeenCalled();
  });
});
