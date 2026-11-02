/* eslint-disable @next/next/no-img-element -- static decorative webp, already sized */
import Link from "next/link";

import { Badge, buttonClass, EmptyState, Skeleton } from "@/components/ui";

import { ago, type HomeJob } from "./use-home";

const KIND_LABEL: Record<string, string> = { part: "Part", assembly: "Assembly", sheet_metal: "Sheet metal", product: "Product" };

/**
 * Needs you (Paper · 01 Home). Real items today: jobs that failed in the
 * last 7 days. Clarifications, import reviews and broken references have
 * no list endpoint or backend yet, so they appear as Planned cards.
 */
export function NeedsYou({ jobs, loading }: { jobs: HomeJob[]; loading: boolean }) {
  const count = jobs.length;
  return (
    <section aria-labelledby="needs-h" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <h2 id="needs-h" className="text-lg font-semibold text-ink">
          Needs you
        </h2>
        {!loading ? <span className="text-sm text-body">{count === 0 ? "nothing is waiting" : `${count} waiting`}</span> : null}
      </div>

      {loading ? (
        <div aria-busy="true" aria-label="Loading items that need you" className="grid gap-3 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-3 rounded-lg border border-line p-4">
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-[30px] w-24" />
            </div>
          ))}
        </div>
      ) : count === 0 ? (
        <div className="rounded-lg border border-line">
          <EmptyState
            image="/imagery/sh-emp-06-nothing-needs-you-128.webp"
            imageSize={64}
            title="Nothing needs you"
            detail="No builds have failed in the last 7 days."
            className="min-h-0"
          />
        </div>
      ) : (
        <ul aria-label="Items that need you" className="grid gap-3 md:grid-cols-3">
          {jobs.slice(0, 3).map((job) => (
            <li key={job.id} className="flex min-w-0 flex-col gap-3 rounded-lg border border-line p-4">
              <div className="flex items-center gap-2">
                <img src="/imagery/sh-card-25-solver-error-128.webp" alt="" width={26} height={26} className="size-[26px] shrink-0" />
                <Badge tone="fail">Build failed</Badge>
                <span className="ml-auto min-w-0 truncate text-xs text-muted-text">
                  {job.projectName} · {ago(job.updated_at)}
                </span>
              </div>
              <p className="text-md text-ink">
                <span className="font-semibold">{KIND_LABEL[job.kind] ?? "Job"} build failed.</span>{" "}
                {job.error?.message ?? "The job stopped without a message."}
              </p>
              <div className="mt-auto flex gap-2">
                <Link href={`/projects/${job.project_id}`} className={buttonClass("dark", "md")}>
                  Open project
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!loading ? <PlannedKinds /> : null}
    </section>
  );
}

const PLANNED = [
  { image: "sh-card-10-clarification", title: "Clarifications", detail: "Questions the planner needs answered before it builds." },
  { image: "sh-card-27-import-review", title: "Import reviews", detail: "Features found in an imported file, waiting for you to confirm." },
  { image: "sh-card-29-broken-ref", title: "Broken references", detail: "Steps that point at a hole or face that no longer exists." },
];

function PlannedKinds() {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-body">Also coming to this list</p>
      <ul aria-label="Planned items" className="grid gap-3 md:grid-cols-3">
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
