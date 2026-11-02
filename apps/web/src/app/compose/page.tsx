"use client";

import { ArrowRight, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CompositionStage } from "@/components/compose/composition-stage";
import { applyReason, InterpretationView } from "@/components/compose/interpretation-card";
import { MentionEditor, type Token } from "@/components/compose/mention-editor";
import { StepsList } from "@/components/compose/steps-list";
import { Badge, Button, EmptyState, Progress, Select, Spinner, TextInput } from "@/components/ui";
import { useSession } from "@/context/session-context";
import {
  api,
  ApiError,
  composeApi,
  errText,
  streamJob,
  type CompositionStepRow,
  type CompositionSummary,
  type InterpretationCard,
  type ComposePatch,
  type JobEvent,
  type Project,
  type Version,
} from "@/lib/api";
import { buildPrompt, eventText } from "@/lib/compose";
import { loadLibrary, type LibraryItem } from "@/lib/library";

const NEW_PROJECT = "__new";

type Building = { events: JobEvent[]; state: string | null };

/**
 * Composer (Paper · 05 @ picker, 06 Clarification, 07 Validation). Three
 * columns on desktop: step history, stage with the prompt bar, interpretation
 * card. A composition belongs to a project and its id lives in the URL (?c=)
 * so a reload resumes. Interpret reads the prompt into a card and builds
 * nothing; Apply builds one step and the result shows in the stage.
 */
export default function ComposePage() {
  const { me, health } = useSession();
  const [library, setLibrary] = useState<LibraryItem[] | null>(null);
  const [tokens, setTokens] = useState<Token[]>([]);
  const [draft, setDraft] = useState("");
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectId, setProjectId] = useState("");
  const [newName, setNewName] = useState<string | null>(null);
  const [comp, setComp] = useState<CompositionSummary | null>(null);
  const [steps, setSteps] = useState<CompositionStepRow[]>([]);
  const [version, setVersion] = useState<Version | null>(null);
  const [card, setCard] = useState<{ card: InterpretationCard; prompt: string; key: string } | null>(null);
  const [busy, setBusy] = useState<"interpret" | "answer" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [plannerOff, setPlannerOff] = useState(false);
  const [building, setBuilding] = useState<Building | null>(null);
  const applyKey = useRef<string>("");
  const stopStream = useRef<(() => void) | null>(null);

  const readOnly = me ? !me.can_write : false;
  const planner = plannerOff || health?.planner === "disabled" || health?.planner === "not_configured";
  const chips = tokens.filter((t): t is Extract<Token, { type: "chip" }> => t.type === "chip");

  /* Everything the prompt currently says, to tell whether the card is out of date. */
  const promptKey = useMemo(
    () => JSON.stringify([tokens.map((t) => (t.type === "text" ? t.text : t.label)), draft.trim()]),
    [tokens, draft],
  );
  const stale = !!card && card.key !== promptKey;

  const showVersion = useCallback(async (id: string | null) => {
    setVersion(id ? await api.version(id).catch(() => null) : null);
  }, []);

  const refresh = useCallback(
    async (id: string) => {
      const [c, s] = await Promise.all([composeApi.get(id), composeApi.steps(id)]);
      setComp(c);
      setSteps(s);
      await showVersion(c.head_version_id);
      return c;
    },
    [showVersion],
  );

  /* Library and projects, once. */
  useEffect(() => {
    let cancelled = false;
    loadLibrary()
      .then((l) => !cancelled && setLibrary(l))
      .catch(() => !cancelled && setLibrary([]));
    api
      .projects()
      .then((p) => {
        if (cancelled) return;
        setProjects(p);
        setProjectId((cur) => cur || p[0]?.id || "");
      })
      .catch((e) => !cancelled && (setProjects([]), setError(errText(e))));
    return () => {
      cancelled = true;
    };
  }, []);

  /* ?c=<id> resumes a composition. */
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("c");
    if (!id || !me) return;
    let cancelled = false;
    Promise.resolve()
      .then(() => refresh(id))
      .then((c) => !cancelled && setProjectId(c.project_id))
      .catch((e) => !cancelled && setError(errText(e)));
    return () => {
      cancelled = true;
    };
  }, [me, refresh]);

  useEffect(() => () => stopStream.current?.(), []);

  function setUrl(id: string | null) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("c", id);
    else url.searchParams.delete("c");
    window.history.replaceState(null, "", url);
  }

  function reset() {
    stopStream.current?.();
    setComp(null);
    setSteps([]);
    setVersion(null);
    setCard(null);
    setBuilding(null);
    setError(null);
    setNotice(null);
    setUrl(null);
  }

  async function createProject() {
    const name = (newName ?? "").trim();
    if (!name) return;
    try {
      const p = await api.createProject(name);
      setProjects((l) => [p, ...(l ?? [])]);
      setProjectId(p.id);
      setNewName(null);
    } catch (e) {
      setError(errText(e));
    }
  }

  async function ensureComposition(): Promise<CompositionSummary | null> {
    if (comp) return comp;
    if (!projectId) {
      setError("Pick a project for this composition first.");
      return null;
    }
    const c = await composeApi.create(projectId, "Composition");
    setComp(c);
    setUrl(c.id);
    return c;
  }

  async function run<T>(kind: "interpret" | "answer" | "apply", fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(kind);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      if (e instanceof ApiError && e.info.code === "planner_disabled") {
        setPlannerOff(true);
        setError(null);
      } else setError(errText(e));
    } finally {
      setBusy(null);
    }
    return undefined;
  }

  async function interpret() {
    setNotice(null);
    await run("interpret", async () => {
      const c = await ensureComposition();
      if (!c) return;
      const built = await buildPrompt(tokens, draft);
      if (!built.prompt) {
        setError("Write a prompt first. Type @ to pick a part.");
        return;
      }
      const res = await composeApi.interpret(c.id, { prompt: built.prompt, mentions: built.mentions });
      applyKey.current = crypto.randomUUID();
      setCard({ card: res, prompt: built.prompt, key: promptKey });
    });
  }

  /* Choosing an option sends the card's steps back with the option's patch: no model call. */
  async function answer(patch: ComposePatch[]) {
    if (!card || !comp) return;
    await run("answer", async () => {
      const res = await composeApi.interpret(comp.id, { prompt: "", steps: card.card.steps, answers: patch });
      applyKey.current = crypto.randomUUID();
      setCard({
        prompt: card.prompt,
        key: card.key,
        card: res.mentions.length ? res : { ...res, mentions: card.card.mentions },
      });
    });
  }

  async function apply() {
    if (!card || !comp) return;
    const { card: c, prompt } = card;
    setNotice(null);
    const out = await run("apply", async () => {
      try {
        return await composeApi.apply(
          comp.id,
          { prompt, steps: c.steps, base_version_id: c.base_version_id, spec_hash: c.spec_hash },
          applyKey.current,
        );
      } catch (e) {
        if (e instanceof ApiError) {
          const code = e.info.code;
          if (code === "stale_revision" || code === "interpretation_changed") {
            await refresh(comp.id);
            setNotice(
              code === "stale_revision"
                ? "The composition moved on since this reading. Interpret the prompt again."
                : "The parts changed since this reading. Interpret the prompt again.",
            );
            setCard(null);
            return undefined;
          }
          if (code === "step_running") {
            setNotice("The previous step is still building. Wait for it to finish, then apply.");
            return undefined;
          }
          if (code === "blocked") {
            setNotice("The reading has open questions. Answer them, then apply.");
            const res = await composeApi.interpret(comp.id, { prompt: "", steps: c.steps });
            setCard({ prompt, key: card.key, card: res });
            return undefined;
          }
        }
        throw e;
      }
    });
    if (!out) return;
    setCard(null);
    setBuilding({ events: [], state: null });
    stopStream.current?.();
    stopStream.current = streamJob(
      out.job.id,
      (ev) => setBuilding((b) => ({ state: b?.state ?? null, events: [...(b?.events ?? []), ev] })),
      async (state) => {
        setBuilding((b) => ({ events: b?.events ?? [], state }));
        try {
          await refresh(comp.id);
        } catch (e) {
          setError(errText(e));
        }
        if (state === "succeeded") {
          setTokens([]);
          setDraft("");
          setBuilding(null);
        }
      },
    );
    setSteps((s) => [...s.filter((x) => x.id !== out.step.id), out.step]);
  }

  const reason = card ? applyReason(card.card, stale) : null;
  const working = busy !== null;
  const building_ = building !== null && building.state === null;
  const canInterpret = !readOnly && !planner && !working && !building_;
  const noProjects = projects !== null && projects.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:grid lg:grid-cols-[280px_minmax(0,1fr)_320px] lg:overflow-hidden">
      <h1 className="sr-only">Compose a complex part</h1>

      {/* Steps */}
      <section aria-labelledby="steps-h" className="order-3 flex min-h-0 flex-col border-line lg:order-none lg:border-r">
        <header className="flex h-[42px] shrink-0 items-baseline gap-2 px-4 pt-3.5">
          <h2 id="steps-h" className="text-md">
            Steps
          </h2>
          <span className="text-xs text-body">{steps.length} · replay needs no AI</span>
        </header>
        {steps.length ? (
          <StepsList steps={steps} library={library} />
        ) : (
          <EmptyState
            image="/imagery/sh-card-09-steps-128.webp"
            imageSize={48}
            title="No steps yet"
            detail="Each prompt you apply becomes a step. Steps replay deterministically, without the planner."
            className="min-h-[220px] lg:min-h-0"
          />
        )}
      </section>

      {/* Stage + prompt */}
      <section aria-label="Stage" className="order-1 flex min-h-[420px] min-w-0 flex-col bg-bg lg:order-none lg:min-h-0">
        <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pt-3">
          {newName !== null ? (
            <form
              className="flex min-w-0 flex-1 items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void createProject();
              }}
            >
              <TextInput aria-label="New project name" placeholder="Project name" value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus className="h-7 min-w-0 flex-1" />
              <Button size="sm" variant="secondary" type="submit" disabled={!newName.trim()}>
                Create
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setNewName(null)}>
                Cancel
              </Button>
            </form>
          ) : (
            <>
              {projects ? (
                <Select
                  size="sm"
                  aria-label="Project"
                  value={projectId}
                  placeholder={noProjects ? "No projects yet" : "Pick a project"}
                  disabled={!!comp || readOnly}
                  onChange={(e) => (e.target.value === NEW_PROJECT ? setNewName("") : setProjectId(e.target.value))}
                  className="min-w-0 flex-1 sm:max-w-[260px] sm:flex-none"
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                  {!comp && !readOnly ? <option value={NEW_PROJECT}>New project…</option> : null}
                </Select>
              ) : (
                <Spinner label="Loading projects" />
              )}
              {comp ? (
                <>
                  <span className="min-w-0 truncate text-sm text-body">{comp.name}</span>
                  {!readOnly ? (
                    <Button size="sm" variant="ghost" onClick={reset} icon={<Plus size={13} strokeWidth={1.75} aria-hidden />}>
                      New composition
                    </Button>
                  ) : null}
                </>
              ) : null}
            </>
          )}
        </div>

        <div className="relative flex min-h-[260px] flex-1 flex-col px-4 pt-3 lg:min-h-0">
          {version ? (
            <CompositionStage key={version.id} version={version} />
          ) : (
            <div className="relative flex min-h-0 flex-1 items-center justify-center rounded-xl bg-[radial-gradient(var(--color-line-strong)_1px,transparent_1px)] [background-size:16px_16px]">
              <EmptyState
                image="/imagery/sh-card-08-mention-128.webp"
                imageSize={64}
                title="Start with @"
                detail="Pick a part from your library, then say what to do with it: “insert @ISO4032-M6 into every hole on @bracket”."
                className="max-w-[440px] bg-transparent"
              />
            </div>
          )}
        </div>

        <div className="shrink-0 p-4 lg:px-4 lg:pb-4">
          {readOnly ? (
            <div className="rounded-xl border border-line p-4">
              <EmptyState
                image="/imagery/sh-emp-05-viewer-role-128.webp"
                imageSize={48}
                align="start"
                title="You have read-only access"
                detail="Viewers can open compositions and their checks. Ask an org admin for edit access to add steps."
                className="min-h-0 p-0"
              />
            </div>
          ) : (
            <div className="rounded-xl border-[1.5px] border-line-strong bg-bg px-3.5 pt-3 pb-3 transition-[border-color,box-shadow] duration-fast focus-within:border-action focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-action)_12%,transparent)]">
              <MentionEditor
                library={library}
                tokens={tokens}
                onTokens={setTokens}
                draft={draft}
                onDraft={setDraft}
                onSubmit={canInterpret ? () => void interpret() : undefined}
                disabled={building_}
              />
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
                <p className="min-w-0 flex-1 text-xs text-muted-text">@ part · . features · nothing builds until you apply</p>
                <span className="text-xs text-body">mm</span>
                <Button
                  variant={card && !stale && !reason ? "secondary" : "primary"}
                  disabled={!canInterpret}
                  loading={busy === "interpret"}
                  onClick={() => void interpret()}
                  icon={<ArrowRight size={14} strokeWidth={2.2} aria-hidden />}
                >
                  {card ? "Re-interpret" : "Interpret"}
                </Button>
              </div>
              {planner ? (
                <p className="mt-2 text-xs text-body">Planner is off. Mentions and the picker still work, but prompts cannot be read until it is on.</p>
              ) : null}
            </div>
          )}
        </div>
      </section>

      {/* Inspector */}
      <aside aria-labelledby="inspector-h" className="order-2 flex min-h-0 flex-col gap-5 overflow-y-auto border-t border-line px-4 py-4 lg:order-none lg:border-t-0 lg:border-l lg:px-4">
        {error ? (
          <p role="alert" className="rounded-panel border border-fail bg-fail-soft p-3 text-sm text-fail-text">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="rounded-panel border border-consent bg-consent-soft p-3 text-sm text-consent-text">
            {notice}
          </p>
        ) : null}

        {building ? (
          <section aria-label="Build progress" className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <h2 id="inspector-h" className="text-md">
                Building the step
              </h2>
              {building.state === "succeeded" ? <Badge tone="pass">Done</Badge> : building.state ? <Badge tone="fail">Failed</Badge> : null}
            </div>
            {building.state === null ? <Progress label="Building the step" /> : null}
            <ol className="flex flex-col gap-1 text-sm text-body">
              {building.events.map((e) => (
                <li key={e.id} className={e.type === "state.failed" ? "text-fail-text" : undefined}>
                  {eventText(e.type, e.data)}
                </li>
              ))}
            </ol>
            {building.state && building.state !== "succeeded" ? (
              <Button size="sm" onClick={() => setBuilding(null)}>
                Dismiss
              </Button>
            ) : null}
          </section>
        ) : card ? (
          <>
            <InterpretationView card={card.card} stale={stale} busy={working} onAnswer={(p) => void answer(p)} />
            {!readOnly ? (
              <div className="flex flex-col gap-2 border-t border-line pt-3">
                <Button
                  variant={reason ? "secondary" : "primary"}
                  disabled={!!reason || working}
                  loading={busy === "apply"}
                  onClick={() => void apply()}
                >
                  Apply as step {steps.length + 1}
                </Button>
                {reason ? <p className="text-xs text-body">{reason}</p> : <p className="text-xs text-muted-text">Builds one step. Earlier steps stay as they are.</p>}
              </div>
            ) : null}
          </>
        ) : (
          <div className="flex flex-col gap-1">
            <h2 id="inspector-h" className="text-md">
              Interpretation
            </h2>
            {planner ? (
              <p className="text-sm text-body">Planner is off. You can still pick parts with @, but Shilpa cannot read a prompt until the planner is on.</p>
            ) : (
              <p className="text-sm text-body">Interpret a prompt to see how Shilpa reads it, with units normalised, before anything is built.</p>
            )}
          </div>
        )}

        {!card && !building ? (
          <div className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-body">Resolved references</h3>
            {chips.length === 0 ? (
              <p className="text-sm text-muted-text">Mentions you insert appear here with their source.</p>
            ) : (
              <ul className="flex flex-col">
                {chips.map((c, i) => (
                  <li key={i} className="flex min-w-0 items-center gap-2 border-b border-line py-2 last:border-b-0">
                    <span
                      className={`truncate rounded-sm px-1.5 py-px text-sm font-semibold ${c.item.kind === "complex" ? "bg-complex-soft text-complex-text" : "bg-basic-soft text-basic-text"}`}
                    >
                      {c.label}
                    </span>
                    <span className="ml-auto shrink-0 text-xs text-body">{c.item.source === "catalog" ? "catalog" : "native"}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </aside>
    </div>
  );
}
