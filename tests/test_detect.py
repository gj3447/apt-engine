import os
from pathlib import Path

import pytest

from apt_engine.detect import (
    _contiguous_prefix,
    _looks_like_table_of_contents,
    detect_phase,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_scw_repo_detects_scw_as_current():
    report = detect_phase(str(FIXTURES / "scw_repo"))
    assert report["current_phase"] == "SCW"
    assert report["confidence"] == "EXTRACTED"
    assert "apt-progress.md" in report["evidence_sources"]
    assert "feature-spans.json" in report["evidence_sources"]
    assert report["phases_detected"]["SA"] is True
    assert report["phases_detected"]["SCW"] is True
    # No MetaReview/Cleanup markers in the fixture.
    assert report["phases_detected"]["MetaReview"] is False
    assert report["phases_detected"]["Cleanup"] is False


def test_spans_summary_parsed():
    report = detect_phase(str(FIXTURES / "scw_repo"))
    names = {s["name"] for s in report["spans_summary"]}
    assert {"root", "parse-input", "emit-output"} <= names


def test_empty_repo_is_unknown_not_fabricated():
    report = detect_phase(str(FIXTURES / "empty_repo"))
    assert report["current_phase"] == "unknown"
    assert report["confidence"] == "AMBIGUOUS"
    assert report["evidence_sources"] == []


def test_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        detect_phase(str(FIXTURES / "does_not_exist"))


def test_detected_map_uses_canonical_chain_keys():
    report = detect_phase(str(FIXTURES / "scw_repo"))
    assert list(report["phases_detected"].keys()) == [
        "SA",
        "SP",
        "ST",
        "SCW",
        "MetaReview",
        "Cleanup",
    ]


# --------------------------------------------------------------------------- #
#  PROM16 C1/C3 fix: a listing / stray keyword / forward leap must NOT be       #
#  reported as a confident phase. Root cause = a phase needs an explicit STATUS #
#  word next to its name to count as progress (a bare mention is not progress). #
# --------------------------------------------------------------------------- #


def test_roadmap_of_bare_phase_names_detects_nothing():
    # THE regression + root cause: an untouched repo whose apt-progress.md merely
    # LISTS phase names (no status words) used to report current_phase=Cleanup at
    # EXTRACTED. Bare names are a plan, not progress -> nothing detected -> unknown.
    report = detect_phase(str(FIXTURES / "roadmap_repo"))
    assert report["current_phase"] == "unknown"  # not fabricated as Cleanup
    assert report["confidence"] == "AMBIGUOUS"  # not EXTRACTED
    assert not any(report["phases_detected"].values())  # no status word => no marker


def test_scw_prefix_stays_confident_after_the_fix():
    # the guard must NOT touch a genuine in-progress prefix. (Also: the status-
    # required regex fixes the previously-dead ST 'crystalliz' alternative, so the
    # fixture line 'ST crystallization complete' now detects ST.)
    report = detect_phase(str(FIXTURES / "scw_repo"))
    assert report["current_phase"] == "SCW"
    assert report["confidence"] == "EXTRACTED"
    assert report["phases_detected"]["ST"] is True


def test_stray_terminal_keyword_does_not_fabricate_late_phase(tmp_path):
    # HIGH bug: a stray 'cleanup'/'ratchet' in an in-progress doc used to report
    # current_phase=Cleanup@EXTRACTED. The terminal now needs a status word.
    (tmp_path / "apt-progress.md").write_text(
        "- SA bootstrap complete\n- SP decomposition in progress\n"
        "## Future cleanup work will run a ratchet later\n"
    )
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "SP"  # the REAL phase, not Cleanup
    assert report["phases_detected"]["Cleanup"] is False


def test_bare_metareview_mention_not_detected(tmp_path):
    (tmp_path / "apt-progress.md").write_text(
        "- SA bootstrap complete\nWe should schedule a Meta-Review at the very end.\n"
    )
    report = detect_phase(str(tmp_path))
    assert report["phases_detected"]["MetaReview"] is False
    assert report["current_phase"] == "SA"


def test_forward_leap_over_gap_downgrades_to_contiguous(tmp_path):
    # SA complete then a status-bearing Cleanup, but SP/ST/SCW absent: a leap over
    # a gap -> report the furthest gap-free phase (SA) at AMBIGUOUS (C1 invariant),
    # never a confident Cleanup. The raw Cleanup marker stays visible.
    (tmp_path / "apt-progress.md").write_text(
        "- SA bootstrap complete\n- Cleanup ratchet complete\n"
    )
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "SA"
    assert report["confidence"] == "AMBIGUOUS"
    assert report["phases_detected"]["Cleanup"] is True


def test_saturated_status_map_is_unknown(tmp_path):
    # every phase marked (each as its own line subject) WITH a status word ->
    # indistinguishable from a full listing/template -> unknown (saturation guard).
    (tmp_path / "apt-progress.md").write_text(
        "- SA complete\n- SP complete\n- ST complete\n- SCW complete\n"
        "- MetaReview complete\n- Cleanup complete\n"
    )
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "unknown"
    assert report["confidence"] == "AMBIGUOUS"


def test_both_terminal_status_marked_is_unknown(tmp_path):
    # MetaReview + Cleanup both marked (as line subjects) -> saturation -> unknown.
    (tmp_path / "apt-progress.md").write_text("- MetaReview complete\n- Cleanup complete\n")
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "unknown"
    assert report["confidence"] == "AMBIGUOUS"


def test_negated_status_is_not_progress(tmp_path):
    # HIGH (review): "SA not complete" etc. must NOT report progress. A negation
    # before the status word disqualifies the line.
    (tmp_path / "apt-progress.md").write_text(
        "- SA not complete\n- SP not complete\n- ST is not done yet\n"
    )
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "unknown"
    assert not any(report["phases_detected"].values())


def test_negation_after_status_still_detects(tmp_path):
    # "SA complete, no blockers" — the negation is AFTER the status, so SA IS done.
    (tmp_path / "apt-progress.md").write_text("- SA scoping complete, no blockers\n")
    report = detect_phase(str(tmp_path))
    assert report["phases_detected"]["SA"] is True


def test_mid_sentence_phase_token_is_not_a_marker(tmp_path):
    # "the SP diagram is complete" / "CI ratchet gate passed" / "St. Louis ...
    # complete": the phase-looking token is NOT the line subject -> not detected.
    (tmp_path / "apt-progress.md").write_text(
        "- SA anchor complete\n"
        "- SP decomposition complete\n"
        "- the ST diagram is complete\n"  # ST mid-sentence, not the subject
        "- CI ratchet gate passed on this PR\n"  # 'ratchet' mid-line, not Cleanup
        "- The St. Louis rollout is complete\n"  # 'St.' must not match ST
    )
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "SP"  # only SA + SP are genuine subjects
    assert report["phases_detected"]["ST"] is False
    assert report["phases_detected"]["Cleanup"] is False


def test_genuine_near_complete_prefix_stays_extracted(tmp_path):
    # SA..MetaReview marked but NOT Cleanup -> not saturated, contiguous -> confident.
    (tmp_path / "apt-progress.md").write_text(
        "- SA bootstrap complete\n- SP decomposition complete\n"
        "- ST contract complete\n- SCW implementation complete\n- MetaReview done\n"
    )
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "MetaReview"
    assert report["confidence"] == "EXTRACTED"


def test_looks_like_table_of_contents_unit():
    chain = ["SA", "SP", "ST", "SCW", "MetaReview", "Cleanup"]
    all_true = {p: True for p in chain}
    assert _looks_like_table_of_contents(all_true) is True
    both_terminal = {p: False for p in chain}
    both_terminal["MetaReview"] = both_terminal["Cleanup"] = True
    assert _looks_like_table_of_contents(both_terminal) is True
    ordinary_prefix = {p: False for p in chain}
    ordinary_prefix["SA"] = ordinary_prefix["SP"] = ordinary_prefix["SCW"] = True
    assert _looks_like_table_of_contents(ordinary_prefix) is False


def test_contiguous_prefix_unit():
    chain = ["SA", "SP", "ST", "SCW", "MetaReview", "Cleanup"]
    full_prefix = {p: False for p in chain}
    full_prefix["SA"] = full_prefix["SP"] = full_prefix["ST"] = full_prefix["SCW"] = True
    assert _contiguous_prefix(full_prefix) == ("SCW", True)
    gapped = {p: False for p in chain}
    gapped["SA"] = gapped["Cleanup"] = True  # leap over a gap
    assert _contiguous_prefix(gapped) == ("SA", False)
    empty = {p: False for p in chain}
    assert _contiguous_prefix(empty) == ("unknown", True)


# --------------------------------------------------------------------------- #
#  soundness: schema uniformity, spans-only, never-crash on a raced artifact    #
# --------------------------------------------------------------------------- #


def test_empty_report_includes_spans_summary_key():
    # every return path must carry spans_summary (schema uniformity; review fix).
    report = detect_phase(str(FIXTURES / "empty_repo"))
    assert report["spans_summary"] == []


def test_spans_only_repo_is_unknown_not_inferred(tmp_path):
    # feature-spans.json present, apt-progress.md ABSENT: phase can't be inferred
    # from spans in the stdlib core, so 'unknown'/AMBIGUOUS (never a fabricated
    # INFERRED phase — that label is reserved, not emitted).
    (tmp_path / "feature-spans.json").write_text(
        '{"spans": [{"name": "root", "depth": 0, "status": "complete"}]}'
    )
    report = detect_phase(str(tmp_path))
    assert report["current_phase"] == "unknown"
    assert report["confidence"] == "AMBIGUOUS"
    assert report["confidence"] != "INFERRED"
    assert {s["name"] for s in report["spans_summary"]} == {"root"}


def test_malformed_spans_json_degrades_not_crash(tmp_path):
    (tmp_path / "apt-progress.md").write_text("- SA bootstrap complete\n")
    (tmp_path / "feature-spans.json").write_text("{ not valid json")
    report = detect_phase(str(tmp_path))  # must not raise
    assert report["current_phase"] == "SA"
    assert report["spans_summary"] == []


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_unreadable_progress_file_does_not_crash(tmp_path):
    # TOCTOU/permission race: is_file() True but read raises OSError -> degrade to
    # 'unknown' rather than propagate a traceback (the detector never raises for a
    # soft failure).
    p = tmp_path / "apt-progress.md"
    p.write_text("- SCW implementation in progress\n")
    p.chmod(0o000)
    try:
        report = detect_phase(str(tmp_path))  # must not raise
    finally:
        p.chmod(0o644)  # let tmp_path cleanup remove it
    assert report["current_phase"] == "unknown"
    assert report["confidence"] == "AMBIGUOUS"
