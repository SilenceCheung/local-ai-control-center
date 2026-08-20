import { useState } from "react";
import { api, type AgentInfo, type AppConfig, type RuntimeStatus } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { useMetricsStream } from "../hooks/useMetricsStream";
import {
  AdvisoryBanner, Badge, CopyField, ErrorPanel, Section, Stat, StatusDot,
  fmtNum, fmtPct, fmtUptime,
} from "../components/ui";

export default function Overview() {
  const { data: rt, refresh } = usePoll<RuntimeStatus>(() => api.get("/runtime/status"), 5000);
  const { data: cfg } = usePoll<AppConfig>(() => api.get("/settings"), 30000);
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
      <h1 className="page-title">Overview</h1>
      <p className="page-sub">Apple Silicon local model runtime · speculative decoding · agent gateway</p>

      {rt?.advisory && <AdvisoryBanner {...rt.advisory} />}
      {memoryAdvisory && <AdvisoryBanner {...memoryAdvisory} />}
      {rt?.status === "error" && rt.error && (
        <ErrorPanel
          what="Runtime is in an error state"
          detail={rt.error}
          onRetry={() => act("restart")}
        />
      )}
      {actionError && <ErrorPanel what="Runtime action failed" detail={actionError} />}

      <Section title="Runtime">
        <div className="card">
          <div className="row between">
            <div className="row" style={{ gap: 10 }}>
              <StatusDot
                kind={running ? "ok" : rt?.status === "error" ? "err" : starting ? "warn" : "idle"}
                pulse={starting}
              />
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>
                  Local AI Runtime&ensp;
                  <span style={{ fontWeight: 400, color: "var(--text-2)" }}>
                    {starting && busy ? `${busy}…` : rt?.status ?? "…"}
                  </span>
                </div>
                <div style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 2 }}>
                  {rt?.target_model ?? "no target model selected"}
                  {rt?.engine && running && <> · {rt.engine}</>}
                  {rt?.uptime_s != null && <> · up {fmtUptime(rt.uptime_s)}</>}
                </div>
              </div>
            </div>
            <div className="row">
              {!running && (
                <button className="btn primary" disabled={starting} onClick={() => act("start")}>
                  {busy === "start" ? "Starting…" : "Start"}
                </button>
              )}
              {running && (
                <>
                  <button className="btn" disabled={starting} onClick={() => act("restart")}>
                    {busy === "restart" ? "Restarting…" : "Restart"}
                  </button>
                  <button className="btn danger" disabled={starting} onClick={() => act("stop")}>
                    {busy === "stop" ? "Stopping…" : "Stop"}
                  </button>
                </>
              )}
            </div>
          </div>

          {running && (
            <>
              <hr className="divider" style={{ margin: "16px 0" }} />
              <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
                <Stat label="Memory" value={fmtNum(latest?.mem_used_gb, 1)} unit="GB" />
                <Stat label="Generation" value={fmtNum(rm?.decode_tok_s, 1)} unit="tok/s"
                      hint="Weighted decode average since runtime start" />
                <Stat label="TTFT" value={rm?.ttft_s != null ? fmtNum(rm.ttft_s, 2) : "—"} unit="s"
                      hint="Average time-to-first-token of recent requests" />
                <Stat label="Context" value={cfg ? `${Math.round(cfg.runtime.max_context / 1024)}K` : "—"} />
              </div>
            </>
          )}
        </div>
      </Section>

      <Section title="Speculative Decoding">
        <div className="card">
          <div className="row between">
            <div className="row" style={{ gap: 10 }}>
              <StatusDot kind={running && rt?.mode === "fast" ? "ok" : "idle"} />
              <div>
                <div style={{ fontWeight: 600 }}>
                  DFlash&ensp;
                  {rt?.mode === "fast"
                    ? <Badge kind={running ? "ok" : "idle"}>{running ? "ON" : "enabled, runtime stopped"}</Badge>
                    : <Badge kind="idle">OFF — Safe Mode</Badge>}
                </div>
                <div style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 2 }}>
                  {rt?.draft_model ?? cfg?.runtime.draft_model ?? "no draft model"}
                </div>
              </div>
            </div>
          </div>
          {running && rt?.mode === "fast" && (
            <>
              <hr className="divider" style={{ margin: "16px 0" }} />
              <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                <Stat label="Acceptance" value={fmtPct(rm?.acceptance_rate)}
                      hint="Average draft acceptance of recent requests" />
                <Stat label="Prefill" value={fmtNum(rm?.prefill_tok_s, 0)} unit="tok/s" />
                <Stat label="Runtime RSS" value={fmtNum(rm?.rss_gb, 1)} unit="GB" />
              </div>
            </>
          )}
        </div>
      </Section>

      <Section title="API Server">
        <div className="card">
          <div className="row between" style={{ marginBottom: 12 }}>
            <span className="row" style={{ gap: 10 }}>
              <StatusDot kind={rt?.http_healthy ? "ok" : "idle"} />
              <span style={{ fontWeight: 600 }}>OpenAI-compatible API</span>
              <Badge kind={rt?.http_healthy ? "ok" : "idle"}>
                {rt?.http_healthy ? "Healthy" : running ? "starting" : "runtime stopped"}
              </Badge>
            </span>
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <CopyField value={apiBase} label="Base URL" />
            <CopyField value={cfg?.api.alias ?? "qwen3.8-27b-local"} label="Model" />
          </div>
        </div>
      </Section>

      <Section title="Agents">
        <div className="card" style={{ padding: "6px 20px" }}>
          {(agents ?? []).filter((a) => !a.not_supported_natively).map((a) => (
            <div className="kv" key={a.id}>
              <span className="k">{a.name}</span>
              <span className="v">
                {a.status === "connected" ? <Badge kind="ok">Connected</Badge>
                  : a.status === "seen_before" ? <Badge kind="idle">Seen earlier</Badge>
                  : <Badge kind="idle">Unknown</Badge>}
              </span>
            </div>
          ))}
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          “Connected” means this client sent requests through the local API in the last 30 minutes.
        </p>
      </Section>
    </>
  );
}
