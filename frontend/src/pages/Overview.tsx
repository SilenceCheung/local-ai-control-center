import { useState } from "react";
import { api, type AgentInfo, type AppConfig, type RuntimeStatus } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { useMetricsStream } from "../hooks/useMetricsStream";
import {
  AdvisoryBanner, AliasField, Badge, CopyField, ErrorPanel, Section, Stat, StatusDot,
  fmtNum, fmtPct, fmtUptime,
} from "../components/ui";
import { useI18n } from "../i18n";

export default function Overview() {
  const { t } = useI18n();
  const { data: rt, refresh } = usePoll<RuntimeStatus>(() => api.get("/runtime/status"), 5000);
  const { data: cfg, refresh: refreshCfg } = usePoll<AppConfig>(() => api.get("/settings"), 30000);
  const { data: agents } = usePoll<AgentInfo[]>(() => api.get("/agents"), 30000);
  const { latest, memoryAdvisory } = useMetricsStream(60);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const act = async (action: "start" | "stop" | "restart") => {
    setBusy(action);
    setActionError(null);
    try {
      await api.post(`/runtime/${action}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      void refresh();
    }
  };

  const running = rt?.status === "running";
  const starting = rt?.status === "starting" || busy !== null;
  const rm = latest?.runtime;
  const apiBase = cfg ? `http://${cfg.api.host}:${cfg.api.port}/v1` : "http://127.0.0.1:8080/v1";

  return (
    <>
      <h1 className="page-title">{t("nav.overview")}</h1>
      <p className="page-sub">{t("overview.sub")}</p>

      {rt?.advisory && <AdvisoryBanner {...rt.advisory} />}
      {memoryAdvisory && <AdvisoryBanner {...memoryAdvisory} />}
      {rt?.status === "error" && rt.error && (
        <ErrorPanel
          what={t("overview.err.runtime")}
          detail={rt.error}
          onRetry={() => act("restart")}
        />
      )}
      {actionError && <ErrorPanel what={t("overview.err.action")} detail={actionError} />}

      <Section title={t("overview.runtime")}>
        <div className="card">
          <div className="row between">
            <div className="row" style={{ gap: 10 }}>
              <StatusDot
                kind={running ? "ok" : rt?.status === "error" ? "err" : starting ? "warn" : "idle"}
                pulse={starting}
              />
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>
                  {t("overview.runtime.name")}&ensp;
                  <span style={{ fontWeight: 400, color: "var(--text-2)" }}>
                    {starting && busy ? `${busy}…` : rt?.status ?? "…"}
                  </span>
                </div>
                <div style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 2 }}>
                  {rt?.target_model ?? t("overview.no_target")}
                  {rt?.engine && running && <> · {rt.engine}</>}
                  {rt?.uptime_s != null && <> · {t("overview.up", { t: fmtUptime(rt.uptime_s) })}</>}
                </div>
              </div>
            </div>
            <div className="row">
              {!running && (
                <button className="btn primary" disabled={starting} onClick={() => act("start")}>
                  {busy === "start" ? t("overview.starting") : t("overview.start")}
                </button>
              )}
              {running && (
                <>
                  <button className="btn" disabled={starting} onClick={() => act("restart")}>
                    {busy === "restart" ? t("overview.restarting") : t("overview.restart")}
                  </button>
                  <button className="btn danger" disabled={starting} onClick={() => act("stop")}>
                    {busy === "stop" ? t("overview.stopping") : t("overview.stop")}
                  </button>
                </>
              )}
            </div>
          </div>

          {running && (
            <>
              <hr className="divider" style={{ margin: "16px 0" }} />
              <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
                <Stat label={t("overview.mem")} value={fmtNum(latest?.mem_used_gb, 1)} unit="GB" />
                <Stat label={t("overview.gen")} value={fmtNum(rm?.decode_tok_s, 1)} unit="tok/s"
                      hint={t("overview.gen.hint")} />
                <Stat label={t("overview.ttft")} value={rm?.ttft_s != null ? fmtNum(rm.ttft_s, 2) : t("common.emdash")} unit="s"
                      hint={t("overview.ttft.hint")} />
                <Stat label={t("overview.context")} value={cfg ? `${Math.round(cfg.runtime.max_context / 1024)}K` : t("common.emdash")} />
              </div>
            </>
          )}
        </div>
      </Section>

      <Section title={t("overview.dflash")}>
        <div className="card">
          <div className="row between">
            <div className="row" style={{ gap: 10 }}>
              <StatusDot kind={running && rt?.mode === "fast" ? "ok" : "idle"} />
              <div>
                <div style={{ fontWeight: 600 }}>
                  DFlash&ensp;
                  {rt?.mode === "fast"
                    ? <Badge kind={running ? "ok" : "idle"}>{running ? t("overview.dflash.on") : t("overview.dflash.enabled_stopped")}</Badge>
                    : <Badge kind="idle">{t("overview.dflash.off")}</Badge>}
                </div>
                <div style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 2 }}>
                  {rt?.draft_model ?? cfg?.runtime.draft_model ?? t("overview.no_draft")}
                </div>
              </div>
            </div>
          </div>
          {running && rt?.mode === "fast" && (
            <>
              <hr className="divider" style={{ margin: "16px 0" }} />
              <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                <Stat label={t("overview.accept")} value={fmtPct(rm?.acceptance_rate)}
                      hint={t("overview.accept.hint")} />
                <Stat label={t("overview.prefill")} value={fmtNum(rm?.prefill_tok_s, 0)} unit="tok/s" />
                <Stat label={t("overview.rss")} value={fmtNum(rm?.rss_gb, 1)} unit="GB" />
              </div>
            </>
          )}
        </div>
      </Section>

      <Section title={t("overview.api")}>
        <div className="card">
          <div className="row between" style={{ marginBottom: 12 }}>
            <span className="row" style={{ gap: 10 }}>
              <StatusDot kind={rt?.http_healthy ? "ok" : "idle"} />
              <span style={{ fontWeight: 600 }}>{t("overview.api.name")}</span>
              <Badge kind={rt?.http_healthy ? "ok" : "idle"}>
                {rt?.http_healthy ? t("overview.api.healthy") : running ? t("overview.api.starting") : t("overview.api.stopped")}
              </Badge>
            </span>
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <CopyField value={apiBase} label={t("overview.base")} />
            <AliasField
              alias={cfg?.api.alias ?? "Qwen3.8-27B-Heretic-8bit"}
              aliasAuto={cfg?.api.alias_auto ?? true}
              label={t("overview.model")}
              onSave={async (name) => {
                await api.put("/settings", { api: { alias: name, alias_auto: false } });
                void refreshCfg();
              }}
              onReset={async () => {
                await api.put("/settings", { api: { alias_auto: true } });
                void refreshCfg();
              }}
            />
          </div>
        </div>
      </Section>

      <Section title={t("overview.agents")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          {(agents ?? []).filter((a) => !a.not_supported_natively).map((a) => (
            <div className="kv" key={a.id}>
              <span className="k">{a.name}</span>
              <span className="v">
                {a.status === "connected" ? <Badge kind="ok">{t("overview.connected")}</Badge>
                  : a.status === "seen_before" ? <Badge kind="idle">{t("overview.seen")}</Badge>
                  : <Badge kind="idle">{t("overview.unknown")}</Badge>}
              </span>
            </div>
          ))}
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          {t("overview.agents.note")}
        </p>
      </Section>
    </>
  );
}
