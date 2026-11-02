"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { EmptyState } from "@/components/ui";
import { Viewport } from "@/components/studio/chrome";
import type { Version } from "@/lib/api";

// three.js needs the browser: load the viewer on the client only.
const AssemblyViewer = dynamic(() => import("@/components/studio/assembly-viewer"), {
  ssr: false,
  loading: () => <div className="viewer-surface h-full min-h-[240px] w-full" />,
});

/** The composition's current version in the same assembly viewer the project workspace uses. */
export function CompositionStage({ version }: { version: Version }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const viewer = version.viewer;
  const meshes = version.artifacts.find((a) => a.format === "MESHES")?.id ?? null;

  return (
    <Viewport label={`Composition 3D view, v${version.number}`} className="min-h-[260px] flex-1">
      {viewer ? (
        <AssemblyViewer
            meshesId={meshes}
            viewer={viewer}
            jointValues={{}}
            selected={selected}
            hovered={hovered}
            highlight={null}
            onHover={setHovered}
            onSelect={setSelected}
          />
      ) : (
        <EmptyState image="/imagery/sh-emp-01-empty-tray-128.webp" title="No preview" detail="This version has no viewer manifest." />
      )}
    </Viewport>
  );
}
