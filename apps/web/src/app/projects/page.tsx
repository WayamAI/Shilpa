"use client";

import { ChevronRight, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { PageBody, PageHeader } from "@/components/layout/page-header";
import { Badge, Button, EmptyState, InfoPopover, Metric, Skeleton, TextInput } from "@/components/ui";
import { useSession } from "@/context/session-context";
import { api, errText, type Project, type Usage } from "@/lib/api";

export default function ProjectsPage() {
  const router = useRouter();
  const { me } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    api
      .projects()
      .then((list) => (setProjects(list), setError(null)))
      .catch((e) => setError(errText(e)));
    api.usage().then(setUsage).catch(() => {});
  }, [me?.user_id, attempt]);

  const shown = useMemo(
    () => (projects ?? []).filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase())),
    [projects, query],
  );

  async function create(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      const p = await api.createProject(name.trim() || "Untitled project");
      router.push(`/projects/${p.id}`);
    } catch (e) {
      setError(errText(e));
      setCreating(false);
    }
  }

  const models = (projects ?? []).reduce((n, p) => n + p.model_count, 0);
  const jobs = usage ? Object.values(usage.jobs).reduce((a, b) => a + b, 0) : null;
  const succeeded = usage?.jobs.succeeded ?? 0;
  const tokens = usage?.by_kind.llm;

  return (
    <>
      <PageHeader
        title="Projects"
        description="Each project holds parts, their immutable versions and the requests and drawings they came from."
        info={
          <InfoPopover label="About projects">
            <p className="text-xs text-body">
              Open a project to describe a part, upload a drawing or start from a reference part. Every change creates a new version; older
              versions stay available and can be restored.
            </p>
          </InfoPopover>
        }
        actions={
          me?.can_write ? (
            <form onSubmit={create} className="flex w-full items-center gap-2 sm:w-auto">
              <TextInput
                aria-label="New project name"
                placeholder="New project name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="min-w-0 flex-1 sm:w-64 sm:flex-none"
              />
              <Button type="submit" variant="primary" loading={creating} disabled={creating}>
                <Plus size={14} strokeWidth={1.75} aria-hidden />
                Create
              </Button>
            </form>
          ) : null
        }
      />
      <PageBody>
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <Metric label="Projects" image="/imagery/sh-card-26-project-128.webp" value={projects ? String(projects.length) : "…"} hint={me?.tenant_name} />
            <Metric label="Parts" image="/imagery/sh-card-15-parts-list-128.webp" value={projects ? String(models) : "…"} hint="across all projects" />
            <Metric
              label="Jobs completed"
              image="/imagery/sh-card-11-pass-128.webp"
              value={jobs === null ? ", " : String(succeeded)}
              hint={jobs ? `${Math.round((succeeded / jobs) * 100)}% of ${jobs} jobs` : undefined}
            />
            <Metric
              label="Planner tokens"
              image="/imagery/sh-card-22-planner-128.webp"
              value={tokens ? `${Math.round((tokens.input_tokens + tokens.output_tokens) / 1000)}k` : "…"}
              hint={tokens ? `${tokens.events} model calls` : "no model calls yet"}
            />
          </div>

          <section aria-label="All projects" className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-bg">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
              <h2 className="text-md">
                All projects
                {projects ? <span className="ml-1.5 font-normal text-body tabular">{projects.length}</span> : null}
              </h2>
              <label className="flex h-8 w-full items-center gap-2 rounded-md border border-line px-2.5 transition-colors duration-fast focus-within:border-action hover:border-line-strong sm:w-64">
                <Search size={14} strokeWidth={2} className="shrink-0 text-muted" aria-hidden />
                <input
                  type="search"
                  aria-label="Search projects"
                  placeholder="Search projects"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-muted-text focus-visible:shadow-none"
                />
              </label>
            </header>
            {error ? (
              <EmptyState
                image="/imagery/sh-emp-02-import-failed-128.webp"
                imageSize={48}
                title="The projects didn't load"
                detail={error}
                actions={<Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button>}
              />
            ) : !projects ? (
              <ul aria-label="Loading projects" aria-busy="true">
                {[0, 1, 2].map((i) => (
                  <li key={i} className="flex items-center gap-3 border-b border-line px-4 py-3 last:border-b-0">
                    <Skeleton className="size-10 shrink-0" />
                    <span className="flex flex-1 flex-col gap-1.5">
                      <Skeleton className="h-3 w-1/3" />
                      <Skeleton className="h-2.5 w-1/4" />
                    </span>
                  </li>
                ))}
              </ul>
            ) : shown.length === 0 ? (
              <EmptyState
                image="/imagery/sh-card-26-project-128.webp"
                imageSize={64}
                title={projects.length === 0 ? "No projects yet" : "No projects match"}
                detail={projects.length === 0 ? "Create a project to start your first part." : "Try a shorter search."}
              />
            ) : (
              <ul>
                {shown.map((p) => (
                  <li key={p.id} className="border-b border-line last:border-b-0">
                    <Link
                      href={`/projects/${p.id}`}
                      className="group flex items-center gap-3 px-4 py-3 outline-none transition-colors duration-fast hover:bg-surface focus-visible:bg-surface"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element -- static decorative webp */}
                      <img src="/imagery/sh-card-26-project-128.webp" alt="" width={40} height={40} className="size-10 shrink-0" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-md font-semibold text-ink">{p.name}</span>
                        <span className="block truncate text-xs text-muted-text">
                          Created {new Date(p.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
                        </span>
                      </span>
                      <Badge tone="neutral">
                        {p.model_count} part{p.model_count === 1 ? "" : "s"}
                      </Badge>
                      <ChevronRight size={16} strokeWidth={1.8} aria-hidden className="shrink-0 text-muted transition-transform duration-fast group-hover:translate-x-0.5 motion-reduce:transition-none" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </PageBody>
    </>
  );
}
