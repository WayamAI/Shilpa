"use client";

import { Download, FileBox, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, KeyValue, NumberInput } from "@/components/ui/controls";
import { EmptyState, StatusBadge } from "@/components/ui/primitives";
import { downloadArtifact, paramValue, type Check, type Version } from "@/lib/api";

function Caption({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-5 mb-2 text-caption tracking-[0.08em] text-quaternary uppercase first:mt-0">{children}</h3>;
}

function humanize(name: string) {
  return name.replace(/_/g, " ");
}

// --- parameters ---------------------------------------------------------------

export function ParamsPanel({
  version,
  editable,
  isHead,
  onApply,
}: {
  version: Version;
  editable: boolean;
  isHead: boolean;
  onApply: (changes: Record<string, number>) => void;
}) {
  const params = version.recipe?.parameters ?? version.parameters;
  // The parent keys this panel by version id, so a new version starts with an empty draft.
  const [draft, setDraft] = useState<Record<string, string>>({});

  const changes = useMemo(() => {
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v);
      if (v.trim() !== "" && Number.isFinite(n) && n !== paramValue(params[k])) out[k] = n;
    }
    return out;
  }, [draft, params]);
  const units = version.recipe?.units ?? "mm";

  return (
    <div>
      {!isHead ? (
        <p className="mb-3 rounded-lg border border-warning-stroke bg-warning-surface px-3 py-2 text-body-sm text-warning">
          Viewing an older version. Edits apply to the latest version.
        </p>
      ) : null}
      <table className="w-full">
        <tbody>
          {Object.entries(params).map(([name, p]) => {
            const meta = typeof p === "number" ? {} : p;
            const unit = meta.kind === "count" ? "" : meta.kind === "angle" ? (meta.unit ?? "deg") : (meta.unit ?? units);
            const derived = !!meta.expr;
            return (
              <tr key={name} className="border-b border-muted last:border-b-0">
                <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                  <label htmlFor={`p-${name}`} className="text-body-sm text-secondary capitalize">
                    {humanize(name)}
                  </label>
                  {meta.source && meta.source !== "user" ? (
                    <span className="ml-1.5 align-middle">
                      <StatusBadge tone={meta.source === "drawing" ? "info" : "warning"}>{meta.source}</StatusBadge>
                    </span>
                  ) : null}
                </th>
                <td className="py-1.5 text-right">
                  <NumberInput
                    id={`p-${name}`}
                    disabled={!editable || derived}
                    value={draft[name] ?? (paramValue(p) ?? "")}
                    onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
                  />
                </td>
                <td className="w-9 py-1.5 pl-2 text-body-sm text-quaternary">{unit}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {editable ? (
        <div className="mt-3 flex items-center gap-2">
          <Button variant="primary" size="sm" disabled={Object.keys(changes).length === 0} onClick={() => onApply(changes)}>
            Apply as new version
          </Button>
          {Object.keys(changes).length > 0 ? (
            <Button variant="tertiary" size="sm" onClick={() => setDraft({})}>
              Reset
            </Button>
          ) : null}
        </div>
      ) : null}

      {version.recipe?.assumptions && version.recipe.assumptions.length > 0 ? (
        <>
          <Caption>Assumptions</Caption>
          <ul className="flex flex-col gap-1.5">
            {version.recipe.assumptions.map((a) => (
              <li key={a.parameter} className="text-body-sm text-tertiary">
                <span className="text-secondary">{humanize(a.parameter)}</span> — {a.reason}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <Caption>Features · {version.features?.length ?? 0}</Caption>
      <ol className="flex flex-col">
        {(version.features ?? []).map((f, i) => (
          <li key={f.id} className="flex items-baseline gap-2 py-1">
            <span className="w-5 shrink-0 text-right text-caption tabular text-quaternary">{i + 1}</span>
            <code className="truncate text-body-sm text-primary">{f.id}</code>
            <span className="truncate text-body-sm text-quaternary">{humanize(f.op)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// --- validation ----------------------------------------------------------------

const CHECK_LABELS: Record<string, string> = {
  step_reimport: "STEP re-import",
  valid_brep: "Valid solid (BREP)",
  solid_count: "Solid count",
  step_roundtrip_volume: "STEP round-trip volume",
  bbox: "Bounding box",
  volume: "Volume",
  stl_watertight: "STL watertight",
  stl_extent_mm: "STL size",
  glb_extent_m: "Preview size (GLB)",
  freecad_build: "FreeCAD build",
  freecad_matches_build123d_bbox: "FreeCAD matches build123d size",
};

/** Engineering label for a check id, e.g. holes_d6 -> "Ø6 holes", freecad_bbox -> "FreeCAD · Bounding box". */
export function checkLabel(name: string): string {
  if (CHECK_LABELS[name]) return CHECK_LABELS[name];
  const holes = /^(?:oracle_)?holes_d([\d.]+)$/.exec(name);
  if (holes) return `Ø${holes[1]} holes`;
  if (name.startsWith("freecad_")) return `FreeCAD · ${checkLabel(name.slice(8))}`;
  if (name.startsWith("oracle_")) return `Reference · ${checkLabel(name.slice(7))}`;
  return name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function fmt(v: unknown): string {
  if (Array.isArray(v)) return v.map(fmt).join(", ");
  if (typeof v === "number") return String(+v.toFixed(4));
  if (v === null || v === undefined) return "—";
  return String(v);
}

export function ValidationPanel({ version }: { version: Version }) {
  const v = version.validation;
  if (!v) return <EmptyState title="No validation report" />;
  const m = v.measurement;
  const holes = m?.cylinders.filter((c) => c.kind === "hole") ?? [];
  const holeSummary = Object.entries(
    holes.reduce<Record<string, number>>((acc, c) => ({ ...acc, [String(+c.diameter.toFixed(3))]: (acc[String(+c.diameter.toFixed(3))] ?? 0) + 1 }), {}),
  )
    .map(([d, n]) => `${n}× Ø${d}`)
    .join(", ");
  const failed = v.checks.filter((c) => !c.passed);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="shrink-0">
          <StatusBadge tone={v.passed ? "success" : "error"}>{v.passed ? "all checks passed" : `${failed.length} failed`}</StatusBadge>
        </span>
        <span className="text-body-sm text-tertiary">measured on the re-imported STEP</span>
      </div>
      {m ? (
        <KeyValue
          rows={[
            { label: "Size (exact)", value: `${m.bbox_size.map((x) => +x.toFixed(4)).join(" × ")} mm` },
            { label: "Volume", value: `${m.volume.toLocaleString(undefined, { maximumFractionDigits: 3 })} mm³` },
            { label: "Surface area", value: `${m.area.toLocaleString(undefined, { maximumFractionDigits: 1 })} mm²` },
            { label: "Solids", value: `${m.solid_count}${m.valid ? " · valid BREP" : " · invalid BREP"}` },
            { label: "Holes", value: holeSummary || "none" },
          ]}
        />
      ) : null}
      <Caption>Checks · {v.checks.length}</Caption>
      <ul className="flex flex-col">
        {v.checks.map((c: Check, i) => (
          <li key={i} className="flex items-start justify-between gap-3 border-b border-muted py-2 last:border-b-0" title={c.note ?? ""}>
            <span className="min-w-0">
              <span className="block text-body-sm text-primary">{checkLabel(c.name)}</span>
              {c.requested !== null && c.requested !== undefined ? (
                <span className="block truncate text-caption text-quaternary tabular">
                  {fmt(c.requested)} → {fmt(c.actual)}
                </span>
              ) : c.note ? (
                <span className="block truncate text-caption text-quaternary">{c.note}</span>
              ) : null}
            </span>
            <StatusBadge tone={c.passed ? "success" : "error"}>{c.passed ? "pass" : "fail"}</StatusBadge>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-body-sm text-quaternary">
        A valid solid does not establish strength, fit or manufacturability. Tolerances are software comparison tolerances.
      </p>
    </div>
  );
}

// --- versions -------------------------------------------------------------------

export function VersionsPanel({
  versions,
  current,
  canRestore,
  onOpen,
  onRestore,
}: {
  versions: Version[];
  current: string;
  canRestore: boolean;
  onOpen: (id: string) => void;
  onRestore: (id: string) => void;
}) {
  return (
    <div>
    <p className="mb-2 text-caption tracking-[0.08em] text-quaternary uppercase">
      {versions.length} version{versions.length === 1 ? "" : "s"} · each change is a new immutable version
    </p>
    <ol className="flex flex-col gap-2">
      {versions.map((v, i) => {
        const active = v.id === current;
        return (
          <li key={v.id}>
            <div
              className={[
                "rounded-lg border px-3 py-2.5 transition-colors duration-[150ms]",
                active ? "border-active bg-raised" : "border-muted hover:bg-raised",
              ].join(" ")}
            >
              <div className="flex items-center justify-between gap-2">
                <button type="button" onClick={() => onOpen(v.id)} className="flex min-w-0 items-baseline gap-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-active">
                  <span className="font-display text-display-base text-primary">v{v.number}</span>
                  {i === 0 ? <StatusBadge tone="info">latest</StatusBadge> : null}
                  <span className="truncate text-caption text-quaternary">{new Date(v.created_at).toLocaleString(undefined, { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })}</span>
                </button>
                {i > 0 && canRestore ? (
                  <Button size="sm" variant="tertiary" onClick={() => onRestore(v.id)} title="Restore as a new version">
                    <RotateCcw size={13} strokeWidth={1.75} aria-hidden />
                    Restore
                  </Button>
                ) : null}
              </div>
              <p className="mt-1 text-body-sm text-tertiary">{v.change_summary || (v.parent_version_id ? "Edited" : "Initial generation")}</p>
            </div>
          </li>
        );
      })}
    </ol>
    </div>
  );
}

// --- export ---------------------------------------------------------------------

const LABELS: Record<string, [string, string]> = {
  STEP: ["STEP", "Exchange solid for any CAD system"],
  FCSTD: ["FreeCAD", "Native parametric features, Params sheet"],
  STL: ["STL", "Mesh in millimetres, for printing"],
  GLB: ["GLB", "Preview mesh in metres"],
  RECIPE: ["Recipe", "Shilpa IR (JSON) — replayable"],
  VALIDATION: ["Validation report", "All checks (JSON)"],
  STL_UNITS: ["STL units", "Units and tessellation sidecar"],
};

export function ExportPanel({ version, canExport, onExportFcstd }: { version: Version; canExport: boolean; onExportFcstd: () => void }) {
  const files = version.artifacts.filter((a) => LABELS[a.format]);
  const hasFcstd = version.artifacts.some((a) => a.format === "FCSTD");
  return (
    <div>
      <p className="mb-3 text-body-sm text-tertiary">
        Source v{version.number} · build123d {version.engine.build123d} · OCP {version.engine.ocp}
      </p>
      <ul className="flex flex-col">
        {files.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-3 border-b border-muted py-2 last:border-b-0">
            <span className="min-w-0">
              <span className="block text-body-md text-primary">{LABELS[a.format][0]}</span>
              <span className="block truncate text-caption text-quaternary">
                {LABELS[a.format][1]} · {(a.bytes / 1024).toFixed(1)} KB
              </span>
            </span>
            <Button size="sm" onClick={() => downloadArtifact(a.id)} aria-label={`Download ${LABELS[a.format][0]}`}>
              <Download size={13} strokeWidth={1.75} aria-hidden />
              Download
            </Button>
          </li>
        ))}
      </ul>
      {!hasFcstd ? (
        <div className="mt-4 rounded-lg border border-muted bg-raised p-3">
          <div className="flex items-center gap-2">
            <FileBox size={15} strokeWidth={1.75} className="icon-tertiary" aria-hidden />
            <span className="text-body-md text-primary">Native FreeCAD file</span>
          </div>
          <p className="mt-1 text-body-sm text-tertiary">
            Builds Sketcher and PartDesign features driven by a Params sheet, then checks they match this version.
          </p>
          <Button size="sm" variant="primary" className="mt-3" disabled={!canExport} onClick={onExportFcstd}>
            Create FreeCAD file
          </Button>
        </div>
      ) : null}
    </div>
  );
}
