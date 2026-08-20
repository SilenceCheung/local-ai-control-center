import { useMetricsStream } from "../hooks/useMetricsStream";
import { AdvisoryBanner, Badge, Section, Sparkline, fmtNum, fmtPct } from "../components/ui";

export default function Monitoring() {
  const { samples, memoryAdvisory, connected, latest } = useMetricsStream(300);

  const series = (f: (s: typeof samples[number]) => number | null | undefined) => samples.map(f);
  const pressure = latest?.pressure_level;
  const pressureLabel = pressure === 4 ? "critical" : pressure === 2 ? "warning" : pressure === 1 ? "normal" : "—";

  return (
    <>
      <h1 className="page-title">Monitoring</h1>
      <p className="page-sub">
        Live via server-sent events {connected ? "· connected" : "· reconnecting…"} — 2 s sampling, 15 min window
      </p>

      {memoryAdvisory && <AdvisoryBanner {...memoryAdvisory} />}

      <Section title="System">
        <div className="card" style={{ padding: 0 }}>
          <MetricRow label="Unified Memory" value={`${fmtNum(latest?.mem_used_gb, 1)} GB`}
                     sub={`of ${fmtNum(latest?.mem_total_gb, 0)} GB`}
                     spark={series((s) => s.mem_used_gb)}
                     status={latest && latest.mem_pct > 90 ? "warn" : "ok"} />
          <MetricRow label="Memory Pressure" value={pressureLabel}
                     spark={series((s) => s.pressure_level ?? 1)}
                     status={pressure === 4 ? "err" : pressure === 2 ? "warn" : "ok"} />
          <MetricRow label="Swap" value={`${fmtNum(latest?.swap_used_gb, 1)} GB`}
                     spark={series((s) => s.swap_used_gb)}
                     status={latest && latest.swap_used_gb > 4 ? "warn" : "ok"} />
          <MetricRow label="CPU" value={`${fmtNum(latest?.cpu_pct, 0)}%`}
                     spark={series((s) => s.cpu_pct)} status="ok" />
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          GPU utilization is not exposed by macOS without elevated privileges — deliberately not shown rather than faked.
        </p>
      </Section>

      <Section title="Inference">
        {latest?.runtime ? (
          <div className="card" style={{ padding: 0 }}>
            <MetricRow label="Generation" value={`${fmtNum(latest.runtime.decode_tok_s, 1)} tok/s`}
                       spark={series((s) => s.runtime?.decode_tok_s)} status="ok" />
            <MetricRow label="Prompt Processing" value={`${fmtNum(latest.runtime.prefill_tok_s, 0)} tok/s`}
                       spark={series((s) => s.runtime?.prefill_tok_s)} status="ok" />
            <MetricRow label="TTFT" value={latest.runtime.ttft_s != null ? `${fmtNum(latest.runtime.ttft_s, 2)} s` : "—"}
                       spark={series((s) => s.runtime?.ttft_s)} status="ok" />
            <MetricRow label="Acceptance Rate" value={fmtPct(latest.runtime.acceptance_rate)}
                       spark={series((s) => s.runtime?.acceptance_rate)} status="ok" />
            <MetricRow label="Runtime RSS" value={`${fmtNum(latest.runtime.rss_gb, 1)} GB`}
                       spark={series((s) => s.runtime?.rss_gb)} status="ok" />
            <div className="kv" style={{ padding: "10px 20px" }}>
              <span className="k">Active request</span>
              <span className="v">{latest.runtime.active_request
                ? <Badge kind="accent">in flight</Badge> : <Badge kind="idle">idle</Badge>}</span>
            </div>
          </div>
        ) : (
          <div className="card">
            <div className="empty">
              Runtime metrics appear when the engine is running in Fast Mode (dflash-mlx exposes /metrics).
              In Safe Mode, mlx-lm does not publish runtime metrics — shown as unavailable rather than invented.
            </div>
          </div>
        )}
      </Section>
    </>
  );
}

function MetricRow({ label, value, sub, spark, status }: {
  label: string; value: string; sub?: string;
  spark: (number | null | undefined)[]; status: "ok" | "warn" | "err";
}) {
  return (
    <div className="kv" style={{ padding: "12px 20px" }}>
      <span className="k">{label}{sub && <small>{sub}</small>}</span>
      <span className="v" style={{ gap: 16 }}>
        <Sparkline points={spark} color={status === "ok" ? "var(--text-3)" : status === "warn" ? "var(--warn)" : "var(--err)"} />
        <span style={{
          minWidth: 90, textAlign: "right", fontVariantNumeric: "tabular-nums",
          color: "var(--text)", fontWeight: 500,
        }}>{value}</span>
      </span>
    </div>
  );
}
