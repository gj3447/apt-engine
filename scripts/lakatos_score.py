#!/usr/bin/env python3
"""LakatosTree scorer for apt-engine — emits REAL pytest pass-counts as metrics.

No fake green: each metric is the number of *passing* tests collected from an
actual pytest run, so submit_result reflects a receipt, not a claimed number.

Usage:
    PYTHONPATH=src python3 scripts/lakatos_score.py
Prints JSON: {"reconcile": N, "legion": N, "suite_total": N}
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = {"PYTHONPATH": "src"}


def _passed(args: list[str]) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, **ENV},
    )
    out = proc.stdout + proc.stderr
    m = re.search(r"(\d+) passed", out)
    if not m or " failed" in out:
        raise SystemExit(f"scoring run not clean-green:\n{out[-500:]}")
    return int(m.group(1))


def main() -> int:
    metrics = {
        "reconcile": _passed(["tests/test_phase_map.py"]),
        "legion": _passed(["tests/test_legion.py"]),
        "gate_override": _passed(["tests/test_gate_override.py"]),
        "mcp_frontend": _passed(["tests/test_mcp_frontend.py"]),
        "suite_total": _passed([]),
    }
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
