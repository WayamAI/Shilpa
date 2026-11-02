/* eslint-disable @next/next/no-img-element -- static webp thumbnails */
import Link from "next/link";

import { Badge, buttonClass, EmptyState, Skeleton, type BadgeTone } from "@/components/ui";

import { ago, type HomeModel } from "./use-home";

/** Latest job state for the part, the only "checks" signal the project payload carries. */
function status(m: HomeModel): { tone: BadgeTone; label: string } | null {
  const s = m.latestJob?.state;
  if (!s) return null;
  if (s === "succeeded") return { tone: "pass", label: "Built" };
  if (s === "failed") return { tone: "fail", label: "Last build failed" };
  if (s === "cancelled") return { tone: "neutral", label: "Cancelled" };
  return { tone: "complex", label: "Building" };
}

/**
 * Recent complex parts (Paper · 01 Home). Instances, steps and check counts
 * need the compose API, so those columns are left out rather than invented.
 */
export function RecentParts({ parts, loading }: { parts: HomeModel[]; loading: boolean }) {
  return (
    <section aria-labelledby="recent-h" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 id="recent-h" className="text-lg font-semibold text-ink">
          Recent complex parts
        </h2>
        <span className="text-sm text-body">assemblies and products in your projects</span>
      </div>
      <div className="overflow-hidden rounded-panel border border-line">
        {loading ? (
          <ul aria-label="Loading recent parts" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <li key={i} className="flex items-center gap-3 border-b border-line px-4 py-3 last:border-b-0">
                <Skeleton className="h-[30px] w-10 shrink-0" />
                <Skeleton className="h-3.5 w-1/3" />
              </li>
            ))}
          </ul>
        ) : parts.length === 0 ? (
          <EmptyState
            image="/imagery/sh-card-02-complex-part-128.webp"
            imageSize={48}
            title="No complex parts yet"
            detail="Build one from basic parts with @ prompts in the composer."
            actions={
              <Link href="/compose" className={buttonClass("secondary", "md")}>
                Open composer
              </Link>
            }
            className="min-h-0"
          />
        ) : (
          <ul aria-label="Recent complex parts">
            {parts.slice(0, 5).map((m) => {
              const st = status(m);
              return (
                <li key={m.id} className="border-b border-line last:border-b-0">
                  <Link
                    href={`/projects/${m.project_id}`}
                    className="flex min-h-[52px] items-center gap-3 px-4 py-2 transition-colors duration-fast hover:bg-surface"
                  >
                    <span className="flex h-[30px] w-10 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-surface-2">
                      <img
                        src={m.thumb ?? "/imagery/sh-card-02-complex-part-128.webp"}
                        alt=""
                        width={40}
                        height={30}
                        className={m.thumb?.startsWith("/thumbs") ? "size-full object-cover" : "size-[26px] object-contain"}
                      />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-sm font-semibold text-ink">{m.name}</span>
                      <span className="truncate text-xs text-body">{m.projectName}</span>
                    </span>
                    <span className="hidden w-20 shrink-0 text-right text-sm text-ink tabular sm:block">
                      {m.head_number != null ? `v${m.head_number}` : "No version"}
                    </span>
                    <span className="hidden w-36 shrink-0 sm:block">{st ? <Badge tone={st.tone}>{st.label}</Badge> : null}</span>
                    <span className="w-20 shrink-0 text-right text-sm text-body">{ago(m.latestJob?.updated_at ?? m.created_at)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
