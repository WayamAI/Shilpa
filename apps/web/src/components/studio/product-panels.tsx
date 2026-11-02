"use client";

import { useEffect, useState } from "react";

import { Badge, type BadgeTone, EmptyState, KeyValue } from "@/components/ui";
import { fetchBlob, type ProductInfo, type Version } from "@/lib/api";
import { fmtValue } from "@/lib/assembly";

function Caption({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-6 mb-2 text-md first:mt-0">{children}</h3>;
}

const STATUS_TONE: Record<string, BadgeTone> = { passed: "pass", repaired: "complex", unresolved: "fail" };
const SOURCE_TONE: Record<string, BadgeTone> = { user: "neutral", router: "complex", derived: "neutral", table: "neutral", default: "consent" };
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
        <Badge tone={STATUS_TONE[product.status] ?? "neutral"}>{product.status}</Badge>
        <span className="text-xs text-body">
          {router ? `${router.iterations.length} round${router.iterations.length === 1 ? "" : "s"} · ${router.seconds} s` : ""}
        </span>
      </div>
      {product.request ? (
        <p className="mb-3 rounded-lg border border-line bg-surface px-3 py-2 text-xs text-body">
          <span className="text-muted-text">Request · </span>
          {product.request}
        </p>
      ) : null}

      <Caption>Build, check, repair</Caption>
      <ol className="flex flex-col gap-2">
        {(router?.iterations ?? []).map((it) => (
          <li key={it.iteration} className="rounded-lg border border-line px-3 py-2.5" data-iteration={it.iteration}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-ink">Round {it.iteration + 1}</span>
              <span className="flex items-center gap-2">
                <span className="text-xs tabular text-muted-text">{it.seconds} s</span>
                <Badge tone={it.passed ? "pass" : "fail"}>{it.passed ? "Pass" : `${it.failed.length} failed`}</Badge>
              </span>
            </div>
            {it.failed.length ? <p className="mt-1 text-xs text-fail-text [overflow-wrap:anywhere]">Failed: {it.failed.map(humanize).join(", ")}</p> : null}
            {it.warnings.length ? <p className="mt-1 text-xs text-consent-text [overflow-wrap:anywhere]">Warnings: {it.warnings.map(humanize).join(", ")}</p> : null}
            {it.actions.length ? (
              <ul className="mt-1.5 flex flex-col gap-1">
                {it.actions.map((a, k) => (
                  <li key={k} className="text-xs text-body">
                    <Badge tone="complex">{a.level}</Badge> <span className="text-ink">{humanize(a.param)}</span> → {fmtValue(a.new)}
                    <span className="block text-xs text-body">{a.reason}</span>
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
              <li key={k} className="border-b border-line py-2 last:border-b-0">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="text-xs text-ink">{humanize(h.param)}</span>
                  <span className="text-xs tabular text-body">
                    {fmtValue(h.old)} → {fmtValue(h.new)}
                  </span>
                </span>
                <span className="block text-xs text-body">
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
              <li key={k} className="rounded-lg border border-fail/40 bg-fail-soft px-3 py-2 text-xs text-fail-text">
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
              <li key={k} className="rounded-lg border border-consent/40 bg-consent-soft px-3 py-2 text-xs text-consent-text">
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
                <tr key={name} className="border-b border-line last:border-b-0" title={p.note ?? ""}>
                  <th scope="row" className="py-1.5 pr-2 text-left text-xs font-normal text-body">
                    {humanize(name)}
                  </th>
                  <td className="py-1.5 pr-2 text-right text-xs tabular text-ink">
                    {fmtValue(p.value)}
                    {p.unit ? ` ${p.unit}` : ""}
                  </td>
                  <td className="w-16 py-1.5 text-right">
                    <Badge tone={SOURCE_TONE[p.source] ?? "neutral"}>{p.source}</Badge>
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
    <figure className="overflow-hidden rounded-lg border border-line bg-surface">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- an authenticated blob URL, not a static asset
        <img src={src} alt={label} className="block h-auto w-full" />
      ) : (
        <div className="aspect-[16/10] w-full" />
      )}
      <figcaption className="border-t border-line px-3 py-1.5 text-xs text-body">{label}</figcaption>
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
        <EmptyState image="/imagery/sh-card-14-exports-128.webp" imageSize={48} title="No renders" detail="This run produced no side or iso render." />
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
