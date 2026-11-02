"use client";

import { useMemo } from "react";

import { KeyValue } from "@/components/ui/controls";
import { EmptyState, StatusBadge } from "@/components/ui/primitives";
import type { FlatPattern, Viewer, ViewerCheck } from "@/lib/api";
import { fmtValue } from "@/lib/assembly";

function Caption({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-5 mb-2 text-xs tracking-[0.08em] text-muted-text uppercase first:mt-0">{children}</h3>;
}

const n = (v: number, d = 2) => +v.toFixed(d);

// --- flat pattern ----------------------------------------------------------------------

/**
 * The flat pattern as SVG, drawn from the same outline the DXF carries: the cut outline
 * and holes (even-odd fill), bend centre lines dashed, bend-zone tangent lines dotted.
 * CAD Y is up, so every point is drawn at (x, -y).
 */
export function FlatPatternView({ flat, selectedBend, onSelectBend }: { flat: FlatPattern; selectedBend?: string | null; onSelectBend?: (id: string | null) => void }) {
  const [[x0, y0], [x1, y1]] = flat.bbox;
  const w = x1 - x0;
  const h = y1 - y0;
  const pad = Math.max(w, h) * 0.08;
  const view = `${x0 - pad} ${-y1 - pad} ${w + 2 * pad} ${h + 2 * pad + pad * 0.6}`;
  const stroke = Math.max(w, h) / 500;
  const d = useMemo(
    () => flat.loops.map((lp) => "M" + lp.points.map(([x, y]) => `${n(x, 3)} ${n(-y, 3)}`).join(" L") + " Z").join(" "),
    [flat],
  );
  const font = Math.max(w, h) / 22;

  return (
    <div className="viewer-surface relative h-full min-h-[240px] w-full" data-testid="flat-pattern">
      <svg
        viewBox={view}
        role="img"
        aria-label={`Flat pattern ${n(flat.size[0])} × ${n(flat.size[1])} mm`}
        className="block h-full w-full"
        preserveAspectRatio="xMidYMid meet"
      >
        <path d={d} fillRule="evenodd" style={{ fill: "var(--viewer-flat-fill)", stroke: "var(--viewer-edge)" }} strokeWidth={stroke} />
        {flat.extents.map((e) =>
          e.lines.map(([a, b], k) => (
            <line
              key={`${e.id}-${k}`}
              x1={a[0]}
              y1={-a[1]}
              x2={b[0]}
              y2={-b[1]}
              style={{ stroke: "var(--viewer-bend)" }}
              strokeWidth={stroke * 0.7}
              strokeDasharray={`${stroke} ${stroke * 2.5}`}
              opacity={0.7}
            />
          )),
        )}
        {flat.bends.map((b) => {
          const active = selectedBend === b.id;
          const mx = (b.a[0] + b.b[0]) / 2;
          const my = -(b.a[1] + b.b[1]) / 2;
          return (
            <g key={b.id} data-bend={b.id} onClick={() => onSelectBend?.(active ? null : b.id)} className={onSelectBend ? "cursor-pointer" : undefined}>
              <line
                x1={b.a[0]}
                y1={-b.a[1]}
                x2={b.b[0]}
                y2={-b.b[1]}
                style={{ stroke: active ? "var(--viewer-select)" : "var(--viewer-bend)" }}
                strokeWidth={stroke * (active ? 2.2 : 1.3)}
                strokeDasharray={`${stroke * 6} ${stroke * 3}`}
              />
              <text x={mx} y={my - font * 0.4} fontSize={font} textAnchor="middle" style={{ fill: active ? "var(--viewer-select)" : "var(--viewer-bend)" }}>
                {b.id}
              </text>
            </g>
          );
        })}
        <text x={x0 + w / 2} y={-y0 + pad * 0.95} fontSize={font} textAnchor="middle" style={{ fill: "var(--color-muted-text)" }}>
          {n(w)} mm
        </text>
        <text
          x={x1 + pad * 0.55}
          y={-(y0 + h / 2)}
          fontSize={font}
          textAnchor="middle"
          transform={`rotate(-90 ${x1 + pad * 0.55} ${-(y0 + h / 2)})`}
          style={{ fill: "var(--color-muted-text)" }}
        >
          {n(h)} mm
        </text>
      </svg>
      <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap gap-2">
        <span className="rounded-full border border-line bg-bg px-2.5 py-1 text-xs text-muted-text">Flat · mm</span>
        <span className="rounded-full border border-line bg-bg px-2.5 py-1 text-xs tabular text-body" data-testid="flat-size">
          {n(flat.size[0], 3)} × {n(flat.size[1], 3)} mm
        </span>
        <span className="rounded-full border border-line bg-bg px-2.5 py-1 text-xs text-muted-text">
          {flat.bends.length} bend line{flat.bends.length === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}

// --- bend table ------------------------------------------------------------------------

export function BendTable({ viewer, selectedBend, onSelectBend }: { viewer: Viewer; selectedBend: string | null; onSelectBend: (id: string | null) => void }) {
  const meta = viewer.meta;
  const bends = viewer.bend_table ?? [];
  return (
    <div>
      {meta ? (
        <KeyValue
          rows={[
            { label: "Material", value: `${meta.material} · ${meta.thickness} mm` },
            { label: "Flat size", value: `${meta.flat_size.map((v) => n(v, 3)).join(" × ")} mm` },
            { label: "Folded size", value: `${meta.outer_size.map((v) => n(v, 3)).join(" × ")} mm` },
            { label: "Mass", value: meta.mass_kg !== null ? `${n(meta.mass_kg * 1000, 1)} g` : "unknown material" },
          ]}
        />
      ) : null}
      <Caption>Bends · {bends.length}</Caption>
      {bends.length ? (
        <div className="overflow-x-auto">
          <table className="w-full" data-testid="bend-table">
            <thead>
              <tr className="border-b border-line text-left">
                {["Bend", "From", "Angle", "R", "K", "BA"].map((hd) => (
                  <th key={hd} scope="col" className={`py-1.5 pr-2 text-xs font-normal text-muted-text ${hd === "Bend" || hd === "From" ? "" : "text-right"}`}>
                    {hd}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bends.map((b) => (
                <tr
                  key={b.id}
                  onClick={() => onSelectBend(selectedBend === b.id ? null : b.id)}
                  className={`cursor-pointer border-b border-line last:border-b-0 ${selectedBend === b.id ? "bg-surface" : "hover:bg-surface"}`}
                >
                  <td className="py-1.5 pr-2 text-xs text-ink">{b.id}</td>
                  <td className="py-1.5 pr-2 text-xs text-muted-text">{b.parent}</td>
                  <td className="py-1.5 pr-2 text-right text-xs tabular text-ink">
                    {n(b.angle, 1)}° {b.direction}
                  </td>
                  <td className="py-1.5 pr-2 text-right text-xs tabular text-body">{n(b.radius, 2)}</td>
                  <td className="py-1.5 pr-2 text-right text-xs tabular text-body">{n(b.k, 3)}</td>
                  <td className="py-1.5 text-right text-xs tabular text-body">{n(b.allowance, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-text">A flat blank: no bends.</p>
      )}
      <p className="mt-3 text-xs text-muted-text">Bend allowance BA = angle × (R + K·T); K from DIN 6935 unless the spec fixes it. Lengths in mm.</p>
    </div>
  );
}

// --- rule checks -----------------------------------------------------------------------

const RULE_LABEL: Record<string, string> = {
  single_valid_solid: "Single valid solid",
  no_folded_overlap: "No overlap when folded",
  no_flat_overlap: "No overlap in the flat",
  constant_thickness: "Constant thickness",
  min_flange_length: "Minimum flange length",
  hole_to_bend: "Hole to bend distance",
  cutout_inside_wall: "Cutout inside its wall",
  bend_allowance: "Bend allowance",
  refold_points_on_solid: "Refolded flat lands on the solid",
  refold_outer_dims: "Refolded outer size",
  volume_from_flat: "Volume from the flat",
};

function ruleTitle(c: ViewerCheck) {
  const [rule, ...rest] = c.name.split(":");
  return { rule: RULE_LABEL[rule] ?? rule.replace(/_/g, " "), where: rest.join(" · ") };
}

export function SheetChecks({ viewer }: { viewer: Viewer }) {
  if (!viewer.checks.length) return <EmptyState title="No checks" />;
  const failed = viewer.checks.filter((c) => !c.passed);
  const geometry = viewer.checks.filter((c) => !["min_flange_length", "hole_to_bend", "cutout_inside_wall"].includes(c.group));
  const rules = viewer.checks.filter((c) => ["min_flange_length", "hole_to_bend", "cutout_inside_wall"].includes(c.group));
  const list = (items: ViewerCheck[]) => (
    <ul className="flex flex-col">
      {items.map((c) => {
        const t = ruleTitle(c);
        return (
          <li key={c.name} data-check={c.name} data-passed={c.passed} className="flex items-start justify-between gap-3 border-b border-line py-2 last:border-b-0" title={c.note ?? ""}>
            <span className="min-w-0">
              <span className="block text-xs text-ink">
                {t.rule}
                {t.where ? <span className="text-muted-text"> · {t.where}</span> : null}
              </span>
              <span className="block text-xs text-muted-text tabular [overflow-wrap:anywhere]">
                {c.requested !== null && c.requested !== undefined && (typeof c.actual !== "object" || Array.isArray(c.actual))
                  ? `${fmtValue(c.requested)} → ${fmtValue(c.actual)}`
                  : (c.note ?? fmtValue(c.actual))}
              </span>
            </span>
            <span className="shrink-0">
              <StatusBadge tone={c.passed ? "success" : "error"}>{c.passed ? "pass" : "fail"}</StatusBadge>
            </span>
          </li>
        );
      })}
    </ul>
  );
  return (
    <div data-testid="sheet-checks">
      <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusBadge tone={viewer.passed ? "success" : "error"}>
          {viewer.passed ? `all ${viewer.checks.length} checks passed` : `${failed.length} of ${viewer.checks.length} failed`}
        </StatusBadge>
        <span className="text-xs text-muted-text">folded solid and flat pattern</span>
      </div>
      <Caption>Shop rules · {rules.filter((c) => c.passed).length}/{rules.length}</Caption>
      {rules.length ? list(rules) : <p className="text-xs text-muted-text">No flanges or cutouts to check.</p>}
      <Caption>Geometry and unfold · {geometry.filter((c) => c.passed).length}/{geometry.length}</Caption>
      {list(geometry)}
      <p className="mt-3 text-xs text-muted-text">
        Rules are conservative shop defaults (flange ≥ 2.5T + R, holes ≥ 2T + R from a bend), not a specific press brake.
      </p>
    </div>
  );
}
