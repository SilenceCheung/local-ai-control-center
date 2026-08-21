import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Toggle } from "../components/ui";
import { useI18n } from "../i18n";

interface LogData { ok: boolean; lines: string[]; path?: string; error?: string; total_lines?: number }

export default function Logs() {
  const { t } = useI18n();
  const [category, setCategory] = useState("runtime");
  const [query, setQuery] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [importantOnly, setImportantOnly] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [data, setData] = useState<LogData | null>(null);
  const viewRef = useRef<HTMLDivElement>(null);
  const categories = [
    { id: "runtime", label: t("logs.cat.runtime") },
    { id: "api", label: t("logs.cat.api") },
    { id: "backend", label: t("logs.cat.backend") },
    { id: "benchmark", label: t("logs.cat.benchmark") },
  ];
  const downMsg = t("logs.down");

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const d = await api.get<LogData>(
          `/logs?category=${category}&lines=400&query=${encodeURIComponent(query)}` +
          `&errors_only=${errorsOnly}&important_only=${importantOnly}`);
        if (!stop) setData(d);
      } catch {
        if (!stop) setData({ ok: false, lines: [], error: downMsg });
      }
    };
    void load();
    const tick = setInterval(() => { if (!document.hidden) void load(); }, 4000);
    return () => { stop = true; clearInterval(tick); };
  }, [category, query, errorsOnly, importantOnly, downMsg]);

  useEffect(() => {
    if (autoScroll && viewRef.current) {
      viewRef.current.scrollTop = viewRef.current.scrollHeight;
    }
  }, [data, autoScroll]);

  const classify = (line: string) =>
    /error|critical|traceback|exception|failed|crash/i.test(line) ? "err"
    : /warn/i.test(line) ? "warn" : "";

  return (
    <>
      <h1 className="page-title">{t("nav.logs")}</h1>
      <p className="page-sub">{t("logs.sub")}</p>

      <div className="row" style={{ marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label={t("logs.cat.runtime")}>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <input type="text" placeholder={t("logs.search")} value={query}
               onChange={(e) => setQuery(e.target.value)} style={{ width: 200 }} aria-label={t("logs.search")} />
        <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--text-2)" }}>
          <Toggle checked={errorsOnly} onChange={setErrorsOnly} label={t("logs.errors")} /> {t("logs.errors")}
        </label>
        <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--text-2)" }}>
          <Toggle checked={importantOnly} onChange={(v) => setImportantOnly(v)} label={t("logs.important")} /> {t("logs.important")}
        </label>
        <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--text-2)" }}>
          <Toggle checked={autoScroll} onChange={setAutoScroll} label={t("logs.autoscroll")} /> {t("logs.autoscroll")}
        </label>
        <button className="btn small" onClick={() => navigator.clipboard.writeText((data?.lines ?? []).join("\n"))}>
          {t("common.copy")}
        </button>
      </div>

      <div className="log-view" ref={viewRef} role="log" aria-live="off" tabIndex={0}>
        {(data?.lines ?? []).map((l, i) => (
          <div key={i} className={`log-line ${classify(l)}`}>{l}</div>
        ))}
        {data && data.lines.length === 0 && (
          <div style={{ color: "var(--text-3)" }}>
            {data.error ?? t("logs.empty")}
          </div>
        )}
      </div>
      {data?.path && (
        <p style={{ color: "var(--text-3)", fontSize: 11, marginTop: 8 }} className="mono">
          {t("logs.meta", { path: data.path, n: data.total_lines ?? 0 })}
        </p>
      )}
    </>
  );
}
