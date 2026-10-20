import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DurableSession } from "../../api/client";
import { DurableRecovery } from "./DurableRecovery";
vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), api: { durableSession: vi.fn(), resolveDurable: vi.fn(), stopDurable: vi.fn() }, key: () => "decision-stable" }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const state: DurableSession = { managed: true, snapshot: { run: { runId: "run", revision: 9, status: "RECOVERING", desiredState: "LIVE", stopRevision: 0 }, completedPrefix: 0, resumeSequence: 1, bundle: null, unresolvedAttempts: [{ attemptId: "unknown-attempt", commandId: "command", lastCheckpoint: "UNKNOWN" }], decisions: [] }, choice: { state: "RECOVERING", source: "", pending: 2 }, releaseGate: "OUTPUT_FENCE_UNPROVEN" };
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><DurableRecovery sessionId="session" /></QueryClientProvider>); }
describe("DurableRecovery", () => {
 it("keeps the same decision identity, revision and body after a lost ACK", async () => {
  vi.mocked(api.durableSession).mockResolvedValue(state);
  vi.mocked(api.resolveDurable).mockRejectedValueOnce(new Error("lost ACK")).mockResolvedValueOnce({ decisionId: "decision-stable", action: "WAIT_FOR_EVIDENCE", mediaAuthorized: false });
  mount(); fireEvent.click(await screen.findByRole("button", { name: "检查并人工恢复" }));
  fireEvent.change(screen.getByLabelText("待处理任务"), { target: { value: "unknown-attempt" } });
  fireEvent.change(screen.getByLabelText("处理原因"), { target: { value: "等待可信证据" } });
  fireEvent.click(screen.getByRole("button", { name: "提交处理决定" }));
  await waitFor(() => expect(api.resolveDurable).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole("button", { name: "提交处理决定" })).not.toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "提交处理决定" }));
  await screen.findByText("决定已记录，未授权新的口播。");
  expect(vi.mocked(api.resolveDurable).mock.calls[0]).toEqual(vi.mocked(api.resolveDurable).mock.calls[1]);
  expect(vi.mocked(api.resolveDurable).mock.calls[0][1]).toMatchObject({ expectedRevision: 9, action: "WAIT_FOR_EVIDENCE", reason: "等待可信证据" });
 });
 it("does not expose recovery controls for a legacy Session", async () => {
  vi.mocked(api.durableSession).mockResolvedValue({ managed: false });
  const result=mount(); await waitFor(() => expect(api.durableSession).toHaveBeenCalled());
  expect(result.container).toBeEmptyDOMElement();
 });
});
