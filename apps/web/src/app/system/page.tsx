"use client";

import { useEffect, useState } from "react";

import { PageBody, PageHeader } from "@/components/layout/page-header";
import { KeyValue } from "@/components/ui/controls";
import { KpiTile, Panel, SplitRow, StatusBadge, StatusDot } from "@/components/ui/primitives";
import { useSession } from "@/context/session-context";
import { api, type Usage } from "@/lib/api";

/** Operations view (blueprint section 14): services, engines and usage for this tenant. */
export default function SystemPage() {
  const { health, me } = useSession();
  const [usage, setUsage] = useState<Usage | null>(null);

  useEffect(() => {
    api.usage().then(setUsage).catch(() => {});
  }, []);

  const llm = usage?.by_kind.llm;
  const cpu = usage?.by_kind.cad_cpu;
  const jobs = usage?.jobs ?? {};
  const total = Object.values(jobs).reduce((a, b) => a + b, 0);
  const ops = health?.adapters.build123d ?? [];

  return (
    <>
      <PageHeader title="System" description="Services, CAD engines and usage for your organization. Everything here runs locally except the Azure OpenAI planner." />
      <PageBody>
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <KpiTile
              label="Planner"
              value={health ? (health.llm_configured ? "Online" : "Off") : "—"}
              hint={health?.llm_deployment ?? "Azure OpenAI not configured"}
              tone={health?.llm_configured ? "success" : "warning"}
            />
            <KpiTile label="Model calls" value={llm ? String(llm.events) : "0"} hint={llm ? `${(llm.input_tokens / 1000).toFixed(1)}k in · ${(llm.output_tokens / 1000).toFixed(1)}k out` : undefined} />
            <KpiTile label="CAD compute" value={cpu ? `${Math.round(cpu.cpu_seconds)}s` : "0s"} hint={cpu ? `${cpu.events} geometry runs` : undefined} />
            <KpiTile
              label="Job success"
              value={total ? `${Math.round(((jobs.succeeded ?? 0) / total) * 100)}%` : "—"}
              hint={total ? `${jobs.succeeded ?? 0} of ${total} jobs` : "no jobs yet"}
              tone="success"
            />
          </div>

          <SplitRow ratio="1/1.4">
            <Panel title="Services">
              <ul className="flex flex-col">
                {[
                  { name: "API and job queue", detail: "FastAPI · SQLite · DB-backed queue", ok: !!health },
                  { name: "Planner", detail: health?.llm_deployment ? `Azure OpenAI · ${health.llm_deployment}` : "Azure OpenAI", ok: !!health?.llm_configured },
                  { name: "build123d engine", detail: `Open CASCADE · ${ops.length} operations`, ok: ops.length > 0 },
                  { name: "FreeCAD engine", detail: "Native FCStd export", ok: !!health?.freecad_available },
                  { name: "Identity", detail: health?.auth_mode === "dev" ? "Local dev identities (Entra ID in Azure)" : "Entra ID", ok: !!me },
                ].map((s) => (
                  <li key={s.name} className="flex items-center justify-between gap-3 border-b border-muted py-2.5 last:border-b-0">
                    <span className="flex min-w-0 items-center gap-2.5">
                      <StatusDot tone={s.ok ? "success" : "warning"} />
                      <span className="min-w-0">
                        <span className="block text-body-md text-primary">{s.name}</span>
                        <span className="block truncate text-body-sm text-quaternary">{s.detail}</span>
                      </span>
                    </span>
                    <StatusBadge tone={s.ok ? "success" : "warning"}>{s.ok ? "available" : "unavailable"}</StatusBadge>
                  </li>
                ))}
              </ul>
            </Panel>
            <Panel title="Jobs by outcome">
              {total ? (
                <KeyValue rows={Object.entries(jobs).sort((a, b) => b[1] - a[1]).map(([state, n]) => ({ label: state, value: n }))} />
              ) : (
                <p className="text-body-sm text-quaternary">No jobs yet.</p>
              )}
              <h3 className="mt-5 mb-2 text-caption tracking-[0.08em] text-quaternary uppercase">Supported operations · build123d</h3>
              <div className="flex flex-wrap gap-1.5">
                {ops.map((op) => (
                  <span key={op} className="rounded-full border border-muted bg-action px-2.5 py-0.5 text-caption text-tertiary">
                    {op.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </Panel>
          </SplitRow>
        </div>
      </PageBody>
    </>
  );
}
