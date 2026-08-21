import { useMetricsStream } from "../hooks/useMetricsStream";
import { AdvisoryBanner, Badge, Section, Sparkline, fmtNum, fmtPct } from "../components/ui";
import { useI18n } from "../i18n";

export default function Monitoring() {
  const { t } = useI18n();
  const { samples, memoryAdvisory, connected, latest } = useMetricsStream(300);

  const series = (f: (s: typeof samples[number]) => number | null | undefined) => samples.map(f);
  const pressure = latest?.pressure_level;
  const pressureLabel = pressure === 4 ? t("monitor.pressure.critical")
    : pressure === 2 ? t("monitor.pressure.warn")
    : pressure === 1 ? t("monitor.pressure.ok")
    : t("common.emdash");

  return (
    <>
      <h1 className="page-title">{t("nav.monitoring")}</h1>
      <p className="page-sub">
        {t("monitor.sub", { state: connected ? t("monitor.connected") : t("monitor.reconnect") })}
      </p>

      {memoryAdvisory && <AdvisoryBanner {...memoryAdvisory} />}

      <Section title={t("monitor.system")}>
        <div className="card" style={{ padding: 0 }}>
          <MetricRow label={t("monitor.mem")} value={`${fmtNum(latest?.mem_used_gb, 1)} GB`}
                     sub={t("monitor.mem.of", { n: fmtNum(latest?.mem_total_gb, 0) })}
                     spark={series((s) => s.mem_used_gb)}
                     status={latest && latest.mem_pct > 90 ? "warn" : "ok"} />
          <MetricRow label={t("monitor.pressure")} value={pressureLabel}
                     spark={series((s) => s.pressure_level ?? 1)}
                     status={pressure === 4 ? "err" : pressure === 2 ? "warn" : "ok"} />
          <MetricRow label={t("monitor.swap")} value={`${fmtNum(latest?.swap_used_gb, 1)} GB`}
                     spark={series((s) => s.swap_used_gb)}
                     status={latest && latest.swap_used_gb > 4 ? "warn" : "ok"} />
          <MetricRow label={t("monitor.cpu")} value={`${fmtNum(latest?.cpu_pct, 0)}%`}
                     spark={series((s) => s.cpu_pct)} status="ok" />
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          {t("monitor.gpu")}
        </p>
      </Section>

      <Section title={t("monitor.inference")}>
        {latest?.runtime ? (
          <div className="card" style={{ padding: 0 }}>
            <MetricRow label={t("monitor.generation")} value={`${fmtNum(latest.runtime.decode_tok_s, 1)} tok/s`}
                       spark={series((s) => s.runtime?.decode_tok_s)} status="ok" />
            <MetricRow label={t("monitor.prompt")} value={`${fmtNum(latest.runtime.prefill_tok_s, 0)} tok/s`}
                       spark={series((s) => s.runtime?.prefill_tok_s)} status="ok" />
            <MetricRow label={t("monitor.ttft")} value={latest.runtime.ttft_s != null ? `${fmtNum(latest.runtime.ttft_s, 2)} s` : t("common.emdash")}
                       spark={series((s) => s.runtime?.ttft_s)} status="ok" />
            <MetricRow label={t("monitor.accept")} value={fmtPct(latest.runtime.acceptance_rate)}
                       spark={series((s) => s.runtime?.acceptance_rate)} status="ok" />
            <MetricRow label={t("monitor.rss")} value={`${fmtNum(latest.runtime.rss_gb, 1)} GB`}
                       spark={series((s) => s.runtime?.rss_gb)} status="ok" />
            <div className="kv" style={{ padding: "10px 20px" }}>
              <span className="k">{t("monitor.active")}</span>
              <span className="v">{latest.runtime.active_request
                ? <Badge kind="accent">{t("monitor.in_flight")}</Badge> : <Badge kind="idle">{t("monitor.idle")}</Badge>}</span>
            </div>
          </div>
        ) : (
          <div className="card">
            <div className="empty">
              {t("monitor.safe_note")}
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
