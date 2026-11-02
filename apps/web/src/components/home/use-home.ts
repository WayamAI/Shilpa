"use client";

import { useEffect, useState } from "react";

import { api, errText, type Job, type ModelSummary, type ProjectDetail } from "@/lib/api";
import { loadLibrary, type LibraryItem } from "@/lib/library";

const MAX_PROJECTS = 25;

export type HomeJob = Job & { projectName: string };
export type HomeModel = ModelSummary & { projectName: string; thumb: string | null; latestJob: HomeJob | null };

export type HomeData = {
  projects: number;
  /** Library item count (catalog parts plus your own models); null if the library failed to load. */
  libraryCount: number | null;
  jobsSucceeded: number | null;
  /** Assemblies and products, newest first. */
  complexParts: HomeModel[];
};

export type HomeState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: HomeData };

/** Everything Home shows, from existing endpoints only. A failed projects call is an error; the rest degrade. */
export function useHome(userId: string | undefined, attempt: number): HomeState {
  const [state, setState] = useState<HomeState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const projects = await api.projects();
        const [details, library, usage] = await Promise.all([
          Promise.all(projects.slice(0, MAX_PROJECTS).map((p) => api.project(p.id))),
          loadLibrary().catch((): LibraryItem[] | null => null),
          api.usage().catch(() => null),
        ]);
        if (cancelled) return;
        setState({ status: "ready", data: assemble(projects.length, details, library, usage?.jobs.succeeded ?? null) });
      } catch (e) {
        if (!cancelled) setState({ status: "error", message: errText(e) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, attempt]);

  return state;
}

function assemble(projectCount: number, details: ProjectDetail[], library: LibraryItem[] | null, jobsSucceeded: number | null): HomeData {
  const thumbs = new Map((library ?? []).map((i) => [i.id, i.thumb]));
  const jobs: HomeJob[] = details.flatMap((d) => d.recent_jobs.map((j) => ({ ...j, projectName: d.name })));
  const complexParts = details
    .flatMap((d) => d.models.filter((m) => m.kind === "assembly" || m.kind === "product").map((m) => ({ m, d })))
    .map(({ m, d }): HomeModel => {
      const latest = jobs.filter((j) => j.model_id === m.id).sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0] ?? null;
      return { ...m, projectName: d.name, thumb: thumbs.get(`model:${m.id}`) ?? null, latestJob: latest };
    })
    .sort((a, b) => Date.parse(b.latestJob?.updated_at ?? b.created_at) - Date.parse(a.latestJob?.updated_at ?? a.created_at));
  return { projects: projectCount, libraryCount: library?.length ?? null, jobsSucceeded, complexParts };
}

/** "4m ago", "1h ago", "Yesterday", "Oct 30". */
export function ago(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  const mins = Math.max(0, Math.round((now - t) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(t).toLocaleDateString("en", { month: "short", day: "numeric" });
}
