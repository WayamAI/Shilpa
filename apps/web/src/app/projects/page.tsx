"use client";

import { ArrowRight, Box, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { PageBody, PageHeader } from "@/components/layout/page-header";
import { Button, TextInput } from "@/components/ui/controls";
import { InfoPopover } from "@/components/ui/info-popover";
import { EmptyState, KpiTile, Panel } from "@/components/ui/primitives";
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

  useEffect(() => {
    api.projects().then(setProjects).catch((e) => setError(errText(e)));
    api.usage().then(setUsage).catch(() => {});
  }, [me?.user_id]);

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
                className="h-9 sm:w-64"
              />
              <Button type="submit" variant="primary" disabled={creating}>
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
            <KpiTile label="Projects" value={projects ? String(projects.length) : "—"} hint={me?.tenant_name} />
            <KpiTile label="Parts" value={projects ? String(models) : "—"} hint="across all projects" />
            <KpiTile
              label="Jobs completed"
              value={jobs === null ? "—" : String(succeeded)}
              hint={jobs ? `${Math.round((succeeded / jobs) * 100)}% of ${jobs} jobs` : undefined}
              tone="success"
            />
            <KpiTile
              label="Planner tokens"
              value={tokens ? `${Math.round((tokens.input_tokens + tokens.output_tokens) / 1000)}k` : "—"}
              hint={tokens ? `${tokens.events} model calls` : "no model calls yet"}
            />
          </div>

          <Panel
            title={projects ? `All projects · ${projects.length}` : "All projects"}
            padded={false}
            action={
              <label className="flex h-8 items-center gap-2 rounded-full border border-line bg-surface-2 px-3 text-xs font-semibold text-muted-text focus-within:shadow-[var(--focus-ring)]">
                <Search size={13} strokeWidth={1.75} aria-hidden />
                <input
                  aria-label="Search projects"
                  placeholder="Search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="w-28 bg-transparent text-xs font-semibold text-ink outline-none placeholder:text-muted-text sm:w-44"
                />
              </label>
            }
          >
            {error ? <p className="p-4 text-xs text-fail-text">{error}</p> : null}
            {projects && shown.length === 0 ? (
              <EmptyState
                mark={<Box size={22} strokeWidth={1.5} className="text-muted" aria-hidden />}
                title={projects.length === 0 ? "No projects yet" : "No projects match"}
                detail={projects.length === 0 ? "Create a project to start your first part." : undefined}
              />
            ) : null}
            <ul className="min-h-0 overflow-y-auto">
              {shown.map((p) => (
                <li key={p.id} className="border-b border-line last:border-b-0">
                  <Link
                    href={`/projects/${p.id}`}
                    className="group flex items-center justify-between gap-4 px-4 py-3 outline-none transition-colors duration-fast hover:bg-surface focus-visible:bg-surface"
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted">
                        <Box size={16} strokeWidth={1.75} aria-hidden />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-ink">{p.name}</span>
                        <span className="block text-xs text-muted-text">
                          Created {new Date(p.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
                        </span>
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-4">
                      <span className="text-xs tabular text-muted-text">
                        {p.model_count} part{p.model_count === 1 ? "" : "s"}
                      </span>
                      <ArrowRight size={14} strokeWidth={1.75} aria-hidden className="text-muted transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </PageBody>
    </>
  );
}
