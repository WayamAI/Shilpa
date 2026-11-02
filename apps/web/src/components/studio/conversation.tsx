"use client";

import { FileUp, SendHorizontal, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge, type BadgeTone, Button, Dot, NumberInput, Select, Textarea } from "@/components/ui";
import { useSession } from "@/context/session-context";
import { api, errText, uploadDrawing, type Example, type Job, type JobEvent, type Route, type Spec, type Starters, type Version } from "@/lib/api";

import { DrawingReview } from "./drawing-review";

export type ChatItem =
  | { kind: "user"; text: string }
  | { kind: "system"; text: string; tone?: "fail" }
  | { kind: "spec"; spec: Spec }
  | { kind: "job"; jobId: string };

export type JobState = Record<string, { job: Job; events: JobEvent[] }>;

export function Conversation({
  projectId,
  chat,
  jobs,
  editTarget,
  busy,
  say,
  trackJob,
  onSpecUpdate,
}: {
  projectId: string;
  chat: ChatItem[];
  jobs: JobState;
  editTarget: Version | null;
  busy: boolean;
  say: (c: ChatItem) => void;
  trackJob: (j: Job) => void;
  onSpecUpdate: (s: Spec) => void;
}) {
  const { me, health } = useSession();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [examples, setExamples] = useState<Example[]>([]);
  const [starters, setStarters] = useState<Starters | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const llm = !!health?.llm_configured;
  const plannerDisabled = health?.planner === "disabled";
  const canWrite = !!me?.can_write;

  useEffect(() => {
    api.examples().then(setExamples).catch(() => {});
    api.starters().then(setStarters).catch(() => {});
  }, []);
  useEffect(() => {
    // Scroll the list itself; scrollIntoView would also scroll the page.
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [chat, jobs]);

  async function send() {
    const t = text.trim();
    if (!t) return;
    setSending(true);
    say({ kind: "user", text: t });
    setText("");
    try {
      if (editTarget) {
        trackJob(await api.editInstruction(editTarget.model_id, editTarget.id, t));
        return;
      }
      // Route first (rule-based, no model call): only single parts go to the part planner.
      const route = await api.route(t);
      if (route.kind === "product" && health?.products_available) {
        // Product templates read requests with a rule-based parser: no AI call, even with the planner on.
        say({ kind: "system", text: "This reads as a product. Running its template with the offline parser (about 30 s)." });
        trackJob(await api.runProduct(projectId, { request: t }));
        return;
      }
      if (route.kind !== "part" || !llm) {
        say({ kind: "system", text: routeMessage(route, llm), tone: route.supported ? undefined : "fail" });
        return;
      }
      say({ kind: "spec", spec: await api.createSpec(projectId, t) });
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    } finally {
      setSending(false);
    }
  }

  async function upload(file: File) {
    setSending(true);
    const note = text.trim();
    say({ kind: "user", text: `Drawing: ${file.name}${note ? ` — ${note}` : ""}` });
    try {
      const up = await uploadDrawing(projectId, file);
      say({
        kind: "system",
        text: `Reading ${up.filename} — ${up.pages.length} page${up.pages.length === 1 ? "" : "s"}, ${up.has_text_layer ? "text layer" : "scanned image"}.`,
      });
      setText("");
      say({ kind: "spec", spec: await api.specFromUpload(projectId, up.id, note) });
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    } finally {
      setSending(false);
    }
  }

  async function runExample(id: string) {
    const ex = examples.find((x) => x.id === id);
    if (!ex) return;
    say({ kind: "user", text: `Reference part ${ex.id}: ${ex.description}` });
    try {
      trackJob(await api.runRecipe(projectId, ex.recipe));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    }
  }

  async function runStarter(value: string) {
    const [kind, id] = value.split(":");
    if (kind === "product") {
      const pr = starters?.products?.find((x) => x.id === id);
      if (!pr) return;
      say({ kind: "user", text: `Reference product ${pr.title}: ${pr.description}` });
      try {
        trackJob(await api.runProduct(projectId, { request: pr.request, spec: pr.spec, starter: pr.id }));
      } catch (e) {
        say({ kind: "system", text: errText(e), tone: "fail" });
      }
      return;
    }
    const list = kind === "assembly" ? starters?.assemblies : starters?.sheet_metal;
    const st = list?.find((x) => x.id === id);
    if (!st) return;
    say({ kind: "user", text: `Reference ${kind === "assembly" ? "assembly" : "sheet-metal part"} ${st.title}: ${st.description}` });
    try {
      trackJob(kind === "assembly" ? await api.runAssembly(projectId, st.spec, st.id) : await api.runSheetMetal(projectId, st.spec, st.id));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    }
  }

  // With the planner disabled, typing still works: requests are routed and explained, never sent to a model.
  const disabled = (!llm && !plannerDisabled) || sending || busy;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
        {chat.length === 0 ? (
          <div className="flex flex-col gap-2 text-xs text-muted-text">
            <Sparkles size={18} strokeWidth={1.5} className="text-muted" aria-hidden />
            {editTarget ? (
              <p>Describe a change — “make it 100 mm wide and keep the holes 10 mm from the edges” — or edit parameters on the left.</p>
            ) : (
              <>
                <p>
                  Describe a plate, bracket, spacer, shaft, flange or open enclosure with its dimensions, or upload a drawing. Shilpa asks
                  for anything critical that is missing.
                </p>
                <p>
                  Assemblies, sheet-metal parts and products start from the reference starters below. A bike request such as “medium road
                  bike for a 178 cm rider, 700c” runs the bicycle template, and “4:1 gearbox, 20 Nm input at 1500 rpm” runs the gearbox
                  template: none of it needs the AI planner.
                </p>
                {plannerDisabled ? (
                  <p className="rounded-lg border border-line bg-surface px-3 py-2 text-body" data-testid="planner-disabled">
                    The AI planner is disabled on this server (SHILPA_LLM=off). Requests are routed and explained but not planned.
                  </p>
                ) : null}
              </>
            )}
          </div>
        ) : null}
        <div className="flex flex-col gap-3">
          {chat.map((c, i) =>
            c.kind === "user" ? (
              <div key={i} className="ml-8 self-end rounded-2xl rounded-br-md bg-surface-2 px-3.5 py-2.5 text-sm text-ink [overflow-wrap:anywhere]">
                {c.text}
              </div>
            ) : c.kind === "system" ? (
              <div
                key={i}
                role={c.tone === "fail" ? "alert" : undefined}
                className={[
                  "rounded-lg border px-3.5 py-2.5 text-xs [overflow-wrap:anywhere]",
                  c.tone === "fail" ? "border-fail/40 bg-fail-soft text-fail-text" : "border-line bg-surface text-body",
                ].join(" ")}
              >
                {c.text}
              </div>
            ) : c.kind === "spec" ? (
              <SpecCard key={c.spec.id} spec={c.spec} canWrite={canWrite} projectId={projectId} onUpdate={onSpecUpdate} trackJob={trackJob} say={say} />
            ) : (
              <JobCard key={c.jobId} entry={jobs[c.jobId]} />
            ),
          )}
        </div>
      </div>

      {canWrite ? (
        <div className="shrink-0 border-t border-line p-3">
          <Textarea
            aria-label={editTarget ? "Describe an edit" : "Describe a part"}
            placeholder={
              plannerDisabled
                ? "AI planner is disabled — describe a request to see how it is routed, or pick a starter"
                : !llm
                ? "Azure OpenAI is not configured — reference parts still work"
                : editTarget
                  ? "Describe an edit…"
                  : "Mounting plate 80 × 40 × 8 mm with four Ø6 through holes 10 mm from the edges"
            }
            value={text}
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send();
            }}
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" disabled={disabled || !text.trim()} onClick={send}>
              <SendHorizontal size={13} strokeWidth={1.75} aria-hidden />
              {sending ? "Reading…" : plannerDisabled && !editTarget ? "Route" : "Send"}
            </Button>
            {!editTarget ? (
              <>
                <Button size="sm" disabled={disabled || !llm} onClick={() => fileRef.current?.click()}>
                  <FileUp size={13} strokeWidth={1.75} aria-hidden />
                  Upload drawing
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  aria-label="Drawing file"
                  accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                  className="hidden"
                  data-testid="drawing-input"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) upload(f);
                  }}
                />
                <Select
                  aria-label="Start from a reference part"
                  value=""
                  disabled={busy}
                  onChange={(e) => runExample(e.target.value)}
                  size="sm"
                  className="max-w-full"
                >
                  <option value="">Reference parts…</option>
                  {examples.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.id} · {x.description}
                    </option>
                  ))}
                </Select>
                {starters && (starters.assemblies.length || starters.sheet_metal.length) ? (
                  <Select
                    aria-label="Start from a reference assembly, sheet-metal part or product"
                    value=""
                    disabled={busy}
                    onChange={(e) => runStarter(e.target.value)}
                    size="sm"
                    className="w-full"
                  >
                    <option value="">{starters.products?.length ? "Assemblies, sheet metal, products…" : "Assemblies and sheet metal…"}</option>
                    <optgroup label="Reference assemblies">
                      {starters.assemblies.map((x) => (
                        <option key={x.id} value={`assembly:${x.id}`}>
                          {x.title}
                          {(x.expected.fail as string[] | undefined)?.length ? " (fails a check)" : ""}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label="Sheet metal">
                      {starters.sheet_metal.map((x) => (
                        <option key={x.id} value={`sheet_metal:${x.id}`}>
                          {x.title}
                          {x.expected.passed === false ? " (fails a rule)" : ""}
                        </option>
                      ))}
                    </optgroup>
                    {starters.products?.length ? (
                      <optgroup label="Reference products">
                        {starters.products.map((x) => (
                          <option key={x.id} value={`product:${x.id}`}>
                            {x.title}
                            {x.expected.status === "repaired" ? " (router repairs it)" : ""}
                          </option>
                        ))}
                      </optgroup>
                    ) : null}
                  </Select>
                ) : null}
              </>
            ) : null}
            <span className="ml-auto hidden text-xs text-muted-text xl:inline">Ctrl+Enter to send</span>
          </div>
        </div>
      ) : (
        <p className="shrink-0 border-t border-line px-4 py-3 text-xs text-muted-text">Read-only role: you can view parts and download files.</p>
      )}
    </div>
  );
}

// --- requirements card ------------------------------------------------------------

function SpecCard({
  spec,
  canWrite,
  projectId,
  onUpdate,
  trackJob,
  say,
}: {
  spec: Spec;
  canWrite: boolean;
  projectId: string;
  onUpdate: (s: Spec) => void;
  trackJob: (j: Job) => void;
  say: (c: ChatItem) => void;
}) {
  const r = spec.requirements;
  const isDrawing = r.source === "drawing";
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(isDrawing && spec.status === "needs_review");
  const [started, setStarted] = useState(false);

  async function submit(resolved = false) {
    const nums: Record<string, number> = {};
    for (const [k, v] of Object.entries(answers)) if (v.trim() && Number.isFinite(Number(v))) nums[k] = Number(v);
    setBusy(true);
    try {
      onUpdate(await api.answerSpec(spec.id, spec.revision, nums, resolved));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    setBusy(true);
    try {
      trackJob(await api.runSpec(projectId, spec.id));
      setStarted(true);
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    } finally {
      setBusy(false);
    }
  }

  const statusTone: Record<string, BadgeTone> = { ready: "pass", needs_review: "complex", needs_clarification: "consent", unsupported: "fail" };
  const statusLabel: Record<string, string> = { ready: "ready", needs_review: "review drawing", needs_clarification: "needs answers", unsupported: "not supported" };

  return (
    <section className="rounded-lg border border-line bg-bg" aria-label="Requirements" data-testid="spec-card">
      <header className="flex items-start justify-between gap-3 border-b border-line px-3.5 py-2.5">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-body">
            {isDrawing ? "Read from drawing" : "Requirements"} · {r.family} · {r.units}
          </p>
          <p className="mt-0.5 text-sm text-ink">{r.summary}</p>
        </div>
        <Badge tone={statusTone[spec.status] ?? "neutral"}>{statusLabel[spec.status] ?? spec.status}</Badge>
      </header>
      <div className="px-3.5 py-2.5">
        <table className="w-full">
          <tbody>
            {r.dimensions
              .filter((d) => d.value !== null)
              .map((d) => (
                <tr key={d.name} title={d.evidence ?? ""} className="align-baseline">
                  <td className="py-0.5 pr-2 text-xs text-muted-text capitalize">{d.name.replace(/_/g, " ")}</td>
                  <td className="py-0.5 text-right text-xs tabular text-ink whitespace-nowrap">
                    {d.value} {d.kind === "count" ? "" : (d.unit ?? r.units)}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>

        {r.units_source === "project default" ? <p className="mt-2 text-xs text-muted-text">Units not stated — using the project default (mm).</p> : null}

        {r.assumptions && r.assumptions.length > 0 ? (
          <details className="mt-2 group">
            <summary className="cursor-pointer text-xs text-muted-text outline-none hover:text-body">
              {r.assumptions.length} assumed convention{r.assumptions.length === 1 ? "" : "s"}
            </summary>
            <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4 text-xs text-muted-text">
              {r.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </details>
        ) : null}

        {!isDrawing && r.conflicts.length > 0 ? (
          <div className="mt-2 rounded-lg border border-fail/40 bg-fail-soft px-3 py-2 text-xs text-fail-text">
            {r.conflicts.map((c, i) => (
              <p key={i}>{c.description}</p>
            ))}
            {canWrite ? (
              <Button size="sm" variant="ghost" className="mt-1 -ml-3" disabled={busy} onClick={() => submit(true)}>
                I have corrected the values
              </Button>
            ) : null}
          </div>
        ) : null}

        {!isDrawing && r.missing.length > 0 ? (
          <div className="mt-2 flex flex-col gap-2">
            {r.missing.map((m) => (
              <label key={m.name} className="flex items-center justify-between gap-3 text-xs text-body">
                <span>
                  {m.question}
                  {m.critical ? <span className="text-fail-text"> *</span> : null}
                </span>
                <NumberInput aria-label={m.question} value={answers[m.name] ?? ""} onChange={(e) => setAnswers((a) => ({ ...a, [m.name]: e.target.value }))} />
              </label>
            ))}
            {canWrite ? (
              <Button size="sm" className="self-start" disabled={busy} onClick={() => submit()}>
                Answer
              </Button>
            ) : null}
          </div>
        ) : null}

        {spec.status === "unsupported" ? <p className="mt-2 text-xs text-fail-text">{r.status_reason}</p> : null}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {isDrawing ? (
            <Button size="sm" variant={spec.status === "needs_review" ? "primary" : "secondary"} onClick={() => setReviewOpen(true)}>
              {spec.status === "needs_review" ? "Review drawing values" : "View drawing review"}
            </Button>
          ) : null}
          {spec.status === "ready" && canWrite && !started ? (
            <Button size="sm" variant="primary" disabled={busy} onClick={run}>
              Generate CAD
            </Button>
          ) : null}
          {started ? <span className="text-xs text-muted-text">Sent to the CAD workers — progress below.</span> : null}
        </div>
      </div>
      {reviewOpen && isDrawing ? (
        <DrawingReview
          spec={spec}
          canWrite={canWrite}
          onClose={() => setReviewOpen(false)}
          onUpdate={(s) => {
            onUpdate(s);
            if (s.status === "ready") setReviewOpen(false);
          }}
        />
      ) : null}
    </section>
  );
}

// --- job timeline ---------------------------------------------------------------

const EVENT_TEXT: Record<string, (d: Record<string, unknown>) => string> = {
  "state.queued": () => "Queued",
  "state.planning": () => "Planning the feature sequence",
  "state.executing": (d) =>
    d.mode === "direct"
      ? `Building the ${String(d.kind).replace("_", "-")}${d.instances ? ` · ${d.instances} instances` : ""}`
      : `Building attempt ${d.attempt}${d.mode === "repair" ? " with a repaired plan" : ""}`,
  "attempt.started": () => "Geometry worker running",
  "attempt.failed": (d) => `Attempt ${d.attempt} failed: ${(d.error as { message?: string })?.message ?? "error"} — repairing`,
  "state.succeeded": (d) => (d.format ? `${d.format} file created and verified` : `Published version ${d.number}`),
  "state.failed": (d) => `Failed: ${(d.error as { message?: string })?.message ?? "unknown error"}`,
  "state.cancelled": () => "Cancelled",
  "cancel.requested": () => "Cancellation requested",
  progress: (d) => String(d.message ?? ""),
};

const JOB_LABEL: Record<string, string> = {
  export: "Export",
  edit: "Edit",
  generate: "Generate",
  assembly: "Assembly",
  sheet_metal: "Sheet metal",
  product: "Product",
};

const ROUTE_LABEL: Record<string, string> = {
  part: "a single part",
  sheet_metal: "a sheet-metal part",
  assembly: "an assembly",
  product: "a product",
};

/** What happens to a routed request, in plain words. */
function routeMessage(route: Route, llm: boolean): string {
  if (!route.supported) return `${route.reason} Shilpa builds mechanical parts, sheet metal, assemblies and template products.`;
  const what = `This reads as ${ROUTE_LABEL[route.kind]}.`;
  const disabled = route.planner === "disabled" ? " The AI planner is disabled (SHILPA_LLM=off), so it cannot be planned from text." : "";
  const next: Record<string, string> = {
    part: llm ? "" : " Start from a reference part instead, then edit its parameters.",
    sheet_metal: " Language planning for sheet metal is not wired yet: start from a sheet-metal example and build from its spec.",
    assembly: " Language planning for assemblies is not wired yet: start from a reference assembly to see placement and every check.",
    product: " The product templates are not installed on this server yet.",
  };
  return `${what}${disabled}${next[route.kind] ?? ""}`;
}

function eventTone(type: string): BadgeTone {
  if (type === "state.succeeded") return "pass";
  if (type === "state.failed") return "fail";
  if (type === "attempt.failed") return "consent";
  return "neutral";
}

function JobCard({ entry }: { entry?: { job: Job; events: JobEvent[] } }) {
  if (!entry) return null;
  const { job, events } = entry;
  const done = ["succeeded", "failed", "cancelled"].includes(job.state);
  const tone: BadgeTone = job.state === "succeeded" ? "pass" : job.state === "failed" ? "fail" : job.state === "cancelled" ? "neutral" : "complex";
  return (
    <section className="rounded-lg border border-line bg-bg" aria-label="Job progress" data-testid="job-card" data-state={job.state}>
      <header className="flex items-center justify-between gap-3 border-b border-line px-3.5 py-2">
        <span className="text-xs font-semibold text-body">
          {JOB_LABEL[job.kind] ?? "Generate"} · {job.id.slice(0, 8)}
        </span>
        <Badge tone={tone}>{done ? job.state : "running"}</Badge>
      </header>
      <ol className="px-3.5 py-2.5">
        {events.map((e) => (
          <li key={e.id} className="flex items-start gap-2.5 py-0.5 text-xs text-body [overflow-wrap:anywhere]">
            <span className="mt-[7px]">
              <Dot tone={eventTone(e.type)} />
            </span>
            <span className={e.type === "state.failed" ? "text-fail-text" : undefined}>{(EVENT_TEXT[e.type] ?? (() => e.type))(e.data)}</span>
          </li>
        ))}
        {!done ? <li className="py-0.5 pl-4 text-xs text-muted-text">…</li> : null}
      </ol>
    </section>
  );
}
