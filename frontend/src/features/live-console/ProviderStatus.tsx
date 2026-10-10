import { useQuery } from "@tanstack/react-query";
import { integrationApi } from "../settings/integration-client";
import { configApi } from "../../api/config-client";
import { Card } from "../../components/ui/card";
import { ErrorNotice } from "../../components/feedback";
export function ProviderStatus({ sessionId }: { sessionId: string | null }) {
  const me = useQuery({
    queryKey: ["config", "me"],
    queryFn: configApi.me,
    retry: false,
  });
  const defaults = useQuery({
    queryKey: ["config", "profiles"],
    queryFn: configApi.profiles,
    enabled: me.isSuccess,
    retry: false,
    refetchInterval: 10000,
  });
  const bound = useQuery({
    queryKey: ["session-providers", sessionId],
    queryFn: () => integrationApi.providers(sessionId!),
    enabled: !!sessionId && me.isSuccess,
    retry: false,
    refetchInterval: 2000,
  });
  return (
    <Card>
      <h2 className="font-semibold">实际 Provider 绑定</h2>
      <p className="mt-2 text-sm">
        用户：{me.data?.identity.userId ?? (me.isPending ? "正在确认身份…" : "未登录")}
        {!me.data && !me.isPending && " · 请前往用户配置中心登录。"}
      </p>
      <p className="text-sm">
        后续 Session 默认：
        {defaults.data
          ?.filter(
            (p) =>
              p.isDefault &&
              ["LLM", "TTS", "AVATAR", "GPU_WORKER"].includes(p.kind),
          )
          .map((p) => `${p.kind}: ${p.provider} v${p.version}`)
          .join(" · ") || "未配置"}
      </p>
      {bound.data ? (
        <>
          <p className="mt-2 font-semibold" data-testid="provider-mode">
            {bound.data.mode}
            {bound.data.errorCode && ` · ${bound.data.errorCode}`}
          </p>
          <p className="text-sm">
            本次绑定：
            {bound.data.profiles
              .map((p) => `${p.kind}: ${p.provider} v${p.version}`)
              .join(" · ")}
          </p>
          <p className="text-xs text-slate-500">
            生效：{new Date(bound.data.capturedAt).toLocaleString()} · 到期：
            {new Date(bound.data.expiresAt).toLocaleString()}
          </p>
        </>
      ) : (
        <p className="mt-2 text-sm">
          {sessionId
            ? "实际绑定状态尚不可用"
            : "创建 Session 时固定配置；直播期间修改默认项只影响后续 Session。"}
        </p>
      )}
      {bound.error && <ErrorNotice error={bound.error} />}
    </Card>
  );
}
