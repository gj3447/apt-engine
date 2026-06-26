from pathlib import Path

import pytest

from apt_engine.detect import detect_phase

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
        "SA", "SP", "ST", "SCW", "MetaReview", "Cleanup",
    ]
