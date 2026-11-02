"use client";

import { MentionChip, type MentionKind } from "@/components/compose/mention-chip";
import { Badge, type BadgeTone } from "@/components/ui";
import type { CompositionStepRow, StepStatus } from "@/lib/api";
import type { LibraryItem } from "@/lib/library";

const STATUS: Record<StepStatus, { tone: BadgeTone; label: string }> = {
  applied: { tone: "pass", label: "Applied" },
  pending: { tone: "consent", label: "Building" },
  failed: { tone: "fail", label: "Failed" },
};

/** Colour of a mention in a step's prompt: native parts take their library kind; catalog parts are basic. */
function kindsOf(step: CompositionStepRow, library: LibraryItem[] | null): Map<string, MentionKind> {
  const out = new Map<string, MentionKind>();
  for (const s of step.ir.steps) {
    for (const key of ["source", "target"]) {
      const r = s[key] as { text?: string; source?: string; item?: string } | undefined;
      if (!r?.text) continue;
      const item = r.item && r.source === "native" ? library?.find((l) => l.id === `model:${r.item}`) : null;
      out.set(r.text.split(/[.[#]/)[0], item?.kind === "complex" ? "complex" : "basic");
    }
  }
  return out;
}

function PromptText({ text, kinds }: { text: string; kinds: Map<string, MentionKind> }) {
  const bits = text.split(/(@[A-Za-z0-9_\-.[\]*#]+)/);
  return (
    <p className="text-sm leading-6 text-ink">
      {bits.map((b, i) =>
        b.startsWith("@") ? (
          <MentionChip key={i} kind={kinds.get(b.split(/[.[#]/)[0]) ?? "basic"} className="mx-px py-0 text-sm">
            {b}
          </MentionChip>
        ) : (
          <span key={i}>{b}</span>
        ),
      )}
    </p>
  );
}

/** The left column: the append-only history, one row per applied (or running, or failed) prompt. */
export function StepsList({ steps, library }: { steps: CompositionStepRow[]; library: LibraryItem[] | null }) {
  return (
    <ol className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto px-4 pb-4 wrap-anywhere">
      {steps.map((s) => {
        const st = STATUS[s.status];
        return (
          <li key={s.id} className="flex gap-2.5 border-b border-line py-3 last:border-b-0">
            <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-caption font-semibold text-body tabular">
              {s.number}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              {s.prompt ? <PromptText text={s.prompt} kinds={kindsOf(s, library)} /> : null}
              {s.reading ? <p className="text-xs text-body">{s.reading}</p> : null}
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={st.tone}>{st.label}</Badge>
                {s.counts ? (
                  <span className="text-xs text-muted-text tabular">
                    +{s.counts.instances_added} instances, +{s.counts.mates_added} mates
                  </span>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
