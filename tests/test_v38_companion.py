import json
from pathlib import Path

from build_v38_companion import build_state


def test_companion_ui_exposes_audited_semantics_and_keeps_legacy_dashboard():
    html = Path("command-center-v38.html").read_text(encoding="utf-8")
    assert "通常個別株の新規保有可能総数は最大4" in html
    assert "すべて当日終値で判定し、注文は次営業日寄りで執行" in html
    assert "M30_TOUCH30_F80_D10" in html
    for element_id in ("mcEntry", "seedAge", "underlyingTarget", "requestedTarget",
                       "otherExposure", "availableCapacity", "executableTarget"):
        assert f'id="{element_id}"' in html
    assert 'src="command-center.html"' in html


def test_companion_reads_legacy_without_rewriting_and_fails_closed_for_attack_theme(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    for i in range(40):
        det[f"T{i}"] = {
            "px": 100, "dvol": 20, "ma5020": True, "v200": 5,
            "v50": 5 if i < 26 else -5, "rs189": 90, "rs": 90,
            "sth": "Theme A",
        }
    source = tmp_path / "command-center.html"
    original = (f'<script>window.CALC={json.dumps(calc)};</script>'
                f'<script>window.DET={json.dumps(det)};</script>')
    source.write_text(original, encoding="utf-8")
    state = build_state(source)
    assert source.read_text(encoding="utf-8") == original
    assert state["market"]["mode"] == "ATTACK"
    assert state["market"]["breadth50"] == 65
    assert state["ranking"]["mode"] == "LOO_THEME30_DATA_REQUIRED"
    assert state["candidates"][0]["peer_theme_score"] is None
    assert state["ranking"]["candidate_exclusion_required_for_all_components"] is True
    assert state["ranking"]["multiple_theme_policy"] == "MAX_VALID_MEMBERSHIP_SCORE"
    assert state["ranking"]["missing_theme_policy"] == "NEUTRAL_50"
    assert state["candidates"][0]["peer_only_status"] == "DATA_REQUIRED"
    assert state["candidates"][0]["candidate_excluded_from_return"] is None
    assert state["candidates"][0]["peer_theme"] is None


def test_companion_selective_uses_rs189_and_never_theme_approximation(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    for i in range(40):
        det[f"T{i}"] = {
            "px": 100, "dvol": 20, "ma5020": True, "v200": 5,
            "v50": 5 if i < 22 else -5, "rs189": 99 - i / 10,
            "rs": 90, "sth": "Theme A",
        }
    source = tmp_path / "legacy.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    state = build_state(source)
    assert state["market"]["mode"] == "SELECTIVE"
    assert state["ranking"]["mode"] == "RS189_ONLY"
    assert state["candidates"][0]["final_rank"] == 1


def test_companion_tqqq_schema_separates_current_hierarchy_floor_and_allocation(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Yellow"}
    source = tmp_path / "legacy.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps({})};</script>', encoding="utf-8")
    state = build_state(source)
    assert state["normal_tqqq"]["underlying_target_pct"] is None
    assert state["panic_tqqq"]["candidate"] == "M30_TOUCH30_F80_D10"
    assert state["panic_tqqq"]["floor_pct_when_active"] == 80
    assert state["panic_tqqq"]["entry_requires_mc57_gte"] == 20
    assert state["panic_tqqq"]["allocation_priority"] == "NOT REPRODUCED"


def test_companion_coverage_guard_stops_new_entries(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": {"v50": 1 if i < 10 else None} for i in range(40)}
    source = tmp_path / "legacy.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    state = build_state(source)
    assert state["market"]["mode"] == "STOP"
    assert not state["market"]["coverage_ok"]
