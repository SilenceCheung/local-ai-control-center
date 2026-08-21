import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Advisory, type ModelInfo } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { useMetricsStream } from "../hooks/useMetricsStream";
import {
  AdvisoryBanner, Badge, ErrorPanel, Section, Stat, Toggle, fmtNum, fmtPct,
} from "../components/ui";
import { useI18n } from "../i18n";

interface DFlashState {
  config: {
    enabled: boolean; verify_mode: string; verify_len_cap: number;
    draft_quant: string; fastpath_max_tokens: number; prefix_cache: boolean;
    runtime_block_size?: number; draft_bits?: number; reasoning?: string;
    prefill_step_size?: number; draft_sink_size?: number; draft_window_size?: number;
    prefix_cache_l2?: boolean; prefix_cache_max_entries?: number;
    prefix_cache_max_bytes?: string; prefix_cache_l2_max_bytes?: string;
    cache_limit?: string;
  };
  mode: string;
  active: boolean;
  draft_model: string;
  target_model?: string;
  block_size_trained: number | null;
  metrics: { available: boolean; reason?: string; data?: Record<string, unknown> };
  fallback_count: number;
  advisory: Advisory | null;
  recipe_id?: string;
  generation?: string;
  missing?: { id: string; role: string }[];
  engine?: {
    package: string; version: string | null;
    knobs_live: Record<string, boolean>;
  };
}

export default function DFlash() {
  const { t } = useI18n();
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
  if (df?.draft_model && !drafts.some((d) => d.id === df.draft_model)) {
    drafts.unshift({ id: df.draft_model, extra: { is_dflash_draft: true } } as ModelInfo);
  }
  const official = df?.recipe_id === "official_dflash2";
  const live = df?.engine?.knobs_live ?? {};
  const rm = latest?.runtime;
  const recents = ((df?.metrics.data?.recent_requests as Record<string, unknown>[] | undefined) ?? []);
  const lastReq = recents[recents.length - 1];

  return (
    <>
      <h1 className="page-title">{t("nav.dflash")}</h1>
      <p className="page-sub">{t("dflash.sub")}</p>

      {df?.advisory && <AdvisoryBanner {...df.advisory} />}
      {!!df?.missing?.length && (
        <div className="advisory warn" role="status">
          <span>{t("dflash.missing")} {df.missing.map((m) => m.id).join(" · ")}</span>
          <Link className="btn small" to={`/models?tab=discover&q=${encodeURIComponent(df.missing[0].id)}`}>
            {t("dflash.missing.download")}
          </Link>
          <button className="btn small" onClick={() => { void api.post("/models/scan").then(() => refresh()); }} disabled={busy}>
            {t("dflash.missing.scan")}
          </button>
        </div>
      )}
      {err && <ErrorPanel what={t("dflash.err")} detail={err} />}
      {restartNeeded && (
        <div className="advisory warn" role="status">
          <span style={{ fontWeight: 600 }}>{t("dflash.restart")}</span>
          <span>{t("dflash.restart.body")}</span>
          <button className="btn small" onClick={restartNow} disabled={busy}>{t("dflash.restart.now")}</button>
        </div>
      )}

      <Section title={t("dflash.status")}>
        <div className="card">
          <div className="row between">
            <div className="row" style={{ gap: 10 }}>
              <span style={{ fontWeight: 600 }}>DFlash</span>
              <Badge kind={df?.recipe_id === "official_dflash2" ? "accent" : "idle"}>
                {df?.recipe_id === "official_dflash2" ? t("dflash.recipe.official") : t("dflash.recipe.heretic")}
              </Badge>
              <Badge kind="idle">
                {df?.generation === "dflash2" ? t("dflash.gen.dflash2") : t("dflash.gen.dflash1")}
              </Badge>
              {df?.active ? <Badge kind="ok">{t("dflash.enabled_active")}</Badge>
                : df?.mode === "fast" ? <Badge kind="warn">{t("dflash.enabled_stopped")}</Badge>
                : <Badge kind="idle">{t("dflash.disabled")}</Badge>}
            </div>
            <Toggle
              label={t("dflash.toggle")}
              checked={df?.mode === "fast"}
              disabled={busy || !df}
              onChange={(v) => update({ enabled: v })}
            />
          </div>
          <hr className="divider" style={{ margin: "16px 0" }} />
          <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", rowGap: 20 }}>
            <Stat label={t("dflash.accept")} value={fmtPct(rm?.acceptance_rate)} />
            <Stat label={t("dflash.cycle")} value={
              lastReq && typeof lastReq.tokens_per_cycle === "number"
                ? fmtNum(lastReq.tokens_per_cycle as number, 1) : t("common.emdash")
            } hint={t("dflash.cycle.hint")} />
            <Stat label={t("dflash.gen")} value={fmtNum(rm?.decode_tok_s, 1)} unit="tok/s" />
            <Stat label={t("dflash.fallbacks")} value={df?.fallback_count ?? 0} />
          </div>
          {!df?.metrics.available && df?.mode === "fast" && (
            <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 14 }}>
              {t("dflash.metrics.off", { reason: df.metrics.reason ?? t("dflash.metrics.reason") })}
            </p>
          )}
          {df?.engine && (
            <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 10 }}>
              {t("dflash.engine", { pkg: df.engine.package, ver: df.engine.version ?? "" })}
            </p>
          )}
        </div>
      </Section>

      <Section title={t("dflash.config")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">{t("dflash.draft")}</span>
            <span className="v">
              <select
                value={form?.draft_model ?? ""}
                disabled={busy || drafts.length === 0}
                onChange={(e) => { setForm((f) => f && { ...f, draft_model: e.target.value }); void update({ draft_model: e.target.value }); }}
              >
                {drafts.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
                {drafts.length === 0 && <option value="">{t("dflash.draft.none")}</option>}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              {t("dflash.block")}
              <small>{t("dflash.block.sub")}</small>
            </span>
            <span className="v mono">{t("dflash.block.unit", { n: df?.block_size_trained ?? 16 })}</span>
          </div>
          {official && (
            <>
              <div className="kv">
                <span className="k">
                  {t("dflash.block.runtime")}
                  <small>{t("dflash.block.runtime.sub")}</small>
                </span>
                <span className="v mono">{t("dflash.block.runtime.auto")}</span>
              </div>
              <div className="kv">
                <span className="k">
                  {t("dflash.bits")}
                  <small>{live.draft_bits ? t("dflash.bits.sub") : t("dflash.knob.intent")}</small>
                </span>
                <span className="v">
                  <select
                    value={df?.config.draft_bits ?? 4} disabled={busy}
                    onChange={(e) => void update({ draft_bits: Number(e.target.value) })}
                  >
                    <option value={0}>{t("dflash.cap.default")}</option>
                    <option value={4}>4</option>
                  </select>
                </span>
              </div>
              <div className="kv">
                <span className="k">
                  {t("dflash.reasoning")}
                  <small>{t("dflash.reasoning.sub")}</small>
                </span>
                <span className="v">
                  <select
                    value={df?.config.reasoning ?? "xhigh"} disabled={busy}
                    onChange={(e) => void update({ reasoning: e.target.value })}
                  >
                    <option value="default">{t("dflash.reasoning.default")}</option>
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="xhigh">xhigh</option>
                  </select>
                </span>
              </div>
            </>
          )}
          <div className="kv">
            <span className="k">
              {t("dflash.verify")}
              <small>{t("dflash.verify.sub")}</small>
            </span>
            <span className="v">
              <select
                value={form?.verify_mode ?? "adaptive"} disabled={busy}
                onChange={(e) => { setForm((f) => f && { ...f, verify_mode: e.target.value }); void update({ verify_mode: e.target.value }); }}
              >
                <option value="adaptive">{t("dflash.verify.adaptive")}</option>
                <option value="dflash">{t("dflash.verify.dflash")}</option>
                {!official && <option value="ddtree">{t("dflash.verify.ddtree")}</option>}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              {t("dflash.cap")}
              <small>{t("dflash.cap.sub")}</small>
            </span>
            <span className="v">
              <select
                value={form?.verify_len_cap ?? 0} disabled={busy}
                onChange={(e) => { const v = Number(e.target.value); setForm((f) => f && { ...f, verify_len_cap: v }); void update({ verify_len_cap: v }); }}
              >
                <option value={0}>{t("dflash.cap.default")}</option>
                <option value={4}>4</option>
                {official && <option value={5}>5</option>}
                {!official && <option value={8}>8</option>}
                {!official && <option value={16}>16</option>}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              {t("dflash.prefill")}
              <small>{live.prefill_step_size ? t("dflash.prefill.sub") : t("dflash.knob.intent")}</small>
            </span>
            <span className="v">
              <select
                value={df?.config.prefill_step_size ?? 2048} disabled={busy}
                onChange={(e) => void update({ prefill_step_size: Number(e.target.value) })}
              >
                {[1024, 2048, 4096, 8192].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">
              {t("dflash.cache.l2")}
              <small>{t("dflash.cache.l2.sub")}</small>
            </span>
            <span className="v">
              <Toggle
                label={t("dflash.cache.l2")}
                checked={df?.config.prefix_cache_l2 ?? true}
                disabled={busy || !live.prefix_cache_l2}
                onChange={(v) => update({ prefix_cache_l2: v })}
              />
            </span>
          </div>
          <div className="kv">
            <span className="k">
              {t("dflash.cache.limit")}
              <small>{live.cache_limit ? t("dflash.cache.limit.sub") : t("dflash.knob.intent")}</small>
            </span>
            <span className="v">
              <select
                value={df?.config.cache_limit ?? "4GB"} disabled={busy || !live.cache_limit}
                onChange={(e) => void update({ cache_limit: e.target.value })}
              >
                {["2GB", "4GB", "8GB"].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </span>
          </div>
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          {t("dflash.tune")}
        </p>
      </Section>

      <Section title={t("dflash.recent")}>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th className="num">{t("dflash.col.tokens")}</th><th className="num">{t("dflash.col.toks")}</th>
                <th className="num">{t("dflash.col.accept")}</th><th className="num">{t("dflash.col.cycle")}</th>
                <th className="num">{t("dflash.col.cycles")}</th>
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
                <tr><td colSpan={5}><div className="empty">{t("dflash.empty.recent")}</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
