import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Toggle } from "../components/ui";

interface LogData { ok: boolean; lines: string[]; path?: string; error?: string; total_lines?: number }

const CATEGORIES = [
  { id: "runtime", label: "Runtime" },
  { id: "api", label: "API" },
  { id: "backend", label: "Backend" },
  { id: "benchmark", label: "Benchmark" },
];

export default function Logs() {
  const [category, setCategory] = useState("runtime");
  const [query, setQuery] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [importantOnly, setImportantOnly] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [data, setData] = useState<LogData | null>(null);
  const viewRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const d = await api.get<LogData>(
          `/logs?category=${category}&lines=400&query=${encodeURIComponent(query)}` +
          `&errors_only=${errorsOnly}&important_only=${importantOnly}`);
        if (!stop) setData(d);
      } catch {
        if (!stop) setData({ ok: false, lines: [], error: "backend unreachable" });
      }
    };
    void load();
    const t = setInterval(() => { if (!document.hidden) void load(); }, 4000);
    return () => { stop = true; clearInterval(t); };
  }, [category, query, errorsOnly, importantOnly]);

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
      <h1 className="page-title">Logs</h1>
      <p className="page-sub">Noise-filtered by default — warnings, errors, restarts, model loads and benchmarks first</p>

      <div className="row" style={{ marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Log category">
          {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <input type="text" placeholder="Search…" value={query}
               onChange={(e) => setQuery(e.target.value)} style={{ width: 200 }} aria-label="Search logs" />
        <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--text-2)" }}>
          <Toggle checked={errorsOnly} onChange={setErrorsOnly} label="Errors only" /> Errors only
        </label>
        <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--text-2)" }}>
          <Toggle checked={importantOnly} onChange={(v) => setImportantOnly(v)} label="Important only" /> Important only
        </label>
        <label className="row" style={{ gap: 6, fontSize: 12, color: "var(--text-2)" }}>
          <Toggle checked={autoScroll} onChange={setAutoScroll} label="Auto scroll" /> Auto scroll
        </label>
        <button className="btn small" onClick={() => navigator.clipboard.writeText((data?.lines ?? []).join("\n"))}>
          Copy
        </button>
      </div>

      <div className="log-view" ref={viewRef} role="log" aria-live="off" tabIndex={0}>
        {(data?.lines ?? []).map((l, i) => (
          <div key={i} className={`log-line ${classify(l)}`}>{l}</div>
        ))}
        {data && data.lines.length === 0 && (
          <div style={{ color: "var(--text-3)" }}>
            {data.error ?? "No matching log lines."}
          </div>
        )}
      </div>
      {data?.path && (
        <p style={{ color: "var(--text-3)", fontSize: 11, marginTop: 8 }} className="mono">
          {data.path} · {data.total_lines ?? 0} lines total
        </p>
      )}
    </>
  );
}
