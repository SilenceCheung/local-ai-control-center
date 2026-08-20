import { useState } from "react";
import { api, type AppConfig, type RuntimeStatus } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, ErrorPanel, Section, StatusDot, fmtTime, fmtUptime } from "../components/ui";

interface EventRow { id: number; kind: string; detail: string; created_at: number }

export default function Runtime() {
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
      <h1 className="page-title">Runtime</h1>
      <p className="page-sub">Inference engine control — mode switches restart the model process, agents keep the same endpoint</p>

      {err && <ErrorPanel what="Mode switch failed" detail={err} />}

      <Section title="Mode">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">
              Safe Mode
              <small>Target only · mlx-lm · maximum stability</small>
            </span>
            <span className="v">
              {rt?.mode === "safe" && <Badge kind="accent">active</Badge>}
              <button className="btn small" disabled={busy || rt?.mode === "safe"}
                      onClick={() => switchMode("safe")}>
                {busy ? "…" : "Use Safe"}
              </button>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              Fast Mode
              <small>Target + DFlash draft · dflash-mlx speculative decoding</small>
            </span>
            <span className="v">
              {rt?.mode === "fast" && <Badge kind="accent">active</Badge>}
              <button className="btn small" disabled={busy || rt?.mode === "fast"}
                      onClick={() => switchMode("fast")}>
                {busy ? "…" : "Use Fast"}
              </button>
            </span>
          </div>
        </div>
        {running && (
          <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
            Switching modes reloads the model (~30–60 s). The public API endpoint and model alias never change.
          </p>
        )}
      </Section>

      <Section title="Process">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv"><span className="k">Status</span>
            <span className="v"><StatusDot kind={running ? "ok" : rt?.status === "error" ? "err" : "idle"} />{rt?.status ?? "…"}</span></div>
          <div className="kv"><span className="k">Engine</span><span className="v">{running ? rt?.engine : "—"}</span></div>
          <div className="kv"><span className="k">PID</span><span className="v mono">{rt?.pid ?? "—"}</span></div>
          <div className="kv"><span className="k">Uptime</span><span className="v">{fmtUptime(rt?.uptime_s)}</span></div>
          <div className="kv"><span className="k">Internal port</span>
            <span className="v mono">{cfg?.runtime.internal_port ?? "…"} (127.0.0.1 only)</span></div>
          <div className="kv"><span className="k">HTTP health</span>
            <span className="v">{rt?.http_healthy ? <Badge kind="ok">healthy</Badge> : <Badge kind="idle">unreachable</Badge>}</span></div>
          <div className="kv"><span className="k">Fallback events</span>
            <span className="v">{rt?.fallback_count ?? 0}</span></div>
        </div>
      </Section>

      <Section title="Recent Events">
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="tbl">
            <thead><tr><th style={{ width: 170 }}>Time</th><th style={{ width: 110 }}>Event</th><th>Detail</th></tr></thead>
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
                <tr><td colSpan={3}><div className="empty">No runtime events yet.</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
