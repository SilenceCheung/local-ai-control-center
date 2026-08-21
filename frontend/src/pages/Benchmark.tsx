import { useEffect, useState } from "react";
import { api, type BenchJob, type BenchRun } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, ErrorPanel, Section, Stat, fmtNum, fmtPct, fmtTime } from "../components/ui";
import { useI18n } from "../i18n";

interface GenResult {
  ok?: boolean; tokens?: number; total_s?: number; ttft_s?: number; tok_s?: number;
  ram_used_gb?: number; acceptance_rate?: number | null; error?: string;
}

export default function Benchmark() {
  const { t } = useI18n();
  const { data: prompts } = usePoll<Record<string, { label: string; max_tokens: number }>>(
    () => api.get("/benchmark/prompts"), 120000);
  const { data: job, refresh: refreshJob } = usePoll<BenchJob>(() => api.get("/benchmark/job"), 3000);
  const { data: history, refresh: refreshHistory } = usePoll<BenchRun[]>(
    () => api.get("/benchmark/history?limit=30"), 20000);
  const [promptKey, setPromptKey] = useState("coding_long");
  const [err, setErr] = useState<string | null>(null);
  const [wasBusy, setWasBusy] = useState(false);

  useEffect(() => {
    if (job?.busy) setWasBusy(true);
    else if (wasBusy) { setWasBusy(false); void refreshHistory(); }
  }, [job?.busy, wasBusy, refreshHistory]);

  const run = async (path: string, body?: unknown) => {
    setErr(null);
    try {
      const r = await api.post<{ ok: boolean; error?: string }>(path, body);
      if (!r.ok && r.error) setErr(r.error);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      void refreshJob();
    }
  };

  const busy = job?.busy ?? false;
  const current = job?.job;

  return (
    <>
      <h1 className="page-title">{t("nav.benchmark")}</h1>
      <p className="page-sub">{t("bench.sub")}</p>

      {err && <ErrorPanel what={t("bench.err.start")} detail={err} />}

      <Section title={t("bench.run")}>
        <div className="card">
          <div className="row" style={{ marginBottom: 14 }}>
            <label htmlFor="bench-prompt" className="stat-label">Prompt</label>
            <select id="bench-prompt" value={promptKey} onChange={(e) => setPromptKey(e.target.value)} disabled={busy}>
              {Object.entries(prompts ?? {}).map(([k, v]) => (
                <option key={k} value={k}>{v.label} · {v.max_tokens} tok</option>
              ))}
            </select>
          </div>
          <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
            <button className="btn primary" disabled={busy}
                    onClick={() => run("/benchmark/quick", { prompt_key: promptKey })}>
              {t("bench.quick")}
            </button>
            <button className="btn" disabled={busy}
                    onClick={() => run("/benchmark/ab", { prompt_key: promptKey })}>
              {t("bench.ab")}
            </button>
            <button className="btn" disabled={busy} onClick={() => run("/benchmark/autotune")}>
              {t("bench.autotune")}
            </button>
            <button className="btn" disabled={busy} onClick={() => run("/benchmark/tool-calling")}>
              {t("bench.tool")}
            </button>
          </div>
          <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 10 }}>
            A/B and Auto Tune restart the runtime between passes (the model reloads for each configuration) —
            expect several minutes. The previous mode is restored afterwards.
          </p>
        </div>
      </Section>

      {current && (busy || current.status !== "done" || recentlyFinished(current)) && (
        <Section title={t("bench.job")}>
          <div className="card">
            <div className="row between" style={{ marginBottom: 10 }}>
              <span className="row" style={{ gap: 8 }}>
                {busy && <span className="spin" aria-hidden />}
                <span style={{ fontWeight: 600 }}>{current.kind}</span>
                {current.status === "running" ? <Badge kind="accent">{current.current}</Badge>
                  : current.status === "done" ? <Badge kind="ok">{t("bench.done")}</Badge>
                  : <Badge kind="err">{current.status}</Badge>}
              </span>
            </div>
            {current.status === "error" && (
              <ErrorPanel what={t("bench.err.job")} detail={current.error} />
            )}
            <ol style={{ margin: 0, paddingLeft: 18, color: "var(--text-2)", fontSize: 12 }}>
              {current.steps.map((s, i) => (
                <li key={i}>{s.step}{s.detail && <span style={{ color: "var(--text-3)" }}> — {s.detail}</span>}</li>
              ))}
            </ol>
            {current.status === "done" && current.result != null && (
              <JobResult kind={current.kind} result={current.result} />
            )}
          </div>
        </Section>
      )}

      <Section title={t("bench.history")}>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 160 }}>{t("bench.col.time")}</th><th>{t("bench.col.kind")}</th><th>{t("bench.col.prompt")}</th>
                <th className="num">{t("bench.col.toks")}</th><th className="num">{t("bench.col.ttft")}</th>
                <th className="num">{t("bench.col.speedup")}</th><th className="num">{t("bench.col.accept")}</th>
              </tr>
            </thead>
            <tbody>
              {(history ?? []).map((h) => {
                const r = h.results as Record<string, GenResult | number | string | boolean | undefined>;
                const dflash = r.dflash as GenResult | undefined;
                const single = (typeof r.tok_s === "number" ? r as GenResult : undefined);
                const tokS = dflash?.tok_s ?? single?.tok_s;
                const ttft = dflash?.ttft_s ?? single?.ttft_s;
                const acc = dflash?.acceptance_rate ?? single?.acceptance_rate;
                const ok = (r.ok as boolean | undefined) ?? single?.ok;
                return (
                  <tr key={h.id}>
                    <td style={{ color: "var(--text-2)" }}>{fmtTime(h.created_at)}</td>
                    <td><Badge kind={ok === false ? "err" : "idle"}>{h.kind}</Badge></td>
                    <td>{h.label}</td>
                    <td className="num">{fmtNum(tokS as number | undefined, 1)}</td>
                    <td className="num">{ttft != null ? `${fmtNum(ttft as number, 2)}s` : t("common.emdash")}</td>
                    <td className="num">{typeof r.speedup === "number" ? `${r.speedup}×` : t("common.emdash")}</td>
                    <td className="num">{typeof acc === "number" ? fmtPct(acc) : t("common.emdash")}</td>
                  </tr>
                );
              })}
              {(history ?? []).length === 0 && (
                <tr><td colSpan={7}><div className="empty">{t("bench.empty")}</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}

function recentlyFinished(job: { finished_at?: number }): boolean {
  return job.finished_at != null && Date.now() / 1000 - job.finished_at < 600;
}

function JobResult({ kind, result }: { kind: string; result: Record<string, unknown> }) {
  const { t } = useI18n();
  if (kind === "ab") {
    const normal = result.normal as GenResult | undefined;
    const dflash = result.dflash as GenResult | undefined;
    return (
      <div style={{ marginTop: 16 }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)", rowGap: 18 }}>
          <Stat label={t("bench.normal")} value={fmtNum(normal?.tok_s, 1)} unit="tok/s" />
          <Stat label={t("bench.fast")} value={fmtNum(dflash?.tok_s, 1)} unit="tok/s" />
          <Stat label={t("bench.col.speedup")} value={typeof result.speedup === "number" ? `${result.speedup}×` : t("common.emdash")} />
          <Stat label={t("bench.ttft.ab")}
                value={`${fmtNum(normal?.ttft_s, 2)} / ${fmtNum(dflash?.ttft_s, 2)}`} unit="s" />
          <Stat label={t("bench.ram")} value={fmtNum(dflash?.ram_used_gb, 1)} unit="GB" />
          <Stat label={t("bench.col.accept")} value={typeof dflash?.acceptance_rate === "number" ? fmtPct(dflash.acceptance_rate) : t("common.emdash")} />
        </div>
        {(normal?.error || dflash?.error) && (
          <p style={{ color: "var(--err)", fontSize: 12, marginTop: 12 }}>
            {normal?.error && <>{t("bench.pass.normal", { e: normal.error })}<br /></>}
            {dflash?.error && <>{t("bench.pass.dflash", { e: dflash.error })}</>}
          </p>
        )}
      </div>
    );
  }
  if (kind === "autotune") {
    const cands = (result.candidates as Array<GenResult & { label: string }> | undefined) ?? [];
    return (
      <div style={{ marginTop: 16 }}>
        {typeof result.recommendation_text === "string" && (
          <p style={{ fontWeight: 600, marginTop: 0 }}>{result.recommendation_text}</p>
        )}
        <table className="tbl">
          <thead><tr><th>{t("bench.col.config")}</th><th className="num">{t("bench.col.toks")}</th><th className="num">{t("bench.col.ttft")}</th><th className="num">{t("bench.col.accept")}</th></tr></thead>
          <tbody>
            {cands.map((c, i) => (
              <tr key={i}>
                <td>{c.label}{c.error && <span style={{ color: "var(--err)" }}> — {c.error}</span>}</td>
                <td className="num">{fmtNum(c.tok_s, 1)}</td>
                <td className="num">{c.ttft_s != null ? `${fmtNum(c.ttft_s, 2)}s` : t("common.emdash")}</td>
                <td className="num">{typeof c.acceptance_rate === "number" ? fmtPct(c.acceptance_rate) : t("common.emdash")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (kind === "tool_calling") {
    return (
      <div style={{ marginTop: 16 }}>
        <div className="row" style={{ gap: 8 }}>
          {result.supported
            ? <Badge kind="ok">{t("bench.tools.ok")}</Badge>
            : <Badge kind="err">{t("bench.tools.none")}</Badge>}
          {result.valid_call === true && <Badge kind="ok">{t("bench.tools.json")}</Badge>}
          {typeof result.finish_reason === "string" && <Badge kind="idle">{t("bench.tools.finish", { r: result.finish_reason })}</Badge>}
        </div>
        {result.tool_calls != null && (
          <code style={{ display: "block", marginTop: 10, fontSize: 11, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(result.tool_calls, null, 2)}
          </code>
        )}
      </div>
    );
  }
  const r = result as GenResult & { mode?: string };
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginTop: 16 }}>
      <Stat label={t("bench.speed.mode", { m: r.mode ?? "current" })} value={fmtNum(r.tok_s, 1)} unit="tok/s" />
      <Stat label={t("bench.col.ttft")} value={fmtNum(r.ttft_s, 2)} unit="s" />
      <Stat label={t("bench.tokens")} value={r.tokens ?? t("common.emdash")} />
      <Stat label={t("bench.col.accept")} value={typeof r.acceptance_rate === "number" ? fmtPct(r.acceptance_rate) : t("common.emdash")} />
    </div>
  );
}
