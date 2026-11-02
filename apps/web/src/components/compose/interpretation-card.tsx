"use client";

import { AlertTriangle, ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

import { Badge, Button, Dot } from "@/components/ui";
import type { ComposeBlocker, ComposeMention, ComposePatch, InterpretationCard } from "@/lib/api";

const MENTION_TONE: Record<ComposeMention["status"], "pass" | "consent" | "fail"> = {
  ok: "pass",
  ambiguous: "consent",
  unknown: "fail",
  invalid: "fail",
};

export const blockingOf = (card: InterpretationCard) => card.blockers.filter((b) => b.blocking);

/** Why Apply is off, or null when it can go. */
export function applyReason(card: InterpretationCard, stale: boolean): string | null {
  if (stale) return "The prompt changed since this reading. Interpret it again.";
  const n = blockingOf(card).length;
  if (n > 0) return `Answer ${n === 1 ? "the question" : `${n} questions`} above to enable Apply.`;
  if (card.status === "empty" || !card.spec_hash) return "Nothing to build yet.";
  return null;
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col gap-2 wrap-anywhere">
      <h3 className="flex items-baseline gap-1.5 text-xs font-semibold text-body">
        {title}
        {count !== undefined ? <span className="font-normal text-muted-text tabular">{count}</span> : null}
      </h3>
      {children}
    </section>
  );
}

/** Interpretation card (Paper · 06 Clarification, 07 Validation). A view over the API's card. */
export function InterpretationView({
  card,
  stale,
  busy,
  onAnswer,
}: {
  card: InterpretationCard;
  stale: boolean;
  busy: boolean;
  onAnswer: (patch: ComposePatch[]) => void;
}) {
  const blocking = blockingOf(card);
  const acks = card.blockers.filter((b) => !b.blocking);
  const c = card.counts;
  const cost = card.llm.used ? card.llm : null;

  return (
    <div className="flex flex-col gap-5" aria-busy={busy || undefined}>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <h2 id="inspector-h" className="text-md">
            Interpretation
          </h2>
          {stale ? (
            <Badge tone="consent">Out of date</Badge>
          ) : card.status === "ready" ? (
            <Badge tone="pass">Ready</Badge>
          ) : card.status === "blocked" ? (
            <Badge tone="consent">{blocking.length === 1 ? "1 question" : `${blocking.length} questions`}</Badge>
          ) : (
            <Badge>Empty</Badge>
          )}
        </div>
        {card.reading ? <p className="text-prose text-ink">{card.reading}</p> : <p className="text-sm text-body">Nothing to build from this prompt.</p>}
        <p className="text-xs text-body tabular">
          Adds {c.instances_added} {c.instances_added === 1 ? "instance" : "instances"} and {c.mates_added} {c.mates_added === 1 ? "mate" : "mates"} · {c.instances_total} instances, {c.mates_total}{" "}
          mates in total
        </p>
      </div>

      {blocking.map((b) => (
        <Question key={b.id} blocker={b} disabled={busy || stale} onPick={onAnswer} />
      ))}

      {card.quantities.length ? (
        <Section title="Quantities" count={card.quantities.length}>
          <ul className="flex flex-col">
            {card.quantities.map((q) => (
              <li key={`${q.step_id}${q.field}`} className="flex min-w-0 items-baseline gap-2 border-b border-line py-1.5 text-sm last:border-b-0">
                <span className="min-w-0 flex-1 truncate text-body">{q.field}</span>
                <span className="shrink-0 font-semibold text-ink tabular">{q.normalised || q.as_typed}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {card.filters.length ? (
        <Section title="Filters" count={card.filters.length}>
          <ul className="flex flex-col gap-1.5">
            {card.filters.map((f, i) => (
              <li key={`${f.step_id}${i}`} className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="rounded-sm bg-action-soft px-1.5 py-px font-semibold text-action-text">
                  {f.path}
                  {f.filter.map((p) => ` ${p.attr} ${p.op} ${String(p.value)}${p.unit ? ` ${p.unit}` : ""}`).join("")}
                </span>
                <span className="text-body tabular">
                  {f.count} of {f.of}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {card.assumptions.length ? (
        <Section title="Assumptions" count={card.assumptions.length}>
          <ul className="flex flex-col gap-2">
            {card.assumptions.map((a, i) => (
              <li key={`${a.step_id}${a.field}${i}`} className="flex flex-col gap-0.5 text-sm">
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate text-body">{a.field}</span>
                  <span className="shrink-0 font-semibold text-ink">{typeof a.value === "string" ? a.value : JSON.stringify(a.value)}</span>
                </span>
                <span className="text-xs text-muted-text">{a.reason}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {card.mentions.length ? (
        <Section title="References" count={card.mentions.length}>
          <ul className="flex flex-col">
            {card.mentions.map((m) => (
              <li key={m.id} className="flex min-w-0 flex-col gap-0.5 border-b border-line py-2 last:border-b-0">
                <span className="flex min-w-0 items-center gap-2">
                  <Dot tone={MENTION_TONE[m.status]} />
                  <span className="min-w-0 truncate text-sm font-semibold text-ink">{m.text}</span>
                  <span className="ml-auto shrink-0 text-xs text-body">{m.ref?.source ?? m.status}</span>
                </span>
                {m.message ? (
                  <span className="text-xs text-body">{m.message}</span>
                ) : m.label && m.label !== m.text ? (
                  <span className="text-xs text-muted-text">{m.label}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {card.warnings.length || acks.length ? (
        <Section title="Warnings" count={card.warnings.length + acks.length}>
          <ul className="flex flex-col gap-1.5">
            {[...card.warnings, ...acks].map((w, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-body">
                <AlertTriangle size={14} strokeWidth={2} className="mt-px shrink-0 text-consent" aria-hidden />
                <span className="min-w-0">{w.message}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <div className="flex flex-col gap-0.5 text-caption text-muted-text">
        {cost ? (
          <p className="tabular">
            Planner · {cost.llm_calls ?? 0} {(cost.llm_calls ?? 0) === 1 ? "call" : "calls"} ·{" "}
            {cost.cost_unpriced_calls ? "cost not priced for this model" : `$${(cost.cost_usd ?? 0).toFixed(4)}`}
          </p>
        ) : (
          <p>No planner call for this reading</p>
        )}
        <p>{card.disclaimer}</p>
      </div>
    </div>
  );
}

/** A blocker as a question: each option is a button that carries its patch (Paper · 06). */
function Question({ blocker, disabled, onPick }: { blocker: ComposeBlocker; disabled: boolean; onPick: (patch: ComposePatch[]) => void }) {
  return (
    <section aria-label={`Question: ${blocker.code.replace(/_/g, " ")}`} className="flex flex-col gap-2.5 rounded-panel border border-consent bg-consent-soft p-3">
      <div className="flex items-center gap-2">
        <Badge tone="consent">Blocks apply</Badge>
        <span className="text-xs text-consent-text">{blocker.code.replace(/_/g, " ")}</span>
      </div>
      <p className="text-prose text-ink">{blocker.message}</p>
      {blocker.options.length ? (
        <div className="flex flex-wrap gap-2">
          {blocker.options.map((o, i) => (
            <Button key={i} size="sm" disabled={disabled} onClick={() => onPick(o.patch)} icon={<ArrowRight size={12} strokeWidth={2} aria-hidden />}>
              {o.label}
            </Button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-body">Change the prompt to resolve this, then interpret again.</p>
      )}
    </section>
  );
}
