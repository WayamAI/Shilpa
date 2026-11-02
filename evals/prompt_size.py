"""Offline measurement of the plan system prompt: legacy fixed eight examples vs per-request selection.

Makes no model calls. Prints characters and an estimated token count (chars / 4) per corpus request.

Run:  uv run python evals/prompt_size.py [--k 3]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shilpa.agent import planner  # noqa: E402
from shilpa.agent.examples import select_example_ids  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    before_total = after_total = 0
    rows = sorted(planner.CORPUS.glob("*.json"))
    print(f"{'id':5} {'before chars':>12} {'after chars':>11} {'saved tok~':>10}  selected")
    for p in rows:
        fx = json.loads(p.read_text(encoding="utf-8"))
        query = f"{fx['description']} {fx.get('family', '')}"
        before = len(planner.plan_system(query, fx.get("family"), -1))
        after = len(planner.plan_system(query, fx.get("family"), args.k))
        before_total += before
        after_total += after
        print(f"{fx['id']:5} {before:12} {after:11} {(before - after) // 4:10}  {','.join(select_example_ids(query, args.k, fx.get('family')))}")
    n = len(rows)
    print(f"\nmean system prompt: {before_total // n} -> {after_total // n} chars "
          f"(~{before_total // n // 4} -> ~{after_total // n // 4} tokens, -{100 * (before_total - after_total) / before_total:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
