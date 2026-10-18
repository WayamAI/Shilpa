// Typed client for the Shilpa /v1 API. Dev auth uses "dev:<email>" bearer tokens.

export type ErrorInfo = {
  code: string;
  message: string;
  feature_id?: string | null;
  field?: string | null;
  retryable?: boolean;
  details?: Record<string, unknown> | null;
};

export type Me = { user_id: string; email: string; name: string; tenant_id: string; tenant_name: string; role: string; can_write: boolean };
export type Health = { ok: boolean; llm_configured: boolean; auth_mode: string };
export type ModelSummary = { id: string; project_id: string; name: string; head_version_id: string | null; head_number: number | null; created_at: string };
export type Project = { id: string; name: string; created_at: string; model_count: number };
export type Job = {
  id: string; project_id: string; kind: string; state: string; state_revision: number; model_id: string | null;
  base_version_id: string | null; result_version_id: string | null; error: ErrorInfo | null; cancel_requested: boolean;
  budget_used: Record<string, number>; input: Record<string, unknown>; created_at: string; updated_at: string;
  recipe?: Recipe | null; attempts?: Attempt[];
};
export type Attempt = { number: number; status: string; error: ErrorInfo | null; worker: string | null; features: FeatureResult[] | null; validation: Validation | null };
export type ProjectDetail = Project & { models: ModelSummary[]; recent_jobs: Job[] };

export type Param = { value?: number | null; expr?: string | null; kind?: string; unit?: string | null; source?: string; critical?: boolean };
export type Recipe = { name?: string; units: string; parameters: Record<string, number | Param>; features: Array<Record<string, unknown> & { id: string; op: string }>; assumptions?: { parameter: string; reason: string }[] };
export type Check = { name: string; passed: boolean; requested: unknown; actual: unknown; tolerance: unknown; note: string | null };
export type Measurement = { valid: boolean; solid_count: number; bbox_size: [number, number, number]; volume: number; area: number; cylinders: { diameter: number; kind: string; center: [number, number] }[] };
export type Validation = { passed: boolean; measurement: Measurement | null; checks: Check[] };
export type FeatureResult = { id: string; op: string; status: string; ms: number; volume: number | null; detail: Record<string, unknown> };
export type ArtifactRef = { id: string; format: string; bytes: number; sha256: string };
export type Version = {
  id: string; model_id: string; number: number; parent_version_id: string | null; job_id: string; recipe_hash: string;
  engine: Record<string, string>; validation_state: string; validation_passed: boolean; change_summary: string | null;
  created_at: string; artifacts: ArtifactRef[]; parameters: Record<string, number | Param>;
  recipe?: Recipe; validation?: Validation; features?: FeatureResult[];
};
export type Dimension = { name: string; value: number | null; unit: string | null; kind: string; critical: boolean; source: string; evidence: string | null };
export type Requirements = {
  task_class: string; family: string; summary: string; units: string; units_source?: string; dimensions: Dimension[]; features: string[]; assumptions?: string[];
  missing: { name: string; question: string; critical: boolean }[]; conflicts: { description: string; fields: string[] }[];
  status: string; status_reason: string | null;
};
export type Spec = { id: string; project_id: string; prompt: string; status: string; revision: number; requirements: Requirements };
export type Example = { id: string; family: string; description: string; recipe: Recipe };

export class ApiError extends Error {
  constructor(public status: number, public info: ErrorInfo & Record<string, unknown>) {
    super(info.message);
  }
}

const TOKEN_KEY = "shilpa.devToken";
export const DEV_USERS = ["dev@wayam.local", "viewer@wayam.local", "other@example.com"];

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || `dev:${DEV_USERS[0]}`;
  } catch {
    return `dev:${DEV_USERS[0]}`;
  }
}
export function setToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* storage unavailable: token lasts for this page only */
  }
}

async function req<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { Authorization: `Bearer ${getToken()}`, ...(body ? { "Content-Type": "application/json" } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data ?? { code: "http_error", message: res.statusText });
  return data as T;
}

const key = () => crypto.randomUUID();

export const api = {
  health: () => req<Health>("GET", "/v1/health"),
  me: () => req<Me>("GET", "/v1/me"),
  projects: () => req<Project[]>("GET", "/v1/projects"),
  createProject: (name: string) => req<Project>("POST", "/v1/projects", { name }),
  project: (id: string) => req<ProjectDetail>("GET", `/v1/projects/${id}`),
  examples: () => req<Example[]>("GET", "/v1/examples"),
  createSpec: (projectId: string, prompt: string) => req<Spec>("POST", `/v1/projects/${projectId}/specifications`, { prompt }),
  answerSpec: (id: string, revision: number, answers: Record<string, number>, resolved_conflicts = false) =>
    req<Spec>("PATCH", `/v1/specifications/${id}`, { revision, answers, resolved_conflicts }),
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
  exportVersion: (versionId: string, format: "FCSTD") =>
    req<{ artifact_id: string | null; job: Job | null }>("POST", `/v1/versions/${versionId}/exports`, { format }),
  restore: (modelId: string, base_version_id: string, restore_version_id: string) =>
    req<Job>("POST", `/v1/models/${modelId}/edits`, { base_version_id, restore_version_id }, { "Idempotency-Key": key() }),
};

export async function fetchArtifact(id: string): Promise<ArrayBuffer> {
  const res = await fetch(`/v1/artifacts/${id}/download`, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new ApiError(res.status, { code: "download_failed", message: res.statusText });
  return res.arrayBuffer();
}

export async function downloadArtifact(id: string) {
  const res = await fetch(`/v1/artifacts/${id}/download`, { headers: { Authorization: `Bearer ${getToken()}` } });
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

// SSE over fetch so the bearer header can be sent. Reconnects with Last-Event-ID.
export function streamJob(jobId: string, onEvent: (e: JobEvent) => void, onEnd: (state: string) => void): () => void {
  let lastId = 0;
  let stopped = false;
  let ctrl = new AbortController();

  const run = async () => {
    while (!stopped) {
      try {
        const res = await fetch(`/v1/jobs/${jobId}/events`, {
          headers: { Authorization: `Bearer ${getToken()}`, "Last-Event-ID": String(lastId), Accept: "text/event-stream" },
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
            let ev = "message", id = "", data = "";
            for (const line of block.split("\n")) {
              if (line.startsWith("event:")) ev = line.slice(6).trim();
              else if (line.startsWith("id:")) id = line.slice(3).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (ev === "job" && data) {
              lastId = Number(id) || lastId;
              const parsed = JSON.parse(data);
              onEvent({ id: lastId, ...parsed });
            } else if (ev === "end") {
              stopped = true;
              onEnd(JSON.parse(data).state);
              return;
            }
          }
        }
      } catch (err) {
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
