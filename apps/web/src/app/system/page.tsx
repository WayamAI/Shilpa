"use client";

import { useEffect, useState } from "react";

import { PageBody, PageHeader } from "@/components/layout/page-header";
import { Badge, Dot, KeyValue, Metric, Panel, SplitRow } from "@/components/ui";
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
  const plannerOff = health?.planner === "disabled";

  return (
    <>
      <PageHeader title="System" description="Services, CAD engines and usage for your organization. Everything here runs locally except the Azure OpenAI planner." />
      <PageBody>
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <Metric
              label="Planner"
              value={health ? (health.llm_configured ? "Online" : plannerOff ? "Disabled" : "Off") : "…"}
              hint={plannerOff ? "SHILPA_LLM=off · no model calls" : (health?.llm_deployment ?? "Azure OpenAI not configured")}
            />
            <Metric label="Model calls" value={llm ? String(llm.events) : "0"} hint={llm ? `${(llm.input_tokens / 1000).toFixed(1)}k in · ${(llm.output_tokens / 1000).toFixed(1)}k out` : undefined} />
            <Metric label="CAD compute" value={cpu ? `${Math.round(cpu.cpu_seconds)}s` : "0s"} hint={cpu ? `${cpu.events} geometry runs` : undefined} />
            <Metric
              label="Job success"
              value={total ? `${Math.round(((jobs.succeeded ?? 0) / total) * 100)}%` : "…"}
              hint={total ? `${jobs.succeeded ?? 0} of ${total} jobs` : "no jobs yet"}
            />
          </div>

          <SplitRow>
            <Panel title="Services">
              <ul className="flex flex-col">
                {[
                  { name: "API and job queue", detail: "FastAPI · SQLite · DB-backed queue", ok: !!health },
                  {
                    name: "Planner",
                    image: "/imagery/sh-card-22-planner-128.webp",
                    detail: plannerOff ? "Disabled by SHILPA_LLM=off" : health?.llm_deployment ? `Azure OpenAI · ${health.llm_deployment}` : "Azure OpenAI",
                    ok: !!health?.llm_configured,
                  },
                  { name: "Assemblies and sheet metal", detail: "Placement, interference, sweep, flat pattern · no AI needed", ok: !!health },
                  { name: "Product templates", detail: health?.products_available ? "shilpa.product installed" : "Not installed yet", ok: !!health?.products_available },
                  { name: "build123d engine", image: "/imagery/sh-card-21-kernel-128.webp", detail: `Open CASCADE · ${ops.length} operations`, ok: ops.length > 0 },
                  { name: "FreeCAD engine", image: "/imagery/sh-card-23-freecad-adapter-128.webp", detail: "Native FCStd export", ok: !!health?.freecad_available },
                  { name: "Identity", detail: health?.auth_mode === "dev" ? "Local dev identities (Entra ID in Azure)" : "Entra ID", ok: !!me },
                ].map((s) => (
                  <li key={s.name} className="flex items-center justify-between gap-3 border-b border-line py-2 last:border-b-0">
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="flex size-8 shrink-0 items-center justify-center">
                        {"image" in s && s.image ? (
                          // eslint-disable-next-line @next/next/no-img-element -- static decorative webp
                          <img src={s.image} alt="" width={32} height={32} className="size-8" />
                        ) : (
                          <Dot tone={s.ok ? "pass" : "consent"} />
                        )}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-sm text-ink">{s.name}</span>
                        <span className="block truncate text-xs text-muted-text">{s.detail}</span>
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      {"image" in s && s.image ? <Dot tone={s.ok ? "pass" : "consent"} /> : null}
                      <Badge tone={s.ok ? "pass" : "consent"}>{s.ok ? "available" : "unavailable"}</Badge>
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
            <Panel title="Jobs by outcome">
              {total ? (
                <KeyValue rows={Object.entries(jobs).sort((a, b) => b[1] - a[1]).map(([state, n]) => ({ label: state, value: n }))} />
              ) : (
                <p className="text-sm text-body">No jobs yet.</p>
              )}
              <h3 className="mt-5 mb-2 text-md">Supported operations</h3>
              <div className="flex flex-wrap gap-1.5">
                {ops.map((op) => (
                  <Badge key={op} tone="neutral">
                    {op.replace(/_/g, " ")}
                  </Badge>
                ))}
              </div>
            </Panel>
          </SplitRow>
        </div>
      </PageBody>
    </>
  );
}
