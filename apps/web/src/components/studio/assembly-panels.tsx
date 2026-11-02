"use client";

import { Download, FileBox, Pause, Play, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button, IconButton } from "@/components/ui/controls";
import { EmptyState, StatusBadge, StatusDot } from "@/components/ui/primitives";
import { downloadArtifact, type Version, type Viewer, type ViewerCheck, type ViewerJoint } from "@/lib/api";
import { checkDetail, checkTitle, groupLabel, isWarning, partsTree } from "@/lib/assembly";

import type { Highlight } from "./assembly-viewer";

function Caption({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-5 mb-2 text-xs tracking-[0.08em] text-muted-text uppercase first:mt-0">{children}</h3>;
}

function Swatch({ color }: { color: string | null }) {
  return (
    <span
      aria-hidden
      className="inline-block size-3 shrink-0 rounded-full border border-line-strong"
      style={color ? { background: color } : undefined}
    />
  );
}

/** Instances that some failed check names, for the tree's status dots. */
export function failingInstances(viewer: Viewer): Set<string> {
  return new Set(viewer.checks.filter((c) => !c.passed && !isWarning(c)).flatMap((c) => c.instances));
}

// --- parts tree --------------------------------------------------------------------

export function PartsTree({
  viewer,
  selected,
  hovered,
  onHover,
  onSelect,
}: {
  viewer: Viewer;
  selected: string | null;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}) {
  const rows = useMemo(() => partsTree(viewer), [viewer]);
  const failing = useMemo(() => failingInstances(viewer), [viewer]);
  return (
    <div>
      <p className="mb-2 text-xs tracking-[0.08em] text-muted-text uppercase">
        {viewer.instances.length} part{viewer.instances.length === 1 ? "" : "s"} · {viewer.mates.length} mate{viewer.mates.length === 1 ? "" : "s"} ·
        DOF {viewer.dof.computed ?? "—"}
      </p>
      <ul role="tree" aria-label="Parts" data-testid="parts-tree" className="flex flex-col gap-0.5">
        {rows.map(({ inst, depth, via }) => {
          const active = selected === inst.id;
          return (
            <li key={inst.id} role="treeitem" aria-selected={active} aria-level={depth + 1} data-instance={inst.id}>
              <button
                type="button"
                onMouseEnter={() => onHover(inst.id)}
                onMouseLeave={() => onHover(null)}
                onFocus={() => onHover(inst.id)}
                onBlur={() => onHover(null)}
                onClick={() => onSelect(active ? null : inst.id)}
                className={[
                  "flex w-full min-w-0 items-center gap-2 rounded-lg border py-1.5 pr-2 text-left outline-none transition-colors duration-fast",
                  active ? "border-line-strong bg-surface" : hovered === inst.id ? "border-line bg-surface" : "border-transparent hover:bg-surface",
                ].join(" ")}
                style={{ paddingLeft: `${8 + Math.min(depth, 6) * 14}px` }}
              >
                <Swatch color={inst.color} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs text-ink">{inst.id}</span>
                  <span className="block truncate text-xs text-muted-text">
                    {inst.part_number}
                    {inst.copy_of ? ` · copy of ${inst.copy_of}` : ""}
                    {inst.grounded ? " · ground" : via ? ` · ${via}` : !inst.placed ? " · not placed" : ""}
                  </span>
                </span>
                {failing.has(inst.id) ? (
                  <span title="Involved in a failed check" className="shrink-0">
                    <StatusDot tone="error" />
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
      {viewer.issues.length ? (
        <>
          <Caption>Spec issues</Caption>
          <ul className="flex flex-col gap-1.5">
            {viewer.issues.map((i, k) => (
              <li key={k} className="rounded-lg border border-consent/40 bg-consent-soft px-3 py-2 text-xs text-consent-text">
                {i.message}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

// --- bill of materials -------------------------------------------------------------

export function BomTable({ viewer, onSelect }: { viewer: Viewer; onSelect: (id: string | null) => void }) {
  if (!viewer.bom.length) return <EmptyState title="No bill of materials" />;
  const total = viewer.bom.reduce((n, l) => n + l.quantity, 0);
  const withMass = viewer.bom.some((l) => l.mass_g !== undefined && l.mass_g !== null);
  const mass = viewer.bom.reduce((n, l) => n + (l.mass_g ?? 0) * l.quantity, 0);
  return (
    <div>
      <p className="mb-2 text-xs tracking-[0.08em] text-muted-text uppercase">
        {viewer.bom.length} line{viewer.bom.length === 1 ? "" : "s"} · {total} item{total === 1 ? "" : "s"}
        {withMass ? ` · ${(mass / 1000).toFixed(2)} kg` : ""}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[300px]" data-testid="bom-table">
          <thead>
            <tr className="border-b border-line text-left">
              <th scope="col" className="py-1.5 pr-2 text-xs font-normal text-muted-text">Part number</th>
              <th scope="col" className="py-1.5 pr-2 text-right text-xs font-normal text-muted-text">Qty</th>
              <th scope="col" className="py-1.5 pr-2 text-xs font-normal text-muted-text">Source</th>
              <th scope="col" className="py-1.5 text-right text-xs font-normal text-muted-text">{withMass ? "Mass g" : "Volume mm³"}</th>
            </tr>
          </thead>
          <tbody>
            {viewer.bom.map((line) => (
              <tr
                key={line.part_number}
                className="cursor-pointer border-b border-line last:border-b-0 hover:bg-surface"
                onClick={() => onSelect(line.instances[0] ?? null)}
                title={`Instances: ${line.instances.join(", ")}`}
              >
                <td className="py-1.5 pr-2 text-xs text-ink">
                  <span className="block truncate">{line.part_number}</span>
                  {(line.description ?? line.name) && (line.description ?? line.name) !== line.part_number ? (
                    <span className="block truncate text-xs text-muted-text">{line.description ?? line.name}</span>
                  ) : null}
                </td>
                <td className="py-1.5 pr-2 text-right text-xs tabular text-ink">{line.quantity}</td>
                <td className="py-1.5 pr-2 text-xs text-muted-text">{line.procurement ?? line.generator ?? line.source}</td>
                <td className="py-1.5 text-right text-xs tabular text-body">
                  {withMass
                    ? line.mass_g !== null && line.mass_g !== undefined
                      ? line.mass_g.toLocaleString(undefined, { maximumFractionDigits: 0 })
                      : "—"
                    : line.volume_mm3 !== null
                      ? line.volume_mm3.toLocaleString(undefined, { maximumFractionDigits: 1 })
                      : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --- checks --------------------------------------------------------------------------

const GROUP_ORDER = [
  "clearance", "ground", "motion", "fit", "drivetrain", "static", "standards",
  "interference", "contact", "dof", "sweep", "product", "bom", "spec", "build", "freecad_assembly",
];

export function ChecksPanel({
  viewer,
  highlight,
  onHighlight,
}: {
  viewer: Viewer;
  highlight: Highlight;
  onHighlight: (h: Highlight) => void;
}) {
  const groups = useMemo(() => {
    const by = new Map<string, ViewerCheck[]>();
    for (const c of viewer.checks) by.set(c.group, [...(by.get(c.group) ?? []), c]);
    // Product checks first, then the generic assembly report (groups prefixed assembly_).
    const rank = (g: string): number =>
      g.startsWith("assembly_") ? 100 + rank(g.slice(9)) : GROUP_ORDER.includes(g) ? GROUP_ORDER.indexOf(g) : GROUP_ORDER.length;
    return [...by.entries()].sort((a, b) => rank(a[0]) - rank(b[0]));
  }, [viewer]);
  const failed = viewer.checks.filter((c) => !c.passed && !isWarning(c));
  const warnings = viewer.checks.filter(isWarning);

  return (
    <div data-testid="checks-panel">
      <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="shrink-0">
          <StatusBadge tone={viewer.passed ? "success" : "error"}>
            {viewer.passed && !failed.length ? `all ${viewer.checks.length} checks passed` : `${failed.length} of ${viewer.checks.length} failed`}
          </StatusBadge>
        </span>
        {warnings.length ? (
          <span className="shrink-0">
            <StatusBadge tone="warning">
              {warnings.length} warning{warnings.length === 1 ? "" : "s"}
            </StatusBadge>
          </span>
        ) : null}
        <span className="text-xs text-muted-text">measured on the placed solids</span>
        {highlight ? (
          <Button size="sm" variant="tertiary" className="ml-auto" onClick={() => onHighlight(null)}>
            <X size={13} strokeWidth={1.75} aria-hidden />
            Clear highlight
          </Button>
        ) : null}
      </div>
      {groups.map(([group, checks]) => (
        <section key={group} aria-label={groupLabel(group)}>
          <Caption>
            {groupLabel(group)} · {checks.filter((c) => c.passed || isWarning(c)).length}/{checks.length}
          </Caption>
          <ul className="flex flex-col gap-1">
            {checks.map((c) => {
              const active = highlight?.label === c.name;
              const clickable = c.instances.length > 0;
              const warn = isWarning(c);
              return (
                <li key={c.name} data-check={c.name} data-passed={c.passed} data-severity={c.severity ?? "error"}>
                  <button
                    type="button"
                    disabled={!clickable}
                    aria-pressed={active}
                    onClick={() => onHighlight(active ? null : { ids: c.instances, tone: c.passed ? "pass" : "clash", label: c.name })}
                    title={clickable ? `Highlight ${c.instances.join(", ")}` : (c.note ?? "")}
                    className={[
                      "flex w-full items-start justify-between gap-3 rounded-lg border px-2.5 py-2 text-left outline-none transition-colors duration-fast",
                      active
                        ? "border-line-strong bg-surface"
                        : c.passed
                          ? "border-transparent"
                          : warn
                            ? "border-consent/40 bg-consent-soft"
                            : "border-fail/40 bg-fail-soft",
                      clickable ? "hover:bg-surface" : "cursor-default",
                    ].join(" ")}
                  >
                    <span className="min-w-0">
                      <span className="block text-xs text-ink [overflow-wrap:anywhere]">{checkTitle(c)}</span>
                      <span className="block text-xs text-muted-text tabular [overflow-wrap:anywhere]">{checkDetail(c)}</span>
                    </span>
                    <span className="shrink-0">
                      <StatusBadge tone={c.passed ? "success" : warn ? "warning" : "error"}>{c.passed ? "pass" : warn ? "warn" : "fail"}</StatusBadge>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      <p className="mt-4 text-xs text-muted-text">
        Interference and clearance are measured with exact boolean and distance passes on the B-reps. A clean check is not an engineering
        review: fits, loads and tolerances still need an engineer.
      </p>
    </div>
  );
}

// --- joints --------------------------------------------------------------------------

function JointRow({ joint, value, onChange }: { joint: ViewerJoint; value: number; onChange: (v: number) => void }) {
  const [lo, hi] = joint.limits;
  const step = joint.param === "angle" ? 1 : Math.max(0.1, +((hi - lo) / 200).toFixed(1));
  const playing = useRef<number | null>(null);
  const [isPlaying, setPlaying] = useState(false);
  const latest = useRef(value);
  useEffect(() => {
    latest.current = value;
  }, [value]);
  useEffect(() => () => {
    if (playing.current) cancelAnimationFrame(playing.current);
  }, []);

  function sweep() {
    if (playing.current) {
      cancelAnimationFrame(playing.current);
      playing.current = null;
      setPlaying(false);
      onChange(latest.current);
      return;
    }
    setPlaying(true);
    const t0 = performance.now();
    const period = 3000;
    const tick = (t: number) => {
      const phase = ((t - t0) % period) / period;
      const tri = phase < 0.5 ? phase * 2 : 2 - phase * 2;
      onChange(+(lo + (hi - lo) * tri).toFixed(2));
      playing.current = requestAnimationFrame(tick);
    };
    playing.current = requestAnimationFrame(tick);
  }

  const id = `joint-${joint.name}`;
  return (
    <li className="rounded-lg border border-line px-3 py-2.5" data-joint={joint.name}>
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0">
          <label htmlFor={id} className="block truncate text-xs text-ink">
            {joint.name}
          </label>
          <span className="block truncate text-xs text-muted-text">
            {joint.type} · {joint.moving.join(", ")} on {joint.a === joint.moving[0] ? joint.b : joint.a}
            {joint.has_limits ? "" : " · no limits set"}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1">
          <span className="w-20 text-right text-sm tabular text-ink" data-testid={`joint-value-${joint.name}`}>
            {+value.toFixed(2)} {joint.unit}
          </span>
          <IconButton label={`Sweep ${joint.name}`} onClick={sweep}>
            {isPlaying ? <Pause size={13} strokeWidth={1.75} aria-hidden /> : <Play size={13} strokeWidth={1.75} aria-hidden />}
          </IconButton>
          <IconButton label={`Reset ${joint.name}`} onClick={() => onChange(joint.value)} disabled={value === joint.value}>
            <RotateCcw size={13} strokeWidth={1.75} aria-hidden />
          </IconButton>
        </span>
      </div>
      <input
        id={id}
        type="range"
        aria-label={`${joint.name} joint ${joint.param === "angle" ? "angle" : "position"}`}
        min={lo}
        max={hi}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-[var(--viewer-select)]"
      />
      <div className="flex justify-between text-xs tabular text-muted-text">
        <span>
          {lo} {joint.unit}
        </span>
        <span>assembled {joint.value}</span>
        <span>
          {hi} {joint.unit}
        </span>
      </div>
    </li>
  );
}

export function JointsPanel({
  viewer,
  values,
  onChange,
}: {
  viewer: Viewer;
  values: Record<string, number>;
  onChange: (name: string, value: number) => void;
}) {
  if (!viewer.joints.length) {
    return <EmptyState title="No moving joints" detail="Every mate in this assembly is rigid (fixed), so there is nothing to scrub." />;
  }
  return (
    <div>
      <p className="mb-2 text-xs text-muted-text">
        Drag a joint across its limits to see the motion the sweep check samples. Poses are previews; the published version keeps the
        assembled values.
      </p>
      <ul className="flex flex-col gap-2" data-testid="joints-panel">
        {viewer.joints.map((j) => (
          <JointRow key={j.name} joint={j} value={values[j.name] ?? j.value} onChange={(v) => onChange(j.name, v)} />
        ))}
      </ul>
    </div>
  );
}

// --- export --------------------------------------------------------------------------

const KIND_LABELS: Record<string, [string, string]> = {
  STEP: ["STEP", "Assembly with instance names and colours"],
  FCSTD: ["FreeCAD", "Native Assembly with links and joints"],
  BOM_CSV: ["BOM (CSV)", "One line per part number"],
  BOM_JSON: ["BOM (JSON)", "Lines with instances and volumes"],
  PLACEMENTS: ["Placements", "Part-to-world matrix per instance (JSON)"],
  DXF: ["Flat pattern (DXF)", "Outline, bend lines and bend extents"],
  PRODUCT_BOM_CSV: ["Product BOM (CSV)", "Make / buy / standard, tree node, mass"],
  PRODUCT_BOM_JSON: ["Product BOM (JSON)", "Product tree joined with the BOM"],
  RECIPE: ["Spec", "Replayable spec (JSON)"],
  ASSEMBLY_SPEC: ["Assembly spec", "Derived instances and mates (JSON)"],
  VALIDATION: ["Validation report", "All checks (JSON)"],
  PRODUCT: ["Product report", "Status, checks, router log (JSON)"],
  RENDER_SIDE: ["Side render", "PNG"],
  RENDER_ISO: ["Iso render", "PNG"],
};

export function KindExportPanel({
  version,
  canExport,
  freecadAvailable,
  onExportFcstd,
}: {
  version: Version;
  canExport: boolean;
  freecadAvailable: boolean;
  onExportFcstd: () => void;
}) {
  const files = version.artifacts.filter((a) => KIND_LABELS[a.format]);
  const order = Object.keys(KIND_LABELS);
  files.sort((a, b) => order.indexOf(a.format) - order.indexOf(b.format));
  const hasFcstd = version.artifacts.some((a) => a.format === "FCSTD");
  const assembly = version.kind === "assembly" || version.kind === "product";
  return (
    <div>
      <p className="mb-3 text-xs text-muted-text">
        Source v{version.number} · build123d {version.engine.build123d} · OCP {version.engine.ocp}
      </p>
      <ul className="flex flex-col">
        {files.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-3 border-b border-line py-2 last:border-b-0">
            <span className="min-w-0">
              <span className="block text-sm text-ink">{KIND_LABELS[a.format][0]}</span>
              <span className="block truncate text-xs text-muted-text">
                {KIND_LABELS[a.format][1]} · {(a.bytes / 1024).toFixed(1)} KB
              </span>
            </span>
            <Button size="sm" onClick={() => downloadArtifact(a.id)} aria-label={`Download ${KIND_LABELS[a.format][0]}`}>
              <Download size={13} strokeWidth={1.75} aria-hidden />
              Download
            </Button>
          </li>
        ))}
      </ul>
      {assembly && !hasFcstd ? (
        <div className="mt-4 rounded-lg border border-line bg-surface p-3">
          <div className="flex items-center gap-2">
            <FileBox size={15} strokeWidth={1.75} className="text-muted" aria-hidden />
            <span className="text-sm text-ink">Native FreeCAD assembly</span>
          </div>
          <p className="mt-1 text-xs text-muted-text">
            One App::Link per instance and a native joint per mate; FreeCAD&apos;s solver re-places the parts and Shilpa checks the joints hold.
          </p>
          <Button size="sm" variant="primary" className="mt-3" disabled={!canExport || !freecadAvailable} onClick={onExportFcstd}>
            Create FreeCAD file
          </Button>
          {!freecadAvailable ? <p className="mt-2 text-xs text-muted-text">FreeCAD is not installed on this server.</p> : null}
        </div>
      ) : null}
    </div>
  );
}
