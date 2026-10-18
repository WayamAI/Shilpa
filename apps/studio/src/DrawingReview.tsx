import { useEffect, useMemo, useState } from "react";
import { api, getToken, type Spec } from "./api";

// Engineer review of values read from a drawing (blueprint section 11): every extracted dimension is
// shown on the source page with its printed text and verification state, and can be corrected before
// the specification is confirmed. Nothing generates until this review is done.

type DrawingDim = {
  name: string; value: number | null; unit: string | null; kind: string; meaning: string; original_text: string;
  page: number; bbox: number[] | null; view: string | null; confidence: string; verified: boolean | null; review: string;
};
type Drawing = {
  title_block: { units: string | null; scale: string | null; part_name: string | null; general_tolerance: string | null };
  views: string[]; dimensions: DrawingDim[]; notes: string[]; ignored_instructions: string[]; consistency: string[];
};

function usePageImage(uploadId: string | null, page: number) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!uploadId) return;
    let revoke: string | null = null;
    fetch(`/v1/uploads/${uploadId}/pages/${page}`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((b) => {
        revoke = URL.createObjectURL(b);
        setUrl(revoke);
      })
      .catch(() => setUrl(null));
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [uploadId, page]);
  return url;
}

export function DrawingReview({ spec, canWrite, onClose, onUpdate }: { spec: Spec; canWrite: boolean; onClose: () => void; onUpdate: (s: Spec) => void }) {
  const drawing = (spec.requirements as unknown as { drawing: Drawing }).drawing;
  const r = spec.requirements;
  const [page, setPage] = useState(1);
  const [hover, setHover] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const img = usePageImage(spec.upload_id ?? null, page);
  const pages = useMemo(() => Array.from(new Set(drawing.dimensions.map((d) => d.page))).sort(), [drawing]);
  const reviewed = drawing.dimensions.every((d) => d.review !== "unreviewed");

  const confirm = async (resolvedConflicts: boolean) => {
    const nums: Record<string, number> = {};
    for (const [k, v] of Object.entries({ ...edits, ...answers })) if (v.trim() && Number.isFinite(Number(v))) nums[k] = Number(v);
    setBusy(true);
    setError(null);
    try {
      onUpdate(await api.answerSpec(spec.id, spec.revision, nums, resolvedConflicts, true));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Review drawing values">
      <div className="modal-body review">
        <div className="review-head">
          <div>
            <strong>Review values read from the drawing</strong>
            <div className="small muted">
              {drawing.title_block.part_name ?? "Drawing"} · units {drawing.title_block.units ?? "?"} · scale {drawing.title_block.scale ?? "?"}
              {drawing.views.length > 0 && ` · views: ${drawing.views.join(", ")}`}
            </div>
          </div>
          <button onClick={onClose}>Close</button>
        </div>
        <div className="review-grid">
          <div className="sheet">
            {pages.length > 1 && (
              <div className="row small">
                {pages.map((p) => <button key={p} className={p === page ? "active" : ""} onClick={() => setPage(p)}>Page {p}</button>)}
              </div>
            )}
            <div className="sheet-frame">
              {img ? <img src={img} alt={`Drawing page ${page}`} /> : <div className="muted">Loading page…</div>}
              {drawing.dimensions.filter((d) => d.page === page && d.bbox).map((d) => {
                const [x0, y0, x1, y1] = d.bbox!;
                return (
                  <div
                    key={d.name}
                    className={`box ${hover === d.name ? "hot" : ""} ${d.verified === false || d.confidence === "low" ? "warn" : ""}`}
                    style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` }}
                    onMouseEnter={() => setHover(d.name)}
                    onMouseLeave={() => setHover(null)}
                    title={`${d.name}: ${d.original_text}`}
                  />
                );
              })}
            </div>
          </div>
          <div className="review-side">
            {drawing.ignored_instructions.length > 0 && (
              <div className="note">
                Text on the drawing tried to give instructions; Shilpa ignored it:
                <ul>{drawing.ignored_instructions.map((t, i) => <li key={i}>“{t}”</li>)}</ul>
              </div>
            )}
            <table className="review-table">
              <thead><tr><th>Value</th><th>Printed</th><th>Check</th></tr></thead>
              <tbody>
                {drawing.dimensions.map((d) => (
                  <tr key={d.name} className={hover === d.name ? "hot" : ""} onMouseEnter={() => setHover(d.name)} onMouseLeave={() => setHover(null)}>
                    <td>
                      <label className="small" htmlFor={`dv-${d.name}`}>{d.name.replace(/_/g, " ")}</label>
                      <div className="row">
                        <input
                          id={`dv-${d.name}`}
                          type="number"
                          step="any"
                          disabled={!canWrite || reviewed}
                          value={edits[d.name] ?? (d.value ?? "")}
                          onChange={(e) => setEdits((x) => ({ ...x, [d.name]: e.target.value }))}
                        />
                        <span className="muted small">{d.kind === "count" ? "" : d.unit ?? r.units}</span>
                      </div>
                    </td>
                    <td className="small"><code>{d.original_text}</code><div className="muted">{d.meaning}</div></td>
                    <td className="small">
                      {d.verified === true && <span className="pill ok" title="Matches the PDF text layer">text ✓</span>}
                      {d.verified === false && <span className="pill bad" title="Does not match the PDF text layer">mismatch</span>}
                      {d.verified === null && <span className="pill warn" title="Scanned page: read from the image only">scan</span>}
                      {d.confidence !== "high" && <div className="muted">{d.confidence} confidence</div>}
                      {d.review !== "unreviewed" && <div className="ok-text">{d.review}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {r.conflicts.length > 0 && (
              <div className="error small">{r.conflicts.map((c, i) => <div key={i}>Conflict: {c.description}</div>)}</div>
            )}
            {r.missing.length > 0 && (
              <div className="questions">
                {r.missing.map((m) => (
                  <label key={m.name}>
                    {m.question}{m.critical ? " *" : ""}
                    <input type="number" step="any" value={answers[m.name] ?? ""} onChange={(e) => setAnswers((a) => ({ ...a, [m.name]: e.target.value }))} />
                  </label>
                ))}
              </div>
            )}
            {drawing.notes.length > 0 && <div className="small muted">Notes: {drawing.notes.join(" · ")}</div>}
            {error && <div className="error small">{error}</div>}
            {canWrite && !reviewed && (
              <div className="row">
                <button className="primary" disabled={busy} onClick={() => confirm(r.conflicts.length > 0)}>
                  {r.conflicts.length > 0 ? "Values corrected — confirm" : "Confirm values"}
                </button>
              </div>
            )}
            {reviewed && <div className="ok-text small">Reviewed. {spec.status === "ready" ? "Ready to generate." : r.status_reason}</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
