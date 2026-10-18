"""Debug helper: build the first N lowered ops of a corpus fixture in FreeCAD and dump the last sketch.

Run:  uv run python evals/fc_probe.py P01 2
"""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shilpa.adapters import build123d_adapter as b, freecad_adapter as fa  # noqa: E402

fid, n = sys.argv[1], int(sys.argv[2])
fx = json.load(open(Path(__file__).parent / "corpus" / f"{fid}.json"))
r = b.build(fx["recipe"])
plan = fa.lower(r.compiled, [asdict(f) for f in r.features])
plan["ops"] = plan["ops"][:n]
out = (Path(__file__).parent / "out" / "fcprobe").resolve()
out.mkdir(parents=True, exist_ok=True)
probe = out / "probe.py"
probe.write_text(f'''
exec(open(r"{fa.SCRIPT.as_posix()}").read().split(chr(10) + "try:" + chr(10) + "    build()")[0])
JOB["out_fcstd"] = r"{(out / 'probe.FCStd').as_posix()}"; JOB["out_step"] = r"{(out / 'probe.step').as_posix()}"
try:
    build()
except Exception as exc:
    print("BUILD ERROR", exc)
doc = App.ActiveDocument
for o in doc.Objects:
    print("OBJ", o.Name, o.TypeId, o.State, "valid" if not hasattr(o, "Shape") or o.Shape.isNull() else ("solids=%d vol=%.4f" % (len(o.Shape.Solids), o.Shape.Volume)))
sk = [o for o in doc.Objects if o.TypeId == "Sketcher::SketchObject"][-1]
print("SKETCH", sk.Name, "solve", sk.solve(), "wires", len(sk.Shape.Wires), "placement", sk.Placement)
for g in sk.Geometry: print("  GEO", g)
for k, v in sk.ExpressionEngine: print("  EXPR", k, "=", v)
''', encoding="utf-8")
job = out / "job.json"
job.write_text(json.dumps({"mode": "build", **plan, "result": str(out / "r.json"), "out_fcstd": "", "out_step": ""}))
p = subprocess.run([str(fa.freecad_cmd()), str(probe)], env={**os.environ, "SHILPA_FC_JOB": str(job)}, capture_output=True, text=True, timeout=180)
print("\n".join(l for l in p.stdout.splitlines() if l.startswith(("OBJ", "SKETCH", "  ", "BUILD"))))
print("\n".join(l for l in p.stderr.splitlines() if "%" not in l and l.strip())[-2500:])
