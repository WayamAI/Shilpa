"use client";

import { useState } from "react";

import { NeedsYouEmpty, NeedsYouError, NeedsYouSkeleton, PlannedKinds } from "@/components/home/needs-you";
import { NeedsYouCard } from "@/components/home/needs-you-card";
import { useNeedsYou } from "@/components/home/use-needs-you";
import { PageBody, PageHeader } from "@/components/layout/page-header";

/** Needs you: every question and failed build waiting on a person. */
export default function NeedsYouPage() {
  const [attempt, setAttempt] = useState(0);
  const state = useNeedsYou(attempt);
  const count = state.status === "ready" ? state.items.length : 0;
  const summary =
    state.status !== "ready"
      ? "Questions to answer and builds to look at."
      : count === 0
        ? "Nothing is waiting."
        : `${count} ${count === 1 ? "item is" : "items are"} waiting.`;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Needs you" description={summary} />
      <PageBody>
        <div className="mx-auto flex max-w-[1128px] flex-col gap-4" aria-live="polite">
          {state.status === "loading" ? (
            <NeedsYouSkeleton cols="md:grid-cols-2 xl:grid-cols-3" />
          ) : state.status === "error" ? (
            <NeedsYouError message={state.message} onRetry={() => setAttempt((n) => n + 1)} />
          ) : count === 0 ? (
            <NeedsYouEmpty />
          ) : (
            <ul aria-label="Items that need you" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {state.items.map((item) => (
                <NeedsYouCard key={item.id} item={item} />
              ))}
            </ul>
          )}
          {state.status !== "loading" ? <PlannedKinds /> : null}
        </div>
      </PageBody>
    </div>
  );
}
