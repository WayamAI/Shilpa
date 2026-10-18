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
export type Health = { ok: boolean; llm_configured: boolean; auth_mode: string; llm_deployment: string | null; freecad_available: boolean; adapters: Record<string, string[]> };
export type Usage = {
  by_kind: Record<string, { events: number; input_tokens: number; output_tokens: number; cpu_seconds: number }>;
  jobs: Record<string, number>;
};
export type ModelSummary = { id: string; project_id: string; name: string; head_version_id: string | null; head_number: number | null; created_at: string };
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
  recipe?: Recipe; validation?: Validation; features?: FeatureResult[];
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
