"""APT config-resolver drift detection — stdlib core, no KG/jinja needed."""

from apt_engine.resolver import (
    CORE_MAGIC_FIELDS,
    DictConfigSource,
    check_drift,
    find_markers,
    verify_core_present,
)
from apt_engine.resolver.config_source import MissingConfigError

import pytest

CFG = {
    "vibe_coding_sweet_min": 200,
    "vibe_coding_sweet_max": 500,
    "lens_count_constitutional": 9,
    "contract_default_fields": 7,
    "st_decision_areas": 8,
}


def test_find_markers_dedup_sorted():
    body = "use {{ cfg.st_decision_areas }} and {{cfg.lens_count_constitutional}} and {{ cfg.st_decision_areas }}"
    assert find_markers(body) == ("lens_count_constitutional", "st_decision_areas")


def test_clean_template_is_ok():
    body = (
        "budget {{cfg.vibe_coding_sweet_min}}-{{cfg.vibe_coding_sweet_max}} lines, "
        "{{cfg.lens_count_constitutional}} lenses, {{cfg.contract_default_fields}} fields, "
        "{{cfg.st_decision_areas}} areas"
    )
    report = check_drift(body, CFG)
    assert report.ok
    assert report.missing_in_cfg == ()
    assert report.bare_inline_numbers == ()


def test_bare_magic_number_is_drift():
    body = "keep tasks under 500 lines"  # hardcoded magic instead of {{cfg.vibe_coding_sweet_max}}
    report = check_drift(body, CFG)
    assert not report.ok
    assert (1, "500") in report.bare_inline_numbers


def test_parenthetical_hint_is_not_drift():
    body = "tasks stay within the sweet spot (현재 200-500)"
    report = check_drift(body, CFG)
    assert report.bare_inline_numbers == ()


def test_marker_missing_from_cfg_is_drift():
    body = "uses {{cfg.nonexistent_field}}"
    report = check_drift(body, CFG)
    assert not report.ok
    assert "nonexistent_field" in report.missing_in_cfg


def test_orphan_cfg_field_when_unreferenced():
    body = "only {{cfg.st_decision_areas}} referenced"
    report = check_drift(body, CFG)
    # all other core fields are present in cfg but unreferenced -> orphans
    assert "vibe_coding_sweet_min" in report.orphan_cfg_fields
    assert "st_decision_areas" not in report.orphan_cfg_fields


def test_dict_config_source_roundtrip():
    src = DictConfigSource(CFG)
    assert src.fetch() == CFG


def test_verify_core_present_passes_and_fails():
    verify_core_present(CFG)  # no raise
    with pytest.raises(MissingConfigError):
        verify_core_present({"vibe_coding_sweet_min": 200})
    assert set(CORE_MAGIC_FIELDS) == set(CFG)
