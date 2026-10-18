import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiError, DEV_USERS, downloadArtifact, getToken, setToken, streamJob,
  type Example, type Health, type Job, type JobEvent, type Me, type ModelSummary, type Param, type Project,
  type ProjectDetail, type Spec, type Version,
} from "./api";
import { Viewer } from "./Viewer";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

function errText(e: unknown): string {
  if (e instanceof ApiError) return `${e.info.code}: ${e.info.message}`;
  return e instanceof Error ? e.message : String(e);
}

function paramValue(p: number | Param): number | null {
  return typeof p === "number" ? p : p.value ?? null;
}

// ------------------------------------------------------------------ shell

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [projectId, setProjectId] = useState<string | null>(() => new URLSearchParams(location.search).get("project"));
  const [fatal, setFatal] = useState<string | null>(null);

  const reload = useCallback(() => {
    setFatal(null);
    api.health().then(setHealth).catch(() => setFatal("The Shilpa API is not reachable on :8000. Start it with `uv run python -m shilpa.dev`."));
    api.me().then(setMe).catch((e) => setFatal(errText(e)));
  }, []);
  useEffect(reload, [reload]);

  const openProject = (id: string | null) => {
    setProjectId(id);
    const url = new URL(location.href);
    if (id) url.searchParams.set("project", id);
    else url.searchParams.delete("project");
    history.replaceState(null, "", url);
  };

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => openProject(null)}>
          <span className="brand-mark">श</span> Shilpa
        </button>
        <span className="muted">{me?.tenant_name}</span>
        <div className="spacer" />
        {health && (
          <span className={`pill ${health.llm_configured ? "ok" : "warn"}`} title="Azure OpenAI planner">
            {health.llm_configured ? "Planner online" : "Planner not configured"}
          </span>
        )}
        <select
          aria-label="Dev user"
          value={getToken().slice(4)}
          onChange={(e) => {
            setToken(`dev:${e.target.value}`);
            openProject(null);
            reload();
          }}
        >
          {DEV_USERS.map((u) => (
            <option key={u} value={u}>{u}</option>
          ))}
        </select>
      </header>
      {fatal ? (
        <div className="center-msg">{fatal}</div>
      ) : !me ? (
        <div className="center-msg">Loading…</div>
      ) : projectId ? (
        <Workspace key={projectId + me.user_id} projectId={projectId} me={me} health={health} onBack={() => openProject(null)} />
      ) : (
        <Projects me={me} onOpen={openProject} />
      )}
    </div>
  );
}

// ------------------------------------------------------------------ projects

function Projects({ me, onOpen }: { me: Me; onOpen: (id: string) => void }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [name, setName] = useState("");
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.projects().then(setProjects).catch((e) => setErr(errText(e)));
  }, []);
  const create = async () => {
    try {
      const p = await api.createProject(name.trim() || "Untitled project");
      onOpen(p.id);
    } catch (e) {
      setErr(errText(e));
    }
  };
  const shown = (projects || []).filter((p) => p.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <main className="projects">
      <h1>Projects</h1>
      {me.can_write && (
        <div className="row">
          <input placeholder="New project name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()} />
          <button className="primary" onClick={create}>Create project</button>
        </div>
      )}
      <input className="search" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} />
      {err && <div className="error">{err}</div>}
      <ul className="project-list">
        {shown.map((p) => (
          <li key={p.id}>
            <button onClick={() => onOpen(p.id)}>
              <strong>{p.name}</strong>
              <span className="muted">{p.model_count} model{p.model_count === 1 ? "" : "s"} · {new Date(p.created_at).toLocaleString()}</span>
            </button>
          </li>
        ))}
        {projects && shown.length === 0 && <li className="muted">No projects yet.</li>}
      </ul>
      <p className="muted small">Role: {me.role}. Generated models are geometry-validated, not approved for engineering release.</p>
    </main>
  );
}

// ------------------------------------------------------------------ workspace

type ChatItem =
  | { kind: "user"; text: string }
  | { kind: "system"; text: string; tone?: "error" | "ok" }
  | { kind: "spec"; spec: Spec }
  | { kind: "job"; jobId: string };

function Workspace({ projectId, me, health, onBack }: { projectId: string; me: Me; health: Health | null; onBack: () => void }) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [modelId, setModelId] = useState<string | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [version, setVersion] = useState<Version | null>(null);
  const [tab, setTab] = useState<"params" | "validation" | "versions" | "export">("params");
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [jobs, setJobs] = useState<Record<string, { job: Job | null; events: JobEvent[] }>>({});
  const [err, setErr] = useState<string | null>(null);

  const loadProject = useCallback(async () => {
    const p = await api.project(projectId);
    setProject(p);
    return p;
  }, [projectId]);

  const loadModel = useCallback(async (mid: string, versionId?: string | null) => {
    const vs = await api.versions(mid);
    setVersions(vs);
    const target = versionId || vs[0]?.id;
    setVersion(target ? await api.version(target) : null);
  }, []);

  useEffect(() => {
    loadProject()
      .then((p) => {
        if (p.models[0]) {
          setModelId(p.models[0].id);
          loadModel(p.models[0].id);
        }
      })
      .catch((e) => setErr(errText(e)));
  }, [loadProject, loadModel]);

  const say = (item: ChatItem) => setChat((c) => [...c, item]);

  const trackJob = useCallback(
    (job: Job) => {
      setJobs((j) => ({ ...j, [job.id]: { job, events: [] } }));
      say({ kind: "job", jobId: job.id });
      streamJob(
        job.id,
        (ev) => setJobs((j) => ({ ...j, [job.id]: { job: j[job.id]?.job ?? job, events: [...(j[job.id]?.events ?? []), ev] } })),
        async () => {
          const final = await api.job(job.id);
          setJobs((j) => ({ ...j, [job.id]: { ...j[job.id], job: final } }));
          if (final.state === "succeeded" && final.model_id) {
            await loadProject();
            setModelId(final.model_id);
            await loadModel(final.model_id, final.result_version_id);
          }
        },
      );
    },
    [loadModel, loadProject],
  );

  const selectModel = (m: ModelSummary) => {
    setModelId(m.id);
    loadModel(m.id).catch((e) => setErr(errText(e)));
  };

  const headId = versions[0]?.id ?? null;
  const isHead = version?.id === headId;
  const glb = version?.artifacts.find((a) => a.format === "GLB")?.id ?? null;
  const activeJob = Object.values(jobs).map((j) => j.job).find((j) => j && !TERMINAL.has(j.state)) ?? null;

  return (
    <div className="workspace">
      <aside className="left">
        <div className="panel-head">
          <button className="link" onClick={onBack}>← Projects</button>
          <h2>{project?.name ?? "…"}</h2>
        </div>
        {project && project.models.length > 0 && (
          <div className="models">
            {project.models.map((m) => (
              <button key={m.id} className={m.id === modelId ? "model active" : "model"} onClick={() => selectModel(m)}>
                {m.name} <span className="muted">v{m.head_number}</span>
              </button>
            ))}
            <button className={modelId ? "model" : "model active"} onClick={() => { setModelId(null); setVersion(null); setVersions([]); }}>
              + New part
            </button>
          </div>
        )}
        <nav className="tabs" role="tablist">
          {(["params", "validation", "versions", "export"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {{ params: "Parameters", validation: "Validation", versions: "Versions", export: "Export" }[t]}
            </button>
          ))}
        </nav>
        <div className="tab-body">
          {!version ? (
            <p className="muted">No model yet.</p>
          ) : tab === "params" ? (
            <ParamsPanel
              version={version}
              editable={me.can_write && isHead && !activeJob}
              notHead={!isHead}
              onApply={async (changes) => {
                try {
                  say({ kind: "user", text: "Edit: " + Object.entries(changes).map(([k, v]) => `${k} = ${v}`).join(", ") });
                  trackJob(await api.editParams(version.model_id, version.id, changes));
                } catch (e) {
                  say({ kind: "system", text: errText(e), tone: "error" });
                }
              }}
            />
          ) : tab === "validation" ? (
            <ValidationPanel version={version} />
          ) : tab === "versions" ? (
            <VersionsPanel
              versions={versions}
              current={version.id}
              canRestore={me.can_write && !activeJob}
              onOpen={async (id) => setVersion(await api.version(id))}
              onRestore={async (id) => {
                if (!headId) return;
                try {
                  trackJob(await api.restore(version.model_id, headId, id));
                } catch (e) {
                  say({ kind: "system", text: errText(e), tone: "error" });
                }
              }}
            />
          ) : (
            <ExportPanel version={version} />
          )}
        </div>
      </aside>

      <section className="center">
        <Viewer glbId={glb} bbox={version?.validation?.measurement?.bbox_size ?? null} />
        <div className="statusbar">
          {version ? (
            <>
              <strong>{project?.models.find((m) => m.id === version.model_id)?.name}</strong>
              <span>v{version.number}{isHead ? " (latest)" : " (older version)"}</span>
              <span className={`pill ${version.validation_passed ? "ok" : "bad"}`}>
                {version.validation_passed ? "Geometry validated" : "Validation failed"}
              </span>
              <span className="muted">Not reviewed for engineering release</span>
            </>
          ) : (
            <span className="muted">No model selected</span>
          )}
          <div className="spacer" />
          {activeJob && (
            <>
              <span className="pill run">{activeJob.state}…</span>
              {me.can_write && <button onClick={() => api.cancel(activeJob.id)}>Cancel</button>}
            </>
          )}
        </div>
        {err && <div className="error">{err}</div>}
      </section>

      <aside className="right">
        <Conversation
          me={me}
          health={health}
          projectId={projectId}
          chat={chat}
          jobs={jobs}
          editTarget={modelId && version && isHead ? version : null}
          busy={!!activeJob}
          say={say}
          trackJob={trackJob}
          onSpecUpdate={(spec) => setChat((c) => c.map((x) => (x.kind === "spec" && x.spec.id === spec.id ? { kind: "spec", spec } : x)))}
        />
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------ left panels

function ParamsPanel({ version, editable, notHead, onApply }: { version: Version; editable: boolean; notHead: boolean; onApply: (c: Record<string, number>) => void }) {
  const params = version.recipe?.parameters ?? version.parameters;
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    setDraft({});
  }, [version.id]);
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
      {notHead && <p className="note">You are viewing an older version. Edits apply to the latest version.</p>}
      <table className="params">
        <tbody>
          {Object.entries(params).map(([name, p]) => {
            const v = paramValue(p);
            const meta = typeof p === "number" ? {} : p;
            const unit = meta.kind === "count" ? "" : meta.kind === "angle" ? meta.unit ?? "deg" : meta.unit ?? units;
            const derived = !!meta.expr;
            return (
              <tr key={name}>
                <th scope="row">
                  <label htmlFor={`p-${name}`}>{name.replace(/_/g, " ")}</label>
                  {meta.source && meta.source !== "user" && <span className="tag">{meta.source}</span>}
                </th>
                <td>
                  <input
                    id={`p-${name}`}
                    type="number"
                    step="any"
                    disabled={!editable || derived}
                    value={draft[name] ?? (v ?? "")}
                    onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
                  />
                </td>
                <td className="muted">{unit}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {editable && (
        <button className="primary" disabled={Object.keys(changes).length === 0} onClick={() => onApply(changes)}>
          Apply as new version
        </button>
      )}
      {version.recipe?.assumptions && version.recipe.assumptions.length > 0 && (
        <>
          <h3>Assumptions</h3>
          <ul className="assumptions">
            {version.recipe.assumptions.map((a) => (
              <li key={a.parameter}><strong>{a.parameter}</strong>: {a.reason}</li>
            ))}
          </ul>
        </>
      )}
      <h3>Features</h3>
      <ol className="features">
        {(version.features ?? []).map((f) => (
          <li key={f.id} className={f.status}>
            <code>{f.id}</code> <span className="muted">{f.op.replace(/_/g, " ")}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function fmt(v: unknown): string {
  if (Array.isArray(v)) return v.map(fmt).join(", ");
  if (typeof v === "number") return String(+v.toFixed(4));
  if (v === null || v === undefined) return "–";
  return String(v);
}

function ValidationPanel({ version }: { version: Version }) {
  const v = version.validation;
  if (!v) return <p className="muted">No validation report.</p>;
  const m = v.measurement;
  return (
    <div>
      <p className={v.passed ? "ok-text" : "error"}>{v.passed ? "All required checks passed." : "Some required checks failed."}</p>
      {m && (
        <dl className="measure">
          <dt>Size (exact)</dt><dd>{m.bbox_size.map((x) => +x.toFixed(4)).join(" × ")} mm</dd>
          <dt>Volume</dt><dd>{m.volume.toFixed(3)} mm³</dd>
          <dt>Solids</dt><dd>{m.solid_count} {m.valid ? "(valid BREP)" : "(invalid BREP)"}</dd>
          <dt>Holes</dt><dd>{m.cylinders.filter((c) => c.kind === "hole").map((c) => `Ø${+c.diameter.toFixed(3)}`).join(", ") || "none"}</dd>
        </dl>
      )}
      <table className="checks">
        <thead><tr><th>Check</th><th>Requested</th><th>Actual</th><th /></tr></thead>
        <tbody>
          {v.checks.map((c, i) => (
            <tr key={i} title={c.note ?? ""}>
              <td>{c.name.replace(/_/g, " ")}</td>
              <td>{fmt(c.requested)}</td>
              <td>{fmt(c.actual)}</td>
              <td className={c.passed ? "ok-text" : "error"}>{c.passed ? "pass" : "fail"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Checks are measured on the re-imported STEP file. A valid solid does not establish strength, fit or manufacturability.</p>
    </div>
  );
}

function VersionsPanel({ versions, current, canRestore, onOpen, onRestore }: { versions: Version[]; current: string; canRestore: boolean; onOpen: (id: string) => void; onRestore: (id: string) => void }) {
  return (
    <ol className="versions" reversed>
      {versions.map((v, i) => (
        <li key={v.id} className={v.id === current ? "active" : ""}>
          <button className="link" onClick={() => onOpen(v.id)}>v{v.number}</button>
          <span className="muted"> {new Date(v.created_at).toLocaleTimeString()}</span>
          <div className="small">{v.change_summary || (v.parent_version_id ? "Edited" : "Initial generation")}</div>
          {i > 0 && canRestore && <button className="small-btn" onClick={() => onRestore(v.id)}>Restore as new version</button>}
        </li>
      ))}
    </ol>
  );
}

function ExportPanel({ version }: { version: Version }) {
  const labels: Record<string, string> = { STEP: "STEP (exchange solid)", STL: "STL (mesh, mm)", GLB: "GLB (preview)", RECIPE: "Shilpa recipe (JSON)", VALIDATION: "Validation report (JSON)", STL_UNITS: "STL units sidecar" };
  return (
    <div>
      <p className="small">Source: v{version.number} · engine {version.engine.build123d} / OCP {version.engine.ocp}</p>
      <ul className="exports">
        {version.artifacts.filter((a) => labels[a.format]).map((a) => (
          <li key={a.id}>
            <button onClick={() => downloadArtifact(a.id)}>{labels[a.format]}</button>
            <span className="muted small"> {(a.bytes / 1024).toFixed(1)} KB</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ conversation

function Conversation(props: {
  me: Me; health: Health | null; projectId: string; chat: ChatItem[]; jobs: Record<string, { job: Job | null; events: JobEvent[] }>;
  editTarget: Version | null; busy: boolean; say: (c: ChatItem) => void; trackJob: (j: Job) => void; onSpecUpdate: (s: Spec) => void;
}) {
  const { me, health, projectId, chat, jobs, editTarget, busy, say, trackJob, onSpecUpdate } = props;
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [examples, setExamples] = useState<Example[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    api.examples().then(setExamples).catch(() => {});
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat, jobs]);

  const llm = !!health?.llm_configured;
  const send = async () => {
    const t = text.trim();
    if (!t) return;
    setSending(true);
    say({ kind: "user", text: t });
    setText("");
    try {
      if (editTarget) {
        trackJob(await api.editInstruction(editTarget.model_id, editTarget.id, t));
      } else {
        const spec = await api.createSpec(projectId, t);
        say({ kind: "spec", spec });
      }
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "error" });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="conversation">
      <div className="panel-head"><h2>{editTarget ? "Edit with Shilpa" : "New part"}</h2></div>
      <div className="chat">
        {chat.length === 0 && (
          <div className="muted small">
            {editTarget
              ? "Describe a change, e.g. “make it 100 mm wide and keep the holes 10 mm from the edges”. Or edit parameters on the left."
              : "Describe a supported part: plates, brackets, spacers, shafts, flanges or open enclosures. Give the dimensions you need; Shilpa will ask for anything critical that is missing."}
          </div>
        )}
        {chat.map((c, i) =>
          c.kind === "user" ? (
            <div key={i} className="msg user">{c.text}</div>
          ) : c.kind === "system" ? (
            <div key={i} className={`msg system ${c.tone ?? ""}`}>{c.text}</div>
          ) : c.kind === "spec" ? (
            <SpecCard key={c.spec.id + c.spec.revision} spec={c.spec} canWrite={me.can_write} projectId={projectId} onUpdate={onSpecUpdate} trackJob={trackJob} say={say} />
          ) : (
            <JobCard key={c.jobId} entry={jobs[c.jobId]} />
          ),
        )}
        <div ref={endRef} />
      </div>
      {me.can_write && (
        <div className="composer">
          <textarea
            rows={3}
            placeholder={llm ? (editTarget ? "Describe an edit…" : "e.g. Mounting plate 80 x 40 x 8 mm with four 6 mm through holes 10 mm from the edges") : "Configure Azure OpenAI in .env to enable language input"}
            value={text}
            disabled={!llm || sending || busy}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.ctrlKey || e.metaKey) && send()}
          />
          <div className="row">
            <button className="primary" disabled={!llm || sending || busy || !text.trim()} onClick={send}>{sending ? "Reading…" : "Send"}</button>
            {!editTarget && (
              <select
                aria-label="Start from an example"
                value=""
                disabled={busy}
                onChange={async (e) => {
                  const ex = examples.find((x) => x.id === e.target.value);
                  if (!ex) return;
                  say({ kind: "user", text: `Example ${ex.id}: ${ex.description}` });
                  try {
                    trackJob(await api.runRecipe(projectId, ex.recipe));
                  } catch (err) {
                    say({ kind: "system", text: errText(err), tone: "error" });
                  }
                }}
              >
                <option value="">Start from an example…</option>
                {examples.map((x) => (
                  <option key={x.id} value={x.id}>{x.id} · {x.description}</option>
                ))}
              </select>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function SpecCard({ spec, canWrite, projectId, onUpdate, trackJob, say }: { spec: Spec; canWrite: boolean; projectId: string; onUpdate: (s: Spec) => void; trackJob: (j: Job) => void; say: (c: ChatItem) => void }) {
  const r = spec.requirements;
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const submit = async (resolved = false) => {
    const nums: Record<string, number> = {};
    for (const [k, v] of Object.entries(answers)) if (v.trim() && Number.isFinite(Number(v))) nums[k] = Number(v);
    setBusy(true);
    try {
      onUpdate(await api.answerSpec(spec.id, spec.revision, nums, resolved));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };
  const run = async () => {
    setBusy(true);
    try {
      trackJob(await api.runSpec(projectId, spec.id));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="msg system spec">
      <div><strong>{r.summary}</strong></div>
      <div className="small muted">{r.family} · units {r.units}{r.units_source === "project default" ? " (project default — say if different)" : ""}</div>
      <table className="dims">
        <tbody>
          {r.dimensions.filter((d) => d.value !== null).map((d) => (
            <tr key={d.name} title={d.evidence ?? ""}>
              <td>{d.name.replace(/_/g, " ")}</td>
              <td>{d.value} {d.kind === "count" ? "" : d.unit ?? r.units}</td>
              <td className="muted small">{d.source !== "user" ? d.source : d.evidence ? `“${d.evidence}”` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.conflicts.length > 0 && (
        <div className="error small">
          {r.conflicts.map((c, i) => <div key={i}>Conflict: {c.description}</div>)}
          {canWrite && <button className="small-btn" disabled={busy} onClick={() => submit(true)}>I've corrected the values below</button>}
        </div>
      )}
      {r.missing.length > 0 && (
        <div className="questions">
          {r.missing.map((m) => (
            <label key={m.name}>
              {m.question}{m.critical ? " *" : ""}
              <input type="number" step="any" value={answers[m.name] ?? ""} onChange={(e) => setAnswers((a) => ({ ...a, [m.name]: e.target.value }))} />
            </label>
          ))}
          {canWrite && <button disabled={busy} onClick={() => submit()}>Answer</button>}
        </div>
      )}
      {spec.status === "unsupported" && <div className="error small">Not supported yet: {r.status_reason}</div>}
      {spec.status === "ready" && canWrite && (
        <button className="primary" disabled={busy} onClick={run}>Generate CAD</button>
      )}
    </div>
  );
}

const EVENT_TEXT: Record<string, (d: Record<string, unknown>) => string> = {
  "state.queued": () => "Queued",
  "state.planning": () => "Planning the feature sequence",
  "state.executing": (d) => `Building attempt ${d.attempt}${d.mode === "repair" ? " (repaired plan)" : ""}`,
  "attempt.started": () => "Geometry worker running",
  "attempt.failed": (d) => `Attempt ${d.attempt} failed: ${(d.error as { message?: string })?.message ?? "error"} — repairing`,
  "state.succeeded": (d) => `Published version ${d.number}`,
  "state.failed": (d) => `Failed: ${(d.error as { message?: string })?.message ?? "unknown error"}`,
  "state.cancelled": () => "Cancelled",
  "cancel.requested": () => "Cancellation requested",
};

function JobCard({ entry }: { entry?: { job: Job | null; events: JobEvent[] } }) {
  if (!entry) return null;
  const { job, events } = entry;
  const state = events.length ? events[events.length - 1].type.replace("state.", "") : job?.state;
  return (
    <div className={`msg system job ${job?.state === "failed" ? "error" : job?.state === "succeeded" ? "ok" : ""}`}>
      <div className="small muted">Job {job?.id.slice(0, 8)} · {state}</div>
      <ul>
        {events.map((e) => (
          <li key={e.id}>{(EVENT_TEXT[e.type] ?? (() => e.type))(e.data)}</li>
        ))}
      </ul>
    </div>
  );
}
