from apt_engine.phases import (
    CHAIN,
    PHASES,
    is_self_application,
    next_phase,
    phase_by_name,
)


def test_canonical_order_matches_adr_not_skeleton():
    # ADR: SA -> SP -> ST -> SCW -> MetaReview(Phase5) -> Cleanup(Phase6).
    # The bhgman_tool skeleton reversed the last two; we must NOT.
    assert CHAIN == ("SA", "SP", "ST", "SCW", "MetaReview", "Cleanup")
    assert [p.number for p in PHASES] == [1, 2, 3, 4, 5, 6]


def test_phase_numbers_are_sequential_and_unique():
    numbers = [p.number for p in PHASES]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)


def test_lookup_by_name_and_alias():
    assert phase_by_name("scw").name == "SCW"
    assert phase_by_name("Meta-Review").name == "MetaReview"
    assert phase_by_name("Phase 6").name == "Cleanup"


def test_unknown_phase_raises():
    try:
        phase_by_name("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for unknown phase")


def test_next_phase_walks_chain_then_terminates():
    assert next_phase("SA").name == "SP"
    assert next_phase("SCW").name == "MetaReview"
    assert next_phase("MetaReview").name == "Cleanup"
    assert next_phase("Cleanup") is None


def test_gate_version_strings_are_canonical():
    assert phase_by_name("SA").gate_version_on_fail == "v27_phase_sa_no_topic"
    assert phase_by_name("SCW").gate_version_on_fail == "v27_phase_scw_dispatch_guard"
    assert (
        phase_by_name("MetaReview").gate_version_on_fail == "v27_phase_meta_review_dispatch_guard"
    )


def test_metareview_self_application_forbidden():
    assert is_self_application("MetaReview", "MetaReview") is True
    # Other phases recursing on themselves is not the forbidden MetaReview loop.
    assert is_self_application("SCW", "SCW") is False
    assert is_self_application("SCW", "MetaReview") is False


def test_optional_flags():
    assert phase_by_name("SA").optional is False
    assert phase_by_name("MetaReview").optional is True
    assert phase_by_name("Cleanup").optional is True
