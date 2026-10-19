"use client";

import { Download, Library, Search } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { PageBody, PageHeader } from "@/components/layout/page-header";
import { Button, KeyValue, NumberInput, Tabs, TextInput } from "@/components/ui/controls";
import { EmptyState, Panel, Select, StatusBadge, StatusDot } from "@/components/ui/primitives";
import {
  catalogApi,
  downloadCatalogStep,
  errText,
  type Catalog,
  type CatalogGenerator,
  type CatalogMatch,
  type CatalogPreview,
  type SchemaProp,
} from "@/lib/api";

const PartViewer = dynamic(() => import("@/components/studio/part-viewer"), {
  ssr: false,
  loading: () => <EmptyState title="Loading the 3D view…" />,
});

const SELECT =
  "h-8 w-full min-w-0 rounded-full border border-muted bg-action text-body-sm text-primary outline-none focus-visible:ring-2 focus-visible:ring-active";

// ---------------------------------------------------------------- schema helpers

/** The non-null branch of an Optional[...] property, and whether null is allowed. */
function base(prop: SchemaProp): { p: SchemaProp; nullable: boolean } {
  if (!prop.anyOf) return { p: prop, nullable: false };
  const real = prop.anyOf.filter((x) => x.type !== "null");
  return { p: { ...real[0], default: prop.default, title: prop.title, description: prop.description }, nullable: real.length < prop.anyOf.length };
}

function label(name: string, prop: SchemaProp): string {
  const t = prop.title ?? name;
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

function limits(p: SchemaProp): string | null {
  const lo = p.minimum ?? p.exclusiveMinimum;
  const hi = p.maximum ?? p.exclusiveMaximum;
  if (lo === undefined && hi === undefined) return null;
  const a = lo === undefined ? "" : `${p.exclusiveMinimum !== undefined ? ">" : "≥"} ${lo}`;
  const b = hi === undefined ? "" : `${p.exclusiveMaximum !== undefined ? "<" : "≤"} ${hi}`;
  return [a, b].filter(Boolean).join(", ");
}

function show(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

/** Raw form text -> the typed value sent to the API, or undefined to use the generator default. */
function parse(raw: string | boolean | undefined, prop: SchemaProp): unknown {
  const { p } = base(prop);
  if (raw === undefined || raw === "") return undefined;
  if (p.type === "boolean") return raw === true;
  if (p.enum) return p.enum.find((e) => String(e) === raw) ?? raw;
  if (p.type === "number" || p.type === "integer") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (p.type === "array") {
    return String(raw)
      .split(/[,\s]+/)
      .filter(Boolean)
      .map((s) => (Number.isFinite(Number(s)) ? Number(s) : s));
  }
  return raw;
}

type Draft = Record<string, string | boolean>;

function paramsOf(gen: CatalogGenerator, draft: Draft): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, prop] of Object.entries(gen.params.properties)) {
    const v = parse(draft[name], prop);
    if (v !== undefined) out[name] = v;
  }
  return out;
}

function ParamField({
  name,
  prop,
  value,
  materials,
  onChange,
}: {
  name: string;
  prop: SchemaProp;
  value: string | boolean | undefined;
  materials: string[];
  onChange: (v: string | boolean) => void;
}) {
  const { p, nullable } = base(prop);
  const placeholder = p.default === null || p.default === undefined ? (nullable ? "auto" : "") : show(p.default);
  let control;
  if (name === "material") {
    control = (
      <Select aria-label={label(name, prop)} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} className={SELECT}>
        <option value="">{p.default ? `default (${String(p.default)})` : "none (no mass)"}</option>
        {materials.map((m) => (
          <option key={m} value={m}>
            {m.replace(/_/g, " ")}
          </option>
        ))}
      </Select>
    );
  } else if (p.type === "boolean") {
    const checked = value === undefined ? p.default === true : value === true;
    control = (
      <input type="checkbox" aria-label={label(name, prop)} checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-current" />
    );
  } else if (p.enum) {
    control = (
      <Select aria-label={label(name, prop)} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} className={SELECT}>
        <option value="">{nullable && (p.default === null || p.default === undefined) ? "auto" : `default (${show(p.default)})`}</option>
        {p.enum.map((e) => (
          <option key={String(e)} value={String(e)}>
            {String(e).replace(/_/g, " ")}
          </option>
        ))}
      </Select>
    );
  } else if (p.type === "number" || p.type === "integer") {
    control = (
      <NumberInput
        aria-label={label(name, prop)}
        value={String(value ?? "")}
        placeholder={placeholder}
        step={p.type === "integer" ? 1 : "any"}
        onChange={(e) => onChange(e.target.value)}
        className="w-28"
      />
    );
  } else {
    control = (
      <TextInput
        aria-label={label(name, prop)}
        value={String(value ?? "")}
        placeholder={placeholder || (p.type === "array" ? "comma separated" : "")}
        onChange={(e) => onChange(e.target.value)}
        className="!h-8 text-body-sm"
      />
    );
  }
  const hint = [limits(p), p.description].filter(Boolean).join(" · ");
  return (
    <div className="flex items-center justify-between gap-3 border-b border-muted py-2 last:border-b-0">
      <div className="min-w-0">
        <p className="truncate text-body-sm text-primary">{label(name, prop)}</p>
        {hint ? <p className="truncate text-caption text-quaternary" title={hint}>{hint}</p> : null}
      </div>
      <div className="flex max-w-[55%] shrink-0 justify-end">{control}</div>
    </div>
  );
}

// ---------------------------------------------------------------- page

/** Typed-name matches ("M6x20 socket head", "6204-2RS"): one click opens the part with its sizes filled in. */
function Suggestions({ matches, onPick }: { matches: CatalogMatch[]; onPick: (m: CatalogMatch) => void }) {
  if (!matches.length) return null;
  return (
    <div className="mb-3" data-testid="catalog-matches">
      <p className="mb-1 text-caption tracking-[0.08em] text-quaternary uppercase">Exact part</p>
      <ul className="flex flex-col gap-1">
        {matches.map((m) => (
          <li key={`${m.generator}|${JSON.stringify(m.params)}`}>
            <button
              type="button"
              onClick={() => onPick(m)}
              className="w-full rounded-md border border-muted bg-raised px-2 py-1.5 text-left outline-none transition-colors duration-[180ms] hover:bg-raised-2 focus-visible:ring-2 focus-visible:ring-active"
            >
              <span className="block truncate text-body-sm text-primary">{m.label}</span>
              <span className="block truncate text-caption text-quaternary">{m.summary}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Tab = "params" | "data" | "ports";

const META_FIRST = ["designation", "standard", "size", "mass_g", "mass_basis", "provenance"];

export default function CatalogPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [result, setResult] = useState<{ key: string; preview?: CatalogPreview; error?: string } | null>(null);
  const [shown, setShown] = useState<CatalogPreview | null>(null);
  const [tab, setTab] = useState<Tab>("params");
  const [showPorts, setShowPorts] = useState(true);
  const [port, setPort] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [matches, setMatches] = useState<{ q: string; items: CatalogMatch[] }>({ q: "", items: [] });
  const latest = useRef("");

  useEffect(() => {
    catalogApi
      .list()
      .then((c) => {
        setCatalog(c);
        setSelected((s) => s ?? c.generators[0]?.name ?? null);
      })
      .catch((e) => setError(errText(e)));
  }, []);

  const gen = catalog?.generators.find((g) => g.name === selected) ?? null;
  const draft = useMemo(() => (selected ? (drafts[selected] ?? {}) : {}), [drafts, selected]);
  const params = useMemo(() => (gen ? paramsOf(gen, draft) : {}), [gen, draft]);
  const key = gen ? `${gen.name}|${JSON.stringify(params)}` : "";

  // Rebuild after a short pause in typing; only the newest request may update the view.
  useEffect(() => {
    if (!gen) return;
    latest.current = key;
    const timer = setTimeout(() => {
      catalogApi
        .preview(gen.name, params)
        .then((preview) => {
          if (latest.current !== key) return;
          setResult({ key, preview });
          setShown(preview);
        })
        .catch((e) => latest.current === key && setResult({ key, error: errText(e) }));
    }, 350);
    return () => clearTimeout(timer);
  }, [gen, key, params]);

  // Typed names resolve on the server (rule-based, no AI) after a short pause in typing.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) return;
    const timer = setTimeout(() => {
      catalogApi
        .lookup(q)
        .then((r) => setMatches({ q, items: r.matches }))
        .catch(() => setMatches({ q, items: [] }));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);
  const suggestions = matches.q === query.trim() ? matches.items : [];

  const busy = !!gen && result?.key !== key;
  const current = shown && gen && shown.generator === gen.name ? shown : null;
  const buildError = result?.key === key ? result.error : undefined;

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const hits = (catalog?.generators ?? []).filter(
      (g) => !q || `${g.name} ${g.summary} ${g.standard} ${g.family}`.toLowerCase().includes(q),
    );
    return (catalog?.families ?? []).map((f) => ({ family: f, items: hits.filter((g) => g.family === f) })).filter((x) => x.items.length);
  }, [catalog, query]);

  function edit(name: string, v: string | boolean) {
    if (!selected) return;
    setDrafts((d) => ({ ...d, [selected]: { ...(d[selected] ?? {}), [name]: v } }));
  }

  function pick(name: string) {
    setSelected(name);
    setPort(null);
  }

  function applyMatch(m: CatalogMatch) {
    const draftFrom: Draft = {};
    for (const [k, v] of Object.entries(m.params)) draftFrom[k] = typeof v === "boolean" ? v : show(v);
    setDrafts((d) => ({ ...d, [m.generator]: draftFrom }));
    pick(m.generator);
    setTab("params");
  }

  async function download() {
    if (!gen) return;
    setDownloading(true);
    try {
      await downloadCatalogStep(gen.name, params);
    } catch (e) {
      setError(errText(e));
    } finally {
      setDownloading(false);
    }
  }

  const meta = current?.meta ?? {};
  const metaRows = [
    ...META_FIRST.filter((k) => meta[k] !== undefined && meta[k] !== null),
    ...Object.keys(meta).filter((k) => !META_FIRST.includes(k) && ["string", "number", "boolean"].includes(typeof meta[k])),
  ].map((k) => ({ label: k.replace(/_/g, " "), value: <span className="tabular">{show(meta[k])}</span> }));

  return (
    <>
      <PageHeader
        title="Parts catalogue"
        description="Standard and stock parts Shilpa builds without the AI planner: set the sizes, inspect the ports that mates connect to, download STEP."
      />
      <PageBody>
        {error ? <p className="mb-3 text-body-sm text-error">{error}</p> : null}
        <div className="flex min-h-0 flex-col gap-4 xl:h-[calc(100vh-190px)] xl:flex-row">
          {/* Narrow screens pick from a grouped list so the 3D view stays near the top. */}
          <div className="flex flex-col gap-2 xl:hidden">
            <TextInput aria-label="Type a part" placeholder="Type a part: M6x20 socket head, 6204-2RS…" value={query} onChange={(e) => setQuery(e.target.value)} className="!h-10 text-body-sm" />
            <Suggestions matches={suggestions} onPick={applyMatch} />
            <Select
              aria-label="Part"
              value={selected ?? ""}
              onChange={(e) => pick(e.target.value)}
              className="h-10 w-full min-w-0 rounded-full border border-muted bg-action text-body-sm text-primary outline-none focus-visible:ring-2 focus-visible:ring-active"
            >
              {(catalog?.families ?? []).map((f) => (
                <optgroup key={f} label={f}>
                  {(catalog?.generators ?? [])
                    .filter((g) => g.family === f)
                    .map((g) => (
                      <option key={g.name} value={g.name}>
                        {g.summary}
                      </option>
                    ))}
                </optgroup>
              ))}
            </Select>
          </div>

          <div className="hidden xl:block xl:w-72 xl:shrink-0">
            <Panel title="Parts">
              <div className="relative mb-3">
                <Search size={14} strokeWidth={1.75} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 icon-quaternary" aria-hidden />
                <TextInput
                  aria-label="Search parts"
                  placeholder="Search, or type M6x20 socket head"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="!h-9 pl-8 text-body-sm"
                />
              </div>
              <Suggestions matches={suggestions} onPick={applyMatch} />
              {!catalog ? <EmptyState title="Loading the catalogue…" /> : null}
              <nav aria-label="Catalogue parts" className="flex flex-col gap-4" data-testid="catalog-list">
                {groups.map(({ family, items }) => (
                  <div key={family}>
                    <p className="mb-1 text-caption tracking-[0.08em] text-quaternary uppercase">
                      {family} <span className="tabular">· {items.length}</span>
                    </p>
                    <ul className="flex flex-col">
                      {items.map((g) => (
                        <li key={g.name}>
                          <button
                            type="button"
                            onClick={() => pick(g.name)}
                            aria-current={g.name === selected ? "true" : undefined}
                            className={`w-full rounded-md px-2 py-1.5 text-left outline-none transition-colors duration-[180ms] focus-visible:ring-2 focus-visible:ring-active ${
                              g.name === selected ? "bg-raised-2 text-primary" : "text-secondary hover:bg-raised"
                            }`}
                          >
                            <span className="block truncate text-body-sm">{g.summary}</span>
                            <span className="block truncate text-caption text-quaternary">
                              {g.name} · {g.standard}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                {catalog && !groups.length ? <EmptyState title="No parts match" /> : null}
              </nav>
            </Panel>
          </div>

          <Panel
            title={gen ? gen.summary : "Preview"}
            padded={false}
            className="min-h-[420px] flex-1"
            action={
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-label-sm text-tertiary">
                  <input type="checkbox" checked={showPorts} onChange={(e) => setShowPorts(e.target.checked)} className="size-3.5" />
                  Ports
                </label>
                <Button size="sm" onClick={download} disabled={!current || downloading || !!buildError}>
                  <Download size={14} strokeWidth={1.75} aria-hidden />
                  {downloading ? "Exporting…" : "STEP"}
                </Button>
              </div>
            }
          >
            {gen ? (
              <div className="relative h-full min-h-[420px]">
                <PartViewer mesh={current?.mesh ?? null} ports={current?.ports ?? []} showPorts={showPorts} selectedPort={port} busy={busy} />
                {buildError ? (
                  <p className="absolute inset-x-3 bottom-3 rounded-md border border-muted bg-container px-3 py-2 text-body-sm text-error" data-testid="build-error">
                    {buildError}
                  </p>
                ) : current ? (
                  <p className="pointer-events-none absolute bottom-3 left-3 rounded-full border border-muted bg-container px-2.5 py-1 text-caption tabular text-secondary">
                    {current.size.map((v) => +v.toFixed(2)).join(" × ")} mm · {(current.volume_mm3 / 1000).toFixed(1)} cm³ ·{" "}
                    {current.timings_ms.build < 1 ? "cached" : `built in ${Math.round(current.timings_ms.build)} ms`}
                  </p>
                ) : null}
              </div>
            ) : (
              <EmptyState mark={<Library size={24} strokeWidth={1.5} className="icon-quaternary" aria-hidden />} title="Pick a part" />
            )}
          </Panel>

          <Panel title={current ? String(meta.designation ?? current.name) : "Part"} className="xl:w-[26rem] xl:shrink-0">
            <div className="mb-3">
              <Tabs<Tab>
                label="Part details"
                value={tab}
                onChange={setTab}
                tabs={[
                  { id: "params", label: "Parameters" },
                  { id: "data", label: "Data" },
                  { id: "ports", label: `Ports${current ? ` · ${current.ports.length}` : ""}` },
                ]}
              />
            </div>
            {tab === "params" && gen ? (
              <div data-testid="param-form">
                {Object.entries(gen.params.properties).map(([name, prop]) => (
                  <ParamField key={name} name={name} prop={prop} value={draft[name]} materials={catalog?.materials ?? []} onChange={(v) => edit(name, v)} />
                ))}
                {Object.keys(draft).length ? (
                  <div className="mt-3 flex justify-end">
                    <Button size="sm" variant="secondary" onClick={() => selected && setDrafts((d) => ({ ...d, [selected]: {} }))}>
                      Reset to defaults
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : null}
            {tab === "data" ? (
              current ? (
                <KeyValue
                  rows={[
                    { label: "generator", value: current.generator },
                    ...metaRows,
                    { label: "volume", value: <span className="tabular">{current.volume_mm3.toFixed(0)} mm³</span> },
                  ]}
                />
              ) : (
                <EmptyState title="Building…" />
              )
            ) : null}
            {tab === "ports" ? (
              current ? (
                <ul className="flex flex-col" data-testid="port-list">
                  {current.ports.map((p) => (
                    <li key={p.name}>
                      <button
                        type="button"
                        onClick={() => setPort(port === p.name ? null : p.name)}
                        aria-pressed={port === p.name}
                        className={`w-full border-b border-muted px-1 py-2 text-left outline-none last:border-b-0 focus-visible:ring-2 focus-visible:ring-active ${
                          port === p.name ? "bg-raised-2" : "hover:bg-raised"
                        }`}
                      >
                        <span className="flex items-center gap-2">
                          <StatusDot tone={p.on_geometry ? "success" : "error"} />
                          <span className="truncate text-body-sm text-primary">{p.name}</span>
                          <StatusBadge tone="neutral">{p.kind}</StatusBadge>
                        </span>
                        {p.label ? <span className="mt-0.5 block truncate text-caption text-tertiary">{p.label}</span> : null}
                        {Object.keys(p.contract).length ? (
                          <span className="mt-0.5 block truncate text-caption tabular text-quaternary">
                            {Object.entries(p.contract)
                              .filter(([k]) => k !== "kind" && k !== "straddle")
                              .map(([k, v]) => `${k} ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                              .join(" · ")}
                          </span>
                        ) : null}
                        {!p.on_geometry && p.note ? <span className="mt-0.5 block text-caption text-error">{p.note}</span> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="Building…" />
              )
            ) : null}
          </Panel>
        </div>
      </PageBody>
    </>
  );
}
