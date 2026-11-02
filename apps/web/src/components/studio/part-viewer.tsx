"use client";

import { GizmoHelper, GizmoViewport, Grid, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";

import { IconButton } from "@/components/ui/controls";
import { EmptyState } from "@/components/ui/primitives";
import type { CatalogPort, PartMesh } from "@/lib/api";

import { usePalette, webglAvailable } from "./model-viewer";

// One catalog part in its own millimetre frame, Z up, with its ports drawn as arrows along
// each port's z axis. The group turns CAD Z to scene Y like the assembly viewer.

function decode(m: PartMesh): THREE.BufferGeometry {
  const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(bytes(m.positions).buffer), 3));
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(bytes(m.indices).buffer), 1));
  g.computeVertexNormals();
  g.computeBoundingBox();
  return g;
}

/**
 * Frame the part by its bounding sphere so long rails and flat plates both fit, looking
 * from the usual three-quarter direction. Runs when the part's size class changes or on reset.
 */
function FitPart({ geometry, sizeKey, nonce }: { geometry: THREE.BufferGeometry | null; sizeKey: number; nonce: number }) {
  const { camera, controls } = useThree() as unknown as {
    camera: THREE.PerspectiveCamera;
    controls: { target: THREE.Vector3; update: () => void } | null;
  };
  useEffect(() => {
    if (!geometry?.boundingBox) return;
    // CAD Z up -> scene Y up (the group's -90 deg turn about X).
    const box = geometry.boundingBox.clone().applyMatrix4(new THREE.Matrix4().makeRotationX(-Math.PI / 2));
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const r = Math.max(sphere.radius, 1);
    const dist = (r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.15;
    const dir = new THREE.Vector3(0.85, 0.7, 0.95).normalize();
    camera.position.copy(sphere.center).addScaledVector(dir, dist);
    // eslint-disable-next-line react-hooks/immutability -- three.js camera, not React state
    camera.near = dist / 1000;
    camera.far = dist * 100;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(sphere.center);
      controls.update();
    }
    // Refit on a new size class, not on every edit that keeps the part about the same size.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sizeKey, nonce, camera, controls]);
  return null;
}

function useKindColors() {
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const v = (name: string) => css.getPropertyValue(name).trim();
    return { face: v("--viewer-axis-x"), axis: v("--viewer-axis-z"), point: v("--viewer-axis-y"), select: v("--viewer-select") };
  }, []);
}

function PortMarker({ port, length, color, selected }: { port: CatalogPort; length: number; color: string; selected: boolean }) {
  const arrow = useMemo(() => {
    const dir = new THREE.Vector3(...(port.z as [number, number, number])).normalize();
    const origin = new THREE.Vector3(...(port.origin as [number, number, number]));
    const len = selected ? length * 1.5 : length;
    const a = new THREE.ArrowHelper(dir, origin, len, new THREE.Color(color), len * 0.28, len * 0.14);
    // Ports often sit inside bores or on hidden faces: draw them over the part.
    a.traverse((o) => {
      const m = (o as THREE.Mesh).material as THREE.Material | undefined;
      if (m) {
        m.depthTest = false;
        m.transparent = true;
      }
      o.renderOrder = 10;
    });
    return a;
  }, [port, length, color, selected]);
  useEffect(
    () => () => {
      arrow.dispose();
    },
    [arrow],
  );
  return (
    <group>
      <primitive object={arrow} />
      <mesh position={port.origin as [number, number, number]} renderOrder={10}>
        <sphereGeometry args={[length * (selected ? 0.1 : 0.06), 16, 12]} />
        <meshBasicMaterial color={color} depthTest={false} transparent />
      </mesh>
    </group>
  );
}

export default function PartViewer({
  mesh,
  ports,
  showPorts,
  selectedPort,
  busy,
}: {
  mesh: PartMesh | null;
  ports: CatalogPort[];
  showPorts: boolean;
  selectedPort: string | null;
  busy: boolean;
}) {
  const palette = usePalette();
  const kinds = useKindColors();
  const [hasGL] = useState(() => webglAvailable());
  const [nonce, setNonce] = useState(0);

  const geometry = useMemo(() => (mesh ? decode(mesh) : null), [mesh]);
  const edges = useMemo(() => (geometry ? new THREE.EdgesGeometry(geometry, 30) : null), [geometry]);
  useEffect(() => () => geometry?.dispose(), [geometry]);
  useEffect(() => () => edges?.dispose(), [edges]);
  const extent = geometry?.boundingBox ? geometry.boundingBox.getSize(new THREE.Vector3()).length() : 0;
  const sizeKey = extent ? Math.round(Math.log2(extent) * 4) : 0;
  const marker = Math.max(extent * 0.09, 2);

  if (!hasGL) return <EmptyState title="3D preview needs WebGL" detail="Download the STEP file instead." />;

  return (
    <div className="viewer-surface relative h-full min-h-[360px] w-full" data-testid="part-viewer" data-ready={geometry ? "true" : "false"}>
      <Canvas camera={{ fov: 38, position: [200, 160, 200] }} dpr={[1, 2]}>
        <color attach="background" args={[palette.background]} />
        <hemisphereLight args={["#ffffff", palette.section, 1.0]} />
        <directionalLight position={[220, 320, 160]} intensity={1.3} />
        <directionalLight position={[-220, 120, -160]} intensity={0.45} />
        <group rotation={[-Math.PI / 2, 0, 0]}>
          {geometry ? (
            <mesh geometry={geometry}>
              <meshStandardMaterial color={palette.material} metalness={0.25} roughness={0.5} side={THREE.DoubleSide} />
            </mesh>
          ) : null}
          {edges ? (
            <lineSegments geometry={edges}>
              <lineBasicMaterial color={palette.edge} />
            </lineSegments>
          ) : null}
          {showPorts
            ? ports.map((p) => (
                <PortMarker
                  key={p.name}
                  port={p}
                  length={marker}
                  color={selectedPort === p.name ? kinds.select : kinds[p.kind]}
                  selected={selectedPort === p.name}
                />
              ))
            : null}
        </group>
        <Grid position={[0, -0.05, 0]} args={[2400, 2400]} cellSize={10} sectionSize={100} cellColor={palette.cell} sectionColor={palette.section} fadeDistance={1400} />
        <OrbitControls makeDefault enableDamping />
        <FitPart geometry={geometry} sizeKey={sizeKey} nonce={nonce} />
        <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
          <GizmoViewport axisColors={[palette.x, palette.z, palette.y]} labels={["X", "Z", "-Y"]} labelColor="#ffffff" />
        </GizmoHelper>
      </Canvas>

      <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap gap-2">
        <span className="rounded-full border border-line bg-bg px-2.5 py-1 text-xs text-muted-text">Units mm</span>
        {showPorts ? (
          <span className="flex items-center gap-2 rounded-full border border-line bg-bg px-2.5 py-1 text-xs text-body">
            {(["face", "axis", "point"] as const).map((k) => (
              <span key={k} className="flex items-center gap-1">
                <span className="inline-block size-2 rounded-full" style={{ background: kinds[k] }} aria-hidden />
                {k}
              </span>
            ))}
          </span>
        ) : null}
        {busy ? <span className="rounded-full border border-line bg-bg px-2.5 py-1 text-xs text-body">Building…</span> : null}
      </div>
      {geometry ? (
        <div className="absolute top-3 right-3">
          <IconButton label="Reset view" onClick={() => setNonce((n) => n + 1)} className="bg-bg">
            <RotateCcw size={14} strokeWidth={1.75} aria-hidden />
          </IconButton>
        </div>
      ) : null}
    </div>
  );
}
