"use client";

import { GizmoHelper, GizmoViewport, Grid, OrbitControls } from "@react-three/drei";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { Boxes, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { IconButton } from "@/components/ui/controls";
import { EmptyState } from "@/components/ui/primitives";
import { useTheme } from "@/context/theme-context";
import { fetchBlob, type MeshSet, type Viewer } from "@/lib/api";
import { posedMatrices } from "@/lib/assembly";

import { usePalette, webglAvailable } from "./model-viewer";

// Meshes arrive in part-local millimetres with Z up; each instance carries its
// part-to-world matrix. The scene is Y up, so one group turns CAD Z to scene Y
// (X->X, Y->-Z, Z->Y), matching the single-part viewer.

export type Highlight = { ids: string[]; tone: "clash" | "pass"; label: string } | null;

function useAccent() {
  const { theme } = useTheme();
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const v = (name: string) => css.getPropertyValue(name).trim();
    return { select: v("--viewer-select"), hover: v("--viewer-hover"), clash: v("--viewer-clash"), pass: v("--viewer-pass"), theme };
  }, [theme]);
}

function decode(meshes: MeshSet): Record<string, THREE.BufferGeometry> {
  const out: Record<string, THREE.BufferGeometry> = {};
  const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  for (const [key, m] of Object.entries(meshes.parts)) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(bytes(m.positions).buffer), 3));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(bytes(m.indices).buffer), 1));
    g.computeVertexNormals();
    g.computeBoundingBox();
    out[key] = g;
  }
  return out;
}

/** Frame the assembly once its meshes exist (and again on reset). Reads the group ref inside an effect. */
function FitGroup({ target, ready, nonce }: { target: React.RefObject<THREE.Group | null>; ready: boolean; nonce: number }) {
  const { camera, controls } = useThree() as unknown as {
    camera: THREE.PerspectiveCamera;
    controls: { target: THREE.Vector3; update: () => void } | null;
  };
  useEffect(() => {
    const object = target.current;
    if (!ready || !object) return;
    const box = new THREE.Box3().setFromObject(object);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3()).length() || 100;
    const center = box.getCenter(new THREE.Vector3());
    camera.position.set(center.x + size * 0.85, center.y + size * 0.7, center.z + size * 0.95);
    // eslint-disable-next-line react-hooks/immutability -- three.js camera, not React state
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [target, ready, camera, controls, nonce]);
  return null;
}

type InstanceProps = {
  id: string;
  geometry: THREE.BufferGeometry;
  edges: THREE.EdgesGeometry;
  matrix: number[][];
  color: string;
  edgeColor: string;
  dim: boolean;
  emphasis: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
};

function Instance({ id, geometry, edges, matrix, color, edgeColor, dim, emphasis, onHover, onSelect }: InstanceProps) {
  const { position, quaternion, scale } = useMemo(() => {
    const m = new THREE.Matrix4().set(...(matrix.flat() as Parameters<THREE.Matrix4["set"]>));
    const p = new THREE.Vector3();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    m.decompose(p, q, s);
    return { position: p, quaternion: q, scale: s };
  }, [matrix]);
  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: emphasis ?? color,
        metalness: 0.2,
        roughness: 0.55,
        side: THREE.DoubleSide,
        transparent: dim,
        opacity: dim ? 0.24 : 1,
        depthWrite: !dim,
        emissive: emphasis ? new THREE.Color(emphasis) : new THREE.Color(0x000000),
        emissiveIntensity: emphasis ? 0.28 : 0,
      }),
    [color, dim, emphasis],
  );
  const lineMaterial = useMemo(
    () => new THREE.LineBasicMaterial({ color: emphasis ?? edgeColor, transparent: dim, opacity: dim ? 0.2 : 1 }),
    [edgeColor, emphasis, dim],
  );
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => lineMaterial.dispose(), [lineMaterial]);

  return (
    <group position={position} quaternion={quaternion} scale={scale}>
      <mesh
        geometry={geometry}
        material={material}
        userData={{ instance: id }}
        onPointerOver={(e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation();
          onHover(id);
        }}
        onPointerOut={() => onHover(null)}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          onSelect(id);
        }}
      />
      <lineSegments geometry={edges} material={lineMaterial} raycast={() => null} />
    </group>
  );
}

export default function AssemblyViewer({
  meshesId,
  viewer,
  jointValues,
  selected,
  hovered,
  highlight,
  onHover,
  onSelect,
}: {
  meshesId: string | null;
  viewer: Viewer;
  jointValues: Record<string, number>;
  selected: string | null;
  hovered: string | null;
  highlight: Highlight;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}) {
  const palette = usePalette();
  const accent = useAccent();
  const [hasGL] = useState(() => webglAvailable());
  const [loaded, setLoaded] = useState<{ id: string; geoms?: Record<string, THREE.BufferGeometry>; error?: string } | null>(null);
  const [nonce, setNonce] = useState(0);
  const groupRef = useRef<THREE.Group>(null);
  const current = loaded && loaded.id === meshesId ? loaded : null;
  const geoms = current?.geoms ?? null;

  useEffect(() => {
    if (!meshesId) return;
    let cancelled = false;
    fetchBlob(`/v1/artifacts/${meshesId}/download`)
      .then((b) => b.text())
      .then((t) => {
        if (!cancelled) setLoaded({ id: meshesId, geoms: decode(JSON.parse(t) as MeshSet) });
      })
      .catch((e) => !cancelled && setLoaded({ id: meshesId, error: String(e?.message ?? e) }));
    return () => {
      cancelled = true;
    };
  }, [meshesId]);

  const edges = useMemo(() => {
    const out: Record<string, THREE.EdgesGeometry> = {};
    for (const [k, g] of Object.entries(geoms ?? {})) out[k] = new THREE.EdgesGeometry(g, 30);
    return out;
  }, [geoms]);

  const matrices = useMemo(() => posedMatrices(viewer, jointValues), [viewer, jointValues]);
  const focus = new Set(highlight?.ids ?? (selected ? [selected] : []));

  if (!hasGL) return <EmptyState title="3D preview needs WebGL" detail="Download STEP from the Export tab instead." />;

  return (
    <div
      className="viewer-surface relative h-full min-h-[320px] w-full"
      data-testid="assembly-viewer"
      data-ready={geoms ? "true" : "false"}
      data-selected={selected ?? ""}
      data-highlight={(highlight?.ids ?? []).join(",")}
      data-joints={JSON.stringify(jointValues)}
    >
      <Canvas camera={{ fov: 38, position: [200, 160, 200] }} dpr={[1, 2]} onPointerMissed={() => onSelect(null)}>
        <color attach="background" args={[palette.background]} />
        <hemisphereLight args={["#ffffff", palette.section, 1.0]} />
        <directionalLight position={[220, 320, 160]} intensity={1.3} />
        <directionalLight position={[-220, 120, -160]} intensity={0.45} />
        <group ref={groupRef} rotation={[-Math.PI / 2, 0, 0]}>
          {geoms
            ? viewer.instances.map((inst) => {
                const g = inst.mesh ? geoms[inst.mesh] : undefined;
                const m = matrices[inst.id];
                if (!g || !m) return null;
                const emphasis = highlight?.ids.includes(inst.id)
                  ? highlight.tone === "clash"
                    ? accent.clash
                    : accent.pass
                  : selected === inst.id
                    ? accent.select
                    : hovered === inst.id
                      ? accent.hover
                      : null;
                return (
                  <Instance
                    key={inst.id}
                    id={inst.id}
                    geometry={g}
                    edges={edges[inst.mesh!]}
                    matrix={m}
                    color={inst.color ?? palette.material}
                    edgeColor={palette.edge}
                    dim={focus.size > 0 && !focus.has(inst.id) && hovered !== inst.id}
                    emphasis={emphasis}
                    onHover={onHover}
                    onSelect={onSelect}
                  />
                );
              })
            : null}
        </group>
        <Grid
          position={[0, -0.05, 0]}
          args={[2400, 2400]}
          cellSize={10}
          sectionSize={100}
          cellColor={palette.cell}
          sectionColor={palette.section}
          fadeDistance={1400}
        />
        <OrbitControls makeDefault enableDamping />
        <FitGroup target={groupRef} ready={!!geoms} nonce={nonce} />
        <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
          <GizmoViewport axisColors={[palette.x, palette.z, palette.y]} labels={["X", "Z", "-Y"]} labelColor="#ffffff" />
        </GizmoHelper>
      </Canvas>

      <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap gap-2">
        <span className="rounded-full border border-muted bg-container px-2.5 py-1 text-caption text-tertiary">Units mm</span>
        {viewer.size ? (
          <span className="rounded-full border border-muted bg-container px-2.5 py-1 text-caption tabular text-secondary" title="Assembled envelope">
            {viewer.size.map((v) => +v.toFixed(2)).join(" × ")} mm
          </span>
        ) : null}
        {hovered || selected ? (
          <span className="rounded-full border border-muted bg-container px-2.5 py-1 text-caption text-primary">{hovered ?? selected}</span>
        ) : null}
      </div>
      {geoms ? (
        <div className="absolute top-3 right-3">
          <IconButton label="Reset view" onClick={() => setNonce((n) => n + 1)} className="bg-container">
            <RotateCcw size={14} strokeWidth={1.75} aria-hidden />
          </IconButton>
        </div>
      ) : null}
      {!meshesId ? (
        <div className="absolute inset-0 flex items-center justify-center">
          <EmptyState mark={<Boxes size={24} strokeWidth={1.5} className="icon-quaternary" aria-hidden />} title="No preview meshes" />
        </div>
      ) : null}
      {current?.error ? <p className="absolute inset-x-0 bottom-3 text-center text-body-sm text-error">Preview failed: {current.error}</p> : null}
    </div>
  );
}
