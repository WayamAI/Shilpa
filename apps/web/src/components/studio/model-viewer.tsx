"use client";

import { GizmoHelper, GizmoViewport, Grid, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { EmptyState } from "@/components/ui";
import { fetchBlob } from "@/lib/api";

import { ToolbarButton, ViewportCaption, ViewportToolbar } from "./chrome";

// glTF from the CAD worker is in metres with Y up. The scene works in millimetres
// (scale 1000). CAD axes map to scene axes as X->X, Y->-Z, Z->Y.

export type Palette = { background: string; material: string; edge: string; cell: string; section: string; x: string; y: string; z: string };

/**
 * Resolve the --viewer-* tokens once. This component is client-only (dynamic
 * import, ssr: false), so reading computed styles during render is safe.
 */
export function usePalette(): Palette {
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const v = (name: string) => css.getPropertyValue(name).trim();
    return {
      background: v("--viewer-background"),
      material: v("--viewer-material"),
      edge: v("--viewer-edge"),
      cell: v("--viewer-grid-cell"),
      section: v("--viewer-grid-section"),
      x: v("--viewer-axis-x"),
      y: v("--viewer-axis-y"),
      z: v("--viewer-axis-z"),
    };
  }, []);
}

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function FitCamera({ object, nonce }: { object: THREE.Object3D | null; nonce: number }) {
  const { camera, controls } = useThree() as unknown as {
    camera: THREE.PerspectiveCamera;
    controls: { target: THREE.Vector3; update: () => void } | null;
  };
  useEffect(() => {
    if (!object) return;
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3()).length() || 100;
    const center = box.getCenter(new THREE.Vector3());
    // three.js cameras are mutable scene objects; updating them in place is the R3F way.
    camera.position.set(center.x + size * 0.85, center.y + size * 0.7, center.z + size * 0.95);
    // eslint-disable-next-line react-hooks/immutability -- three.js camera, not React state
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [object, camera, controls, nonce]);
  return null;
}

export default function ModelViewer({ glbId, size }: { glbId: string | null; size?: [number, number, number] | null }) {
  const palette = usePalette();
  // Loaded results are keyed by artifact id, so a stale model is never shown for a new id.
  const [loaded, setLoaded] = useState<{ id: string; scene?: THREE.Group; error?: string } | null>(null);
  const [nonce, setNonce] = useState(0);
  const [hasGL] = useState(() => webglAvailable());
  const current = loaded && loaded.id === glbId ? loaded : null;
  const scene = current?.scene ?? null;
  const error = current?.error ?? null;

  useEffect(() => {
    if (!glbId) return;
    let cancelled = false;
    fetchBlob(`/v1/artifacts/${glbId}/download`)
      .then((b) => b.arrayBuffer())
      .then((buf) => new GLTFLoader().parseAsync(buf, ""))
      .then((gltf) => {
        if (cancelled) return;
        gltf.scene.scale.setScalar(1000);
        setLoaded({ id: glbId, scene: gltf.scene });
      })
      .catch((e) => !cancelled && setLoaded({ id: glbId, error: String(e?.message ?? e) }));
    return () => {
      cancelled = true;
    };
  }, [glbId]);

  // Apply the viewer material and edges once the model loads.
  useEffect(() => {
    if (!scene || !palette) return;
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      m.material = new THREE.MeshStandardMaterial({ color: palette.material, metalness: 0.25, roughness: 0.5, side: THREE.DoubleSide });
      m.children.filter((c) => c.userData.edges).forEach((c) => m.remove(c));
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 30), new THREE.LineBasicMaterial({ color: palette.edge }));
      edges.userData.edges = true;
      m.add(edges);
    });
  }, [scene, palette]);

  const label = useMemo(() => (size ? size.map((v) => +v.toFixed(3)).join(" × ") : null), [size]);

  if (!hasGL) {
    return <EmptyState title="3D preview needs WebGL" detail="Download STEP or STL from the Exports tab instead." />;
  }

  return (
    <div className="viewer-surface relative h-full min-h-[320px] w-full" data-testid="model-viewer">
      {(
        <Canvas camera={{ fov: 38, position: [160, 130, 160] }} dpr={[1, 2]}>
          <color attach="background" args={[palette.background]} />
          <hemisphereLight args={["#ffffff", palette.section, 1.0]} />
          <directionalLight position={[220, 320, 160]} intensity={1.3} />
          <directionalLight position={[-220, 120, -160]} intensity={0.45} />
          {scene ? <primitive object={scene} /> : null}
          <Grid
            position={[0, -0.05, 0]}
            args={[1200, 1200]}
            cellSize={10}
            sectionSize={100}
            cellColor={palette.cell}
            sectionColor={palette.section}
            fadeDistance={900}
          />
          <OrbitControls makeDefault enableDamping />
          <FitCamera object={scene} nonce={nonce} />
          <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
            {/* Scene Y is CAD Z, scene -Z is CAD Y. */}
            <GizmoViewport axisColors={[palette.x, palette.z, palette.y]} labels={["X", "Z", "-Y"]} labelColor="#ffffff" />
          </GizmoHelper>
        </Canvas>
      )}

      <div className="absolute top-3 left-3 max-w-[calc(100%-24px)]">
        <ViewportToolbar label="View">
          <ToolbarButton onClick={() => setNonce((n) => n + 1)} disabled={!scene} label="Fit view to part">
            Fit
          </ToolbarButton>
          <ToolbarButton planned>Section</ToolbarButton>
        </ViewportToolbar>
      </div>
      <ViewportCaption
        facts={label ? <span title="Exact size from the validated STEP">{label} mm</span> : undefined}
        hint="Drag to orbit · scroll to zoom"
        className="pr-24"
      />
      {!glbId ? (
        <div className="absolute inset-0 flex items-center justify-center">
          <EmptyState
            image="/imagery/sh-emp-01-empty-tray-128.webp"
            title="No part yet"
            detail="Describe a part, upload a drawing, or start from a reference part."
          />
        </div>
      ) : null}
      {error ? <p className="absolute inset-x-0 bottom-3 text-center text-xs text-fail-text">Preview failed: {error}</p> : null}
    </div>
  );
}
