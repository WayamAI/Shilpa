"use client";

import dynamic from "next/dynamic";
import { useState, type ReactNode } from "react";

import { EmptyState } from "@/components/ui";
import type { Version } from "@/lib/api";

import { Facts, Inspector, Viewport, WorkspaceLayout } from "./chrome";
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
  /** The request thread, shown under the viewport. */
  footer: ReactNode;
};

/**
 * Viewport and inspector of the workspace for assemblies, products and sheet metal.
 * Selection, hover, check highlight and joint poses live here so the tree, the BOM,
 * the checks list, the joint sliders and the 3D view stay in sync. The parent keys
 * this component by version id, so a new version starts from its assembled pose.
 */
export function KindWorkspace(props: Props) {
  return props.version.kind === "sheet_metal" ? <SheetMetalWorkspace {...props} /> : <AssemblyWorkspace {...props} />;
}

function AssemblyWorkspace({ version, versions, canWrite, busy, freecadAvailable, onOpenVersion, onRestore, onExportFcstd, footer }: Props) {
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

  const sizeFact = viewer?.size ? viewer.size.map((v) => +v.toFixed(0)).join("×") : "None";
  return (
    <WorkspaceLayout
      footer={footer}
      facts={
        <Facts
          items={[
            { label: "Size mm", value: sizeFact },
            { label: "Parts", value: viewer?.instances.length ?? "None" },
            { label: "Version", value: `v${version.number}` },
          ]}
        />
      }
      viewport={
        <Viewport label={`${version.kind === "product" ? "Product" : "Assembly"} 3D view${isHead ? "" : `, v${version.number}`}`} className="min-h-[300px] flex-1">
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
          ) : (
            <EmptyState image="/imagery/sh-emp-01-empty-tray-128.webp" title="No preview" detail="This version has no viewer manifest." />
          )}
        </Viewport>
      }
      inspector={
        viewer ? (
          <Inspector<AsmTab> label={version.kind === "product" ? "Product" : "Assembly"} value={tab} onChange={setTab} tabs={tabs} className="flex-1">
            {tab === "parts" ? (
              <>
                <PartsTree viewer={viewer} selected={selected} hovered={hovered} onHover={setHovered} onSelect={select} />
                {product && viewer.joints.length ? (
                  <>
                    <h3 className="mt-6 mb-2 text-md">Joints</h3>
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
          </Inspector>
        ) : (
          <EmptyState image="/imagery/sh-emp-02-import-failed-128.webp" imageSize={48} title="No assembly report" detail="This version has no viewer manifest." />
        )
      }
    />
  );
}

function SheetMetalWorkspace({ version, versions, canWrite, busy, freecadAvailable, onOpenVersion, onRestore, onExportFcstd, footer }: Props) {
  const viewer = version.viewer;
  const [tab, setTab] = useState<SheetTab>(viewer && !viewer.passed ? "checks" : "bends");
  const [bend, setBend] = useState<string | null>(null);
  const meshes = version.artifacts.find((a) => a.format === "MESHES")?.id ?? null;

  return (
    <WorkspaceLayout
      footer={footer}
      facts={
        <Facts
          items={[
            { label: "Flat mm", value: viewer?.flat ? viewer.flat.size.map((v) => +v.toFixed(0)).join("×") : "None" },
            { label: "Bends", value: viewer?.flat?.bends.length ?? "None" },
            { label: "Version", value: `v${version.number}` },
          ]}
        />
      }
      viewport={
        <>
          <Viewport label="Folded 3D view" className="min-h-[300px] flex-1">
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
          </Viewport>
          <Viewport label="Flat pattern" className="min-h-[260px] flex-1">
            {viewer?.flat ? (
              <FlatPatternView flat={viewer.flat} selectedBend={bend} onSelectBend={setBend} />
            ) : (
              <EmptyState title="No flat pattern" />
            )}
          </Viewport>
        </>
      }
      inspector={
        viewer ? (
          <Inspector<SheetTab>
            label="Sheet metal"
            value={tab}
            onChange={setTab}
            className="flex-1"
            tabs={[
              { id: "bends", label: "Bends" },
              { id: "checks", label: "Checks" },
              { id: "versions", label: "Versions" },
              { id: "export", label: "Exports" },
            ]}
          >
            {tab === "bends" ? (
              <BendTable viewer={viewer} selectedBend={bend} onSelectBend={setBend} />
            ) : tab === "checks" ? (
              <SheetChecks viewer={viewer} />
            ) : tab === "versions" ? (
              <VersionsPanel versions={versions} current={version.id} canRestore={canWrite && !busy} onOpen={onOpenVersion} onRestore={onRestore} />
            ) : (
              <KindExportPanel version={version} canExport={canWrite && !busy} freecadAvailable={freecadAvailable} onExportFcstd={onExportFcstd} />
            )}
          </Inspector>
        ) : (
          <EmptyState image="/imagery/sh-emp-02-import-failed-128.webp" imageSize={48} title="No sheet-metal report" />
        )
      }
    />
  );
}
