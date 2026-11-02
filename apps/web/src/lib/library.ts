import { api, catalogApi, fetchBlob, type CatalogGenerator, type ModelSummary, type Project } from "@/lib/api";

/**
 * One list of everything a user can @-mention, assembled from what exists
 * today: catalog generators (basic, catalog) and project models (native;
 * parts and sheet metal are basic, assemblies and products are complex).
 * Imported parts are planned (no import API yet), so none appear.
 */

export type PartKind = "basic" | "complex";
export type PartSource = "catalog" | "native";

export type LibraryItem = {
  id: string;
  name: string;
  kind: PartKind;
  source: PartSource;
  /** One line under the name: what it is. */
  summary: string;
  standard: string | null;
  family: string | null;
  version: number | null;
  href: string;
  thumb: string;
  /** "render" is a real render of the part's own geometry; "icon" is the category object. */
  thumbKind: "render" | "icon";
  /** Search haystack: name, summary, standard, family. */
  haystack: string;
};

/* Category icons from the SH imagery set: the fallback when a part has no
   render of its own. Never geometry. */
const CATALOG_THUMB = "/imagery/sh-card-04-catalog-part-128.webp";
const NATIVE_THUMB = "/imagery/sh-card-05-native-part-128.webp";
const COMPLEX_THUMB = "/imagery/sh-card-02-complex-part-128.webp";

/** Catalog thumbnails are real renders of each generator at default parameters
    (scripts/render_catalog_thumbs.py); index.json lists which ones exist.
    Model thumbnails come from the API first: the THUMB artifact the CAD worker
    renders for every version (thumb_artifact_id on the model). Models without
    one (versions older than the worker change and not yet backfilled with
    `python -m shilpa.thumbs backfill`) fall back to the static renders of the
    head version, named <model_id>-v<n> (scripts/render_model_thumbs.py), then
    to the icon. */
const THUMB_DIR = "/thumbs/catalog";
const MODEL_THUMB_DIR = "/thumbs/models";

async function loadRendered(dir: string): Promise<Set<string>> {
  try {
    const res = await fetch(`${dir}/index.json`);
    return res.ok ? new Set((await res.json()) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

/* The download route needs the bearer header, which an <img src> cannot send,
   so the bytes are fetched once per artifact and shown through an object URL. */
const apiThumbs = new Map<string, Promise<string | null>>();

function apiThumb(artifactId: string): Promise<string | null> {
  let hit = apiThumbs.get(artifactId);
  if (!hit) {
    hit = fetchBlob(`/v1/artifacts/${artifactId}/download`).then(
      (b) => URL.createObjectURL(b),
      () => null,
    );
    apiThumbs.set(artifactId, hit);
  }
  return hit;
}

function fromGenerator(g: CatalogGenerator, rendered: Set<string>): LibraryItem {
  const family = g.family ?? null;
  const own = rendered.has(g.name);
  return {
    id: `catalog:${g.name}`,
    name: g.name,
    kind: "basic",
    source: "catalog",
    summary: g.summary,
    standard: g.standard ?? null,
    family,
    version: null,
    href: `/catalog?gen=${encodeURIComponent(g.name)}`,
    thumb: own ? `${THUMB_DIR}/${encodeURIComponent(g.name)}.webp` : CATALOG_THUMB,
    thumbKind: own ? "render" : "icon",
    haystack: [g.name, g.summary, g.standard, family].filter(Boolean).join(" ").toLowerCase(),
  };
}

const KIND_LABEL: Record<string, string> = { part: "Part", sheet_metal: "Sheet metal", assembly: "Assembly", product: "Product" };

function fromModel(m: ModelSummary, project: Project, rendered: Set<string>, fromApi: string | null): LibraryItem {
  const complex = m.kind === "assembly" || m.kind === "product";
  const what = KIND_LABEL[m.kind ?? "part"] ?? "Part";
  const file = `${m.id}-v${m.head_number}`;
  const own = fromApi != null || (m.head_number != null && rendered.has(file));
  return {
    id: `model:${m.id}`,
    name: m.name,
    kind: complex ? "complex" : "basic",
    source: "native",
    summary: `${what} · ${project.name}`,
    standard: null,
    family: what,
    version: m.head_number,
    href: `/projects/${project.id}`,
    thumb: fromApi ?? (own ? `${MODEL_THUMB_DIR}/${file}.webp` : complex ? COMPLEX_THUMB : NATIVE_THUMB),
    thumbKind: own ? "render" : "icon",
    haystack: [m.name, what, project.name].join(" ").toLowerCase(),
  };
}

export async function loadLibrary(): Promise<LibraryItem[]> {
  const [catalog, projects, rendered, modelRendered] = await Promise.all([
    catalogApi.list(),
    api.projects(),
    loadRendered(THUMB_DIR),
    loadRendered(MODEL_THUMB_DIR),
  ]);
  const details = await Promise.all(projects.filter((p) => p.model_count > 0).map((p) => api.project(p.id)));
  const models = await Promise.all(
    details.flatMap((d) =>
      d.models.map(async (m) =>
        fromModel(m, d, modelRendered, m.thumb_artifact_id ? await apiThumb(m.thumb_artifact_id) : null),
      ),
    ),
  );
  const parts = catalog.generators.filter((g) => g.listed !== false).map((g) => fromGenerator(g, rendered));
  /* Your own models first, then the catalog. */
  return [...models, ...parts];
}

/**
 * Fuzzy-enough search: every whitespace token must appear somewhere in the
 * haystack, with "x" and "×" treated alike so "M6x20" finds "M6×20".
 */
export function matches(item: LibraryItem, query: string): boolean {
  const q = query.trim().toLowerCase().replace(/×/g, "x");
  if (!q) return true;
  const hay = item.haystack.replace(/×/g, "x");
  return q.split(/\s+/).every((t) => hay.includes(t));
}
