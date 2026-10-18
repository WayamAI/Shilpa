"""Start the whole local stack: API, coordinator, CAD worker and (optionally) the studio.

Run:  uv run python -m shilpa.dev            # backend + studio dev server
      uv run python -m shilpa.dev --no-studio
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time

from .settings import ROOT, settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-studio", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    from .db import init_db

    init_db()
    py = sys.executable
    procs: list[tuple[str, subprocess.Popen]] = [
        ("api", subprocess.Popen([py, "-m", "uvicorn", "shilpa.api.app:app", "--port", str(args.port), "--host", "127.0.0.1"], cwd=ROOT)),
        ("coordinator", subprocess.Popen([py, "-m", "shilpa.coordinator"], cwd=ROOT)),
    ]
    for i in range(args.workers):
        procs.append((f"worker{i}", subprocess.Popen([py, "-m", "shilpa.workers.cad"], cwd=ROOT)))
    if not args.no_studio:
        npm = shutil.which("npm")
        if npm:
            procs.append(("studio", subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "apps" / "studio", shell=False)))
        else:
            print("npm not found; studio not started")

    print(f"\nShilpa local stack: API http://127.0.0.1:{args.port}  studio http://localhost:5173")
    print(f"Azure OpenAI planner: {'configured' if settings.llm_configured else 'NOT configured (set .env)'}\n")
    try:
        while True:
            for name, p in procs:
                if p.poll() is not None:
                    print(f"{name} exited with code {p.returncode}; stopping")
                    raise KeyboardInterrupt
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
