import { useEffect, useState } from "react";
import { api, type Advisory, type ModelInfo } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { useMetricsStream } from "../hooks/useMetricsStream";
import {
  AdvisoryBanner, Badge, ErrorPanel, Section, Stat, Toggle, fmtNum, fmtPct,
} from "../components/ui";

interface DFlashState {
  config: {
    enabled: boolean; verify_mode: string; verify_len_cap: number;
    draft_quant: string; fastpath_max_tokens: number; prefix_cache: boolean;
  };
  mode: string;
  active: boolean;
  draft_model: string;
  block_size_trained: number | null;
  metrics: { available: boolean; reason?: string; data?: Record<string, unknown> };
  fallback_count: number;
  advisory: Advisory | null;
}

export default function DFlash() {
  const { data: df, refresh } = usePoll<DFlashState>(() => api.get("/dflash"), 8000);
  const { data: models } = usePoll<ModelInfo[]>(() => api.get("/models"), 60000);
  const { latest } = useMetricsStream(60);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [form, setForm] = useState<{ verify_mode: string; verify_len_cap: number; draft_model: string } | null>(null);

  useEffect(() => {
    if (df && !form) {
      setForm({
        verify_mode: df.config.verify_mode,
        verify_len_cap: df.config.verify_len_cap,
        draft_model: df.draft_model,
      });
    }
  }, [df, form]);

  const update = async (patch: Record<string, unknown>) => {
    setBusy(true); setErr(null);
    try {
      const r = await api.put<{ restart_required: boolean }>("/dflash", patch);
      if (r.restart_required) setRestartNeeded(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false); void refresh();
    }
  };

  const restartNow = async () => {
    setBusy(true);
    try { await api.post("/runtime/restart"); setRestartNeeded(false); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); void refresh(); }
  };

  const drafts = (models ?? []).filter((m) => m.extra?.is_dflash_draft);
  const rm = latest?.runtime;
  const recents = ((df?.metrics.data?.recent_requests as Record<string, unknown>[] | undefined) ?? []);
  const lastReq = recents[recents.length - 1];

  return (
    <>
      <h1 className="page-title">DFlash</h1>
      <p className="page-sub">Block-diffusion speculative decoding — draft proposes 16 tokens per cycle, target verifies in one pass</p>

      {df?.advisory && <AdvisoryBanner {...df.advisory} />}
      {err && <ErrorPanel what="DFlash update failed" detail={err} />}
      {restartNeeded && (
        <div className="advisory warn" role="status">
          <span style={{ fontWeight: 600 }}>Restart required</span>
          <span>Settings are saved but the running engine still uses the previous values.</span>
          <button className="btn small" onClick={restartNow} disabled={busy}>Restart now</button>
        </div>
      )}

      <Section title="Status">
        <div className="card">
          <div className="row between">
            <div className="row" style={{ gap: 10 }}>
              <span style={{ fontWeight: 600 }}>DFlash</span>
              {df?.active ? <Badge kind="ok">Enabled · active</Badge>
                : df?.mode === "fast" ? <Badge kind="warn">Enabled · runtime not running</Badge>
                : <Badge kind="idle">Disabled (Safe Mode)</Badge>}
            </div>
            <Toggle
              label="DFlash enabled"
              checked={df?.mode === "fast"}
              disabled={busy || !df}
              onChange={(v) => update({ enabled: v })}
            />
          </div>
          <hr className="divider" style={{ margin: "16px 0" }} />
          <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", rowGap: 20 }}>
            <Stat label="Acceptance Rate" value={fmtPct(rm?.acceptance_rate)} />
            <Stat label="Accepted / cycle" value={
              lastReq && typeof lastReq.tokens_per_cycle === "number"
                ? fmtNum(lastReq.tokens_per_cycle as number, 1) : "—"
            } hint="Tokens emitted per draft-verify cycle (last request)" />
            <Stat label="Generation" value={fmtNum(rm?.decode_tok_s, 1)} unit="tok/s" />
            <Stat label="Fallbacks" value={df?.fallback_count ?? 0} />
          </div>
          {!df?.metrics.available && df?.mode === "fast" && (
            <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 14 }}>
              Live metrics unavailable: {df.metrics.reason ?? "runtime not running"}.
            </p>
          )}
        </div>
      </Section>

      <Section title="Configuration">
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">Draft model</span>
            <span className="v">
              <select
                value={form?.draft_model ?? ""}
                disabled={busy || drafts.length === 0}
                onChange={(e) => { setForm((f) => f && { ...f, draft_model: e.target.value }); void update({ draft_model: e.target.value }); }}
              >
                {drafts.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
                {drafts.length === 0 && <option value="">no DFlash draft found</option>}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              Draft block size
              <small>Fixed at training time by this draft checkpoint — not a runtime knob</small>
            </span>
            <span className="v mono">{df?.block_size_trained ?? 16} tokens</span>
          </div>
          <div className="kv">
            <span className="k">
              Verify mode
              <small>adaptive shortens low-acceptance blocks automatically</small>
            </span>
            <span className="v">
              <select
                value={form?.verify_mode ?? "adaptive"} disabled={busy}
                onChange={(e) => { setForm((f) => f && { ...f, verify_mode: e.target.value }); void update({ verify_mode: e.target.value }); }}
              >
                <option value="adaptive">adaptive (recommended)</option>
                <option value="dflash">dflash (fixed block)</option>
                <option value="ddtree">ddtree (experimental)</option>
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              Verify length cap
              <small>Max tokens verified per target forward · 0 = engine default</small>
            </span>
            <span className="v">
              <select
                value={form?.verify_len_cap ?? 0} disabled={busy}
                onChange={(e) => { const v = Number(e.target.value); setForm((f) => f && { ...f, verify_len_cap: v }); void update({ verify_len_cap: v }); }}
              >
                <option value={0}>default</option>
                <option value={4}>4</option>
                <option value={8}>8</option>
                <option value={16}>16</option>
              </select>
            </span>
          </div>
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          Use Benchmark → Auto Tune to measure these options on your hardware instead of guessing.
        </p>
      </Section>

      <Section title="Recent Requests">
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th className="num">Tokens</th><th className="num">Decode tok/s</th>
                <th className="num">Acceptance</th><th className="num">Tokens / cycle</th>
                <th className="num">Cycles</th>
              </tr>
            </thead>
            <tbody>
              {recents.slice(-8).reverse().map((r, i) => (
                <tr key={i}>
                  <td className="num">{String(r.generated_tokens ?? r.tokens ?? "—")}</td>
                  <td className="num">{typeof r.decode_tok_s === "number" ? fmtNum(r.decode_tok_s as number, 1) : "—"}</td>
                  <td className="num">{typeof r.acceptance_rate === "number"
                    ? fmtPct((r.acceptance_rate as number) > 1 ? (r.acceptance_rate as number) / 100 : r.acceptance_rate as number) : "—"}</td>
                  <td className="num">{typeof r.tokens_per_cycle === "number" ? fmtNum(r.tokens_per_cycle as number, 1) : "—"}</td>
                  <td className="num">{String(r.cycles ?? "—")}</td>
                </tr>
              ))}
              {recents.length === 0 && (
                <tr><td colSpan={5}><div className="empty">No requests recorded yet in this runtime session.</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
