import { Canvas, useThree } from "@react-three/fiber";
import { GizmoHelper, GizmoViewport, Grid, OrbitControls } from "@react-three/drei";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { fetchArtifact } from "./api";

// glTF from the CAD worker is in metres, Y up. The scene works in millimetres, so the
// mesh is scaled by 1000. CAD axes map to scene axes as X->X, Y->-Z, Z->Y.

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function Fit({ object }: { object: THREE.Object3D | null }) {
  const { camera, controls } = useThree() as unknown as { camera: THREE.PerspectiveCamera; controls: { target: THREE.Vector3; update: () => void } | null };
  useEffect(() => {
    if (!object) return;
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3()).length() || 100;
    const center = box.getCenter(new THREE.Vector3());
    camera.position.set(center.x + size * 0.8, center.y + size * 0.7, center.z + size * 0.9);
    camera.near = size / 1000;
    camera.far = size * 100;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [object, camera, controls]);
  return null;
}

export function Viewer({ glbId, bbox }: { glbId: string | null; bbox?: [number, number, number] | null }) {
  const [scene, setScene] = useState<THREE.Group | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasGL = useMemo(webglAvailable, []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    if (!glbId) {
      setScene(null);
      return;
    }
    fetchArtifact(glbId)
      .then((buf) => new GLTFLoader().parseAsync(buf, ""))
      .then((gltf) => {
        if (cancelled) return;
        const g = gltf.scene;
        g.scale.setScalar(1000);
        g.traverse((o) => {
          const m = o as THREE.Mesh;
          if (m.isMesh) {
            m.material = new THREE.MeshStandardMaterial({ color: "#9fb4c8", metalness: 0.35, roughness: 0.45, side: THREE.DoubleSide });
            m.castShadow = true;
            const edges = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 30), new THREE.LineBasicMaterial({ color: "#1f2933" }));
            m.add(edges);
          }
        });
        setScene(g);
      })
      .catch((e) => !cancelled && setError(String(e.message || e)));
    return () => {
      cancelled = true;
    };
  }, [glbId]);

  if (!hasGL) {
    return <div className="viewer-empty">3D preview needs WebGL. Use the Export tab to download STEP or STL.</div>;
  }

  return (
    <div className="viewer">
      <Canvas camera={{ fov: 40, position: [150, 120, 150] }} shadows>
        <color attach="background" args={["#eef1f4"]} />
        <hemisphereLight args={["#ffffff", "#b0b8c0", 0.9]} />
        <directionalLight position={[200, 300, 150]} intensity={1.4} castShadow />
        <directionalLight position={[-200, 100, -150]} intensity={0.4} />
        {scene && <primitive object={scene} />}
        <Grid position={[0, -0.05, 0]} args={[1000, 1000]} cellSize={10} sectionSize={100} cellColor="#cfd6dd" sectionColor="#9aa5b1" fadeDistance={800} />
        <OrbitControls makeDefault enableDamping />
        <Fit object={scene} />
        <GizmoHelper alignment="bottom-right" margin={[64, 64]}>
          {/* Scene Y is CAD Z, scene -Z is CAD Y. */}
          <GizmoViewport axisColors={["#d64545", "#3a7bd5", "#2f9e44"]} labels={["X", "Z", "-Y"]} labelColor="#fff" />
        </GizmoHelper>
      </Canvas>
      <div className="viewer-overlay">
        <span>Units: mm</span>
        {bbox && (
          <span title="Exact CAD bounding box from the validated STEP">
            Size {bbox.map((v) => +v.toFixed(3)).join(" × ")} mm
          </span>
        )}
      </div>
      {!glbId && <div className="viewer-hint">Describe a part on the right, or start from an example.</div>}
      {error && <div className="viewer-hint error">Preview failed: {error}</div>}
    </div>
  );
}
