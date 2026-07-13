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
from pathlib import Path
from typing import Sequence

from .detect import detect_phase
from .gate import Verdict, evaluate_transition
from .phases import PHASES
from .precondition import (
    evaluate_measured_default,
    evaluate_measured_default_with_receipt,
    evaluate_measured_mandated_default,
    evaluate_measured_mandated_default_with_receipt,
)
from .receipt import build_gate_receipt


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
    want_receipt = args.receipt_out is not None
    receipt = None
    if args.measure is not None and args.impact_manifest is not None:
        # Mandated measured path (H-C): the precondition is the transition's
        # MANDATED impact_tests (from the manifest) actually running green under
        # `target` — an unrelated passing dir FAILs.
        if want_receipt:
            result, receipt = evaluate_measured_mandated_default_with_receipt(
                args.from_phase,
                args.to_phase,
                target=args.measure,
                manifest_path=args.impact_manifest,
                conditional=args.conditional,
                skipped=args.skip,
            )
        else:
            result = evaluate_measured_mandated_default(
                args.from_phase,
                args.to_phase,
                target=args.measure,
                manifest_path=args.impact_manifest,
                conditional=args.conditional,
                skipped=args.skip,
            )
    elif args.measure is not None:
        # Bare measured path: a REAL pytest run on `target` (no caller bool, no
        # injectable runner). WEAK — runs whatever is under target; prefer
        # --impact-manifest to bind to the phase's mandated tests.
        if want_receipt:
            result, receipt = evaluate_measured_default_with_receipt(
                args.from_phase,
                args.to_phase,
                target=args.measure,
                conditional=args.conditional,
                skipped=args.skip,
            )
        else:
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
        if want_receipt:
            receipt = build_gate_receipt(result, gate_kind="asserted")
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
    if receipt is not None:
        # Auditable, replay-checkable record of this gate run (ADR-0003 honesty
        # boundary: records what was observed; not a security attestation).
        Path(args.receipt_out).write_text(receipt.to_json())
    # Fail-closed at the PROCESS boundary too: only an advancing PASS exits 0;
    # FAIL/SKIP/CONDITIONAL/ERROR exit nonzero so `&&` / `set -e` / CI pipelines block.
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
    g.add_argument(
        "--impact-manifest",
        metavar="PATH",
        default=None,
        help="with --measure: bind to the transition's MANDATED impact_tests "
        "declared in PATH (an unrelated passing dir then fails)",
    )
    # Mutually exclusive by gate semantics: a skipped transition was never
    # evaluated, a conditional one was (gate.py precedence step 0). Enforced at
    # the parser so the CLI errors cleanly (exit 2) instead of a traceback.
    flags = g.add_mutually_exclusive_group()
    flags.add_argument("--conditional", action="store_true")
    flags.add_argument("--skip", action="store_true")
    g.add_argument(
        "--receipt-out",
        metavar="PATH",
        default=None,
        help="write an auditable, replay-checkable GateReceipt (JSON) for this gate "
        "run to PATH (mandated path records mandated/matched node ids + pinned vs "
        "observed shas + pytest exit code + runner tier)",
    )
    g.set_defaults(func=_cmd_gate)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
