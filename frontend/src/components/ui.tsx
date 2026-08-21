import { useEffect, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";

export function StatusDot({ kind, pulse }: { kind: "ok" | "warn" | "err" | "idle"; pulse?: boolean }) {
  return <span className={`status-dot ${kind}${pulse ? " pulse" : ""}`} aria-hidden />;
}

export function Badge({ kind, children }: { kind: "ok" | "warn" | "err" | "idle" | "accent"; children: ReactNode }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

export function Stat({ label, value, unit, hint }: {
  label: string; value: ReactNode; unit?: string; hint?: string;
}) {
  return (
    <div title={hint}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
    </div>
  );
}

export function Section({ title, children, actions }: {
  title: string; children: ReactNode; actions?: ReactNode;
}) {
  return (
    <section className="section">
      <div className="row between" style={{ marginBottom: 10 }}>
        <h2 className="section-title" style={{ margin: 0 }}>{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Toggle({ checked, onChange, disabled, label }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string;
}) {
  return (
    <button
      type="button" role="switch" aria-checked={checked} aria-label={label}
      className="toggle" disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  );
}

export function CopyField({ value, label }: { value: string; label?: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  return (
    <div className="copy-field">
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {label && <span style={{ color: "var(--text-3)", marginRight: 8 }}>{label}</span>}
        {value}
      </span>
      <button
        className="btn small" type="button"
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        }}
      >
        {copied ? t("common.copied") : t("common.copy")}
      </button>
    </div>
  );
}

export function AliasField({
  alias,
  aliasAuto = true,
  label,
  onSave,
  onReset,
}: {
  alias: string;
  aliasAuto?: boolean;
  label?: string;
  onSave: (name: string) => void | Promise<void>;
  onReset: () => void | Promise<void>;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(alias);
  const [copied, setCopied] = useState(false);
  useEffect(() => { setDraft(alias); }, [alias]);
  const dirty = draft.trim() !== alias;

  const save = async () => {
    const next = draft.trim().replace(/\s+/g, "-");
    if (!next) {
      setDraft(alias);
      return;
    }
    if (next === alias) return;
    await onSave(next);
  };

  return (
    <div>
      <div className="copy-field">
        <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flex: 1 }}>
          {label && <span style={{ color: "var(--text-3)", flex: "0 0 auto" }}>{label}</span>}
          <input
            className="alias-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => { void save(); }}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
            aria-label={label || t("api.model")}
            spellCheck={false}
          />
        </span>
        <button
          className="btn small"
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(draft.trim() || alias);
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
            void save();
          }}
        >
          {copied ? t("common.copied") : t("common.copy")}
        </button>
      </div>
      <p className="alias-hint">
        <span>
          {dirty ? t("api.alias.dirty") : aliasAuto ? t("api.alias.auto_hint") : t("api.alias.manual_hint")}
        </span>
        {(!aliasAuto || dirty) && (
          <button className="btn small" type="button" onClick={() => { void onReset(); }}>
            {t("api.alias.reset")}
          </button>
        )}
      </p>
    </div>
  );
}

export function Sparkline({ points, width = 120, height = 28, color = "var(--accent)" }: {
  points: (number | null | undefined)[]; width?: number; height?: number; color?: string;
}) {
  const vals = points.filter((p): p is number => typeof p === "number" && isFinite(p));
  if (vals.length < 2) return <svg className="sparkline" width={width} height={height} aria-hidden />;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  let d = "";
  points.forEach((p, i) => {
    if (typeof p !== "number" || !isFinite(p)) return;
    const x = i * step;
    const y = height - 3 - ((p - min) / span) * (height - 6);
    d += d ? ` L${x.toFixed(1)},${y.toFixed(1)}` : `M${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg className="sparkline" width={width} height={height} aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function AdvisoryBanner({ level, title, detail }: { level: string; title: string; detail: string }) {
  return (
    <div className={`advisory ${level === "critical" || level === "error" ? "err" : "warn"}`} role="alert">
      <span style={{ fontWeight: 600, flexShrink: 0 }}>{title}</span>
      <span style={{ opacity: 0.9 }}>{detail}</span>
    </div>
  );
}

export function ErrorPanel({ what, detail, onRetry }: { what: string; detail?: string; onRetry?: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="advisory err" role="alert" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
      <div className="row between">
        <span style={{ fontWeight: 600 }}>{what}</span>
        <span className="row" style={{ gap: 8 }}>
          {detail && (
            <button className="btn small" onClick={() => setOpen(!open)}>
              {open ? t("common.hide_details") : t("common.details")}
            </button>
          )}
          {onRetry && <button className="btn small" onClick={onRetry}>{t("common.retry")}</button>}
        </span>
      </div>
      {open && detail && <code style={{ whiteSpace: "pre-wrap", fontSize: 11 }}>{detail}</code>}
    </div>
  );
}

export function fmtBytes(n?: number | null): string {
  if (!n) return "—";
  if (n > 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n > 1e6) return `${(n / 1e6).toFixed(0)} MB`;
  return `${(n / 1e3).toFixed(0)} KB`;
}

export function fmtNum(n?: number | null, digits = 1): string {
  if (n === null || n === undefined || !isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function fmtPct(n?: number | null): string {
  if (n === null || n === undefined || !isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

export function fmtUptime(s?: number | null): string {
  if (!s) return "—";
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function fmtTime(t?: number | null): string {
  if (!t) return "—";
  return new Date(t * 1000).toLocaleString();
}
