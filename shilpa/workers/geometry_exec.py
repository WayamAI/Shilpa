"""Restricted geometry subprocess: one recipe in, artifacts and result.json out.

Started by the CAD worker with a scrubbed environment (no model keys, no database
URL). It reads only its recipe file and writes only into its output directory.
A cancel flag file is checked between modeling operations.

  python -m shilpa.workers.geometry_exec <recipe.json> <out_dir> [<cancel_flag>]
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def main() -> int:
    recipe_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    cancel_flag = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from shilpa.pipeline import execute

        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        res = execute(recipe, out_dir, cancel_check=(lambda: cancel_flag.exists()) if cancel_flag else None)
        payload = res.to_dict()
    except Exception as exc:  # last resort: report instead of dying silently
        from shilpa.contracts.errors import ErrorCode, ShilpaError

        info = exc.info if isinstance(exc, ShilpaError) else ShilpaError(ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}").info
        payload = {"ok": False, "error": info.model_dump(mode="json"), "features": [], "validation": None,
                   "artifacts": [], "trace": traceback.format_exc()[-4000:]}
    (out_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
