import { api, catalogApi, type CatalogGenerator, type ModelSummary, type Project } from "@/lib/api";

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
  /** "render" is a part placeholder render; "icon" is the category object. */
  thumbKind: "render" | "icon";
  /** Search haystack: name, summary, standard, family. */
  haystack: string;
};

/* Category art from the SH imagery set. These are placeholder renders, never
   geometry: the library labels them as such. Only kinds that genuinely
   match get a part render; the rest use the category icon. */
const FAMILY_THUMB: Record<string, string> = {
  Nuts: "/imagery/sh-th-03-hex-nut-m6-640.webp",
  Screws: "/imagery/sh-th-05-cap-screw-640.webp",
  Bearings: "/imagery/sh-th-06-bearing-6204-640.webp",
};
const CATALOG_THUMB = "/imagery/sh-card-04-catalog-part-128.webp";
const NATIVE_THUMB = "/imagery/sh-card-05-native-part-128.webp";
const COMPLEX_THUMB = "/imagery/sh-card-02-complex-part-128.webp";

function fromGenerator(g: CatalogGenerator): LibraryItem {
  const family = g.family ?? null;
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
    thumb: (family && FAMILY_THUMB[family]) || CATALOG_THUMB,
    thumbKind: family && FAMILY_THUMB[family] ? "render" : "icon",
    haystack: [g.name, g.summary, g.standard, family].filter(Boolean).join(" ").toLowerCase(),
  };
}

const KIND_LABEL: Record<string, string> = { part: "Part", sheet_metal: "Sheet metal", assembly: "Assembly", product: "Product" };

function fromModel(m: ModelSummary, project: Project): LibraryItem {
  const complex = m.kind === "assembly" || m.kind === "product";
  const what = KIND_LABEL[m.kind ?? "part"] ?? "Part";
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
    thumb: complex ? COMPLEX_THUMB : NATIVE_THUMB,
    thumbKind: "icon",
    haystack: [m.name, what, project.name].join(" ").toLowerCase(),
  };
}

export async function loadLibrary(): Promise<LibraryItem[]> {
  const [catalog, projects] = await Promise.all([catalogApi.list(), api.projects()]);
  const details = await Promise.all(projects.filter((p) => p.model_count > 0).map((p) => api.project(p.id)));
  const models = details.flatMap((d) => d.models.map((m) => fromModel(m, d)));
  const parts = catalog.generators.filter((g) => g.listed !== false).map(fromGenerator);
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
