import csv
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
            "sth": "Theme A", "sec": "Technology",
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
    assert state["ranking"]["candidate_list_semantics"] == "RS189_PREVIEW_ONLY_UNTIL_LOO_LIVE"
    assert "RS189 preview only" in state["ranking"]["note"]
    assert state["candidates"][0]["entry_status"] == "RS189_PREVIEW_ONLY_LOO_DATA_REQUIRED"
    assert state["candidates"][0]["peer_theme_score"] is None
    assert state["ranking"]["candidate_exclusion_required_for_all_components"] is True
    assert state["ranking"]["multiple_theme_policy"] == "MAX_VALID_MEMBERSHIP_SCORE"
    assert state["ranking"]["missing_theme_policy"] == "NEUTRAL_50"
    assert state["candidates"][0]["peer_only_status"] == "DATA_REQUIRED"
    assert state["candidates"][0]["candidate_excluded_from_return"] is None
    assert state["candidates"][0]["peer_theme"] is None
    assert state["rotation_intelligence"]["fund_flow"]["status"] == "DATA_REQUIRED"
    assert "RESEARCH" in state["rotation_intelligence"]["matrix"]["quality"]
    assert state["rotation_intelligence"]["macro"]["status"] == "DATA_REQUIRED"
    assert state["rotation_intelligence"]["sector_groups"][0]["top_stocks"][0]["ticker"].startswith("T")


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
    assert state["ranking"]["candidate_list_semantics"] == "EXECUTABLE_RS189_RANK"
    assert state["candidates"][0]["final_rank"] == 1
    assert state["candidates"][0]["entry_status"] == "NEXT_OPEN_WHEN_CAPACITY"


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


def test_structural_small_clinical_biotech_exclusion_matches_research_rule(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    for i in range(37):
        det[f"T{i}"] = {
            "px": 100, "dvol": 20, "ma5020": True, "v200": 5,
            "v50": 5, "rs189": 90, "rs": 90, "sth": "Other",
        }
    det.update({
        "CLYM": {"px": 14.57, "dvol": 20, "ma5020": True, "v200": 5,
                 "v50": 5, "rs189": 99, "rs": 95, "sth": "バイオ"},
        "SMALLPHARMA": {"px": 22, "dvol": 20, "ma5020": True, "v200": 5,
                        "v50": 5, "rs189": 98.5, "rs": 95, "sth": "医薬"},
        "BIGBIO": {"px": 100, "dvol": 20, "ma5020": True, "v200": 5,
                   "v50": 5, "rs189": 98, "rs": 95, "sth": "バイオ"},
        "MISSREV": {"px": 80, "dvol": 20, "ma5020": True, "v200": 5,
                    "v50": 5, "rs189": 97, "rs": 94, "sth": "バイオ"},
    })
    source = tmp_path / "command-center.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")

    with (tmp_path / "universe.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["シンボル", "業種", "時価総額", "売上高TTM"])
        writer.writeheader()
        writer.writerow({"シンボル": "CLYM", "業種": "Biotechnology", "時価総額": 836_846_183, "売上高TTM": 0})
        writer.writerow({"シンボル": "SMALLPHARMA", "業種": "Pharmaceuticals: Other", "時価総額": 800_000_000, "売上高TTM": 10_000_000})
        writer.writerow({"シンボル": "BIGBIO", "業種": "Biotechnology", "時価総額": 20_000_000_000, "売上高TTM": 0})
        writer.writerow({"シンボル": "MISSREV", "業種": "Pharmaceuticals: Other", "時価総額": 800_000_000, "売上高TTM": ""})
        for i in range(37):
            writer.writerow({"シンボル": f"T{i}", "業種": "Software", "時価総額": 2_000_000_000, "売上高TTM": 200_000_000})

    state = build_state(source)
    tickers = {row["ticker"] for row in state["candidates"]}
    assert "CLYM" not in tickers
    assert "SMALLPHARMA" not in tickers
    assert "BIGBIO" in tickers
    assert "MISSREV" in tickers
    assert state["eligibility"]["structural_metadata_status"] == "LIVE"
    assert state["eligibility"]["revenue_missing_policy"] == "FAIL_OPEN"
    assert state["eligibility"]["excluded_count"] == 2


def test_rotation_macro_requires_explicit_exact_route(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Yellow"}
    det = {f"T{i}": {"v50": 1, "sec": "Technology", "sth": "Software", "rs189": 80, "rs": 78} for i in range(40)}
    source = tmp_path / "command-center.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    (tmp_path / "rotation-macro.json").write_text(json.dumps({
        "exact": True, "asof": "2026-08-28", "source": "fixture",
        "us10y_yield": 4.73, "real10y_yield": 2.11, "dxy": 101.4,
        "credit_spread": 0.82, "vix": 14.42, "fear_greed": 54,
    }), encoding="utf-8")
    state = build_state(source)
    macro = state["rotation_intelligence"]["macro"]
    assert macro["status"] == "EXACT"
    assert macro["us10y_yield"] == 4.73
    assert macro["fear_greed"] == 54.0
