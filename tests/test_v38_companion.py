import json
from pathlib import Path

from build_v38_companion import build_state


def test_companion_ui_exposes_audited_semantics_and_keeps_legacy_dashboard():
    html = Path("command-center-v38.html").read_text(encoding="utf-8")
    assert "通常個別株の新規保有可能総数は最大4" in html
    assert "すべて当日終値で判定し、注文は次営業日寄りで執行" in html
    assert "M30_TOUCH30_F80_D10" in html
    for element_id in ("mcEntry", "seedAge", "underlyingTarget", "requestedTarget",
                       "resetAllocation", "tqqqParts", "normalAllocation", "executableTarget"):
        assert f'id="{element_id}"' in html
    assert 'src="command-center.html"' in html


def test_workflow_reports_build_export_mirror_and_pages_as_separate_stages():
    workflow = Path(".github/workflows/dashboard.yml").read_text(encoding="utf-8")
    for phrase in (
        "Build / validation: PASS",
        "main generated-state persistence: PASS",
        "Public export creation: PASS",
        "SKIPPED / NOT CONFIGURED",
        "GitHub Pages currentness: SEPARATE CHECK REQUIRED",
    ):
        assert phrase in workflow


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
    assert state["ranking"]["mode"] == "RS189 PREVIEW ONLY / ATTACK FINAL RANK DATA REQUIRED"
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
    assert state["panic_tqqq"]["allocation_priority"].startswith("GROSS100 RESEARCH CANDIDATE")
    assert state["gross100_allocation"]["run_id"] == 33339918881


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


def test_companion_structural_bio_filter_ignores_legacy_theme_label(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    base = {"px": 100, "dvol": 20, "ma5020": True, "v200": 5,
            "v50": 5, "rs189": 90, "rs": 90, "sth": "臨床段階・中小型バイオ"}
    det = {
        "SMALLBIO": dict(base), "SMALLPHARMA": dict(base),
        "BIGBIO": dict(base), "MISSINGREV": dict(base), "LABELONLY": dict(base),
    }
    # Add enough ordinary rows for breadth coverage.
    det.update({f"T{i}": dict(base, sth="Theme A") for i in range(35)})
    source = tmp_path / "legacy.html"
    source.write_text(f'<script>window.CALC={json.dumps(calc)};</script>'
                      f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    caps = {k: {"value": v} for k, v in {
        "SMALLBIO": 2e9, "SMALLPHARMA": 3e9, "BIGBIO": 12e9,
        "MISSINGREV": 2e9, "LABELONLY": 2e9}.items()}
    industries = {"map": {
        "SMALLBIO": ["Health Technology", "Biotechnology"],
        "SMALLPHARMA": ["Health Technology", "Pharmaceuticals: Other"],
        "BIGBIO": ["Health Technology", "Biotechnology"],
        "MISSINGREV": ["Health Technology", "Biotechnology"],
        "LABELONLY": ["Technology", "Semiconductors"],
    }}
    revenues = {"records": {
        "SMALLBIO": {"revenue_ttm": 20e6},
        "SMALLPHARMA": {"revenue_ttm": 40e6},
        "BIGBIO": {"revenue_ttm": 10e6},
        "LABELONLY": {"revenue_ttm": 0},
    }}
    cap_path, ind_path, rev_path = (tmp_path / "cap.json", tmp_path / "ind.json", tmp_path / "rev.json")
    cap_path.write_text(json.dumps(caps), encoding="utf-8")
    ind_path.write_text(json.dumps(industries), encoding="utf-8")
    rev_path.write_text(json.dumps(revenues), encoding="utf-8")
    state = build_state(source, market_cap_path=cap_path, industry_path=ind_path,
                        revenue_path=rev_path)
    got = {row["ticker"]: row for row in state["candidates"]}
    assert "SMALLBIO" not in got and "SMALLPHARMA" not in got
    assert "BIGBIO" in got and "MISSINGREV" in got and "LABELONLY" in got
    assert got["MISSINGREV"]["clinical_biotech"]["revenue_missing_fail_open"] is True


def test_attack_strict_loo_uses_s2t_memberships_and_full_universe_before_top50(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": {"px": 100, "dvol": 20, "ma5020": True, "v200": 5,
                           "v50": 5, "rs189": 90 + i / 100, "rs": 90, "sth": "DISPLAY"}
           for i in range(60)}
    source = tmp_path / "legacy.html"
    source.write_text(f'<script>window.CALC={json.dumps(calc)};</script>'
                      f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    sector = {"s2t": {ticker: ["A", "B"] for ticker in det}}
    loo = {"candidates": {}}
    for ticker in det:
        loo["candidates"][ticker] = {"history_sessions": 21, "themes": {
            "A": {"theme_rs63_pct": 60, "acceleration20_pct": 60, "breadth21_pct": 60,
                  "candidate_excluded_from_return": True,
                  "candidate_excluded_from_acceleration": True,
                  "candidate_excluded_from_breadth21": True},
            "B": {"theme_rs63_pct": 80, "acceleration20_pct": 80, "breadth21_pct": 80,
                  "candidate_excluded_from_return": True,
                  "candidate_excluded_from_acceleration": True,
                  "candidate_excluded_from_breadth21": True},
        }}
    sector_path, loo_path = tmp_path / "sector.json", tmp_path / "loo.json"
    sector_path.write_text(json.dumps(sector), encoding="utf-8")
    loo_path.write_text(json.dumps(loo), encoding="utf-8")
    state = build_state(source, sector_snapshot_path=sector_path, strict_loo_path=loo_path)
    assert state["ranking"]["full_eligible_count"] == 60
    assert state["ranking"]["display_limit_applied_after_full_sort"] == 50
    assert state["ranking"]["strict_loo_live_status"] == "READY"
    assert state["candidates"][0]["peer_theme"] == "B"
    assert state["candidates"][0]["theme_memberships"] == ["A", "B"]
