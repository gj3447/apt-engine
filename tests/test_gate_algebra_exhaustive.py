"""Exhaustive gate-algebra sweep — the ENTIRE finite input space, enumerated.

The verdict algebra's input space is small: 6 phases x 6 phases x 2^3 flags =
288 tuples. Example-based tests sample it; this module enumerates ALL of it
(finite domain -> enumerate, don't sample — stdlib `itertools.product`, no
Hypothesis dependency, per the stdlib-only-core rule). 72 tuples are the
contradictory `conditional & skipped` combos and must raise ValueError
(gate.py precedence step 0); the remaining 216 are compared against a pure
precedence ORACLE that independently restates the docstring's branch order,
turning the prose contract into an executable, diffable one.

# KG: rf-prom16-apt-gate-exhaustive-test, rf-prom16-apt-conditional-unenforced
#     (cycle prom16-apt-engine-hardening-2026-07-13, cells A1/A4/A3)
"""

import itertools

import pytest

from apt_engine.gate import Verdict, can_advance, evaluate_transition
from apt_engine.phases import CHAIN, is_self_application, next_phase, phase_by_name

_FLAGS = (False, True)
_ALL = list(itertools.product(CHAIN, CHAIN, _FLAGS, _FLAGS, _FLAGS))
_VALID = [t for t in _ALL if not (t[3] and t[4])]  # conditional & skipped excluded
_CONTRADICTORY = [t for t in _ALL if t[3] and t[4]]


def _oracle(frm: str, to: str, pre: bool, cond: bool, skip: bool) -> Verdict:
    """The docstring's precedence order (steps 1-6) as an independent function.

    Deliberately NOT calling into gate.py's branch logic — this is a second,
    parallel statement of the contract, so a precedence regression in either
    place breaks the agreement test below.
    """
    if is_self_application(frm, to):
        return Verdict.FAIL
    expected = next_phase(frm)
    if expected is None or expected.name != to:
        return Verdict.FAIL
    if skip:
        return Verdict.SKIP
    if not pre:
        return Verdict.FAIL
    if cond:
        return Verdict.CONDITIONAL
    return Verdict.PASS


def test_sweep_covers_the_full_finite_space():
    # 6 x 6 x 2 x 2 x 2 = 288; contradictory = 6 x 6 x 2 (precondition free) = 72.
    assert len(_ALL) == 288
    assert len(_VALID) == 216
    assert len(_CONTRADICTORY) == 72


def test_precedence_oracle_agrees_on_every_valid_tuple():
    # THE core sweep: gate.py's branch order == the docstring order, everywhere.
    for frm, to, pre, cond, skip in _VALID:
        r = evaluate_transition(frm, to, precondition_met=pre, conditional=cond, skipped=skip)
        expected = _oracle(frm, to, pre, cond, skip)
        assert r.verdict is expected, (
            f"precedence mismatch at ({frm}->{to}, pre={pre}, cond={cond}, "
            f"skip={skip}): gate={r.verdict}, oracle={expected}"
        )


def test_only_pass_unlocks_across_all_valid_tuples():
    for frm, to, pre, cond, skip in _VALID:
        r = evaluate_transition(frm, to, precondition_met=pre, conditional=cond, skipped=skip)
        assert can_advance(r.verdict) == (r.verdict is Verdict.PASS), (
            f"unlock rule broken at ({frm}->{to}, pre={pre}, cond={cond}, skip={skip})"
        )


def test_skip_never_unlocks_and_is_skip_when_reachable():
    # skipped=True: never an advance; and exactly SKIP once the structural
    # failures (self-application / non-adjacency) don't pre-empt it.
    for frm, to, pre, cond, skip in _VALID:
        if not skip:
            continue
        r = evaluate_transition(frm, to, precondition_met=pre, conditional=cond, skipped=True)
        assert can_advance(r.verdict) is False, f"SKIP advanced at ({frm}->{to}, pre={pre})"
        structural_fail = is_self_application(frm, to) or (
            next_phase(frm) is None or next_phase(frm).name != to
        )
        expected = Verdict.FAIL if structural_fail else Verdict.SKIP
        assert r.verdict is expected, f"skip shape at ({frm}->{to}, pre={pre}): {r.verdict}"


def test_self_application_always_fails_regardless_of_flags():
    # MetaReview->MetaReview must FAIL for every VALID flag combo — the current
    # example tests never combine it with skipped/conditional (PROM16 A4 gap).
    for pre, cond, skip in itertools.product(_FLAGS, _FLAGS, _FLAGS):
        if cond and skip:
            continue  # contradictory combos covered below (they raise instead)
        r = evaluate_transition(
            "MetaReview", "MetaReview", precondition_met=pre, conditional=cond, skipped=skip
        )
        assert r.verdict is Verdict.FAIL
        assert "self_application_forbidden" in r.reason


def test_pure_transition_never_returns_error_across_all_valid_tuples():
    # ERROR (could-not-evaluate) is exclusively a measured-wrapper outcome — the
    # pure, I/O-free evaluate_transition has nothing that can be unevaluable, so
    # it may only ever yield PASS/FAIL/SKIP/CONDITIONAL. Pins the docstring claim.
    for frm, to, pre, cond, skip in _VALID:
        r = evaluate_transition(frm, to, precondition_met=pre, conditional=cond, skipped=skip)
        assert r.verdict is not Verdict.ERROR, (
            f"pure transition produced ERROR at ({frm}->{to}, pre={pre}, "
            f"cond={cond}, skip={skip})"
        )


def test_contradictory_flags_raise_on_every_tuple():
    # conditional & skipped is a caller bug for EVERY transition — including
    # self-application pairs (input validation precedes semantic evaluation).
    for frm, to, pre, _cond, _skip in _CONTRADICTORY:
        with pytest.raises(ValueError, match="mutually exclusive"):
            evaluate_transition(
                frm, to, precondition_met=pre, conditional=True, skipped=True
            )


def test_gate_version_iff_fail_and_reason_always_set():
    # BOTH directions, swept (adversarial-review CONFIRMED finding 2026-07-13:
    # asserting only "non-FAIL => None" let a mutation that DROPPED the
    # gate_version from a FAIL branch pass the whole suite): non-FAIL carries
    # None; every FAIL carries exactly the DESTINATION's canonical
    # gate_version_on_fail — and every result explains itself with a reason.
    for frm, to, pre, cond, skip in _VALID:
        r = evaluate_transition(frm, to, precondition_met=pre, conditional=cond, skipped=skip)
        assert r.reason, f"empty reason at ({frm}->{to}, pre={pre}, cond={cond}, skip={skip})"
        if r.verdict is Verdict.FAIL:
            assert r.gate_version == phase_by_name(to).gate_version_on_fail, (
                f"FAIL lost its canonical gate_version at ({frm}->{to}, pre={pre}, "
                f"cond={cond}, skip={skip}): {r.gate_version!r}"
            )
        else:
            assert r.gate_version is None, (
                f"non-FAIL carried gate_version at ({frm}->{to}, pre={pre}, "
                f"cond={cond}, skip={skip})"
            )
