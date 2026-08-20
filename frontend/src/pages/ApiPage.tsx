import { api, type AppConfig, type RuntimeStatus } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, CopyField, Section, Stat, StatusDot, fmtTime } from "../components/ui";

interface GatewayStats {
  ok: boolean; live: boolean;
  stats: {
    started_at: number; requests_total: number; requests_active: number;
    errors_total: number; tokens_generated: number; last_request_at: number | null;
    agents_seen: Record<string, number>;
  } | null;
}

export default function ApiPage() {
  const { data: cfg } = usePoll<AppConfig>(() => api.get("/settings"), 30000);
  const { data: rt } = usePoll<RuntimeStatus>(() => api.get("/runtime/status"), 6000);
  const { data: gw } = usePoll<GatewayStats>(() => api.get("/gateway/stats"), 6000);

  const base = cfg ? `http://${cfg.api.host}:${cfg.api.port}/v1` : "http://127.0.0.1:8080/v1";
  const s = gw?.stats;

  return (
    <>
      <h1 className="page-title">API</h1>
      <p className="page-sub">OpenAI-compatible inference endpoint — stable across runtime restarts and mode switches</p>

      <Section title="Connection">
        <div className="grid" style={{ gridTemplateColumns: "1fr", gap: 8 }}>
          <CopyField label="Base URL" value={base} />
          <CopyField label="API Key" value={cfg?.api.api_key ?? "local"} />
          <CopyField label="Model" value={cfg?.api.alias ?? "qwen3.8-27b-local"} />
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          The endpoint listens on 127.0.0.1 only. The API key is accepted as-is for local clients that require one.
        </p>
      </Section>

      <Section title="Server Status">
        <div className="card">
          <div className="row" style={{ gap: 10, marginBottom: 16 }}>
            <StatusDot kind={gw?.live ? (rt?.http_healthy ? "ok" : "warn") : "err"} />
            <span style={{ fontWeight: 600 }}>
              Gateway {gw?.live ? "running" : "not responding"}
            </span>
            {gw?.live && (rt?.http_healthy
              ? <Badge kind="ok">runtime reachable</Badge>
              : <Badge kind="warn">runtime {rt?.status ?? "stopped"}</Badge>)}
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            <Stat label="Requests" value={s?.requests_total ?? "—"} />
            <Stat label="Active" value={s?.requests_active ?? "—"} />
            <Stat label="Tokens Generated" value={s ? s.tokens_generated.toLocaleString() : "—"}
                  hint="Approximate: counted from streamed chunks and usage fields" />
            <Stat label="Errors" value={s?.errors_total ?? "—"} />
          </div>
          <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 14 }}>
            Last request: {fmtTime(s?.last_request_at)}
          </p>
        </div>
      </Section>

      <Section title="Endpoints">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv"><span className="k mono">GET /v1/models</span>
            <span className="v"><Badge kind="ok">supported</Badge></span></div>
          <div className="kv"><span className="k mono">POST /v1/chat/completions</span>
            <span className="v"><Badge kind="ok">supported · streaming · tool calls</Badge></span></div>
          <div className="kv">
            <span className="k mono">POST /v1/responses
              <small>Minimal non-streaming adapter in Fast Mode (dflash-mlx); not implemented by mlx-lm in Safe Mode</small>
            </span>
            <span className="v">{rt?.mode === "fast"
              ? <Badge kind="warn">partial (Fast Mode only)</Badge>
              : <Badge kind="idle">not supported in Safe Mode</Badge>}</span>
          </div>
          <div className="kv"><span className="k mono">POST /v1/completions</span>
            <span className="v"><Badge kind="warn">depends on engine</Badge></span></div>
        </div>
      </Section>

      <Section title="Quick Test">
        <div className="card">
          <code style={{ whiteSpace: "pre-wrap", display: "block", fontSize: 11.5, lineHeight: 1.7 }}>
{`curl ${base}/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${cfg?.api.alias ?? "qwen3.8-27b-local"}", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100, "stream": true}'`}
          </code>
        </div>
      </Section>
    </>
  );
}
