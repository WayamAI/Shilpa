"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge, Button, Dialog, NumberInput } from "@/components/ui";
import { api, errText, fetchBlob, type DrawingDim, type Spec } from "@/lib/api";

/**
 * Engineer review of values read from a drawing (blueprint section 11): every
 * extracted dimension is shown on the source page with its printed text and
 * verification state, and can be corrected before the specification is confirmed.
 */
export function DrawingReview({
  spec,
  canWrite,
  onClose,
  onUpdate,
}: {
  spec: Spec;
  canWrite: boolean;
  onClose: () => void;
  onUpdate: (s: Spec) => void;
}) {
  const r = spec.requirements;
  const drawing = r.drawing!;
  const [page, setPage] = useState(1);
  const [hover, setHover] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [img, setImg] = useState<string | null>(null);
  const pages = useMemo(() => Array.from(new Set(drawing.dimensions.map((d) => d.page))).sort(), [drawing]);
  const reviewed = drawing.dimensions.length > 0 && drawing.dimensions.every((d) => d.review !== "unreviewed");

  useEffect(() => {
    if (!spec.upload_id) return;
    let url: string | null = null;
    fetchBlob(`/v1/uploads/${spec.upload_id}/pages/${page}`)
      .then((b) => {
        url = URL.createObjectURL(b);
        setImg(url);
      })
      .catch(() => setImg(null));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [spec.upload_id, page]);

  async function confirm() {
    const nums: Record<string, number> = {};
    for (const [k, v] of Object.entries({ ...edits, ...answers })) if (v.trim() && Number.isFinite(Number(v))) nums[k] = Number(v);
    setBusy(true);
    setError(null);
    try {
      onUpdate(await api.answerSpec(spec.id, spec.revision, nums, r.conflicts.length > 0, true));
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  const tb = drawing.title_block;

  return (
    <Dialog
      size="xl"
      title="Review values read from the drawing"
      description={
        <span>
          {tb.part_name ?? "Drawing"} · units {tb.units ?? "?"} · scale {tb.scale ?? "?"}
          {drawing.views.length ? ` · ${drawing.views.join(", ")}` : ""}
        </span>
      }
      onClose={onClose}
      actions={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-muted-text">
            {reviewed
              ? spec.status === "ready"
                ? "Reviewed — ready to generate."
                : r.status_reason
              : "Check each value against the sheet, correct anything misread, then confirm."}
          </span>
          {canWrite && !reviewed ? (
            <Button variant="primary" disabled={busy} onClick={confirm}>
              {r.conflicts.length > 0 ? "Values corrected — confirm" : "Confirm values"}
            </Button>
          ) : (
            <Button onClick={onClose}>Close</Button>
          )}
        </div>
      }
    >
      <div className="grid h-[min(78vh,860px)] min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_440px]">
        <div className="min-h-0 overflow-auto bg-surface p-4">
          {pages.length > 1 ? (
            <div className="mb-3 flex gap-1.5">
              {pages.map((p) => (
                <Button key={p} size="sm" variant={p === page ? "primary" : "secondary"} onClick={() => setPage(p)}>
                  Page {p}
                </Button>
              ))}
            </div>
          ) : null}
          <div className="relative w-full">
            {img ? (
              // eslint-disable-next-line @next/next/no-img-element -- authenticated blob URL, not a static asset
              <img src={img} alt={`Drawing page ${page}`} className="block w-full rounded-md border border-line bg-white" />
            ) : (
              <div className="flex h-64 items-center justify-center text-xs text-muted-text">Loading page…</div>
            )}
            {drawing.dimensions
              .filter((d) => d.page === page && d.bbox)
              .map((d) => {
                const [x0, y0, x1, y1] = d.bbox!;
                const warn = d.verified === false || d.confidence === "low";
                return (
                  <div
                    key={d.name}
                    title={`${d.name}: ${d.original_text}`}
                    onMouseEnter={() => setHover(d.name)}
                    onMouseLeave={() => setHover(null)}
                    className={[
                      "absolute -m-[3px] box-content rounded-[3px] border-2 p-[3px] transition-colors duration-fast",
                      warn ? "border-consent" : "border-pass",
                      hover === d.name ? "bg-consent-soft" : "bg-transparent",
                    ].join(" ")}
                    style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` }}
                  />
                );
              })}
          </div>
        </div>

        <div className="flex min-h-0 flex-col overflow-y-auto border-t border-line lg:border-t-0 lg:border-l">
          {drawing.ignored_instructions.length > 0 ? (
            <div role="note" className="m-4 mb-0 flex gap-2.5 rounded-lg border border-consent/40 bg-consent-soft p-3 text-xs text-consent-text">
              <AlertTriangle size={15} strokeWidth={1.75} className="mt-0.5 shrink-0" aria-hidden />
              <div>
                Text on the drawing tried to give instructions. Shilpa ignored it:
                <ul className="mt-1 list-disc pl-4">
                  {drawing.ignored_instructions.map((t, i) => (
                    <li key={i}>“{t}”</li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
          <table className="w-full">
            <thead className="sticky top-0 bg-bg">
              <tr className="border-b border-line text-left">
                <th className="px-4 py-2 text-xs font-medium tracking-[0.08em] text-muted-text uppercase">Value</th>
                <th className="py-2 text-xs font-medium tracking-[0.08em] text-muted-text uppercase">Printed</th>
                <th className="py-2 pr-5 pl-4 text-right text-xs font-medium tracking-[0.08em] text-muted-text uppercase">Check</th>
              </tr>
            </thead>
            <tbody>
              {drawing.dimensions.map((d: DrawingDim) => (
                <tr
                  key={d.name}
                  onMouseEnter={() => setHover(d.name)}
                  onMouseLeave={() => setHover(null)}
                  className={`border-b border-line align-top transition-colors duration-fast ${hover === d.name ? "bg-surface" : ""}`}
                >
                  <td className="px-4 py-2.5">
                    <label htmlFor={`dv-${d.name}`} className="block text-xs text-body capitalize">
                      {d.name.replace(/_/g, " ")}
                    </label>
                    <div className="mt-1 flex items-center gap-1.5">
                      <NumberInput
                        id={`dv-${d.name}`}
                        disabled={!canWrite || reviewed}
                        value={edits[d.name] ?? (d.value ?? "")}
                        onChange={(e) => setEdits((x) => ({ ...x, [d.name]: e.target.value }))}
                        className="w-[88px]"
                      />
                      <span className="text-xs text-muted-text">{d.kind === "count" ? "" : (d.unit ?? r.units)}</span>
                    </div>
                  </td>
                  <td className="py-2.5 pr-2">
                    <code className="block text-xs text-ink">{d.original_text}</code>
                    <span className="block text-xs text-muted-text">{d.meaning}</span>
                  </td>
                  <td className="py-2.5 pr-5 pl-4 text-right">
                    {d.verified === true ? <Badge tone="pass">text ✓</Badge> : null}
                    {d.verified === false ? <Badge tone="fail">mismatch</Badge> : null}
                    {d.verified === null ? <Badge tone="neutral">scan</Badge> : null}
                    {d.confidence !== "high" ? <span className="mt-1 block text-xs text-consent-text">{d.confidence} confidence</span> : null}
                    {d.review !== "unreviewed" ? <span className="mt-1 block text-xs text-pass-text">{d.review}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex flex-col gap-3 p-4">
            {r.conflicts.length > 0 ? (
              <div className="rounded-lg border border-fail/40 bg-fail-soft px-3 py-2 text-xs text-fail-text">
                {r.conflicts.map((c, i) => (
                  <p key={i}>Conflict: {c.description}</p>
                ))}
              </div>
            ) : null}
            {r.missing.length > 0 ? (
              <div className="flex flex-col gap-2">
                {r.missing.map((m) => (
                  <label key={m.name} className="flex items-center justify-between gap-3 text-xs text-body">
                    <span>
                      {m.question}
                      {m.critical ? <span className="text-fail-text"> *</span> : null}
                    </span>
                    <NumberInput aria-label={m.question} value={answers[m.name] ?? ""} onChange={(e) => setAnswers((a) => ({ ...a, [m.name]: e.target.value }))} />
                  </label>
                ))}
              </div>
            ) : null}
            {drawing.notes.length > 0 ? <p className="text-xs text-muted-text">Notes: {drawing.notes.join(" · ")}</p> : null}
            {error ? <p className="text-xs text-fail-text">{error}</p> : null}
          </div>
        </div>
      </div>
    </Dialog>
  );
}
