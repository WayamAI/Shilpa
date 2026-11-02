"use client";

import { Download, FileBox, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, Button, EmptyState, KeyValue, NumberInput } from "@/components/ui";
import { downloadArtifact, paramValue, type Check, type Version } from "@/lib/api";

function Caption({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-6 mb-2 text-md first:mt-0">{children}</h3>;
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
        <p className="mb-3 rounded-lg border border-consent/40 bg-consent-soft px-3 py-2 text-xs text-consent-text">
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
              <tr key={name} className="border-b border-line last:border-b-0">
                <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                  <label htmlFor={`p-${name}`} className="text-xs text-body capitalize">
                    {humanize(name)}
                  </label>
                  {meta.source && meta.source !== "user" ? (
                    <span className="ml-1.5 align-middle">
                      <Badge tone={meta.source === "drawing" ? "complex" : "consent"}>{meta.source}</Badge>
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
                <td className="w-9 py-1.5 pl-2 text-xs text-muted-text">{unit}</td>
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
            <Button variant="ghost" size="sm" onClick={() => setDraft({})}>
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
              <li key={a.parameter} className="text-xs text-muted-text">
                <span className="text-body">{humanize(a.parameter)}</span>: {a.reason}
              </li>
            ))}
          </ul>
        </>
      ) : null}

    </div>
  );
}

// --- features -------------------------------------------------------------------

/** Paper part detail, Features tab: feature, operation, then metadata and "Used in". */
export function FeaturesPanel({ version }: { version: Version }) {
  const features = version.features ?? [];
  const units = version.recipe?.units ?? "mm";
  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Features">
        <h3 className="mb-2 text-md">
          Features <span className="ml-1 font-normal text-body tabular">{features.length}</span>
        </h3>
        {features.length ? (
          <table className="w-full">
            <thead>
              <tr>
                <th scope="col" className="h-7 w-9 text-right text-xs font-semibold text-body">#</th>
                <th scope="col" className="h-7 pl-3 text-left text-xs font-semibold text-body">@ name</th>
                <th scope="col" className="h-7 text-left text-xs font-semibold text-body">Operation</th>
              </tr>
            </thead>
            <tbody>
              {features.map((f, i) => (
                <tr key={f.id} className="h-9 border-t border-line last:border-b">
                  <td className="text-right text-xs tabular text-muted-text">{i + 1}</td>
                  <td className="max-w-0 truncate pl-3 text-sm font-semibold text-ink">{f.id}</td>
                  <td className="text-sm text-ink">{humanize(f.op)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-body">This version records no features.</p>
        )}
      </section>
      <section aria-label="Metadata">
        <h3 className="mb-2 text-md">Metadata</h3>
        <KeyValue
          rows={[
            { label: "Version", value: `v${version.number}` },
            { label: "Units", value: units },
            { label: "Recipe hash", value: <span className="text-xs">{version.recipe_hash.slice(0, 12)}</span>, title: version.recipe_hash },
            { label: "Engine", value: `build123d ${version.engine.build123d} · OCP ${version.engine.ocp}` },
          ]}
        />
      </section>
      <section aria-label="Used in">
        <h3 className="mb-2 flex items-center gap-2 text-md">
          Used in <Badge tone="consent">Planned</Badge>
        </h3>
        <p className="text-sm text-body">Complex parts that pin this part, with their pinned version, will be listed here.</p>
      </section>
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
  if (v === null || v === undefined) return "None";
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
      <div className="mb-4 flex items-center gap-3">
        {v.passed ? (
          // eslint-disable-next-line @next/next/no-img-element -- static decorative webp
          <img src="/imagery/sh-card-11-pass-128.webp" alt="" width={48} height={48} className="size-12 shrink-0" />
        ) : null}
        <div className="flex min-w-0 flex-col gap-1">
          <span className="self-start">
            <Badge tone={v.passed ? "pass" : "fail"}>{v.passed ? "all checks passed" : `${failed.length} failed`}</Badge>
          </span>
          <span className="text-xs text-body">Measured on the re-imported STEP</span>
        </div>
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
      <ul className="flex flex-col gap-1" aria-label="Checks">
        {v.checks.map((c: Check, i) => (
          <li
            key={i}
            className={`flex items-start justify-between gap-3 ${c.passed ? "border-b border-line py-2.5" : "rounded-lg border border-fail/40 bg-fail-soft px-3 py-2.5"}`}
            title={c.note ?? ""}
          >
            <span className="min-w-0">
              <span className="block text-sm text-ink">{checkLabel(c.name)}</span>
              {c.requested !== null && c.requested !== undefined ? (
                <span className="block text-xs text-body tabular [overflow-wrap:anywhere]">
                  Oracle · {fmt(c.requested)} → {fmt(c.actual)}
                </span>
              ) : c.note ? (
                <span className="block text-xs text-body [overflow-wrap:anywhere]">{c.note}</span>
              ) : null}
            </span>
            <Badge tone={c.passed ? "pass" : "fail"}>{c.passed ? "Pass" : "Fail"}</Badge>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs text-body">
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
      <p className="mb-2 text-xs text-body">
        {versions.length} version{versions.length === 1 ? "" : "s"} · each change is a new immutable version
      </p>
      <ol className="flex flex-col">
        {versions.map((v, i) => {
          const active = v.id === current;
          return (
            <li
              key={v.id}
              aria-current={active ? "true" : undefined}
              className={`flex items-center gap-2 border-t border-line py-1 last:border-b ${active ? "bg-surface" : ""}`}
            >
              <button type="button" onClick={() => onOpen(v.id)} className="flex min-h-9 min-w-0 flex-1 items-center gap-3 rounded-sm text-left">
                <span className="w-9 shrink-0 pl-1 text-sm font-semibold text-ink">v{v.number}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-ink [overflow-wrap:anywhere]">
                    {v.change_summary || (v.parent_version_id ? "Edited" : "Initial generation")}
                  </span>
                  <span className="flex items-center gap-2 text-xs text-body">
                    {new Date(v.created_at).toLocaleString(undefined, { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })}
                    {i === 0 ? <Badge tone="complex">latest</Badge> : null}
                  </span>
                </span>
              </button>
              {i > 0 && canRestore ? (
                <Button size="sm" variant="ghost" onClick={() => onRestore(v.id)} title="Restore as a new version">
                  <RotateCcw size={13} strokeWidth={1.75} aria-hidden />
                  Restore
                </Button>
              ) : null}
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
  RECIPE: ["Recipe", "Shilpa IR (JSON), replayable"],
  VALIDATION: ["Validation report", "All checks (JSON)"],
  STL_UNITS: ["STL units", "Units and tessellation sidecar"],
};

export function ExportPanel({ version, canExport, onExportFcstd }: { version: Version; canExport: boolean; onExportFcstd: () => void }) {
  const files = version.artifacts.filter((a) => LABELS[a.format]);
  const hasFcstd = version.artifacts.some((a) => a.format === "FCSTD");
  return (
    <div>
      <p className="mb-3 text-xs text-body">
        Source v{version.number} · build123d {version.engine.build123d} · OCP {version.engine.ocp}
      </p>
      <ul className="flex flex-col">
        {files.map((a) => (
          <li key={a.id} className="flex min-h-12 items-center justify-between gap-3 border-t border-line py-2 last:border-b">
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-ink">{LABELS[a.format][0]}</span>
              <span className="block text-xs text-body">
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
        <div className="mt-4 flex items-start gap-3 rounded-lg border border-line bg-surface p-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- static decorative webp */}
          <img src="/imagery/sh-card-14-exports-128.webp" alt="" width={40} height={40} className="size-10 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">Native FreeCAD file</p>
            <p className="mt-0.5 text-xs text-body">
              Builds Sketcher and PartDesign features driven by a Params sheet, then checks they match this version.
            </p>
            <Button size="sm" className="mt-3" icon={<FileBox size={13} strokeWidth={1.75} aria-hidden />} disabled={!canExport} onClick={onExportFcstd}>
              Create FreeCAD file
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
