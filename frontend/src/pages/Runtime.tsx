import { useState } from "react";
import { api, type AppConfig, type RuntimeStatus } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, ErrorPanel, Section, StatusDot, fmtTime, fmtUptime } from "../components/ui";
import { useI18n } from "../i18n";

interface EventRow { id: number; kind: string; detail: string; created_at: number }

export default function Runtime() {
  const { t } = useI18n();
  const { data: rt, refresh } = usePoll<RuntimeStatus>(() => api.get("/runtime/status"), 5000);
  const { data: cfg, refresh: refreshCfg } = usePoll<AppConfig>(() => api.get("/settings"), 30000);
  const { data: events, refresh: refreshEvents } = usePoll<EventRow[]>(() => api.get("/events?limit=30"), 15000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const running = rt?.status === "running";

  const switchMode = async (mode: "safe" | "fast") => {
    if (rt?.mode === mode) return;
    setBusy(true); setErr(null);
    try {
      await api.post("/runtime/mode", { mode });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false); void refresh(); void refreshCfg(); void refreshEvents();
    }
  };

  return (
    <>
      <h1 className="page-title">{t("nav.runtime")}</h1>
      <p className="page-sub">{t("runtime.sub")}</p>

      {err && <ErrorPanel what={t("runtime.err.mode")} detail={err} />}

      <Section title={t("runtime.mode")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">
              {t("runtime.safe")}
              <small>{t("runtime.safe.sub")}</small>
            </span>
            <span className="v">
              {rt?.mode === "safe" && <Badge kind="accent">{t("runtime.active")}</Badge>}
              <button className="btn small" disabled={busy || rt?.mode === "safe"}
                      onClick={() => switchMode("safe")}>
                {busy ? "…" : t("runtime.use_safe")}
              </button>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              {t("runtime.fast")}
              <small>{t("runtime.fast.sub")}</small>
            </span>
            <span className="v">
              {rt?.mode === "fast" && <Badge kind="accent">{t("runtime.active")}</Badge>}
              <button className="btn small" disabled={busy || rt?.mode === "fast"}
                      onClick={() => switchMode("fast")}>
                {busy ? "…" : t("runtime.use_fast")}
              </button>
            </span>
          </div>
        </div>
        {running && (
          <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
            {t("runtime.switch.note")}
          </p>
        )}
      </Section>

      <Section title={t("runtime.process")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv"><span className="k">{t("runtime.status")}</span>
            <span className="v"><StatusDot kind={running ? "ok" : rt?.status === "error" ? "err" : "idle"} />{rt?.status ?? "…"}</span></div>
          <div className="kv"><span className="k">{t("runtime.engine")}</span><span className="v">{running ? rt?.engine : t("common.emdash")}</span></div>
          <div className="kv"><span className="k">{t("runtime.pid")}</span><span className="v mono">{rt?.pid ?? t("common.emdash")}</span></div>
          <div className="kv"><span className="k">{t("runtime.uptime")}</span><span className="v">{fmtUptime(rt?.uptime_s)}</span></div>
          <div className="kv"><span className="k">{t("runtime.internal")}</span>
            <span className="v mono">{cfg?.runtime.internal_port ?? "…"} {t("runtime.internal.only")}</span></div>
          <div className="kv"><span className="k">{t("runtime.http")}</span>
            <span className="v">{rt?.http_healthy ? <Badge kind="ok">{t("runtime.http.healthy")}</Badge> : <Badge kind="idle">{t("runtime.http.unreachable")}</Badge>}</span></div>
          <div className="kv"><span className="k">{t("runtime.fallbacks")}</span>
            <span className="v">{rt?.fallback_count ?? 0}</span></div>
        </div>
      </Section>

      <Section title={t("runtime.events")}>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="tbl">
            <thead><tr><th style={{ width: 170 }}>{t("runtime.col.time")}</th><th style={{ width: 110 }}>{t("runtime.col.event")}</th><th>{t("runtime.col.detail")}</th></tr></thead>
            <tbody>
              {(events ?? []).map((e) => (
                <tr key={e.id}>
                  <td style={{ color: "var(--text-2)" }}>{fmtTime(e.created_at)}</td>
                  <td>
                    {e.kind === "crash" || e.kind === "fallback" ? <Badge kind="err">{e.kind}</Badge>
                      : e.kind === "warning" ? <Badge kind="warn">{e.kind}</Badge>
                      : <Badge kind="idle">{e.kind}</Badge>}
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: "var(--text-2)" }}>{e.detail}</td>
                </tr>
              ))}
              {(events ?? []).length === 0 && (
                <tr><td colSpan={3}><div className="empty">{t("runtime.empty.events")}</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
