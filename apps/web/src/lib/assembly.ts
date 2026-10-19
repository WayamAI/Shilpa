// Assembly helpers shared by the viewer and the panels: joint poses, the parts tree, check labels.

import type { Matrix4, Viewer, ViewerCheck, ViewerInstance, ViewerJoint } from "./api";

type M = number[][];

function mul(a: M, b: M): M {
  const out: M = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]];
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) out[i][j] += a[i][k] * b[k][j];
  return out;
}

/** Inverse of a rigid (or mirrored) transform: R^T and -R^T t. Joint frames are orthonormal. */
function invRigid(a: M): M {
  const r = [[a[0][0], a[1][0], a[2][0]], [a[0][1], a[1][1], a[2][1]], [a[0][2], a[1][2], a[2][2]]];
  const t = [a[0][3], a[1][3], a[2][3]];
  const ti = r.map((row) => -(row[0] * t[0] + row[1] * t[1] + row[2] * t[2]));
  return [[...r[0], ti[0]], [...r[1], ti[1]], [...r[2], ti[2]], [0, 0, 0, 1]];
}

function motion(joint: ViewerJoint, value: number): M {
  const d = value - joint.value;
  const s = joint.sign;
  const angle = joint.param === "angle" ? s * d : 0;
  const dz = joint.param === "angle" ? (joint.type === "screw" ? (s * d * (joint.pitch ?? 0)) / 360 : 0) : s * d;
  const c = Math.cos((angle * Math.PI) / 180);
  const sn = Math.sin((angle * Math.PI) / 180);
  return [[c, -sn, 0, 0], [sn, c, 0, 0], [0, 0, 1, dz], [0, 0, 0, 1]];
}

/**
 * Part-to-world matrices with some joints moved away from their assembled values.
 * Mirrors ``shilpa/workers/kinds.py``: the moving side of a joint turns by
 * ``J @ motion @ inv(J)``. Joints arrive in placement (breadth-first) order, so applying
 * them deepest-first composes nested joints correctly.
 */
export function posedMatrices(viewer: Viewer, values: Record<string, number>): Record<string, Matrix4> {
  const out: Record<string, M> = {};
  for (const inst of viewer.instances) if (inst.matrix) out[inst.id] = inst.matrix;
  for (const joint of [...viewer.joints].reverse()) {
    const v = values[joint.name];
    if (v === undefined || v === joint.value) continue;
    const W = mul(mul(joint.frame, motion(joint, v)), invRigid(joint.frame));
    for (const id of joint.moving) if (out[id]) out[id] = mul(W, out[id]);
  }
  return out;
}

export type TreeRow = { inst: ViewerInstance; depth: number; via: string | null };

/** Instances as a placement tree from the ground (mates in the tree), unplaced ones last. */
export function partsTree(viewer: Viewer): TreeRow[] {
  const byId = new Map(viewer.instances.map((i) => [i.id, i]));
  const adj = new Map<string, { other: string; type: string }[]>();
  for (const m of viewer.mates.filter((x) => x.in_tree)) {
    adj.set(m.a, [...(adj.get(m.a) ?? []), { other: m.b, type: m.type }]);
    adj.set(m.b, [...(adj.get(m.b) ?? []), { other: m.a, type: m.type }]);
  }
  const rows: TreeRow[] = [];
  const seen = new Set<string>();
  const visit = (id: string, depth: number, via: string | null) => {
    const inst = byId.get(id);
    if (!inst || seen.has(id)) return;
    seen.add(id);
    rows.push({ inst, depth, via });
    for (const e of adj.get(id) ?? []) visit(e.other, depth + 1, e.type);
  };
  const ground = viewer.instances.find((i) => i.grounded) ?? viewer.instances[0];
  if (ground) visit(ground.id, 0, null);
  for (const inst of viewer.instances) if (!seen.has(inst.id)) visit(inst.id, 0, null);
  return rows;
}

const GROUP_LABEL: Record<string, string> = {
  interference: "Interference",
  clearance: "Clearance",
  contact: "Contact",
  dof: "Degrees of freedom",
  sweep: "Joint sweep",
  bom: "Bill of materials",
  spec: "Specification",
  build: "Part build",
  freecad_assembly: "FreeCAD",
  product: "Product",
};

export function groupLabel(group: string): string {
  return GROUP_LABEL[group] ?? group.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** "interference[block+plate]" -> "block + plate"; "contact[plate.top~block.foot]" -> "plate.top ~ block.foot". */
export function checkTitle(c: ViewerCheck): string {
  const m = /^([a-z_]+)\[(.*)\]$/.exec(c.name);
  if (!m) {
    const whole: Record<string, string> = {
      interference: "No clashing pairs",
      dof: "Mechanism DOF",
      spec_valid: "Spec is consistent",
      all_placed: "Every part placed",
      bom_built: "Every part built",
      bom_quantities: "BOM quantities",
      freecad_assembly: "FreeCAD assembly",
    };
    return whole[c.name] ?? c.name.replace(/_/g, " ");
  }
  return m[2].replace(/\+/g, " + ").replace(/~/g, " ~ ");
}

export function fmtValue(v: unknown): string {
  if (Array.isArray(v)) {
    if (v.length && typeof v[0] === "object" && v[0] !== null) return `${v.length} item${v.length === 1 ? "" : "s"}`;
    return v.map(fmtValue).join(", ");
  }
  if (typeof v === "number") return String(+v.toFixed(4));
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** One-line detail for a check row. */
export function checkDetail(c: ViewerCheck): string {
  if (c.name.startsWith("sweep[") && Array.isArray(c.actual) && c.actual.length) {
    const hit = c.actual[0] as { value: number; pair: string; volume: number };
    return `collides at ${hit.value} with ${hit.pair.replace("+", " + ")} (${+hit.volume.toFixed(2)} mm³)`;
  }
  if (c.name.startsWith("interference[")) return `${fmtValue(c.actual)} mm³ overlap, allowed ${fmtValue(c.requested)} mm³`;
  if (c.name.startsWith("contact[")) return `gap ${fmtValue(c.actual)} mm (max ${fmtValue(c.tolerance)} mm)`;
  if (c.name.startsWith("clearance[")) {
    const [lo, hi] = (c.requested as [number, number | null]) ?? [0, null];
    return `distance ${fmtValue(c.actual)} mm, wanted ≥ ${lo}${hi !== null && hi !== undefined ? ` and ≤ ${hi}` : ""} mm`;
  }
  if (c.name === "dof") return `computed ${fmtValue(c.actual)}, intended ${fmtValue(c.requested)}`;
  if (c.name === "interference" || c.name === "all_placed") {
    const items = Array.isArray(c.actual) ? (c.actual as string[]) : [];
    if (!items.length) return c.name === "interference" ? "no pair overlaps beyond its allowance" : "all parts reach the ground";
    return `${c.name === "interference" ? "clashing" : "not placed"}: ${items.map((x) => x.replace("+", " + ")).join(", ")}`;
  }
  if (c.name === "spec_valid") return c.passed ? "no issues" : (c.note ?? "");
  if (c.requested !== null && c.requested !== undefined) return `${fmtValue(c.requested)} → ${fmtValue(c.actual)}`;
  return c.note ?? (c.actual !== null && c.actual !== undefined ? fmtValue(c.actual) : "");
}
