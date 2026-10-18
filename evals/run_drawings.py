"""Drawing-to-CAD evaluation (backlog B035, workbook T063-T069) through the real API, queue and workers.

For each synthetic drawing: upload -> extraction -> score recall of the true dimensions ->
accept the extracted values unchanged (an engineer approving without edits) -> generate ->
compare the validated model with the analytic oracle. Defect variants must stop instead.

Run:  uv run python evals/run_drawings.py [--only P01_vector,F01_scan] [--concurrency 4]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_language import HEADERS, start_stack, stop_stack  # noqa: E402

DRAWINGS = Path(__file__).parent / "drawings"
OUT = Path(__file__).parent / "out"
TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}


def run_one(base: str, project: str, d: dict) -> dict:
    c = httpx.Client(base_url=base, headers=HEADERS, timeout=300)
    rec = {"id": d["id"], "variant": d["variant"], "expected": d["expected"], "outcome": None, "passed": False, "notes": [],
           "recall": None, "tokens": [0, 0]}
    t0 = time.time()
    up = c.post(f"/v1/projects/{project}/uploads", files={"file": (d["file"], (DRAWINGS / d["file"]).read_bytes(), "application/pdf")})
    if up.status_code != 201:
        rec["outcome"] = "upload_rejected"
        rec["notes"].append(up.text[:200])
        return rec
    r = c.post(f"/v1/projects/{project}/specifications", json={"upload_id": up.json()["id"]})
    rec["extract_s"] = round(time.time() - t0, 1)
    if r.status_code != 201:
        rec["outcome"] = "extract_error"
        rec["notes"].append(r.text[:300])
        return rec
    spec = r.json()
    req = spec["requirements"]
    u = req.get("_usage", {})
    rec["tokens"] = [u.get("input_tokens", 0), u.get("output_tokens", 0)]
    units = req.get("units") or "mm"
    found = []
    for dim in req["dimensions"]:
        if dim["value"] is not None and dim["kind"] == "length":
            found.append(round(dim["value"] * TO_MM.get(dim.get("unit") or units, 1.0), 4))
    truth = d["key_values_mm"]
    hit = [v for v in truth if any(abs(v - f) <= 0.01 for f in found)]
    rec["recall"] = round(len(hit) / len(truth), 3) if truth else None
    rec["missed_values"] = [v for v in truth if v not in hit]
    rec["extracted"] = {dim["name"]: dim["value"] for dim in req["dimensions"]}
    rec["verified_fraction"] = _verified(req)
    rec["ignored_instructions"] = req.get("drawing", {}).get("ignored_instructions", [])
    for bad in d.get("must_not_contain_mm", []):
        if any(abs(bad - f) <= 0.01 for f in found):
            rec["notes"].append(f"read {bad:g} (misread decimal)")
    status = spec["status"]

    if d["expected"] == "clarify":
        text = " ".join(f"{m['name']} {m['question']}" for m in req["missing"]).lower()
        rec["outcome"] = "clarify" if status == "needs_clarification" else status
        rec["passed"] = status == "needs_clarification" and any(k in text for k in d.get("expect_missing", [""]))
        return rec
    if d["expected"] == "no_build":
        rec["outcome"] = "clarify" if status == "needs_clarification" else status
        rec["passed"] = status == "needs_clarification"
        if not rec["passed"]:
            rec["notes"].append("conflicting drawing was not stopped at review")
        return rec

    # expected build: accept the extracted values as-is, then generate
    if status != "needs_review":
        rec["outcome"] = status
        rec["notes"].append(f"expected values ready for review, got {status}: {req.get('status_reason')} {req.get('missing')}")
        return rec
    r = c.patch(f"/v1/specifications/{spec['id']}", json={"revision": spec["revision"], "confirm_drawing": True})
    if r.json().get("status") != "ready":
        rec["outcome"] = "not_ready"
        rec["notes"].append(f"after confirm: {r.json().get('status')}")
        return rec
    t1 = time.time()
    job = c.post(f"/v1/projects/{project}/jobs", json={"specification_id": spec["id"]}).json()
    while True:
        job = c.get(f"/v1/jobs/{job['id']}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(1)
    rec["job_s"] = round(time.time() - t1, 1)
    b = job.get("budget_used") or {}
    rec["tokens"] = [rec["tokens"][0] + b.get("input_tokens", 0), rec["tokens"][1] + b.get("output_tokens", 0)]
    if job["state"] != "succeeded":
        rec["outcome"] = "rejected"
        rec["notes"].append(f"{(job.get('error') or {}).get('code')}: {(job.get('error') or {}).get('message', '')[:200]}")
        return rec
    rec["outcome"] = "build"
    v = c.get(f"/v1/versions/{job['result_version_id']}").json()
    m, o = v["validation"]["measurement"], d["oracle"]
    ok_bbox = all(abs(a - b) <= 0.01 for a, b in zip(sorted(m["bbox_size"]), sorted(o["bbox"])))
    rel = abs(m["volume"] - o["volume"]) / o["volume"]
    holes: dict[float, int] = {}
    for cyl in m["cylinders"]:
        if cyl["kind"] == "hole":
            holes[round(cyl["diameter"], 3)] = holes.get(round(cyl["diameter"], 3), 0) + 1
    ok_holes = all(sum(n for dk, n in holes.items() if abs(dk - float(k)) <= 0.01) == want for k, want in (o.get("holes") or {}).items())
    if not ok_bbox:
        rec["notes"].append(f"bbox {m['bbox_size']} != {o['bbox']}")
    if rel > 1e-4:
        rec["notes"].append(f"volume {m['volume']:.3f} != {o['volume']:.3f} (rel {rel:.1e})")
    if not ok_holes:
        rec["notes"].append(f"holes {holes} != {o.get('holes')}")
    rec["passed"] = ok_bbox and rel <= 1e-4 and ok_holes and not any("misread" in n for n in rec["notes"])
    return rec


def _verified(req: dict) -> float | None:
    dims = req.get("drawing", {}).get("dimensions", [])
    vals = [dm.get("verified") for dm in dims if dm.get("verified") is not None]
    return round(sum(bool(v) for v in vals) / len(vals), 3) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--port", type=int, default=8768)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    manifest = json.loads((DRAWINGS / "manifest.json").read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    items = [m for m in manifest if not only or m["id"] in only]
    procs, var = start_stack(args.port, workers=args.concurrency, coordinators=2)
    base = f"http://127.0.0.1:{args.port}"
    t0 = time.time()
    try:
        project = httpx.post(f"{base}/v1/projects", json={"name": "Drawing eval"}, headers=HEADERS).json()["id"]
        rows = []
        with ThreadPoolExecutor(args.concurrency) as pool:
            for rec in pool.map(lambda d: run_one(base, project, d), items):
                rows.append(rec)
                print(f"{'PASS' if rec['passed'] else 'FAIL'} {rec['id']:16} exp={rec['expected']:8} got={str(rec['outcome']):14} "
                      f"recall={rec['recall']}  {'; '.join(rec['notes'])[:170]}", flush=True)
    finally:
        stop_stack(procs)
    rows.sort(key=lambda r: r["id"])
    builds = [r for r in rows if r["expected"] == "build"]
    recalls = [r["recall"] for r in rows if r["recall"] is not None]
    summary = {
        "end_to_end_build": f"{sum(r['passed'] for r in builds)}/{len(builds)}",
        "vector": f"{sum(r['passed'] for r in builds if r['variant'] in ('vector', 'injection'))}/{sum(1 for r in builds if r['variant'] in ('vector', 'injection'))}",
        "scans": f"{sum(r['passed'] for r in builds if r['variant'] in ('scan', 'lowres'))}/{sum(1 for r in builds if r['variant'] in ('scan', 'lowres'))}",
        "defects_stopped": f"{sum(r['passed'] for r in rows if r['expected'] != 'build')}/{sum(1 for r in rows if r['expected'] != 'build')}",
        "mean_value_recall": round(statistics.mean(recalls), 3) if recalls else None,
        "perfect_recall": f"{sum(1 for x in recalls if x == 1.0)}/{len(recalls)}",
        "tokens_per_drawing_in_out": [round(statistics.mean(r["tokens"][0] for r in rows)), round(statistics.mean(r["tokens"][1] for r in rows))],
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    name = f"drawing_report{('_' + args.tag) if args.tag else ''}.json"
    (OUT / name).write_text(json.dumps({"summary": summary, "drawings": rows}, indent=2, default=str), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=2) + f"\nreport: {OUT / name}   stack log: {var / 'stack.log'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
