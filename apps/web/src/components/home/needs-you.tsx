/* eslint-disable @next/next/no-img-element -- static decorative webp, already sized */
import Link from "next/link";

import { Badge, Button, EmptyState, Skeleton } from "@/components/ui";

import { NeedsYouCard } from "./needs-you-card";
import type { NeedsYouState } from "./use-needs-you";

const HOME_LIMIT = 3;

const PLANNED = [
  { image: "sh-card-27-import-review", title: "Import reviews", detail: "Features found in an imported file, waiting for you to confirm." },
  { image: "sh-card-29-broken-ref", title: "Broken references", detail: "Steps that point at a hole or face that no longer exists." },
];

/** Loading placeholder shared by Home and the /needs-you page. */
export function NeedsYouSkeleton({ cols = "md:grid-cols-3" }: { cols?: string }) {
  return (
    <div aria-busy="true" aria-label="Loading items that need you" className={`grid gap-3 ${cols}`}>
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex flex-col gap-3 rounded-lg border border-line p-4">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-[30px] w-24" />
        </div>
      ))}
    </div>
  );
}

export function NeedsYouEmpty() {
  return (
    <div className="rounded-lg border border-line">
      <EmptyState
        image="/imagery/sh-emp-06-nothing-needs-you-128.webp"
        imageSize={64}
        title="Nothing needs you"
        detail="No questions are waiting and no builds failed in the last 7 days."
        className="min-h-0"
      />
    </div>
  );
}

export function NeedsYouError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-line">
      <EmptyState
        image="/imagery/sh-emp-02-import-failed-128.webp"
        imageSize={48}
        title="Needs you didn't load"
        detail={message}
        actions={<Button onClick={onRetry}>Try again</Button>}
        className="min-h-0"
      />
    </div>
  );
}

/**
 * Needs you on Home (Paper · 01 Home): the newest few items from the inbox,
 * with a link to the full list. Import reviews and broken references have no
 * backend yet and stay Planned.
 */
export function NeedsYou({ state, onRetry }: { state: NeedsYouState; onRetry: () => void }) {
  const items = state.status === "ready" ? state.items : [];
  const count = items.length;
  return (
    <section aria-labelledby="needs-h" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <h2 id="needs-h" className="text-lg font-semibold text-ink">
          Needs you
        </h2>
        {state.status === "ready" ? <span className="text-sm text-body">{count === 0 ? "nothing is waiting" : `${count} waiting`}</span> : null}
        {count > HOME_LIMIT ? (
          <Link href="/needs-you" className="ml-auto text-sm font-semibold text-action-text hover:underline">
            See all {count}
          </Link>
        ) : null}
      </div>

      {state.status === "loading" ? (
        <NeedsYouSkeleton />
      ) : state.status === "error" ? (
        <NeedsYouError message={state.message} onRetry={onRetry} />
      ) : count === 0 ? (
        <NeedsYouEmpty />
      ) : (
        <ul aria-label="Items that need you" className="grid gap-3 md:grid-cols-3">
          {items.slice(0, HOME_LIMIT).map((item) => (
            <NeedsYouCard key={item.id} item={item} />
          ))}
        </ul>
      )}

      {state.status !== "loading" ? <PlannedKinds /> : null}
    </section>
  );
}

export function PlannedKinds() {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-body">Also coming to this list</p>
      <ul aria-label="Planned items" className="grid gap-3 md:grid-cols-2">
        {PLANNED.map((p) => (
          <li key={p.title} className="flex min-w-0 items-start gap-3 rounded-lg border border-dashed border-line-strong p-3">
            <img src={`/imagery/${p.image}-128.webp`} alt="" width={26} height={26} className="mt-0.5 size-[26px] shrink-0 opacity-70" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-ink">{p.title}</span>
                <Badge tone="consent">Planned</Badge>
              </div>
              <span className="text-xs text-body">{p.detail}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
