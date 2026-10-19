"use client";

import { useEffect, useState } from "react";

import { KeyValue } from "@/components/ui/controls";
import { EmptyState, StatusBadge, type StatusTone } from "@/components/ui/primitives";
import { fetchBlob, type ProductInfo, type Version } from "@/lib/api";
import { fmtValue } from "@/lib/assembly";

function Caption({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-5 mb-2 text-caption tracking-[0.08em] text-quaternary uppercase first:mt-0">{children}</h3>;
}

const STATUS_TONE: Record<string, StatusTone> = { passed: "success", repaired: "info", unresolved: "error" };
const SOURCE_TONE: Record<string, StatusTone> = { user: "neutral", router: "info", derived: "neutral", table: "neutral", default: "warning" };
const humanize = (s: string) => s.replace(/_/g, " ");

/**
 * The rollback router's record: each build-check round, the repairs it applied (part-level or
 * design-level, with the check that triggered them), what it left unresolved, and the skeleton
 * values with where each came from.
 */
export function RouterPanel({ product }: { product: ProductInfo }) {
  const router = product.router;
  const skeleton = Object.entries(product.skeleton ?? {});
  return (
    <div data-testid="router-panel">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <StatusBadge tone={STATUS_TONE[product.status] ?? "neutral"}>{product.status}</StatusBadge>
        <span className="text-body-sm text-tertiary">
          {router ? `${router.iterations.length} round${router.iterations.length === 1 ? "" : "s"} · ${router.seconds} s` : ""}
        </span>
      </div>
      {product.request ? (
        <p className="mb-3 rounded-lg border border-muted bg-raised px-3 py-2 text-body-sm text-secondary">
          <span className="text-quaternary">Request · </span>
          {product.request}
        </p>
      ) : null}

      <Caption>Build, check, repair</Caption>
      <ol className="flex flex-col gap-2">
        {(router?.iterations ?? []).map((it) => (
          <li key={it.iteration} className="rounded-lg border border-muted px-3 py-2.5" data-iteration={it.iteration}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-body-sm text-primary">Round {it.iteration + 1}</span>
              <span className="flex items-center gap-2">
                <span className="text-caption tabular text-quaternary">{it.seconds} s</span>
                <StatusBadge tone={it.passed ? "success" : "error"}>{it.passed ? "pass" : `${it.failed.length} failed`}</StatusBadge>
              </span>
            </div>
            {it.failed.length ? <p className="mt-1 text-caption text-error [overflow-wrap:anywhere]">Failed: {it.failed.map(humanize).join(", ")}</p> : null}
            {it.warnings.length ? <p className="mt-1 text-caption text-warning [overflow-wrap:anywhere]">Warnings: {it.warnings.map(humanize).join(", ")}</p> : null}
            {it.actions.length ? (
              <ul className="mt-1.5 flex flex-col gap-1">
                {it.actions.map((a, k) => (
                  <li key={k} className="text-body-sm text-secondary">
                    <StatusBadge tone="info">{a.level}</StatusBadge> <span className="text-primary">{humanize(a.param)}</span> → {fmtValue(a.new)}
                    <span className="block text-caption text-quaternary">{a.reason}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>

      {router?.history.length ? (
        <>
          <Caption>Changes · {router.history.length}</Caption>
          <ul className="flex flex-col">
            {router.history.map((h, k) => (
              <li key={k} className="border-b border-muted py-2 last:border-b-0">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="text-body-sm text-primary">{humanize(h.param)}</span>
                  <span className="text-body-sm tabular text-secondary">
                    {fmtValue(h.old)} → {fmtValue(h.new)}
                  </span>
                </span>
                <span className="block text-caption text-quaternary">
                  round {h.iteration} · {h.level}-level · {humanize(h.check)} · {h.reason}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {router?.unresolved.length ? (
        <>
          <Caption>Unresolved</Caption>
          <ul className="flex flex-col gap-1.5">
            {router.unresolved.map((u, k) => (
              <li key={k} className="rounded-lg border border-error-stroke bg-error-surface px-3 py-2 text-body-sm text-error">
                {humanize(u.check)}
                {u.level ? ` (${u.level})` : ""}: {u.reason}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {router?.suggestions.length ? (
        <>
          <Caption>Suggestions</Caption>
          <ul className="flex flex-col gap-1.5">
            {router.suggestions.map((sg, k) => (
              <li key={k} className="rounded-lg border border-warning-stroke bg-warning-surface px-3 py-2 text-body-sm text-warning">
                {humanize(sg.check)}: {sg.suggestion}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {skeleton.length ? (
        <>
          <Caption>Skeleton · {skeleton.length}</Caption>
          <table className="w-full" data-testid="skeleton-table">
            <tbody>
              {skeleton.map(([name, p]) => (
                <tr key={name} className="border-b border-muted last:border-b-0" title={p.note ?? ""}>
                  <th scope="row" className="py-1.5 pr-2 text-left text-body-sm font-normal text-secondary">
                    {humanize(name)}
                  </th>
                  <td className="py-1.5 pr-2 text-right text-body-sm tabular text-primary">
                    {fmtValue(p.value)}
                    {p.unit ? ` ${p.unit}` : ""}
                  </td>
                  <td className="w-16 py-1.5 text-right">
                    <StatusBadge tone={SOURCE_TONE[p.source] ?? "neutral"}>{p.source}</StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </div>
  );
}

function Render({ id, label }: { id: string; label: string }) {
  const [loaded, setLoaded] = useState<{ id: string; url: string } | null>(null);
  useEffect(() => {
    let url = "";
    let cancelled = false;
    fetchBlob(`/v1/artifacts/${id}/download`)
      .then((b) => {
        url = URL.createObjectURL(b);
        if (!cancelled) setLoaded({ id, url });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [id]);
  const src = loaded && loaded.id === id ? loaded.url : null;
  return (
    <figure className="overflow-hidden rounded-lg border border-muted bg-raised">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- an authenticated blob URL, not a static asset
        <img src={src} alt={label} className="block h-auto w-full" />
      ) : (
        <div className="aspect-[16/10] w-full" />
      )}
      <figcaption className="border-t border-muted px-3 py-1.5 text-caption text-quaternary">{label}</figcaption>
    </figure>
  );
}

/** Server-side PNG renders from the product template (side and iso), plus the run's timings. */
export function RendersPanel({ version, product }: { version: Version; product: ProductInfo }) {
  const side = version.artifacts.find((a) => a.format === "RENDER_SIDE");
  const iso = version.artifacts.find((a) => a.format === "RENDER_ISO");
  return (
    <div data-testid="product-renders">
      {side || iso ? (
        <div className="flex flex-col gap-3">
          {side ? <Render id={side.id} label="Side view" /> : null}
          {iso ? <Render id={iso.id} label="Iso view" /> : null}
        </div>
      ) : (
        <EmptyState title="No renders" />
      )}
      {product.timings_s ? (
        <>
          <Caption>Timings</Caption>
          <KeyValue
            rows={Object.entries(product.timings_s)
              .filter(([, v]) => typeof v === "number")
              .map(([k, v]) => ({ label: humanize(k), value: k === "router_iterations" ? String(v) : `${v} s` }))}
          />
        </>
      ) : null}
    </div>
  );
}
