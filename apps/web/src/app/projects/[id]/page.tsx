"use client";

import { ArrowLeft, Plus } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";

import { Conversation, type ChatItem, type JobState } from "@/components/studio/conversation";
import { KindWorkspace } from "@/components/studio/kind-workspace";
import { ExportPanel, ParamsPanel, ValidationPanel, VersionsPanel } from "@/components/studio/part-panels";
import { Button, Tabs } from "@/components/ui/controls";
import { EmptyState, Panel, Select, StatusBadge } from "@/components/ui/primitives";
import { useSession } from "@/context/session-context";
import { api, errText, streamJob, type Job, type ModelKind, type ProjectDetail, type Spec, type Version } from "@/lib/api";

// three.js needs the browser: load the viewer on the client only.
const ModelViewer = dynamic(() => import("@/components/studio/model-viewer"), {
  ssr: false,
  loading: () => <div className="viewer-surface h-full min-h-[320px] w-full" />,
});

type Tab = "params" | "validation" | "versions" | "export";
const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
const KIND_LABEL: Record<ModelKind, string> = { part: "part", assembly: "assembly", sheet_metal: "sheet metal", product: "product" };

export default function WorkspacePage({ params }: PageProps<"/projects/[id]">) {
  const { id: projectId } = use(params);
  const { me, health } = useSession();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [modelId, setModelId] = useState<string | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [version, setVersion] = useState<Version | null>(null);
  const [tab, setTab] = useState<Tab>("params");
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [jobs, setJobs] = useState<JobState>({});
  const [error, setError] = useState<string | null>(null);
  const streams = useRef<(() => void)[]>([]);

  const loadProject = useCallback(async () => {
    const p = await api.project(projectId);
    setProject(p);
    return p;
  }, [projectId]);

  const loadModel = useCallback(async (mid: string, versionId?: string | null) => {
    const vs = await api.versions(mid);
    setVersions(vs);
    const target = versionId || vs[0]?.id;
    setVersion(target ? await api.version(target) : null);
  }, []);

  useEffect(() => {
    api
      .project(projectId)
      .then(async (p) => {
        setProject(p);
        if (!p.models[0]) return;
        setModelId(p.models[0].id);
        const vs = await api.versions(p.models[0].id);
        setVersions(vs);
        setVersion(vs[0] ? await api.version(vs[0].id) : null);
      })
      .catch((e) => setError(errText(e)));
    const active = streams.current;
    return () => active.forEach((stop) => stop());
  }, [projectId, me?.user_id]);

  const say = useCallback((item: ChatItem) => setChat((c) => [...c, item]), []);

  const trackJob = useCallback(
    (job: Job) => {
      setJobs((j) => ({ ...j, [job.id]: { job, events: [] } }));
      say({ kind: "job", jobId: job.id });
      const stop = streamJob(
        job.id,
        (ev) => setJobs((j) => ({ ...j, [job.id]: { job: j[job.id]?.job ?? job, events: [...(j[job.id]?.events ?? []), ev] } })),
        async () => {
          const final = await api.job(job.id);
          setJobs((j) => ({ ...j, [job.id]: { ...j[job.id], job: final } }));
          if (final.state === "succeeded" && final.model_id) {
            await loadProject();
            setModelId(final.model_id);
            await loadModel(final.model_id, final.result_version_id);
            if (final.kind === "export") setTab("export");
          }
        },
      );
      streams.current.push(stop);
    },
    [loadModel, loadProject, say],
  );

  const onSpecUpdate = useCallback((spec: Spec) => setChat((c) => c.map((x) => (x.kind === "spec" && x.spec.id === spec.id ? { kind: "spec", spec } : x))), []);

  const headId = versions[0]?.id ?? null;
  const isHead = !!version && version.id === headId;
  const glb = version?.artifacts.find((a) => a.format === "GLB")?.id ?? null;
  const activeJob = Object.values(jobs).map((j) => j.job).find((j) => !TERMINAL.has(j.state)) ?? null;
  const canWrite = !!me?.can_write;
  const model = project?.models.find((m) => m.id === modelId);
  const kind: ModelKind = version?.kind ?? model?.kind ?? "part";
  const isPart = kind === "part";

  function newPart() {
    setModelId(null);
    setVersion(null);
    setVersions([]);
    setTab("params");
  }

  async function applyParams(changes: Record<string, number>) {
    if (!version) return;
    say({ kind: "user", text: "Edit: " + Object.entries(changes).map(([k, v]) => `${k.replace(/_/g, " ")} = ${v}`).join(", ") });
    try {
      trackJob(await api.editParams(version.model_id, version.id, changes));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "error" });
    }
  }

  async function restore(id: string) {
    if (!version || !headId) return;
    try {
      trackJob(await api.restore(version.model_id, headId, id));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "error" });
    }
  }

  async function exportFcstd() {
    if (!version) return;
    try {
      const r = await api.exportVersion(version.id, "FCSTD");
      if (r.job) trackJob(r.job);
      else setVersion(await api.version(version.id));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "error" });
    }
  }

  if (error) {
    return <EmptyState title="This project could not be opened" detail={error} />;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Workspace header: compact, so the viewer keeps the height. */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/projects"
            aria-label="All projects"
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted outline-none transition-colors duration-[180ms] hover:bg-surface-2 hover:text-body focus-visible:ring-2 focus-visible:ring-line-strong"
          >
            <ArrowLeft size={15} strokeWidth={1.75} aria-hidden />
          </Link>
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-ink">{project?.name ?? "…"}</h2>
            <p className="truncate text-xs text-muted-text">
              {model ? (
                <>
                  {model.name}
                  {!isPart ? ` · ${KIND_LABEL[kind]}` : ""} · v{version?.number ?? model.head_number}
                  {version && !isHead ? " (older version)" : ""}
                </>
              ) : (
                "New part"
              )}
            </p>
          </div>
          {version ? (
            <span className="hidden shrink-0 items-center gap-2 sm:flex">
              <StatusBadge tone={version.validation_passed ? "success" : "error"}>
                {isPart
                  ? version.validation_passed
                    ? "geometry validated"
                    : "validation failed"
                  : version.validation_passed
                    ? "all checks passed"
                    : "checks failed"}
              </StatusBadge>
              <StatusBadge tone="neutral">not reviewed for release</StatusBadge>
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {project && project.models.length > 0 ? (
            <Select
              aria-label="Part"
              value={modelId ?? ""}
              onChange={(e) => {
                if (!e.target.value) return newPart();
                setModelId(e.target.value);
                loadModel(e.target.value).catch((err) => setError(errText(err)));
              }}
              className="h-8 max-w-[260px] rounded-full border border-line bg-surface-2 text-xs font-semibold text-body outline-none focus-visible:ring-2 focus-visible:ring-line-strong"
            >
              {!modelId ? <option value="">New part</option> : null}
              {project.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                  {m.kind && m.kind !== "part" ? ` · ${KIND_LABEL[m.kind]}` : ""} · v{m.head_number}
                </option>
              ))}
            </Select>
          ) : null}
          {canWrite ? (
            <Button size="sm" onClick={newPart} disabled={!modelId}>
              <Plus size={13} strokeWidth={1.75} aria-hidden />
              New part
            </Button>
          ) : null}
          {activeJob && canWrite ? (
            <Button size="sm" variant="tertiary" onClick={() => api.cancel(activeJob.id)}>
              Cancel job
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-y-auto p-3 lg:grid-cols-[320px_minmax(0,1fr)] lg:overflow-hidden xl:grid-cols-[340px_minmax(0,1fr)_380px]">
        {version && !isPart ? (
          <KindWorkspace
            key={version.id}
            version={version}
            versions={versions}
            canWrite={canWrite}
            busy={!!activeJob}
            freecadAvailable={!!health?.freecad_available}
            onOpenVersion={async (vid) => setVersion(await api.version(vid))}
            onRestore={restore}
            onExportFcstd={exportFcstd}
          />
        ) : (
          <>
          <Panel
            padded={false}
            className="min-h-[420px] lg:min-h-0"
            title="Part"
            action={version ? <span className="text-xs tabular text-muted-text">{version.recipe_hash.slice(0, 8)}</span> : undefined}
          >
            {version ? (
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="shrink-0 border-b border-line px-4 py-2.5">
                  <Tabs<Tab>
                    label="Part details"
                    value={tab}
                    onChange={setTab}
                    tabs={[
                      { id: "params", label: "Parameters" },
                      { id: "validation", label: "Checks" },
                      { id: "versions", label: "Versions" },
                      { id: "export", label: "Export" },
                    ]}
                  />
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  {tab === "params" ? (
                    <ParamsPanel key={version.id} version={version} editable={canWrite && isHead && !activeJob} isHead={isHead} onApply={applyParams} />
                  ) : tab === "validation" ? (
                    <ValidationPanel version={version} />
                  ) : tab === "versions" ? (
                    <VersionsPanel
                      versions={versions}
                      current={version.id}
                      canRestore={canWrite && !activeJob}
                      onOpen={async (vid) => setVersion(await api.version(vid))}
                      onRestore={restore}
                    />
                  ) : (
                    <ExportPanel version={version} canExport={canWrite && !activeJob} onExportFcstd={exportFcstd} />
                  )}
                </div>
              </div>
            ) : (
              <EmptyState title="No part selected" detail="The parameters, checks, versions and files of a part appear here." />
            )}
          </Panel>

          <Panel padded={false} className="min-h-[420px] lg:min-h-0" title="Model" action={version ? <span className="text-xs text-muted-text">drag to orbit · scroll to zoom</span> : undefined}>
            <ModelViewer glbId={glb} size={version?.validation?.measurement?.bbox_size ?? null} />
          </Panel>
          </>
        )}

        <Panel padded={false} className="min-h-[480px] lg:col-span-2 lg:min-h-[420px] xl:col-span-1 xl:min-h-0" title={modelId && isHead && isPart ? "Edit with Shilpa" : modelId ? "Shilpa" : "New part"}>
          <Conversation
            projectId={projectId}
            chat={chat}
            jobs={jobs}
            editTarget={modelId && version && isHead && isPart ? version : null}
            busy={!!activeJob}
            say={say}
            trackJob={trackJob}
            onSpecUpdate={onSpecUpdate}
          />
        </Panel>
      </div>
    </div>
  );
}
