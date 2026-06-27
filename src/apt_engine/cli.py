"""apt-engine CLI.

  apt-engine detect <repo_path>   # on-disk APT phase detection -> JSON
  apt-engine chain                # print canonical phase chain + contracts
  apt-engine gate <from> <to>     # evaluate a transition; exit 0 iff PASS.
                                  #   default fail-closed; --precondition-met to assert,
                                  #   --measure TARGET to gate on a real pytest run.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .detect import detect_phase
from .gate import Verdict, evaluate_transition
from .phases import PHASES
from .precondition import evaluate_measured_default


def _cmd_detect(args: argparse.Namespace) -> int:
    print(json.dumps(detect_phase(args.repo_path), indent=2))
    return 0


def _cmd_chain(_args: argparse.Namespace) -> int:
    rows = [
        {
            "number": p.number,
            "name": p.name,
            "title": p.title,
            "optional": p.optional,
            "precondition": p.precondition,
            "postcondition": p.postcondition,
            "gate_version_on_fail": p.gate_version_on_fail,
        }
        for p in PHASES
    ]
    print(json.dumps(rows, indent=2))
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    if args.measure is not None:
        # Measured path: establish the precondition from a REAL pytest run on
        # `target` (no caller bool, no injectable runner) — frontier #1 wired.
        result = evaluate_measured_default(
            args.from_phase,
            args.to_phase,
            target=args.measure,
            conditional=args.conditional,
            skipped=args.skip,
        )
    else:
        result = evaluate_transition(
            args.from_phase,
            args.to_phase,
            precondition_met=args.precondition_met,
            conditional=args.conditional,
            skipped=args.skip,
        )
    print(
        json.dumps(
            {
                "from_phase": result.from_phase,
                "to_phase": result.to_phase,
                "verdict": result.verdict.value,
                "reason": result.reason,
                "gate_version": result.gate_version,
            },
            indent=2,
        )
    )
    # Fail-closed at the PROCESS boundary too: only an advancing PASS exits 0;
    # FAIL/SKIP/CONDITIONAL exit nonzero so `&&` / `set -e` / CI pipelines block.
    return 0 if result.verdict is Verdict.PASS else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apt-engine", description="APT phase-contract engine")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("detect", help="detect current APT phase from on-disk artifacts")
    d.add_argument("repo_path")
    d.set_defaults(func=_cmd_detect)

    c = sub.add_parser("chain", help="print the canonical APT phase chain")
    c.set_defaults(func=_cmd_chain)

    g = sub.add_parser("gate", help="evaluate a phase transition")
    g.add_argument("from_phase")
    g.add_argument("to_phase")
    g.add_argument(
        "--precondition-met",
        action="store_true",
        help="assert the destination precondition holds (default: fail-closed / unmet)",
    )
    g.add_argument(
        "--measure",
        metavar="TARGET",
        default=None,
        help="measure the precondition by running pytest on TARGET (overrides --precondition-met)",
    )
    g.add_argument("--conditional", action="store_true")
    g.add_argument("--skip", action="store_true")
    g.set_defaults(func=_cmd_gate)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
