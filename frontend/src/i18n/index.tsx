import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type AppConfig } from "../api/client";
import { catalog, formatMsg, resolveLang, type LangPref, type MsgKey, type ResolvedLang } from "./catalog";

const STORAGE = "lacc-lang";

type I18nValue = {
  pref: LangPref;
  resolved: ResolvedLang;
  t: (key: MsgKey, vars?: Record<string, string | number>) => string;
  setPref: (p: LangPref) => void;
};

const Ctx = createContext<I18nValue | null>(null);

function readPref(): LangPref {
  const s = localStorage.getItem(STORAGE);
  if (s === "en" || s === "zh-Hans" || s === "system") return s;
  return "system";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<LangPref>(readPref);
  const resolved = useMemo(() => resolveLang(pref), [pref]);
  const dict = useMemo(() => catalog(resolved), [resolved]);

  const t = useCallback(
    (key: MsgKey, vars?: Record<string, string | number>) => formatMsg(dict[key] ?? key, vars),
    [dict],
  );

  const setPref = useCallback((p: LangPref) => {
    setPrefState(p);
    localStorage.setItem(STORAGE, p);
    document.documentElement.lang = resolveLang(p) === "zh-Hans" ? "zh-Hans" : "en";
    void api.put("/settings", { ui: { language: p } }).catch(() => undefined);
  }, []);

  useEffect(() => {
    document.documentElement.lang = resolved === "zh-Hans" ? "zh-Hans" : "en";
  }, [resolved]);

  useEffect(() => {
    let stop = false;
    void api.get<AppConfig>("/settings").then((cfg) => {
      if (stop) return;
      const remote = cfg.ui?.language;
      if (remote === "en" || remote === "zh-Hans" || remote === "system") {
        if (remote !== readPref()) {
          setPrefState(remote);
          localStorage.setItem(STORAGE, remote);
        }
      }
    }).catch(() => undefined);
    return () => { stop = true; };
  }, []);

  const value = useMemo(() => ({ pref, resolved, t, setPref }), [pref, resolved, t, setPref]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n must be used under I18nProvider");
  return v;
}

export function LanguageSelect() {
  const { pref, t, setPref } = useI18n();
  return (
    <label className="lang-switch">
      <span className="stat-label">{t("lang.label")}</span>
      <select
        aria-label={t("lang.label")}
        value={pref}
        onChange={(e) => setPref(e.target.value as LangPref)}
      >
        <option value="system">{t("lang.system")}</option>
        <option value="en">{t("lang.en")}</option>
        <option value="zh-Hans">{t("lang.zh")}</option>
      </select>
    </label>
  );
}
