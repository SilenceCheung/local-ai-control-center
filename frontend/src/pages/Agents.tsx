import { useState } from "react";
import { api, type AgentInfo } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, CopyField, ErrorPanel, Section } from "../components/ui";

interface TestResult {
  ok: boolean; models_ok?: boolean; chat_ok?: boolean; reply?: string;
  elapsed_s?: number; error?: string; base_url?: string;
}

export default function Agents() {
  const { data: agents, refresh } = usePoll<AgentInfo[]>(() => api.get("/agents"), 20000);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);

  const runTest = async () => {
    setTesting(true); setTest(null);
    try {
      setTest(await api.post<TestResult>("/agents/test"));
    } catch (e) {
      setTest({ ok: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false); void refresh();
    }
  };

  return (
    <>
      <h1 className="page-title">Agents</h1>
      <p className="page-sub">Connect coding agents and IDEs to the local model — one alias, one endpoint, no per-agent drift</p>

      <Section
        title="Connection Test"
        actions={
          <button className="btn primary small" onClick={runTest} disabled={testing}>
            {testing ? "Testing…" : "Test Connection"}
          </button>
        }
      >
        <div className="card">
          {!test && !testing && (
            <p style={{ color: "var(--text-2)", margin: 0, fontSize: 12.5 }}>
              Sends a real request through the public endpoint (models list + a tiny completion) —
              exactly what an agent does on first connect.
            </p>
          )}
          {testing && <p style={{ margin: 0 }}><span className="spin" /> Running end-to-end test…</p>}
          {test && (
            test.ok ? (
              <div>
                <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                  <Badge kind="ok">models OK</Badge>
                  <Badge kind="ok">chat OK · {test.elapsed_s}s</Badge>
                </div>
                <code style={{ fontSize: 11.5, color: "var(--text-2)" }}>reply: {test.reply}</code>
              </div>
            ) : (
              <ErrorPanel what="Connection test failed" detail={test.error ?? "unknown"} onRetry={runTest} />
            )
          )}
        </div>
      </Section>

      {(agents ?? []).map((a) => (
        <Section title={a.name} key={a.id}>
          <div className="card">
            <div className="row between" style={{ marginBottom: 12 }}>
              <span className="row" style={{ gap: 8 }}>
                {a.status === "connected" ? <Badge kind="ok">Connected</Badge>
                  : a.status === "seen_before" ? <Badge kind="idle">Seen earlier</Badge>
                  : a.not_supported_natively ? <Badge kind="warn">Needs Anthropic gateway</Badge>
                  : <Badge kind="idle">Unknown</Badge>}
                <span style={{ color: "var(--text-3)", fontSize: 11.5 }}>{a.protocol.toUpperCase()} protocol</span>
              </span>
            </div>
            <p style={{ color: "var(--text-2)", fontSize: 12.5, marginTop: 0 }}>{a.instructions}</p>
            {!a.not_supported_natively && (
              <div className="grid" style={{ gridTemplateColumns: "1fr", gap: 6 }}>
                <CopyField label="Base URL" value={a.config.base_url} />
                <CopyField label="API Key" value={a.config.api_key} />
                <CopyField label="Model" value={a.config.model} />
              </div>
            )}
            {a.config_snippet && (
              <div style={{ marginTop: 10 }}>
                <div className="row between" style={{ marginBottom: 4 }}>
                  <span className="stat-label">Config snippet</span>
                  <button className="btn small" onClick={() => navigator.clipboard.writeText(a.config_snippet!)}>Copy</button>
                </div>
                <code style={{ display: "block", whiteSpace: "pre-wrap", fontSize: 11, background: "var(--surface-2)", padding: 10, borderRadius: 6, border: "1px solid var(--border)" }}>
                  {a.config_snippet}
                </code>
              </div>
            )}
          </div>
        </Section>
      ))}
    </>
  );
}
