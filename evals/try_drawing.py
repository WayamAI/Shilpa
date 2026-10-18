"""Live drawing extraction check: ingest + gpt extraction for one or more drawings.

Run:  uv run python evals/try_drawing.py P01_vector [F01_scan ...]
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shilpa.agent.llm import Budget  # noqa: E402
from shilpa.drawings.extract import extract, to_requirements  # noqa: E402

for name in sys.argv[1:]:
    out = Path(__file__).parent / "out" / "try_drawing" / name
    subprocess.run([sys.executable, "-m", "shilpa.drawings.ingest", str(Path(__file__).parent / "drawings" / f"{name}.pdf"), str(out)], check=True)
    ing = json.loads((out / "ingest.json").read_text(encoding="utf-8"))
    b = Budget(input_tokens=60000, output_tokens=12000, deadline=time.time() + 600)
    t0 = time.time()
    ex = extract(ing, out, b)
    req = to_requirements(ex)
    print(f"== {name}  [{time.time() - t0:.1f}s, tokens {b.used_input}/{b.used_output}]  status={req['status']} family={req['family']} units={req['units']}")
    for d in ex["dimensions"]:
        print(f"   {d['name']:28} {str(d['value']):>8} {d['unit'] or '':3} {d['kind']:6} conf={d['confidence']:6} verified={d['verified']}  '{d['original_text']}'")
    for k in ("missing", "conflicts", "ignored_instructions", "assumptions"):
        if ex.get(k):
            print(f"   {k}: {ex[k]}")
