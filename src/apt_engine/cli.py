"""apt-engine CLI.

  apt-engine detect <repo_path>   # on-disk APT phase detection -> JSON
  apt-engine chain                # print canonical phase chain + contracts
  apt-engine gate <from> <to>     # evaluate a transition (preconds via flags)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .detect import detect_phase
from .gate import evaluate_transition
from .phases import PHASES


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
    result = evaluate_transition(
        args.from_phase,
        args.to_phase,
        precondition_met=not args.precondition_unmet,
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
    return 0


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
    g.add_argument("--precondition-unmet", action="store_true")
    g.add_argument("--conditional", action="store_true")
    g.add_argument("--skip", action="store_true")
    g.set_defaults(func=_cmd_gate)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
