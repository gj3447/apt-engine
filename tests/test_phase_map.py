"""(a) v9 ↔ v27 reconciliation — revert-proof invariants.

Each test bites if the map drops a phase, points at a non-existent v27 phase,
or leaves a v27 phase unreached. That is the double-guard: the map cannot drift
from `phases.CHAIN` without turning this suite red.
"""

from apt_engine.phase_map import (
    V9_PHASES,
    V9_TO_V27,
    is_onto,
    is_total,
    orphans,
    to_v27,
    to_v9,
)
from apt_engine.phases import CHAIN


def test_map_is_total_every_v9_phase_mapped():
    assert is_total()
    assert set(V9_TO_V27.keys()) == set(V9_PHASES)


def test_map_is_onto_no_orphan_v27_phase():
    assert orphans() == ()
    assert is_onto()


def test_every_mapped_v27_name_is_a_real_phase():
    for v9, v27s in V9_TO_V27.items():
        for v27 in v27s:
            assert v27 in CHAIN, f"{v9} maps to non-existent v27 phase {v27!r}"


def test_ph1_and_ph2_both_fold_into_sa():
    assert to_v27("v9_PH1_SA") == ("SA",)
    assert to_v27("v9_PH2_Root") == ("SA",)
    assert set(to_v9("SA")) == {"v9_PH1_SA", "v9_PH2_Root"}


def test_clean_one_to_one_middle():
    assert to_v27("v9_PH3_SP") == ("SP",)
    assert to_v27("v9_PH4_ST") == ("ST",)
    assert to_v27("v9_PH5_SCW") == ("SCW",)


def test_feedback_fans_out_to_metareview_and_cleanup():
    assert to_v27("v9_PH6_Feedback") == ("MetaReview", "Cleanup")
    assert to_v9("MetaReview") == ("v9_PH6_Feedback",)
    assert to_v9("Cleanup") == ("v9_PH6_Feedback",)


def test_inverse_round_trips():
    # For every v9 phase, it appears in the inverse image of each v27 it maps to.
    for v9 in V9_PHASES:
        for v27 in to_v27(v9):
            assert v9 in to_v9(v27)
