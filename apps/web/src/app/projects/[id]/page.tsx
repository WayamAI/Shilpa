"use client";

import { ArrowLeft, Plus } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";

import { Conversation, type ChatItem, type JobState } from "@/components/studio/conversation";
import { KindWorkspace } from "@/components/studio/kind-workspace";
import { Facts, Inspector, Viewport, WorkspaceLayout } from "@/components/studio/chrome";
import { ExportPanel, FeaturesPanel, ParamsPanel, ValidationPanel, VersionsPanel } from "@/components/studio/part-panels";
import { Badge, Button, buttonClass, EmptyState, Panel, Select } from "@/components/ui";
import { useSession } from "@/context/session-context";
import { api, errText, streamJob, type Job, type ModelKind, type ProjectDetail, type Spec, type Version } from "@/lib/api";

// three.js needs the browser: load the viewer on the client only.
const ModelViewer = dynamic(() => import("@/components/studio/model-viewer"), {
  ssr: false,
  loading: () => <div className="viewer-surface h-full min-h-[320px] w-full" />,
});

type Tab = "features" | "params" | "validation" | "versions" | "export";
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
      say({ kind: "system", text: errText(e), tone: "fail" });
    }
  }

  async function restore(id: string) {
    if (!version || !headId) return;
    try {
      trackJob(await api.restore(version.model_id, headId, id));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    }
  }

  async function exportFcstd() {
    if (!version) return;
    try {
      const r = await api.exportVersion(version.id, "FCSTD");
      if (r.job) trackJob(r.job);
      else setVersion(await api.version(version.id));
    } catch (e) {
      say({ kind: "system", text: errText(e), tone: "fail" });
    }
  }

  if (error) {
    return (
      <EmptyState
        image="/imagery/sh-emp-02-import-failed-128.webp"
        title="This project could not be opened"
        detail={error}
        actions={
          <Link href="/projects" className={buttonClass("secondary")}>
            All projects
          </Link>
        }
      />
    );
  }

  const thread = (
    <Panel
      padded={false}
      className="min-h-0 flex-1"
      title={modelId && isHead && isPart ? "Edit with Shilpa" : modelId ? "Shilpa" : "New part"}
    >
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
  );
  const size = version?.validation?.measurement?.bbox_size ?? null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Title row (Paper 03): name, status pills, actions. */}
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3 pb-2 lg:px-8 lg:pt-5 lg:pb-3">
        <Link
          href="/projects"
          aria-label="All projects"
          className="-ml-1 flex size-8 shrink-0 items-center justify-center rounded-md text-body transition-colors duration-fast hover:bg-surface-2 hover:text-ink"
        >
          <ArrowLeft size={16} strokeWidth={1.8} aria-hidden />
        </Link>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold text-ink lg:text-page">{model?.name ?? project?.name ?? "…"}</h1>
          <p className="truncate text-xs text-body">
            {model ? `${project?.name ?? ""}${!isPart ? ` · ${KIND_LABEL[kind]}` : ""} · v${version?.number ?? model.head_number}${version && !isHead ? " (older version)" : ""}` : "New part"}
          </p>
        </div>
        {version ? (
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <Badge tone={isPart ? "basic" : "complex"}>{isPart ? "Basic" : "Complex"}</Badge>
            <Badge tone={version.validation_passed ? "pass" : "fail"}>
              {isPart
                ? version.validation_passed
                  ? "geometry validated"
                  : "validation failed"
                : version.validation_passed
                  ? "all checks passed"
                  : "checks failed"}
            </Badge>
            <span className="hidden sm:inline-flex">
              <Badge tone="neutral">not reviewed for release</Badge>
            </span>
          </span>
        ) : null}
        <span className="hidden flex-1 lg:block" />
        <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
          {project && project.models.length > 0 ? (
            <Select
              aria-label="Part"
              value={modelId ?? ""}
              onChange={(e) => {
                if (!e.target.value) return newPart();
                setModelId(e.target.value);
                loadModel(e.target.value).catch((err) => setError(errText(err)));
              }}
              size="sm"
              className="min-w-0 flex-1 lg:max-w-[260px] lg:flex-none"
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
            <Button size="sm" onClick={newPart} disabled={!modelId} icon={<Plus size={13} strokeWidth={1.75} aria-hidden />}>
              New part
            </Button>
          ) : null}
          {activeJob && canWrite ? (
            <Button size="sm" variant="ghost" onClick={() => api.cancel(activeJob.id)}>
              Cancel job
            </Button>
          ) : null}
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto border-t border-line lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(360px,440px)] lg:overflow-hidden">
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
            footer={thread}
          />
        ) : (
          <WorkspaceLayout
            footer={thread}
            facts={
              version ? (
                <Facts
                  items={[
                    { label: "Size mm", value: size ? size.map((v) => +v.toFixed(0)).join("×") : "None" },
                    { label: "Checks", value: version.validation ? (version.validation.passed ? "Passed" : "Failed") : "Not run" },
                    { label: "Version", value: `v${version.number}` },
                  ]}
                />
              ) : undefined
            }
            viewport={
              <Viewport label="3D view" className="min-h-[300px] flex-1">
                <ModelViewer glbId={glb} size={size} />
              </Viewport>
            }
            inspector={
              version ? (
                <Inspector<Tab>
                  label="Part"
                  value={tab}
                  onChange={setTab}
                  className="flex-1"
                  tabs={[
                    { id: "features", label: "Features", count: version.features?.length ?? 0 },
                    { id: "params", label: "Parameters" },
                    { id: "validation", label: "Checks" },
                    { id: "versions", label: "Versions" },
                    { id: "export", label: "Exports" },
                  ]}
                >
                  {tab === "features" ? (
                    <FeaturesPanel version={version} />
                  ) : tab === "params" ? (
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
                </Inspector>
              ) : (
                <EmptyState
                  image="/imagery/sh-card-15-parts-list-128.webp"
                  imageSize={64}
                  title="No part selected"
                  detail="Features, parameters, checks, versions and files of a part appear here once you create one."
                />
              )
            }
          />
        )}
      </div>
    </div>
  );
}
