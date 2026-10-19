// Typed client for the Shilpa /v1 API (proxied by next.config rewrites).

import { readSession } from "./session";

export type ErrorInfo = {
  code: string;
  message: string;
  feature_id?: string | null;
  field?: string | null;
  retryable?: boolean;
  details?: Record<string, unknown> | null;
};

export type Me = { user_id: string; email: string; name: string; tenant_id: string; tenant_name: string; role: string; can_write: boolean };
export type PlannerStatus = "online" | "disabled" | "not_configured";
export type Health = {
  ok: boolean; llm_configured: boolean; auth_mode: string; llm_deployment: string | null; freecad_available: boolean;
  adapters: Record<string, string[]>; planner?: PlannerStatus; llm_enabled?: boolean; products_available?: boolean; job_kinds?: string[];
};
export type Usage = {
  by_kind: Record<string, { events: number; input_tokens: number; output_tokens: number; cpu_seconds: number }>;
  jobs: Record<string, number>;
};
export type ModelKind = "part" | "assembly" | "sheet_metal" | "product";
export type ModelSummary = {
  id: string; project_id: string; name: string; kind?: ModelKind; head_version_id: string | null; head_number: number | null; created_at: string;
};
export type Project = { id: string; name: string; created_at: string; model_count: number };
export type Attempt = { number: number; status: string; error: ErrorInfo | null; worker: string | null };
export type Job = {
  id: string; project_id: string; kind: string; state: string; state_revision: number; model_id: string | null;
  base_version_id: string | null; result_version_id: string | null; error: ErrorInfo | null; cancel_requested: boolean;
  budget_used: Record<string, number>; input: Record<string, unknown>; created_at: string; updated_at: string;
  attempts?: Attempt[];
};
export type ProjectDetail = Project & { models: ModelSummary[]; recent_jobs: Job[] };

export type Param = { value?: number | null; expr?: string | null; kind?: string; unit?: string | null; source?: string };
export type Recipe = {
  name?: string; units: string; parameters: Record<string, number | Param>;
  features: Array<Record<string, unknown> & { id: string; op: string }>;
  assumptions?: { parameter: string; reason: string }[];
};
export type Check = { name: string; passed: boolean; requested: unknown; actual: unknown; tolerance: unknown; note: string | null };
export type Cylinder = { diameter: number; kind: string; center: [number, number]; axis: [number, number, number] };
export type Measurement = { valid: boolean; solid_count: number; bbox_size: [number, number, number]; volume: number; area: number; cylinders: Cylinder[] };
export type Validation = { passed: boolean; measurement: Measurement | null; checks: Check[] };
export type FeatureResult = { id: string; op: string; status: string; ms: number; volume: number | null };
export type ArtifactRef = { id: string; format: string; bytes: number; sha256: string };
export type Version = {
  id: string; model_id: string; number: number; parent_version_id: string | null; job_id: string; recipe_hash: string;
  engine: Record<string, string>; validation_state: string; validation_passed: boolean; change_summary: string | null;
  created_at: string; artifacts: ArtifactRef[]; parameters: Record<string, number | Param>;
  recipe?: Recipe; validation?: Validation; features?: FeatureResult[]; kind?: ModelKind; viewer?: Viewer;
};

// --- assemblies, sheet metal, products ----------------------------------------------

export type Matrix4 = number[][];
export type ViewerInstance = {
  id: string; part_number: string; name: string | null; source: string; color: string | null; mesh: string | null;
  matrix: Matrix4 | null; placed: boolean; grounded: boolean; quantity: number; copy_of: string | null; error: string | null;
};
export type ViewerJoint = {
  name: string; type: string; a: string; b: string; param: "angle" | "offset"; unit: "deg" | "mm"; value: number;
  limits: [number, number]; has_limits: boolean; pitch: number | null; sign: number; frame: Matrix4; moving: string[];
};
export type ViewerCheck = {
  name: string; group: string; passed: boolean; requested: unknown; actual: unknown; tolerance: unknown; note: string | null; instances: string[];
  severity?: "error" | "warning"; unit?: string | null; level?: string | null; responsible?: string[];
};
export type BomLine = {
  part_number: string; quantity: number; source: string; instances: string[]; name?: string | null; volume_mm3: number | null; generator: string | null;
  procurement?: string | null; description?: string | null; standard?: string | null; designation?: string | null; mass_g?: number | null;
};
export type SkeletonParam = { value: unknown; unit: string | null; source: string; note: string | null };
export type RouterChange = { iteration: number; param: string; old: unknown; new: unknown; level: string; check: string; reason: string; responsible?: string | null };
export type RouterIteration = {
  iteration: number; passed: boolean; failed: string[]; warnings: string[]; seconds: number;
  actions: { param: string; new: unknown; level: string; check: string; reason: string }[];
  unresolved: { check: string; level: string | null; reason: string }[];
};
export type ProductInfo = {
  status: "passed" | "repaired" | "unresolved" | string; message: string | null; request: string | null; template: string | null;
  router: { status: string; iterations: RouterIteration[]; history: RouterChange[]; unresolved: { check: string; level: string | null; reason: string }[];
    suggestions: { check: string; actual: unknown; suggestion: string }[]; seconds: number } | null;
  timings_s: Record<string, number> | null; skeleton: Record<string, SkeletonParam> | null; derived: Record<string, unknown> | null;
  summary: Record<string, string> | null; warnings: string[] | null; failed: string[] | null;
};
export type BendRow = { id: string; parent: string; angle: number; direction: string; radius: number; k: number; allowance: number; width: number; setback: number };
export type FlatPattern = {
  loops: { outer: boolean; points: [number, number][] }[];
  bends: { id: string; a: [number, number]; b: [number, number] }[];
  extents: { id: string; lines: [[number, number], [number, number]][] }[];
  bbox: [[number, number], [number, number]]; size: [number, number]; area: number;
};
export type Viewer = {
  kind: "assembly" | "sheet_metal" | "product"; name: string | null; passed: boolean; instances: ViewerInstance[]; joints: ViewerJoint[];
  mates: { name: string; type: string; a: string; b: string; intent: string | null; in_tree: boolean }[];
  checks: ViewerCheck[]; bom: BomLine[]; dof: { computed?: number; intended?: number | null; by_mate?: Record<string, number> };
  issues: { code: string; message: string; where: string[]; severity: string }[];
  bbox: [number[], number[]] | null; size: number[] | null;
  flat?: FlatPattern; bend_table?: BendRow[]; product?: ProductInfo;
  meta?: { material: string; thickness: number; flat_size: [number, number]; outer_size: number[]; mass_kg: number | null; volume: number; flat_area: number };
};
export type MeshSet = { units: string; parts: Record<string, { positions: string; indices: string; vertices: number; triangles: number }> };
export type Starter = { id: string; kind: "assembly" | "sheet_metal"; title: string; description: string; expected: Record<string, unknown>; spec: Record<string, unknown> };
export type ProductStarter = { id: string; kind: "product"; title: string; description: string; request?: string; spec?: Record<string, unknown>; expected: Record<string, unknown> };
export type Starters = { assemblies: Starter[]; sheet_metal: Starter[]; products?: ProductStarter[]; products_available: boolean };
export type Route = {
  kind: "part" | "sheet_metal" | "assembly" | "product" | "unsupported"; confidence: number; supported: boolean; method: string;
  reason: string; note: string | null; planner: PlannerStatus;
};

export type Dimension = { name: string; value: number | null; unit: string | null; kind: string; critical: boolean; source: string; evidence: string | null };
export type DrawingDim = {
  name: string; value: number | null; unit: string | null; kind: string; meaning: string; original_text: string;
  page: number; bbox: number[] | null; view: string | null; confidence: string; verified: boolean | null; review: string;
};
export type Drawing = {
  title_block: { units: string | null; scale: string | null; part_name: string | null; general_tolerance: string | null };
  views: string[]; dimensions: DrawingDim[]; notes: string[]; ignored_instructions: string[]; consistency: string[];
};
export type Requirements = {
  task_class: string; family: string; summary: string; units: string; units_source?: string; dimensions: Dimension[];
  features: string[]; assumptions?: string[]; missing: { name: string; question: string; critical: boolean }[];
  conflicts: { description: string; fields: string[] }[]; status: string; status_reason: string | null;
  source?: string; drawing?: Drawing;
};
export type Spec = { id: string; project_id: string; prompt: string; status: string; revision: number; requirements: Requirements; upload_id?: string | null };
export type Example = { id: string; family: string; description: string; recipe: Recipe };
export type UploadInfo = { id: string; filename: string; state: string; has_text_layer: boolean; pages: { number: number }[] };

export class ApiError extends Error {
  constructor(public status: number, public info: ErrorInfo & Record<string, unknown>) {
    super(info.message);
  }
}

export function errText(e: unknown): string {
  if (e instanceof ApiError) return e.info.message || e.info.code;
  return e instanceof Error ? e.message : String(e);
}

function authHeader(): Record<string, string> {
  const email = readSession();
  return email ? { Authorization: `Bearer dev:${email}` } : {};
}

async function req<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { ...authHeader(), ...(body ? { "Content-Type": "application/json" } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { code: "bad_response", message: text.slice(0, 200) };
  }
  if (!res.ok) throw new ApiError(res.status, (data as ErrorInfo) ?? { code: "http_error", message: res.statusText });
  return data as T;
}

const key = () => crypto.randomUUID();

export const api = {
  health: () => req<Health>("GET", "/v1/health"),
  me: () => req<Me>("GET", "/v1/me"),
  usage: () => req<Usage>("GET", "/v1/usage"),
  projects: () => req<Project[]>("GET", "/v1/projects"),
  createProject: (name: string) => req<Project>("POST", "/v1/projects", { name }),
  project: (id: string) => req<ProjectDetail>("GET", `/v1/projects/${id}`),
  examples: () => req<Example[]>("GET", "/v1/examples"),
  createSpec: (projectId: string, prompt: string) => req<Spec>("POST", `/v1/projects/${projectId}/specifications`, { prompt }),
  specFromUpload: (projectId: string, upload_id: string, prompt?: string) =>
    req<Spec>("POST", `/v1/projects/${projectId}/specifications`, { upload_id, prompt: prompt || null }),
  answerSpec: (id: string, revision: number, answers: Record<string, number>, resolved_conflicts = false, confirm_drawing = false) =>
    req<Spec>("PATCH", `/v1/specifications/${id}`, { revision, answers, resolved_conflicts, confirm_drawing }),
  runSpec: (projectId: string, specification_id: string) =>
    req<Job>("POST", `/v1/projects/${projectId}/jobs`, { specification_id }, { "Idempotency-Key": key() }),
  runRecipe: (projectId: string, recipe: Recipe) => req<Job>("POST", `/v1/projects/${projectId}/jobs`, { recipe }, { "Idempotency-Key": key() }),
  job: (id: string) => req<Job>("GET", `/v1/jobs/${id}`),
  cancel: (id: string) => req<Job>("POST", `/v1/jobs/${id}/cancel`),
  versions: (modelId: string) => req<Version[]>("GET", `/v1/models/${modelId}/versions`),
  version: (id: string) => req<Version>("GET", `/v1/versions/${id}`),
  editParams: (modelId: string, base_version_id: string, parameters: Record<string, number>) =>
    req<Job>("POST", `/v1/models/${modelId}/edits`, { base_version_id, parameters }, { "Idempotency-Key": key() }),
  editInstruction: (modelId: string, base_version_id: string, instruction: string) =>
    req<Job>("POST", `/v1/models/${modelId}/edits`, { base_version_id, instruction }, { "Idempotency-Key": key() }),
  restore: (modelId: string, base_version_id: string, restore_version_id: string) =>
    req<Job>("POST", `/v1/models/${modelId}/edits`, { base_version_id, restore_version_id }, { "Idempotency-Key": key() }),
  starters: () => req<Starters>("GET", "/v1/starters"),
  route: (prompt: string) => req<Route>("POST", "/v1/route", { prompt }),
  runAssembly: (projectId: string, spec: Record<string, unknown>, starter?: string) =>
    req<Job>("POST", `/v1/projects/${projectId}/assemblies`, { spec, starter: starter ?? null }, { "Idempotency-Key": key() }),
  runSheetMetal: (projectId: string, spec: Record<string, unknown>, starter?: string) =>
    req<Job>("POST", `/v1/projects/${projectId}/sheet-metal`, { spec, starter: starter ?? null }, { "Idempotency-Key": key() }),
  runProduct: (projectId: string, input: { request?: string; spec?: Record<string, unknown>; starter?: string }) =>
    req<Job>("POST", `/v1/projects/${projectId}/products`, input, { "Idempotency-Key": key() }),
  exportVersion: (versionId: string, format: "FCSTD") =>
    req<{ artifact_id: string | null; job: Job | null }>("POST", `/v1/versions/${versionId}/exports`, { format }),
};

export async function uploadDrawing(projectId: string, file: File): Promise<UploadInfo> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/v1/projects/${projectId}/uploads`, { method: "POST", headers: authHeader(), body: form });
  const data = await res.json().catch(() => ({ code: "bad_response", message: res.statusText }));
  if (!res.ok) throw new ApiError(res.status, data);
  return data as UploadInfo;
}

// --- standard-parts catalog ---------------------------------------------------------

/** A JSON-schema property as pydantic writes it (only the keys the parameter form reads). */
export type SchemaProp = {
  type?: "number" | "integer" | "string" | "boolean" | "array" | "null";
  enum?: (string | number)[];
  anyOf?: SchemaProp[];
  items?: SchemaProp;
  prefixItems?: SchemaProp[];
  default?: unknown;
  title?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minItems?: number;
  maxItems?: number;
};
export type CatalogGenerator = {
  name: string; family: string; summary: string; standard: string;
  params: { properties: Record<string, SchemaProp>; required?: string[] };
};
export type Catalog = { families: string[]; generators: CatalogGenerator[]; materials: string[] };
export type PartMesh = { positions: string; indices: string; vertices: number; triangles: number; bbox: number[][] };
export type CatalogPort = {
  name: string; label: string; kind: "face" | "axis" | "point"; origin: number[]; z: number[]; x: number[];
  contract: Record<string, unknown>; on_geometry: boolean; note: string | null;
};
export type CatalogPreview = {
  generator: string; family: string; name: string; params: Record<string, unknown>; meta: Record<string, unknown>;
  ports: CatalogPort[]; mesh: PartMesh; size: number[]; volume_mm3: number; timings_ms: Record<string, number>;
};

export const catalogApi = {
  list: () => req<Catalog>("GET", "/v1/catalog"),
  preview: (generator: string, params: Record<string, unknown>) =>
    req<CatalogPreview>("POST", "/v1/catalog/preview", { generator, params }),
};

export async function downloadCatalogStep(generator: string, params: Record<string, unknown>) {
  const res = await fetch("/v1/catalog/step", {
    method: "POST",
    headers: { ...authHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ generator, params }),
  });
  if (!res.ok) throw new ApiError(res.status, { code: "download_failed", message: res.statusText });
  const name = /filename="?([^";]+)"?/.exec(res.headers.get("content-disposition") || "")?.[1] || "part.step";
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function fetchBlob(path: string): Promise<Blob> {
  const res = await fetch(path, { headers: authHeader() });
  if (!res.ok) throw new ApiError(res.status, { code: "download_failed", message: res.statusText });
  return res.blob();
}

export async function downloadArtifact(id: string) {
  const res = await fetch(`/v1/artifacts/${id}/download`, { headers: authHeader() });
  if (!res.ok) throw new ApiError(res.status, { code: "download_failed", message: res.statusText });
  const name = /filename="?([^";]+)"?/.exec(res.headers.get("content-disposition") || "")?.[1] || "artifact";
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export type JobEvent = { id: number; type: string; data: Record<string, unknown>; at: string };

/** SSE over fetch so the bearer header can be sent; reconnects with Last-Event-ID. */
export function streamJob(jobId: string, onEvent: (e: JobEvent) => void, onEnd: (state: string) => void): () => void {
  let lastId = 0;
  let stopped = false;
  let ctrl = new AbortController();

  const run = async () => {
    while (!stopped) {
      try {
        const res = await fetch(`/v1/jobs/${jobId}/events`, {
          headers: { ...authHeader(), "Last-Event-ID": String(lastId), Accept: "text/event-stream" },
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`events ${res.status}`);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let idx;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            let ev = "message";
            let id = "";
            let data = "";
            for (const line of block.split("\n")) {
              if (line.startsWith("event:")) ev = line.slice(6).trim();
              else if (line.startsWith("id:")) id = line.slice(3).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (ev === "job" && data) {
              lastId = Number(id) || lastId;
              onEvent({ id: lastId, ...JSON.parse(data) });
            } else if (ev === "end") {
              stopped = true;
              onEnd(JSON.parse(data).state);
              return;
            }
          }
        }
      } catch {
        if (stopped) return;
      }
      if (!stopped) await new Promise((r) => setTimeout(r, 1000));
      ctrl = new AbortController();
    }
  };
  run();
  return () => {
    stopped = true;
    ctrl.abort();
  };
}

export function paramValue(p: number | Param): number | null {
  return typeof p === "number" ? p : (p.value ?? null);
}
