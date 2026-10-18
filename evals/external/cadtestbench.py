"""Loader stub for CADTestBench (evaluation only, never training).

Source   https://huggingface.co/datasets/dimitrismallis/CADTestBench  (code: https://github.com/dimitrismallis/CADTestBench)
Paper    https://arxiv.org/html/2605.07807v1
Licence  MIT on both the dataset card and the repository (checked 2026-10-18). The 200 prompts derive from
         CADPrompt (arXiv 2410.05340), whose own data licence was NOT verified; legal review of the upstream
         licence is required before results are published (roadmap: "external benchmarks as evaluation only,
         after legal review of each data licence").
Size     about 1.3 MB of parquet: `samples` (200 sample_ids x abstract/detailed prompts) and `cadtests`
         (5,937 CadQuery test snippets with requirement ids and types).

Nothing is downloaded unless ``--download`` is passed; files go to evals/external/data/cadtestbench/
(gitignored, kept apart from results and never committed). The official tests are CadQuery
predicates over a ``cq.Workplane``; running them needs CadQuery, which Shilpa does not depend on. The intended
path is: prompt -> Shilpa -> STEP -> ``cq.importers.importStep`` -> official ``cadtestbench evaluate`` harness,
reporting Pass Rate per partition and the invalid rate (R1 gates: >=0.80 abstract, >=0.65 detailed, invalid <2%).

Run:  uv run python evals/external/cadtestbench.py [--download]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = "dimitrismallis/CADTestBench"
DATA = Path(__file__).parent / "data" / "cadtestbench"
API = f"https://huggingface.co/api/datasets/{REPO}/parquet"


def download() -> list[Path]:
    """Fetch the auto-converted parquet files listed by the Hugging Face datasets API."""
    import httpx

    DATA.mkdir(parents=True, exist_ok=True)
    index = httpx.get(API, timeout=30, follow_redirects=True).json()  # {config: {split: [urls]}}
    out = []
    for config, splits in index.items():
        for split, urls in splits.items():
            for i, url in enumerate(urls):
                path = DATA / f"{config}-{split}-{i}.parquet"
                r = httpx.get(url, timeout=120, follow_redirects=True)
                r.raise_for_status()
                if len(r.content) > 50 * 1024 * 1024:
                    raise SystemExit(f"{url} is larger than expected ({len(r.content)} bytes); stopping")
                path.write_bytes(r.content)
                out.append(path)
    return out


def load_samples(partition: str = "abstract") -> list[dict]:
    """Prompts for one partition ('abstract' or 'detailed'). Requires a prior --download."""
    import pandas as pd  # optional dependency, only for this stub

    files = sorted(DATA.glob(f"samples-{partition}-*.parquet"))
    if not files:
        raise FileNotFoundError("CADTestBench not downloaded; run with --download")
    return pd.concat(pd.read_parquet(f) for f in files).to_dict("records")


def status() -> dict:
    have = sorted(p.name for p in DATA.glob("*.parquet")) if DATA.exists() else []
    return {"benchmark": "CADTestBench", "downloaded": bool(have), "files": have, "licence": "MIT (upstream CADPrompt unverified)",
            "run": "not yet run", "url": f"https://huggingface.co/datasets/{REPO}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()
    if args.download:
        for p in download():
            print(f"saved {p} ({p.stat().st_size} bytes)")
    print(json.dumps(status(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
