import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  api, type HubCard, type HubHit, type HubSearch, type ModelInfo, type ModelLibrary, type PullJob,
} from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, ErrorPanel, Section, fmtBytes } from "../components/ui";
import { useI18n } from "../i18n";
import type { MsgKey } from "../i18n/catalog";

type Pane = "installed" | "discover" | "downloads";

export default function Models() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const pane: Pane = params.get("tab") === "discover"
    ? "discover"
    : params.get("tab") === "downloads"
      ? "downloads"
      : "installed";
  const { data: models, refresh, loading } = usePoll<ModelInfo[]>(() => api.get("/models"), 20000);
  const { data: library, refresh: refreshLib } = usePoll<ModelLibrary>(() => api.get("/models/library"), 30000);
  const { data: pull, refresh: refreshPull } = usePoll<PullJob>(() => api.get("/models/pull"), 1200);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [libDraft, setLibDraft] = useState("");

  useEffect(() => {
    if (library && !libDraft) setLibDraft(library.library);
  }, [library, libDraft]);

  useEffect(() => {
    if (pull?.job?.status === "done") {
      setNote(t("models.pull.done"));
      void refresh();
    }
    if (pull?.job?.status === "cancelled") setNote(t("models.pull.cancelled"));
  }, [pull?.job?.status, pull?.job?.finished_at, refresh, t]);

  const setPane = (next: Pane) => {
    const p = new URLSearchParams(params);
    if (next === "installed") p.delete("tab");
    else p.set("tab", next);
    setParams(p, { replace: true });
  };

  const setRole = async (id: string, role: string) => {
    setBusy(id); setErr(null);
    try {
      const r = await api.post<{ ok: boolean; restart_required: boolean }>("/models/role", { model_id: id, role });
      if (r.restart_required) setNote(t("models.note.restart"));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null); void refresh();
    }
  };

  const scan = async () => {
    setBusy("__scan"); setErr(null);
    try { await api.post("/models/scan"); } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); void refresh(); }
  };

  const applyLibrary = async () => {
    const path = libDraft.trim();
    if (!path) return;
    setBusy("__lib"); setErr(null);
    try {
      await api.post("/models/library", { path });
      await refreshLib();
      await scan();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); }
  };

  const openFolder = (id: string) => api.post("/models/open-folder", { model_id: id }).catch(() => {});
  const copyId = async (id: string) => {
    await navigator.clipboard.writeText(id);
    setCopied(id); setTimeout(() => setCopied(null), 1400);
  };

  return (
    <>
      <h1 className="page-title">{t("nav.models")}</h1>
      <p className="page-sub">{t("models.sub")}</p>

      {err && <ErrorPanel what={t("models.err")} detail={err} />}
      {note && (
        <div className="advisory warn" role="status">
          <span>{note}</span>
          <button className="btn small" onClick={() => setNote(null)}>{t("common.dismiss")}</button>
        </div>
      )}

      <div className="row between" style={{ marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
        <div className="seg" role="tablist" aria-label={t("nav.models")}>
          <button type="button" className={pane === "installed" ? "active" : ""} onClick={() => setPane("installed")}>
            {t("models.tab.installed")}
          </button>
          <button type="button" className={pane === "discover" ? "active" : ""} onClick={() => setPane("discover")}>
            {t("models.tab.discover")}
          </button>
          <button type="button" className={pane === "downloads" ? "active" : ""} onClick={() => setPane("downloads")}>
            {t("models.tab.downloads")}
            {(pull?.items ?? []).filter((i) => ["running", "queued", "paused", "error"].includes(i.status)).length > 0 && (
              <span> ({(pull?.items ?? []).filter((i) => ["running", "queued", "paused", "error"].includes(i.status)).length})</span>
            )}
          </button>
        </div>
        <div className="library-line">
          <span className="stat-label">{t("models.library")}</span>
          <code className="mono">{library?.library ?? "…"}</code>
        </div>
      </div>

      {pull?.busy && pull.job && pane !== "downloads" && (
        <div className="advisory warn" role="status">
          <span>
            {t(pull.job.current === "resume" ? "models.hub.resuming" : "models.hub.pulling")} {pull.job.repo_id}
            {pull.job.bytes_total > 0 && (
              <> · {fmtBytes(pull.job.bytes_done)} / {fmtBytes(pull.job.bytes_total)}</>
            )}
          </span>
          <button className="btn small" onClick={() => { void api.post("/models/pull/pause", { repo_id: pull.job?.repo_id }).then(() => refreshPull()); }}>
            {t("models.dl.pause")}
          </button>
          <button className="btn small" onClick={() => setPane("downloads")}>{t("models.tab.downloads")}</button>
        </div>
      )}

      {pane === "installed" ? (
        <InstalledTable
          models={models} loading={loading} busy={busy}
          copied={copied} t={t}
          onScan={scan} onRole={setRole} onFolder={openFolder} onCopy={copyId}
          onResume={(id) => {
            setErr(null);
            void api.post("/models/pull/resume", { repo_id: id }).then(() => refreshPull()).catch((e) => {
              setErr(e instanceof Error ? e.message : String(e));
            });
          }}
          onDelete={(id) => {
            if (!window.confirm(t("models.dl.delete.confirm", { id }))) return;
            setErr(null);
            void api.post("/models/delete", {
              model_id: id,
              confirm_model_id: id,
              scope: "installed_model",
            }).then(() => {
              void refresh(); void refreshPull();
            }).catch((e) => {
              setErr(e instanceof Error ? e.message : String(e));
            });
          }}
        />
      ) : pane === "downloads" ? (
        <DownloadsTable
          items={pull?.items ?? []}
          t={t}
          onPause={(id) => { void api.post("/models/pull/pause", { repo_id: id }).then(() => refreshPull()); }}
          onResume={(id) => {
            void api.post("/models/pull/resume", { repo_id: id }).then(() => refreshPull()).catch((e) => {
              setErr(e instanceof Error ? e.message : String(e));
            });
          }}
          onDismiss={(id) => { void api.post("/models/pull/dismiss", { repo_id: id }).then(() => refreshPull()); }}
          onClearPartials={(id) => {
            if (!window.confirm(t("models.dl.clear.confirm", { id }))) return;
            void api.post("/models/pull/clear-partials", { repo_id: id }).then(() => {
              void refresh(); void refreshPull();
            }).catch((e) => {
              setErr(e instanceof Error ? e.message : String(e));
            });
          }}
        />
      ) : (
        <DiscoverPane
          library={library}
          libDraft={libDraft}
          setLibDraft={setLibDraft}
          onApplyLibrary={applyLibrary}
          libBusy={busy === "__lib"}
          onPulled={() => { void refresh(); void refreshPull(); }}
          onError={setErr}
        />
      )}
    </>
  );
}

function InstalledTable({ models, loading, busy, copied, t, onScan, onRole, onFolder, onCopy, onResume, onDelete }: {
  models: ModelInfo[] | null; loading: boolean; busy: string | null; copied: string | null;
  t: (k: MsgKey, vars?: Record<string, string | number>) => string;
  onScan: () => void; onRole: (id: string, role: string) => void;
  onFolder: (id: string) => void; onCopy: (id: string) => void;
  onResume: (id: string) => void; onDelete: (id: string) => void;
}) {
  return (
    <Section
      title={t("models.installed", { n: models?.length ?? "…" })}
      actions={
        <button className="btn small" onClick={onScan} disabled={busy === "__scan"}>
          {busy === "__scan" ? t("models.scanning") : t("models.rescan")}
        </button>
      }
    >
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table className="tbl">
          <thead>
            <tr>
              <th>{t("models.col.model")}</th>
              <th>{t("models.col.role")}</th>
              <th>{t("models.col.quant")}</th>
              <th className="num">{t("models.col.size")}</th>
              <th>{t("models.col.compat")}</th>
              <th style={{ width: 220 }} />
            </tr>
          </thead>
          <tbody>
            {(models ?? []).map((m) => {
              const isDraftModel = m.extra?.is_dflash_draft;
              return (
                <tr key={m.id}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{m.display_name}</div>
                    <div className="mono" style={{ color: "var(--text-3)", fontSize: 11 }}>
                      {m.id}
                      {m.status === "downloading" && <Badge kind="warn">{t("models.downloading")}</Badge>}
                    </div>
                  </td>
                  <td>
                    {m.role === "target" && <Badge kind="accent">{t("models.role.target")}</Badge>}
                    {m.role === "draft" && <Badge kind="accent">{t("models.role.draft")}</Badge>}
                    {m.role === "none" && <span style={{ color: "var(--text-3)" }}>—</span>}
                  </td>
                  <td>{m.quantization ?? "—"}</td>
                  <td className="num">{fmtBytes(m.size_bytes)}</td>
                  <td>
                    {m.compatibility === "mlx" && <Badge kind="ok">MLX</Badge>}
                    {m.compatibility === "mlx-dflash-draft" && <Badge kind="ok">{t("models.compat.dflash")}</Badge>}
                    {m.compatibility === "untested" && <Badge kind="idle">{t("models.compat.untested")}</Badge>}
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {!isDraftModel && m.role !== "target" && m.compatibility === "mlx" && (
                      <button className="btn small" disabled={busy === m.id}
                              onClick={() => onRole(m.id, "target")}>{t("models.set_target")}</button>
                    )}{" "}
                    {isDraftModel && m.role !== "draft" && (
                      <button className="btn small" disabled={busy === m.id}
                              onClick={() => onRole(m.id, "draft")}>{t("models.set_draft")}</button>
                    )}{" "}
                    {m.status === "downloading" && (
                      <button className="btn small" onClick={() => onResume(m.id)}>
                        {t("models.hub.resume")}
                      </button>
                    )}{" "}
                    <button className="btn small" onClick={() => onFolder(m.id)}>{t("models.folder")}</button>{" "}
                    <button className="btn small" onClick={() => onCopy(m.id)}>
                      {copied === m.id ? t("common.copied") : t("models.copy_id")}
                    </button>{" "}
                    <button className="btn small" onClick={() => onDelete(m.id)}>{t("models.dl.delete")}</button>
                  </td>
                </tr>
              );
            })}
            {!loading && (models ?? []).length === 0 && (
              <tr><td colSpan={6}><div className="empty">{t("models.empty")}</div></td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
        {t("models.kicker")}
      </p>
    </Section>
  );
}

function DownloadsTable({ items, t, onPause, onResume, onDismiss, onClearPartials }: {
  items: {
    repo_id: string; status: string; bytes_done?: number; bytes_total?: number;
    error?: string | null; has_partial_files?: boolean; has_complete_model?: boolean;
  }[];
  t: (k: MsgKey, vars?: Record<string, string | number>) => string;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onDismiss: (id: string) => void;
  onClearPartials: (id: string) => void;
}) {
  const statusKey = (s: string): MsgKey => {
    if (s === "running" || s === "pausing") return "models.dl.status.running";
    if (s === "queued") return "models.dl.status.queued";
    if (s === "paused") return "models.dl.status.paused";
    if (s === "error") return "models.dl.status.error";
    if (s === "done") return "models.dl.status.done";
    return "models.dl.status.paused";
  };
  return (
    <Section title={t("models.tab.downloads")}>
      <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: -8 }}>{t("models.dl.kicker")}</p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {items.length === 0 && <div className="empty">{t("models.dl.empty")}</div>}
        {items.map((item) => {
          const total = item.bytes_total ?? 0;
          const done = item.bytes_done ?? 0;
          const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
          return (
            <div key={item.repo_id} className="kv" style={{ alignItems: "flex-start" }}>
              <span className="k">
                <span className="mono">{item.repo_id}</span>
                <small>{t(statusKey(item.status))}
                  {total > 0 ? ` · ${fmtBytes(done)} / ${fmtBytes(total)}` : ""}
                </small>
                {item.status === "error" && item.error && <small>{item.error}</small>}
                {total > 0 && (
                  <span className="dl-bar" aria-hidden>
                    <span className="dl-bar-fill" style={{ width: `${pct}%` }} />
                  </span>
                )}
              </span>
              <span className="v" style={{ flexWrap: "wrap" }}>
                {(item.status === "running" || item.status === "pausing") && (
                  <button className="btn small" onClick={() => onPause(item.repo_id)}>{t("models.dl.pause")}</button>
                )}
                {["paused", "queued", "error"].includes(item.status) && !item.has_complete_model && (
                  <button className="btn small" onClick={() => onResume(item.repo_id)}>{t("models.hub.resume")}</button>
                )}
                {!["running", "pausing"].includes(item.status) && (
                  <button className="btn small" onClick={() => onDismiss(item.repo_id)}>{t("models.dl.dismiss")}</button>
                )}
                {item.has_partial_files && !item.has_complete_model && (
                  <button className="btn small" onClick={() => onClearPartials(item.repo_id)}>
                    {t("models.dl.clear")}
                  </button>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function DiscoverPane({ library, libDraft, setLibDraft, onApplyLibrary, libBusy, onPulled, onError }: {
  library: ModelLibrary | null;
  libDraft: string;
  setLibDraft: (v: string) => void;
  onApplyLibrary: () => void;
  libBusy: boolean;
  onPulled: () => void;
  onError: (msg: string | null) => void;
}) {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const q0 = params.get("q") ?? "";
  const [q, setQ] = useState(q0);
  const [sort, setSort] = useState("downloads");
  const [hits, setHits] = useState<HubHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<string | null>(params.get("id"));
  const [card, setCard] = useState<HubCard | null>(null);

  useEffect(() => { setQ(q0); }, [q0]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      const p = new URLSearchParams(params);
      p.set("tab", "discover");
      if (q.trim()) p.set("q", q.trim()); else p.delete("q");
      setParams(p, { replace: true });
    }, 280);
    return () => window.clearTimeout(handle);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let stop = false;
    const run = async () => {
      setSearching(true);
      try {
        const r = await api.get<HubSearch>(
          `/models/search?q=${encodeURIComponent(q.trim())}&sort=${encodeURIComponent(sort)}&format=mlx`,
        );
        if (!stop) {
          onError(null);
          setHits(r.results ?? []);
        }
      } catch (e) {
        if (!stop) {
          setHits([]);
          onError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!stop) setSearching(false);
      }
    };
    const wait = window.setTimeout(() => { void run(); }, q.trim() ? 320 : 0);
    return () => { stop = true; window.clearTimeout(wait); };
  }, [q, sort, onError]);

  useEffect(() => {
    if (!selected) { setCard(null); return; }
    let stop = false;
    void api.get<HubCard>(`/models/hub?id=${encodeURIComponent(selected)}`).then((c) => {
      if (!stop) setCard(c);
    }).catch((e) => { if (!stop) onError(e instanceof Error ? e.message : String(e)); });
    return () => { stop = true; };
  }, [selected, onError]);

  const reasonKey = (r: HubHit["reason"]): MsgKey | null => {
    if (r === "gguf") return "models.hub.reason.gguf";
    if (r === "vision") return "models.hub.reason.vision";
    if (r === "not_mlx") return "models.hub.reason.not_mlx";
    return null;
  };

  const pull = async (id: string, role?: "target" | "draft") => {
    onError(null);
    try {
      await api.post("/models/pull", { repo_id: id, assign_role: role ?? null });
      onPulled();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  const destPreview = useMemo(() => {
    if (!selected || !library) return "";
    return `${library.library}/${selected}`;
  }, [selected, library]);

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="kv" style={{ paddingTop: 0 }}>
          <span className="k">{t("models.library")}<small>{t("models.library.hint")}</small></span>
          <span className="v" style={{ gap: 8 }}>
            <input type="text" value={libDraft} onChange={(e) => setLibDraft(e.target.value)}
                   style={{ minWidth: 240 }} aria-label={t("models.library")} />
            <button className="btn small" disabled={libBusy} onClick={onApplyLibrary}>
              {t("models.library.apply")}
            </button>
          </span>
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, margin: "0 0 4px" }}>{t("models.library.web")}</p>
      </div>

      <div className="hub-split">
        <div className="hub-list card" style={{ padding: 10 }}>
          <div className="row" style={{ gap: 8, marginBottom: 10 }}>
            <input
              type="text" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={t("models.hub.search")}
              aria-label={t("models.hub.search")}
              style={{ flex: 1, minWidth: 0 }}
            />
            <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("models.hub.sort")}>
              <option value="downloads">{t("models.hub.sort.downloads")}</option>
              <option value="updated">{t("models.hub.sort.updated")}</option>
              <option value="relevance">{t("models.hub.sort.relevance")}</option>
            </select>
          </div>
          {searching && <div className="empty">{t("models.hub.searching")}</div>}
          {!searching && hits.length === 0 && (
            <div className="empty">{q.trim() ? t("models.hub.none") : t("models.hub.empty")}</div>
          )}
          {!searching && !q.trim() && hits.length > 0 && (
            <div className="empty" style={{ textAlign: "left", paddingBottom: 6 }}>{t("models.hub.recommended")}</div>
          )}
          <ul className="hub-rows">
            {hits.map((h) => (
              <li key={h.id}>
                <button
                  type="button"
                  className={`hub-row${selected === h.id ? " active" : ""}${h.runnable ? "" : " muted"}`}
                  onClick={() => setSelected(h.id)}
                >
                  <div className="hub-row-id">{h.id}</div>
                  <div className="hub-row-meta">
                    {h.local && !h.partial && <Badge kind="ok">{t("models.hub.local")}</Badge>}
                    {h.partial && <Badge kind="warn">{t("models.hub.resume")}</Badge>}
                    {h.kind === "target" && <Badge kind="accent">{t("models.hub.kind.target")}</Badge>}
                    {h.kind === "draft" && <Badge kind="ok">{t("models.hub.kind.draft")}</Badge>}
                    {!h.runnable && <Badge kind="warn">{t("models.hub.not_runnable")}</Badge>}
                    <span>{t("models.hub.downloads", { n: h.downloads })}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="hub-detail card">
          {!selected && <div className="empty">{t("models.hub.pick")}</div>}
          {selected && card && (
            <>
              <h2 className="hub-title">{card.id}</h2>
              <div className="hub-row-meta" style={{ marginBottom: 12 }}>
                {card.local && !card.partial && <Badge kind="ok">{t("models.hub.local")}</Badge>}
                {card.partial && <Badge kind="warn">{t("models.hub.resume")}</Badge>}
                {card.kind === "target" && <Badge kind="accent">{t("models.hub.kind.target")}</Badge>}
                {card.kind === "draft" && <Badge kind="ok">{t("models.hub.kind.draft")}</Badge>}
                {!card.runnable && <Badge kind="warn">{t("models.hub.not_runnable")}</Badge>}
              </div>
              {(() => {
                const rk = reasonKey(card.reason);
                return rk ? <p className="hub-reason">{t(rk)}</p> : null;
              })()}
              {card.runnable && card.pipeline_tag === "image-text-to-text" && (
                <p className="hub-reason">{t("models.hub.text_only")}</p>
              )}
              <div className="kv"><span className="k">{t("models.hub.downloads", { n: card.downloads })}</span></div>
              <div className="kv"><span className="k">{t("models.hub.params")}</span><span className="v">{card.param_size ?? "—"}</span></div>
              <div className="kv"><span className="k">{t("models.hub.license")}</span><span className="v">{card.license ?? "—"}</span></div>
              <div className="kv"><span className="k">{t("models.library")}</span><span className="v mono">{destPreview}</span></div>
              <div className="row" style={{ margin: "14px 0", gap: 8 }}>
                <button
                  className="btn primary"
                  disabled={!!(card.local && !card.partial)}
                  onClick={() => void pull(card.id)}
                >
                  {card.partial ? t("models.hub.resume") : t("models.hub.pull")}
                </button>
                {card.kind === "target" && card.runnable && !card.local && (
                  <button className="btn small" onClick={() => void pull(card.id, "target")}>
                    {t("models.set_target")}
                  </button>
                )}
                {card.kind === "draft" && card.runnable && !card.local && (
                  <button className="btn small" onClick={() => void pull(card.id, "draft")}>
                    {t("models.set_draft")}
                  </button>
                )}
                <a className="btn small" href={card.url} target="_blank" rel="noreferrer">{t("models.hub.hf")}</a>
              </div>
              {card.readme && (
                <section>
                  <h3 className="section-title">{t("models.hub.readme")}</h3>
                  <pre className="hub-readme">{card.readme}</pre>
                </section>
              )}
              {card.files.length > 0 && (
                <section>
                  <h3 className="section-title">{t("models.hub.files")}</h3>
                  <ul className="hub-files">
                    {card.files.slice(0, 24).map((f) => (
                      <li key={f.name}>
                        <span className="mono">{f.name}</span>
                        <span className="num">{fmtBytes(f.size_bytes)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
