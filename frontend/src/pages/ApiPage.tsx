import { api, type AppConfig, type RuntimeStatus } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, CopyField, AliasField, Section, Stat, StatusDot, fmtTime } from "../components/ui";
import { useI18n } from "../i18n";

interface GatewayStats {
  ok: boolean; live: boolean;
  stats: {
    started_at: number; requests_total: number; requests_active: number;
    errors_total: number; tokens_generated: number; last_request_at: number | null;
    agents_seen: Record<string, number>;
  } | null;
}

export default function ApiPage() {
  const { t } = useI18n();
  const { data: cfg, refresh: refreshCfg } = usePoll<AppConfig>(() => api.get("/settings"), 30000);
  const { data: rt } = usePoll<RuntimeStatus>(() => api.get("/runtime/status"), 6000);
  const { data: gw } = usePoll<GatewayStats>(() => api.get("/gateway/stats"), 6000);

  const base = cfg ? `http://${cfg.api.host}:${cfg.api.port}/v1` : "http://127.0.0.1:8080/v1";
  const s = gw?.stats;

  return (
    <>
      <h1 className="page-title">{t("nav.api")}</h1>
      <p className="page-sub">{t("api.sub")}</p>

      <Section title={t("api.connection")}>
        <div className="grid" style={{ gridTemplateColumns: "1fr", gap: 8 }}>
          <CopyField label={t("api.base")} value={base} />
          <CopyField label={t("api.key")} value={cfg?.api.api_key ?? "local"} />
          <AliasField
            alias={cfg?.api.alias ?? "Qwen3.8-27B-Heretic-8bit"}
            aliasAuto={cfg?.api.alias_auto ?? true}
            label={t("api.model")}
            onSave={async (name) => {
              await api.put("/settings", { api: { alias: name, alias_auto: false } });
              void refreshCfg();
            }}
            onReset={async () => {
              await api.put("/settings", { api: { alias_auto: true } });
              void refreshCfg();
            }}
          />
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          {t("api.listen")}
        </p>
      </Section>

      <Section title={t("api.server")}>
        <div className="card">
          <div className="row" style={{ gap: 10, marginBottom: 16 }}>
            <StatusDot kind={gw?.live ? (rt?.http_healthy ? "ok" : "warn") : "err"} />
            <span style={{ fontWeight: 600 }}>
              {gw?.live ? t("api.gw.running") : t("api.gw.down")}
            </span>
            {gw?.live && (rt?.http_healthy
              ? <Badge kind="ok">{t("api.rt.ok")}</Badge>
              : <Badge kind="warn">{t("api.rt.status", { s: rt?.status ?? "stopped" })}</Badge>)}
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            <Stat label={t("api.requests")} value={s?.requests_total ?? t("common.emdash")} />
            <Stat label={t("api.active")} value={s?.requests_active ?? t("common.emdash")} />
            <Stat label={t("api.tokens")} value={s ? s.tokens_generated.toLocaleString() : t("common.emdash")}
                  hint={t("api.tokens.hint")} />
            <Stat label={t("api.errors")} value={s?.errors_total ?? t("common.emdash")} />
          </div>
          <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 14 }}>
            {t("api.last", { t: fmtTime(s?.last_request_at) })}
          </p>
        </div>
      </Section>

      <Section title={t("api.endpoints")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv"><span className="k mono">GET /v1/models</span>
            <span className="v"><Badge kind="ok">{t("api.supported")}</Badge></span></div>
          <div className="kv"><span className="k mono">POST /v1/chat/completions</span>
            <span className="v"><Badge kind="ok">{t("api.supported.stream")}</Badge></span></div>
          <div className="kv">
            <span className="k mono">POST /v1/responses
              <small>{t("api.responses.sub")}</small>
            </span>
            <span className="v">{rt?.mode === "fast"
              ? <Badge kind="warn">{t("api.partial")}</Badge>
              : <Badge kind="idle">{t("api.not_safe")}</Badge>}</span>
          </div>
          <div className="kv"><span className="k mono">POST /v1/completions</span>
            <span className="v"><Badge kind="warn">{t("api.depends")}</Badge></span></div>
        </div>
      </Section>

      <Section title={t("api.curl")}>
        <div className="card">
          <code style={{ whiteSpace: "pre-wrap", display: "block", fontSize: 11.5, lineHeight: 1.7 }}>
{`curl ${base}/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${cfg?.api.alias ?? "Qwen3.8-27B-Heretic-8bit"}", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100, "stream": true}'`}
          </code>
        </div>
      </Section>
    </>
  );
}
