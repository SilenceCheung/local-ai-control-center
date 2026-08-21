import { useEffect, useState } from "react";
import { api, type AppConfig, type RecipesStatus } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, AliasField, ErrorPanel, Section, Toggle } from "../components/ui";
import { useI18n } from "../i18n";

interface ServiceStatus {
  [k: string]: { service: string; label: string; installed: boolean; loaded: boolean; pid: number | null };
}

export default function Settings() {
  const { t, pref, setPref } = useI18n();
  const { data: cfg, refresh } = usePoll<AppConfig>(() => api.get("/settings"), 30000);
  const { data: recipes, refresh: refreshRecipes } = usePoll<RecipesStatus>(() => api.get("/recipes"), 15000);
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

  if (!cfg) return <p className="empty">{t("settings.loading")}</p>;

  return (
    <>
      <h1 className="page-title">{t("nav.settings")}</h1>
      <p className="page-sub">{t("settings.sub")}</p>

      {err && <ErrorPanel what={t("settings.err")} detail={err} />}
      {restartNeeded && (
        <div className="advisory warn" role="status">
          <span>{t("settings.restart.body")}</span>
          <button className="btn small" onClick={async () => { await api.post("/runtime/restart"); setRestartNeeded(false); }}>
            {t("settings.restart.now")}
          </button>
        </div>
      )}

      <Section title={t("settings.general")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">{t("lang.label")}</span>
            <span className="v">
              <select aria-label={t("lang.label")} value={pref} onChange={(e) => setPref(e.target.value as "system" | "en" | "zh-Hans")}>
                <option value="system">{t("lang.system")}</option>
                <option value="en">{t("lang.en")}</option>
                <option value="zh-Hans">{t("lang.zh")}</option>
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">{t("settings.appearance")}</span>
            <span className="v">
              <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label={t("settings.appearance")}>
                <option value="system">{t("settings.theme.system")}</option>
                <option value="light">{t("settings.theme.light")}</option>
                <option value="dark">{t("settings.theme.dark")}</option>
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">{t("settings.alias")}<small>{t("settings.alias.sub")}</small></span>
            <span className="v" style={{ flex: 1, justifyContent: "flex-end" }}>
              {cfg && (
                <div style={{ minWidth: 280, maxWidth: 420, width: "100%" }}>
                  <AliasField
                    alias={cfg.api.alias}
                    aliasAuto={cfg.api.alias_auto ?? true}
                    onSave={(name) => patch({ api: { alias: name, alias_auto: false } })}
                    onReset={() => patch({ api: { alias_auto: true } })}
                  />
                </div>
              )}
            </span>
          </div>
        </div>
      </Section>

      <Section title={t("settings.runtime")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">{t("settings.recipe")}<small>{t("settings.recipe.sub")}</small></span>
            <span className="v">
              <select
                aria-label={t("settings.recipe")}
                value={recipes?.active ?? "heretic"}
                onChange={async (e) => {
                  setErr(null);
                  try {
                    const r = await api.post<{ restart_required: boolean }>("/recipes/activate", { id: e.target.value });
                    if (r.restart_required) setRestartNeeded(true);
                  } catch (ex) {
                    setErr(ex instanceof Error ? ex.message : String(ex));
                  } finally {
                    void refresh(); void refreshRecipes();
                  }
                }}
              >
                <option value="heretic">{t("settings.recipe.heretic")}</option>
                <option value="official_dflash2">{t("settings.recipe.official")}</option>
              </select>
            </span>
          </div>
          <p style={{ color: "var(--text-3)", fontSize: 11.5, margin: "0 0 8px" }}>
            {(recipes?.active ?? "heretic") === "official_dflash2"
              ? t("settings.recipe.official.sub")
              : t("settings.recipe.heretic.sub")}
          </p>
          {cfg.runtime.target_model && (
            <div className="kv">
              <span className="k">{t("api.model")}</span>
              <span className="v mono" style={{ fontSize: 11 }}>{cfg.runtime.target_model}</span>
            </div>
          )}
          {!!recipes?.missing?.length && (
            <p style={{ color: "var(--warn, #b45309)", fontSize: 12, margin: "8px 0" }}>
              {t("dflash.missing")}{" "}
              {recipes.missing.map((m) => m.id).join(" · ")}{" "}
              <a href={`/models?tab=discover&q=${encodeURIComponent(recipes.missing[0].id)}`}>
                {t("dflash.missing.download")}
              </a>
            </p>
          )}
          <div className="kv">
            <span className="k">{t("settings.context")}<small>{t("settings.context.sub")}</small></span>
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
            <span className="k">{t("settings.tokens")}</span>
            <span className="v">
              <select value={cfg.runtime.default_max_tokens}
                      onChange={(e) => patch({ runtime: { default_max_tokens: Number(e.target.value) } })}>
                {[1024, 2048, 4096, 8192, 16384].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </span>
          </div>
          <div className="kv">
            <span className="k">{t("settings.thinking")}<small>{t("settings.thinking.sub")}</small></span>
            <span className="v">
              <Toggle checked={cfg.runtime.enable_thinking}
                      onChange={(v) => patch({ runtime: { enable_thinking: v } })} label={t("settings.thinking")} />
            </span>
          </div>
        </div>
      </Section>

      <Section title={t("settings.startup")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">{t("settings.autoload")}
              <small>{t("settings.autoload.sub")}</small></span>
            <span className="v">
              <Toggle checked={cfg.runtime.auto_load}
                      onChange={(v) => patch({ runtime: { auto_load: v } })} label={t("settings.autoload.short")} />
            </span>
          </div>
          {["backend", "gateway"].map((s) => (
            <div className="kv" key={s}>
              <span className="k">launchd · {s}
                <small>{svc?.[s]?.label ?? ""}</small></span>
              <span className="v">
                {svc?.[s]?.loaded ? <Badge kind="ok">{t("settings.launchd.running", { pid: svc[s].pid ?? "?" })}</Badge>
                  : svc?.[s]?.installed ? <Badge kind="warn">{t("settings.launchd.installed")}</Badge>
                  : <Badge kind="idle">{t("settings.launchd.none")}</Badge>}
                {svc?.[s]?.installed
                  ? <button className="btn small" onClick={() => svcAction(s, "uninstall")}>{t("settings.remove")}</button>
                  : <button className="btn small" onClick={() => svcAction(s, "install")}>{t("settings.install")}</button>}
              </span>
            </div>
          ))}
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          {t("settings.launchd.note")}
        </p>
      </Section>

      <Section title={t("settings.privacy")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv">
            <span className="k">{t("settings.telemetry")}</span>
            <span className="v"><Badge kind="ok">{t("settings.telemetry.none")}</Badge></span>
          </div>
          <div className="kv">
            <span className="k">{t("settings.prompts")}<small>{t("settings.prompts.sub")}</small></span>
            <span className="v">
              <Toggle checked={cfg.privacy.log_prompts}
                      onChange={(v) => patch({ privacy: { log_prompts: v } })} label={t("settings.prompts")} />
            </span>
          </div>
        </div>
      </Section>

      <Section title={t("settings.advanced")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv" style={{ cursor: "pointer" }} onClick={() => setAdvancedOpen(!advancedOpen)}
               role="button" tabIndex={0}
               onKeyDown={(e) => e.key === "Enter" && setAdvancedOpen(!advancedOpen)}>
            <span className="k">{t("settings.advanced.show")}</span>
            <span className="v">{advancedOpen ? t("settings.hide") : t("settings.show")}</span>
          </div>
          {advancedOpen && (
            <>
              <div className="kv">
                <span className="k">{t("settings.api_port")}</span>
                <span className="v mono">{cfg.api.port}</span>
              </div>
              <div className="kv">
                <span className="k">{t("settings.dash_port")}</span>
                <span className="v mono">{cfg.dashboard.port}</span>
              </div>
              <div className="kv">
                <span className="k">{t("settings.rt_port")}</span>
                <span className="v mono">{cfg.runtime.internal_port}</span>
              </div>
              <div className="kv">
                <span className="k">{t("settings.bind")}<small>{t("settings.bind.sub")}</small></span>
                <span className="v mono">127.0.0.1</span>
              </div>
              <div className="kv">
                <span className="k">{t("settings.log_level")}</span>
                <span className="v">
                  <select value={cfg.logging.level}
                          onChange={(e) => patch({ logging: { level: e.target.value } })}>
                    {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => <option key={l}>{l}</option>)}
                  </select>
                </span>
              </div>
              <div className="kv">
                <span className="k">{t("settings.swap")}</span>
                <span className="v">
                  <select value={cfg.memory.swap_warn_gb}
                          onChange={(e) => patch({ memory: { swap_warn_gb: Number(e.target.value) } })}>
                    {[2, 4, 8, 16].map((v) => <option key={v} value={v}>{v} GB</option>)}
                  </select>
                </span>
              </div>
              <div className="kv">
                <span className="k">{t("models.library")}<small>{t("models.library.hint")}</small></span>
                <span className="v" style={{ gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <input
                    type="text"
                    defaultValue={cfg.model_dirs[0] ?? ""}
                    key={cfg.model_dirs[0]}
                    onBlur={(e) => {
                      const path = e.target.value.trim();
                      if (path && path !== cfg.model_dirs[0]) {
                        void api.post("/models/library", { path }).then(() => refresh()).catch((err) => {
                          setErr(err instanceof Error ? err.message : String(err));
                        });
                      }
                    }}
                    style={{ minWidth: 220 }}
                    aria-label={t("models.library")}
                  />
                </span>
              </div>
              {cfg.model_dirs.slice(1).length > 0 && (
                <div className="kv">
                  <span className="k">{t("settings.model_dirs")}</span>
                  <span className="v mono" style={{ fontSize: 11, textAlign: "right" }}>
                    {cfg.model_dirs.slice(1).join(" · ")}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      </Section>

      <Section title={t("settings.about")}>
        <div className="card" style={{ padding: "6px 20px" }}>
          <div className="kv"><span className="k">{t("app.name")}</span><span className="v">v0.3.5</span></div>
          <div className="kv"><span className="k">{t("settings.engine.fast")}</span><span className="v mono">dflash-mlx</span></div>
          <div className="kv"><span className="k">{t("settings.engine.safe")}</span><span className="v mono">mlx-lm</span></div>
        </div>
      </Section>
    </>
  );
}
