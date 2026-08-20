import { useEffect, useState } from "react";
import { api, type AppConfig } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, ErrorPanel, Section, Toggle } from "../components/ui";

interface ServiceStatus {
  [k: string]: { service: string; label: string; installed: boolean; loaded: boolean; pid: number | null };
}

export default function Settings() {
  const { data: cfg, refresh } = usePoll<AppConfig>(() => api.get("/settings"), 30000);
  const { data: svc, refresh: refreshSvc } = usePoll<ServiceStatus>(() => api.get("/service/status"), 20000);
  const [err, setErr] = useState<string | null>(null);
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem("lacc-theme") || "system");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("lacc-theme", theme);
  }, [theme]);

  const patch = async (p: Record<string, unknown>) => {
    setErr(null);
    try {
      const r = await api.put<{ restart_required: boolean }>("/settings", p);
      if (r.restart_required) setRestartNeeded(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      void refresh();
    }
  };

  const svcAction = async (service: string, action: "install" | "uninstall") => {
    setErr(null);
    try { await api.post(`/service/${action}`, { service }); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { void refreshSvc(); }
  };

  if (!cfg) return <p className="empty">Loading settings…</p>;

  return (
    <>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">Single source of truth: config/config.yaml — changes persist immediately</p>

      {err && <ErrorPanel what="Settings update failed" detail={err} />}
      {restartNeeded && (
        <div className="advisory warn" role="status">
          <span>Runtime settings changed — restart the runtime to apply.</span>
          <button className="btn small" onClick={async () => { await api.post("/runtime/restart"); setRestartNeeded(false); }}>
            Restart now
          </button>
        </div>
      )}

      <Section title="General">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">Appearance</span>
            <span className="v">
              <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Theme">
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">Model alias<small>What agents see as the model name</small></span>
            <span className="v mono">{cfg.api.alias}</span>
          </div>
        </div>
      </Section>

      <Section title="Runtime">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">Max context<small>Hard cap for the inference engine</small></span>
            <span className="v">
              <select value={cfg.runtime.max_context}
                      onChange={(e) => patch({ runtime: { max_context: Number(e.target.value) } })}>
                {[16384, 32768, 65536, 131072, 262144].map((v) => (
                  <option key={v} value={v}>{v / 1024}K</option>
                ))}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">Default max tokens</span>
            <span className="v">
              <select value={cfg.runtime.default_max_tokens}
                      onChange={(e) => patch({ runtime: { default_max_tokens: Number(e.target.value) } })}>
                {[1024, 2048, 4096, 8192, 16384].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">Thinking mode<small>Qwen3.8 reasoning traces — better quality, more tokens</small></span>
            <span className="v">
              <Toggle checked={cfg.runtime.enable_thinking}
                      onChange={(v) => patch({ runtime: { enable_thinking: v } })} label="Thinking mode" />
            </span>
          </div>
        </div>
      </Section>

      <Section title="Startup">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">Auto-load model on login
              <small>Off by default — a 27B model pins ~29 GB of unified memory</small></span>
            <span className="v">
              <Toggle checked={cfg.runtime.auto_load}
                      onChange={(v) => patch({ runtime: { auto_load: v } })} label="Auto load" />
            </span>
          </div>
          {["backend", "gateway"].map((s) => (
            <div className="kv" key={s}>
              <span className="k">launchd · {s}
                <small>{svc?.[s]?.label ?? ""}</small></span>
              <span className="v">
                {svc?.[s]?.loaded ? <Badge kind="ok">running · pid {svc[s].pid ?? "?"}</Badge>
                  : svc?.[s]?.installed ? <Badge kind="warn">installed, not running</Badge>
                  : <Badge kind="idle">not installed</Badge>}
                {svc?.[s]?.installed
                  ? <button className="btn small" onClick={() => svcAction(s, "uninstall")}>Remove</button>
                  : <button className="btn small" onClick={() => svcAction(s, "install")}>Install</button>}
              </span>
            </div>
          ))}
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          Installing launchd services keeps the dashboard and API gateway available after login and restarts
          them if they crash. The model itself only loads when you press Start (or enable auto-load).
        </p>
      </Section>

      <Section title="Privacy">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">Telemetry</span>
            <span className="v"><Badge kind="ok">none — local first</Badge></span>
          </div>
          <div className="kv">
            <span className="k">Prompt logging<small>Prompt/response bodies are never persisted unless enabled</small></span>
            <span className="v">
              <Toggle checked={cfg.privacy.log_prompts}
                      onChange={(v) => patch({ privacy: { log_prompts: v } })} label="Prompt logging" />
            </span>
          </div>
        </div>
      </Section>

      <Section title="Advanced">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv" style={{ cursor: "pointer" }} onClick={() => setAdvancedOpen(!advancedOpen)}
               role="button" tabIndex={0}
               onKeyDown={(e) => e.key === "Enter" && setAdvancedOpen(!advancedOpen)}>
            <span className="k">Show advanced options</span>
            <span className="v">{advancedOpen ? "Hide" : "Show"}</span>
          </div>
          {advancedOpen && (
            <>
              <div className="kv">
                <span className="k">API port</span>
                <span className="v mono">{cfg.api.port}</span>
              </div>
              <div className="kv">
                <span className="k">Dashboard port</span>
                <span className="v mono">{cfg.dashboard.port}</span>
              </div>
              <div className="kv">
                <span className="k">Runtime internal port</span>
                <span className="v mono">{cfg.runtime.internal_port}</span>
              </div>
              <div className="kv">
                <span className="k">Bind address<small>LAN exposure is intentionally not offered in this version</small></span>
                <span className="v mono">127.0.0.1</span>
              </div>
              <div className="kv">
                <span className="k">Log level</span>
                <span className="v">
                  <select value={cfg.logging.level}
                          onChange={(e) => patch({ logging: { level: e.target.value } })}>
                    {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => <option key={l}>{l}</option>)}
                  </select>
                </span>
              </div>
              <div className="kv">
                <span className="k">Swap warning threshold</span>
                <span className="v">
                  <select value={cfg.memory.swap_warn_gb}
                          onChange={(e) => patch({ memory: { swap_warn_gb: Number(e.target.value) } })}>
                    {[2, 4, 8, 16].map((v) => <option key={v} value={v}>{v} GB</option>)}
                  </select>
                </span>
              </div>
              <div className="kv">
                <span className="k">Model directories</span>
                <span className="v mono" style={{ fontSize: 11, textAlign: "right" }}>
                  {cfg.model_dirs.join(" · ")}
                </span>
              </div>
            </>
          )}
        </div>
      </Section>

      <Section title="About">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv"><span className="k">Local AI Control Center</span><span className="v">v0.1.0</span></div>
          <div className="kv"><span className="k">Engine (Fast Mode)</span><span className="v mono">dflash-mlx</span></div>
          <div className="kv"><span className="k">Engine (Safe Mode)</span><span className="v mono">mlx-lm</span></div>
        </div>
      </Section>
    </>
  );
}
