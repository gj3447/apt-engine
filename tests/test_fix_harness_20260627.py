"""APT fix harness (2026-06-27) — RED-first executable spec of the deep-think fixes.

Each test in SECTION A encodes the *target post-fix behavior* and FAILS against
HEAD today; driving it green IS the fix. SECTION B are ratchet pins that pass
NOW — they lock invariants the deep-think found correct-but-unguarded, so a
future regression goes red.

Provenance: the 2026-06-27 adversarial deep-think (46-agent workflow, 34 findings
25 survived) — see memory `apt-engine-repo-and-kg`. Frontier map:

  A1/A2  frontier #3  — FRONTEND FAIL-CLOSED.
         `_gate`(mcp) and the CLI default `precondition_met=True`, so an
         unstated precondition silently PASSes (cli.py:46, mcp_server.py:38).
         silence==PASS is a textbook fake-green surface in an anti-fake-green
         substrate. FIX: default fail-closed (unstated precondition => not PASS).
         CLI: replace `--precondition-unmet` with opt-in `--precondition-met`
         (`precondition_met=args.precondition_met`); mcp `_gate` default False.

  A3/A4/A5  frontier #1 (🥇) — MEASURED PRECONDITION for one transition.
         The gate's only content-truth input is a caller bool; truth is never
         established (detect.py is unwired, and wiring it is the *refuted* answer
         — markers over self-authored prose != the fact). FIX: a new stdlib
         module `apt_engine.precondition` that runs SCW's mandated impact_tests
         (phases.py:81 "TDAD impact_tests mandatory") and computes the verdict
         from a REAL pytest exit code — an external fact, not an assertion.
         Contract (this test IS the spec):
            measure(runner, target) -> PreconditionEvidence(met, exit_code, source)
            evaluate_measured(from_phase, to_phase, *, runner, target,
                              conditional=False, skipped=False) -> GateResult
         `runner: Callable[[str], int]` is injected (DIP, like the engine's other
         I/O); the real default runner shells out to pytest via subprocess (NOT
         unit-tested here). CRUCIALLY `evaluate_measured` exposes NO
         `precondition_met` parameter — truth is measured, never overridable.

  A6  T5 — CLEANUP PROVENANCE. Cleanup's precond/postcond and
         gate_version_on_fail="v27_phase_cleanup_dispatch_guard" (phases.py:100-102)
         are an ENGINE INVENTION — the phase-contract ADR's tables both end at
         MetaReview. The SSOT must not present invented rows as transcribed.
         FIX: add `Phase.provenance: str` ("adr" default), set Cleanup -> "engine-local".

  A7  frontier #5 — TRUTH IN ADVERTISING. README:107 still says "21 passing"
         (actual 71). FIX: update the README; stop understating.

  B1/B2  frontier #4 — ratchet pins (green now): detect markers cover exactly
         the CHAIN; Phase.number equals tuple position (the dual source behind
         next_phase's off-by-one indexing).

Run RED split:   PYTHONPATH=src python -m pytest tests/test_fix_harness_20260627.py -v
Confirm no regression:
                 PYTHONPATH=src python -m pytest -q --ignore=tests/test_fix_harness_20260627.py
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from apt_engine.detect import _SUBJECT_RE
from apt_engine.frontends.mcp_server import build_tools
from apt_engine.phases import CHAIN, PHASES, phase_by_name

_README = Path(__file__).resolve().parents[1] / "README.md"


# ====================================================================== #
#  SECTION A — RED-first fix specs (must FAIL at HEAD; green == fixed)    #
# ====================================================================== #

# --- A1/A2: frontend fail-closed -------------------------------------- #


def test_mcp_gate_does_not_silently_pass_on_unstated_precondition():
    """An adjacent transition with the precondition UNSTATED must not PASS."""
    apt_gate = build_tools()["apt_gate"]
    r = apt_gate("SA", "SP")  # precondition deliberately not asserted
    assert r["verdict"] != "PASS", (
        "fail-open: unstated precondition yielded PASS — frontend must default "
        "fail-closed (mcp_server.py:38 `precondition_met: bool = True`)"
    )


def test_cli_gate_does_not_silently_pass_on_unstated_precondition(capsys):
    """`apt-engine gate SA SP` with no precondition flag must not print PASS."""
    import json

    from apt_engine.cli import main

    rc = main(["gate", "SA", "SP"])
    out = json.loads(capsys.readouterr().out)
    # fail-closed at BOTH layers: non-PASS verdict AND nonzero exit (red-team H-A).
    assert rc == 1
    assert out["verdict"] != "PASS", (
        "fail-open: CLI defaulted precondition_met=True — precondition is now "
        "opt-in (`--precondition-met`), default unmet, and exit 0 iff PASS"
    )


# --- A3/A4/A5: 🥇 measured precondition (new stdlib module) ------------ #


def test_precondition_module_exists():
    """The measured-precondition resolver module must exist."""
    from apt_engine.precondition import evaluate_measured, measure  # noqa: F401


def test_measured_precondition_pytest_pass_unlocks_metareview():
    """A real pytest PASS (exit 0) on impact_tests => SCW->MetaReview PASS."""
    from apt_engine.precondition import evaluate_measured

    passing_runner = lambda target: 0  # noqa: E731  (injected fake; real one shells to pytest)
    r = evaluate_measured("SCW", "MetaReview", runner=passing_runner, target="impact_tests")
    assert r.verdict.value == "PASS"


def test_measured_precondition_pytest_fail_blocks_and_truth_is_unforgeable():
    """A real pytest FAIL (exit 1) => FAIL, and truth must be MEASURED, not asserted."""
    from apt_engine.precondition import evaluate_measured

    failing_runner = lambda target: 1  # noqa: E731
    r = evaluate_measured("SCW", "MetaReview", runner=failing_runner, target="impact_tests")
    assert r.verdict.value == "FAIL"
    # Anti-fake-green guard: there must be NO caller bool that overrides the
    # measurement — otherwise we have re-introduced the very gap we are closing.
    sig = inspect.signature(evaluate_measured)
    assert "precondition_met" not in sig.parameters, (
        "evaluate_measured exposes precondition_met — truth must be measured "
        "from the runner's exit code, never caller-asserted"
    )


# --- A6: Cleanup provenance honesty ----------------------------------- #


def test_cleanup_rows_are_marked_engine_local_not_canonical():
    """Cleanup's invented contract rows must self-declare non-ADR provenance."""
    cleanup = phase_by_name("Cleanup")
    assert getattr(cleanup, "provenance", "adr") == "engine-local", (
        "Cleanup precond/postcond/gate_version are an engine invention (the "
        "phase-contract ADR ends at MetaReview) but the SSOT presents them as "
        "transcribed — add Phase.provenance and mark Cleanup 'engine-local'"
    )
    # ADR-backed phases must stay marked canonical (no over-correction).
    assert getattr(phase_by_name("SCW"), "provenance", "adr") == "adr"


# --- A7: truth in advertising ----------------------------------------- #


def test_readme_carries_no_stale_numeric_test_count():
    # Not just the old "21 passing": any hard-coded "<n> passing" goes stale.
    text = _README.read_text(errors="replace")
    stale = re.findall(r"\b\d+\s+passing\b", text)
    assert not stale, f"README advertises a hard-coded test count {stale} that will go stale"


# ====================================================================== #
#  SECTION B — ratchet pins (GREEN now; lock unguarded invariants)       #
# ====================================================================== #


def test_detect_patterns_cover_exactly_the_chain():
    """detect.py's de-drift guarantee is order-only; pin MEMBERSHIP too."""
    assert set(_SUBJECT_RE) == set(CHAIN), (
        "detect markers and the canonical CHAIN have diverged in membership"
    )


def test_phase_number_equals_tuple_position():
    """next_phase indexes PHASES by `.number`; lock number == position+1."""
    assert all(p.number == i + 1 for i, p in enumerate(PHASES)), (
        "Phase.number drifted from tuple position — next_phase would mis-index"
    )
