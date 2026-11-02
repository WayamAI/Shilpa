"use client";

/* eslint-disable @next/next/no-img-element -- static decorative webp, already sized */
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageBody } from "@/components/layout/page-header";
import { Button, buttonClass, EmptyState } from "@/components/ui";
import { useSession } from "@/context/session-context";

import { NeedsYou } from "./needs-you";
import { RecentParts } from "./recent-parts";
import { useHome } from "./use-home";

function firstName(name: string | undefined, email: string | undefined): string | null {
  const n = name?.trim().split(/\s+/)[0] || email?.split("@")[0];
  return n || null;
}

/** Home (Paper · 01 Home, 03 Mobile): greeting and composer entry, what needs you, recent complex parts. */
export function HomeScreen() {
  const { me } = useSession();
  const [attempt, setAttempt] = useState(0);
  const home = useHome(me?.user_id, attempt);
  const loading = home.status === "loading";
  const who = firstName(me?.name, me?.email);

  return (
    <PageBody>
      <div className="mx-auto flex max-w-[1128px] flex-col gap-6 pt-3 lg:pt-5">
        <section aria-label="Start" className="flex max-w-[880px] flex-col gap-3.5">
          <div className="flex items-center gap-3">
            <img src="/imagery/sh-card-28-greeting-128.webp" alt="" width={46} height={46} className="size-[46px] shrink-0" />
            <h1 className="min-w-0 text-xl font-semibold tracking-tight text-ink lg:text-2xl">
              {who ? `What are we building today, ${who}?` : "What are we building today?"}
            </h1>
          </div>
          <div className="flex flex-col gap-3 rounded-lg border border-line-strong bg-bg px-4 py-3.5">
            <p className="text-brand text-body">
              Describe a part and point at parts with <span className="font-semibold text-action-text">@</span>. For example: put an M6 nut
              in every hole of a plate.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-body">
                {home.status === "ready"
                  ? [
                      `${home.data.projects} ${home.data.projects === 1 ? "project" : "projects"}`,
                      home.data.libraryCount != null ? `${home.data.libraryCount} parts in the library` : null,
                      home.data.jobsSucceeded != null ? `${home.data.jobsSucceeded} builds completed` : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : " "}
              </span>
              <Link href="/compose" className={buttonClass("primary", "md", "ml-auto")}>
                Open composer
                <ArrowRight size={14} strokeWidth={2.2} aria-hidden />
              </Link>
            </div>
          </div>
        </section>

        {home.status === "error" ? (
          <div className="rounded-panel border border-line">
            <EmptyState
              image="/imagery/sh-emp-02-import-failed-128.webp"
              imageSize={48}
              title="Home didn't load"
              detail={home.message}
              actions={<Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button>}
            />
          </div>
        ) : (
          <>
            <NeedsYou jobs={home.status === "ready" ? home.data.failedJobs : []} loading={loading} />
            <RecentParts parts={home.status === "ready" ? home.data.complexParts : []} loading={loading} />
          </>
        )}
      </div>
    </PageBody>
  );
}
