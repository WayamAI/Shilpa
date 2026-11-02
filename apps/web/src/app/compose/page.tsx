"use client";

import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";

import { MentionEditor, type Token } from "@/components/compose/mention-editor";
import { Badge, Button, EmptyState, Tooltip } from "@/components/ui";
import { useSession } from "@/context/session-context";
import { loadLibrary, type LibraryItem } from "@/lib/library";

/**
 * Composer (Paper · 05 Composer · @ picker open). Three columns on desktop:
 * step history, stage with the prompt bar, step inspector.
 *
 * What is real today: the @ prompt and picker over the live library, and
 * the resolved references of the chips you insert. Interpreting, applying
 * steps and the composition viewer need the compose API (spec P0/P1), so
 * they are shown empty or marked Planned. Nothing here is simulated.
 */
export default function ComposePage() {
  const { me } = useSession();
  const [library, setLibrary] = useState<LibraryItem[] | null>(null);
  const [tokens, setTokens] = useState<Token[]>([]);

  useEffect(() => {
    let cancelled = false;
    loadLibrary()
      .then((l) => !cancelled && setLibrary(l))
      .catch(() => !cancelled && setLibrary([]));
    return () => {
      cancelled = true;
    };
  }, []);

  const readOnly = me ? !me.can_write : false;
  const chips = tokens.filter((t): t is Extract<Token, { type: "chip" }> => t.type === "chip");

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:grid lg:grid-cols-[280px_minmax(0,1fr)_320px] lg:overflow-hidden">
      <h1 className="sr-only">Compose a complex part</h1>

      {/* Steps */}
      <section aria-labelledby="steps-h" className="order-3 flex min-h-0 flex-col border-line lg:order-none lg:border-r">
        <header className="flex h-[42px] shrink-0 items-baseline gap-2 px-4 pt-3.5">
          <h2 id="steps-h" className="text-md">
            Steps
          </h2>
          <span className="text-xs text-body">0 · replay needs no AI</span>
        </header>
        <EmptyState
          image="/imagery/sh-card-09-steps-128.webp"
          imageSize={48}
          title="No steps yet"
          detail="Each prompt you apply becomes a step. Steps replay deterministically, without the planner."
          className="min-h-[220px] lg:min-h-0"
        />
      </section>

      {/* Stage + prompt */}
      <section aria-label="Stage" className="order-1 flex min-h-[420px] flex-col bg-bg lg:order-none lg:min-h-0">
        <div className="relative flex min-h-0 flex-1 items-center justify-center bg-[radial-gradient(var(--color-line-strong)_1px,transparent_1px)] [background-size:16px_16px]">
          <EmptyState
            image="/imagery/sh-card-08-mention-128.webp"
            imageSize={64}
            title="Start with @"
            detail="Pick a part from your library, then say what to do with it: “insert @ISO4032-M6 into every hole on @bracket”."
            className="max-w-[440px] bg-transparent"
          />
          <p className="absolute bottom-3 left-4 text-caption text-muted-text">The composition viewer arrives with the compose API</p>
        </div>

        <div className="shrink-0 p-4 pt-0 lg:px-4 lg:pb-4">
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
              <MentionEditor library={library} tokens={tokens} onTokens={setTokens} />
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
                <p className="min-w-0 flex-1 text-xs text-muted-text">@ part · . features · nothing builds until you apply</p>
                <span className="text-xs text-body">mm</span>
                <Tooltip content="Interpreting a prompt needs the compose API (planned)">
                  <Button variant="primary" disabled icon={<ArrowRight size={14} strokeWidth={2.2} aria-hidden />}>
                    Interpret
                  </Button>
                </Tooltip>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Inspector */}
      <aside aria-labelledby="inspector-h" className="order-2 flex min-h-0 flex-col gap-5 overflow-y-auto border-t border-line px-4 py-4 lg:order-none lg:border-t-0 lg:border-l lg:px-4">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <h2 id="inspector-h" className="text-md">
              Interpretation
            </h2>
            <Badge tone="consent">Planned</Badge>
          </div>
          <p className="text-sm text-body">Shilpa will show how it read your prompt here, with units normalised, before anything is built.</p>
        </div>

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

        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold text-body">Checks · oracle</h3>
          <p className="text-sm text-muted-text">Interference, fit, DOF and unit checks run after a step is applied, each with its oracle.</p>
        </div>
      </aside>
    </div>
  );
}
