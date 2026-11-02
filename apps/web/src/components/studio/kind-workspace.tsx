"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { Tabs } from "@/components/ui/controls";
import { EmptyState, Panel } from "@/components/ui/primitives";
import type { Version } from "@/lib/api";

import { BomTable, ChecksPanel, JointsPanel, KindExportPanel, PartsTree } from "./assembly-panels";
import type { Highlight } from "./assembly-viewer";
import { VersionsPanel } from "./part-panels";
import { RendersPanel, RouterPanel } from "./product-panels";
import { BendTable, FlatPatternView, SheetChecks } from "./sheet-metal-panels";

// three.js needs the browser: load the viewer on the client only.
const AssemblyViewer = dynamic(() => import("@/components/studio/assembly-viewer"), {
  ssr: false,
  loading: () => <div className="viewer-surface h-full min-h-[320px] w-full" />,
});

type AsmTab = "parts" | "bom" | "checks" | "joints" | "router" | "files";
type SheetTab = "bends" | "checks" | "versions" | "export";

type Props = {
  version: Version;
  versions: Version[];
  canWrite: boolean;
  busy: boolean;
  freecadAvailable: boolean;
  onOpenVersion: (id: string) => void;
  onRestore: (id: string) => void;
  onExportFcstd: () => void;
};

/**
 * Left and middle columns of the workspace for assemblies, products and sheet metal.
 * Selection, hover, check highlight and joint poses live here so the tree, the BOM,
 * the checks list, the joint sliders and the 3D view stay in sync. The parent keys
 * this component by version id, so a new version starts from its assembled pose.
 */
export function KindWorkspace(props: Props) {
  return props.version.kind === "sheet_metal" ? <SheetMetalWorkspace {...props} /> : <AssemblyWorkspace {...props} />;
}

function AssemblyWorkspace({ version, versions, canWrite, busy, freecadAvailable, onOpenVersion, onRestore, onExportFcstd }: Props) {
  const viewer = version.viewer;
  const [tab, setTab] = useState<AsmTab>(viewer && !viewer.passed ? "checks" : "parts");
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Highlight>(null);
  const [joints, setJoints] = useState<Record<string, number>>({});
  const meshes = version.artifacts.find((a) => a.format === "MESHES")?.id ?? null;
  const isHead = versions[0]?.id === version.id;
  const product = version.kind === "product" ? (viewer?.product ?? null) : null;
  // Products swap the Joints tab for the router log; their joints sit under the parts tree.
  const tabs: { id: AsmTab; label: string }[] = [
    { id: "parts", label: "Parts" },
    { id: "bom", label: "BOM" },
    { id: "checks", label: "Checks" },
    product ? { id: "router", label: "Router" } : { id: "joints", label: "Joints" },
    { id: "files", label: "Files" },
  ];
  const jointsPanel = viewer ? (
    <JointsPanel viewer={viewer} values={joints} onChange={(name, v) => setJoints((j) => ({ ...j, [name]: v }))} />
  ) : null;

  const select = (id: string | null) => {
    setSelected(id);
    if (id) setHighlight(null);
  };

  return (
    <>
      <Panel
        padded={false}
        className="min-h-[420px] lg:min-h-0"
        title={version.kind === "product" ? "Product" : "Assembly"}
        action={<span className="text-xs tabular text-muted-text">{version.recipe_hash.slice(0, 8)}</span>}
      >
        {viewer ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="shrink-0 border-b border-line px-4 py-2.5">
              <Tabs<AsmTab>
                label="Assembly details"
                value={tab}
                onChange={setTab}
                tabs={tabs}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {tab === "parts" ? (
                <>
                  <PartsTree viewer={viewer} selected={selected} hovered={hovered} onHover={setHovered} onSelect={select} />
                  {product && viewer.joints.length ? (
                    <>
                      <h3 className="mt-5 mb-2 text-xs tracking-[0.08em] text-muted-text uppercase">Joints</h3>
                      {jointsPanel}
                    </>
                  ) : null}
                </>
              ) : tab === "router" && product ? (
                <RouterPanel product={product} />
              ) : tab === "bom" ? (
                <BomTable viewer={viewer} onSelect={select} />
              ) : tab === "checks" ? (
                <ChecksPanel viewer={viewer} highlight={highlight} onHighlight={setHighlight} />
              ) : tab === "joints" ? (
                jointsPanel
              ) : (
                <>
                  {product ? (
                    <div className="mb-6">
                      <RendersPanel version={version} product={product} />
                    </div>
                  ) : null}
                  <KindExportPanel version={version} canExport={canWrite && !busy} freecadAvailable={freecadAvailable} onExportFcstd={onExportFcstd} />
                  <div className="mt-6">
                    <VersionsPanel versions={versions} current={version.id} canRestore={canWrite && !busy} onOpen={onOpenVersion} onRestore={onRestore} />
                  </div>
                </>
              )}
            </div>
          </div>
        ) : (
          <EmptyState title="No assembly report" detail="This version has no viewer manifest." />
        )}
      </Panel>

      <Panel
        padded={false}
        className="min-h-[420px] lg:min-h-0"
        title={isHead ? "Model" : `Model · v${version.number}`}
        action={<span className="text-xs text-muted-text">click a part to select · drag to orbit</span>}
      >
        {viewer ? (
          <AssemblyViewer
            meshesId={meshes}
            viewer={viewer}
            jointValues={joints}
            selected={selected}
            hovered={hovered}
            highlight={highlight}
            onHover={setHovered}
            onSelect={(id) => {
              select(id);
              if (id && (tab === "files" || tab === "bom")) setTab("parts");
            }}
          />
        ) : null}
      </Panel>
    </>
  );
}

function SheetMetalWorkspace({ version, versions, canWrite, busy, freecadAvailable, onOpenVersion, onRestore, onExportFcstd }: Props) {
  const viewer = version.viewer;
  const [tab, setTab] = useState<SheetTab>(viewer && !viewer.passed ? "checks" : "bends");
  const [bend, setBend] = useState<string | null>(null);
  const meshes = version.artifacts.find((a) => a.format === "MESHES")?.id ?? null;

  return (
    <>
      <Panel
        padded={false}
        className="min-h-[420px] lg:min-h-0"
        title="Sheet metal"
        action={<span className="text-xs tabular text-muted-text">{version.recipe_hash.slice(0, 8)}</span>}
      >
        {viewer ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="shrink-0 border-b border-line px-4 py-2.5">
              <Tabs<SheetTab>
                label="Sheet-metal details"
                value={tab}
                onChange={setTab}
                tabs={[
                  { id: "bends", label: "Bends" },
                  { id: "checks", label: "Checks" },
                  { id: "versions", label: "Versions" },
                  { id: "export", label: "Export" },
                ]}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {tab === "bends" ? (
                <BendTable viewer={viewer} selectedBend={bend} onSelectBend={setBend} />
              ) : tab === "checks" ? (
                <SheetChecks viewer={viewer} />
              ) : tab === "versions" ? (
                <VersionsPanel versions={versions} current={version.id} canRestore={canWrite && !busy} onOpen={onOpenVersion} onRestore={onRestore} />
              ) : (
                <KindExportPanel version={version} canExport={canWrite && !busy} freecadAvailable={freecadAvailable} onExportFcstd={onExportFcstd} />
              )}
            </div>
          </div>
        ) : (
          <EmptyState title="No sheet-metal report" />
        )}
      </Panel>

      <div className="grid min-h-[640px] grid-rows-[minmax(0,1.15fr)_minmax(0,1fr)] gap-3 lg:min-h-0">
        <Panel padded={false} className="min-h-0" title="Folded" action={<span className="text-xs text-muted-text">drag to orbit · scroll to zoom</span>}>
          {viewer ? (
            <AssemblyViewer
              meshesId={meshes}
              viewer={viewer}
              jointValues={{}}
              selected={null}
              hovered={null}
              highlight={null}
              onHover={() => {}}
              onSelect={() => {}}
            />
          ) : null}
        </Panel>
        <Panel padded={false} className="min-h-0" title="Flat pattern" action={<span className="text-xs text-muted-text">as cut · DXF in Export</span>}>
          {viewer?.flat ? <FlatPatternView flat={viewer.flat} selectedBend={bend} onSelectBend={setBend} /> : <EmptyState title="No flat pattern" />}
        </Panel>
      </div>
    </>
  );
}
