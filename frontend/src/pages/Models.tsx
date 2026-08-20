import { useState } from "react";
import { api, type ModelInfo } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import { Badge, ErrorPanel, Section, fmtBytes } from "../components/ui";

export default function Models() {
  const { data: models, refresh, loading } = usePoll<ModelInfo[]>(() => api.get("/models"), 20000);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const setRole = async (id: string, role: string) => {
    setBusy(id); setErr(null);
    try {
      const r = await api.post<{ ok: boolean; restart_required: boolean }>("/models/role", { model_id: id, role });
      if (r.restart_required) setNote("Role updated. Restart the runtime (Overview → Restart) to apply.");
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

  const openFolder = (id: string) => api.post("/models/open-folder", { model_id: id }).catch(() => {});
  const copyId = async (id: string) => {
    await navigator.clipboard.writeText(id);
    setCopied(id); setTimeout(() => setCopied(null), 1400);
  };

  return (
    <>
      <h1 className="page-title">Models</h1>
      <p className="page-sub">Local model inventory — scanned from LM Studio and Hugging Face caches (read-only)</p>

      {err && <ErrorPanel what="Model operation failed" detail={err} />}
      {note && (
        <div className="advisory warn" role="status">
          <span>{note}</span>
          <button className="btn small" onClick={() => setNote(null)}>Dismiss</button>
        </div>
      )}

      <Section
        title={`Installed (${models?.length ?? "…"})`}
        actions={
          <button className="btn small" onClick={scan} disabled={busy === "__scan"}>
            {busy === "__scan" ? "Scanning…" : "Rescan"}
          </button>
        }
      >
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Model</th>
                <th>Role</th>
                <th>Quantization</th>
                <th className="num">Size</th>
                <th>Compatibility</th>
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
                        {m.status === "downloading" && <Badge kind="warn">downloading</Badge>}
                      </div>
                    </td>
                    <td>
                      {m.role === "target" && <Badge kind="accent">Target</Badge>}
                      {m.role === "draft" && <Badge kind="accent">Draft</Badge>}
                      {m.role === "none" && <span style={{ color: "var(--text-3)" }}>—</span>}
                    </td>
                    <td>{m.quantization ?? "—"}</td>
                    <td className="num">{fmtBytes(m.size_bytes)}</td>
                    <td>
                      {m.compatibility === "mlx" && <Badge kind="ok">MLX</Badge>}
                      {m.compatibility === "mlx-dflash-draft" && <Badge kind="ok">DFlash draft</Badge>}
                      {m.compatibility === "untested" && <Badge kind="idle">untested</Badge>}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {!isDraftModel && m.role !== "target" && m.compatibility === "mlx" && (
                        <button className="btn small" disabled={busy === m.id}
                                onClick={() => setRole(m.id, "target")}>Set Target</button>
                      )}{" "}
                      {isDraftModel && m.role !== "draft" && (
                        <button className="btn small" disabled={busy === m.id}
                                onClick={() => setRole(m.id, "draft")}>Set Draft</button>
                      )}{" "}
                      <button className="btn small" onClick={() => openFolder(m.id)}>Folder</button>{" "}
                      <button className="btn small" onClick={() => copyId(m.id)}>
                        {copied === m.id ? "Copied" : "Copy ID"}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!loading && (models ?? []).length === 0 && (
                <tr><td colSpan={6}><div className="empty">No local models found in the configured directories.</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
        <p style={{ color: "var(--text-3)", fontSize: 11.5, marginTop: 8 }}>
          Only DFlash draft checkpoints can be assigned the Draft role. Model files are used in place —
          nothing is moved or modified.
        </p>
      </Section>
    </>
  );
}
