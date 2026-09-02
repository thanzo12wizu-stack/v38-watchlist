import csv
import json
import os
import subprocess
import textwrap
from pathlib import Path

from build_v38_companion import build_state


def write_legacy(path, calc, det):
    path.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>',
        encoding="utf-8",
    )


def eligible_row(**overrides):
    row = {
        "px": 100, "dvol": 20, "ma5020": True, "v200": 5,
        "v50": 5, "rs189": 90, "rs": 90, "sth": "Theme A",
    }
    row.update(overrides)
    return row


def test_companion_ui_exposes_audited_semantics_and_keeps_legacy_dashboard():
    html = Path("command-center-v38.html").read_text(encoding="utf-8")
    assert "通常個別株の新規保有可能総数は最大4" in html
    assert "すべて当日終値で判定し、注文は次営業日寄りで執行" in html
    assert "M30_TOUCH30_F80_D10" in html
    assert "$Vol(M)" in html
    assert "50&gt;200" in html and "Price&gt;200" in html
    assert "構造的小型Clinical Biotechだけ除外" in html
    for element_id in ("mcEntry", "seedAge", "underlyingTarget", "requestedTarget",
                       "resetAllocation", "tqqqParts", "normalAllocation", "executableTarget"):
        assert f'id="{element_id}"' in html
    assert 'src="command-center.html"' in html


def test_workflow_reports_build_export_mirror_and_pages_as_separate_stages():
    workflow = Path(".github/workflows/dashboard.yml").read_text(encoding="utf-8")
    assert "Prepare verified PIT taxonomy bootstrap" in workflow
    assert "79073ffd9742102c2b6e9f72d349801a10e126db" in workflow
    assert "Build strict LOO PIT live state with exact t-20 bootstrap" in workflow
    for phrase in (
        "Build / validation: PASS",
        "main generated-state persistence: PASS",
        "Public export creation: PASS",
        "SKIPPED / NOT CONFIGURED",
        "GitHub Pages currentness: SEPARATE CHECK REQUIRED",
    ):
        assert phrase in workflow


def test_workflow_collector_health_summary_executes(tmp_path):
    workflow = Path(".github/workflows/dashboard.yml").read_text(encoding="utf-8")
    section = workflow.split("      - name: Report persistence and data date", 1)[1]
    run_block = section.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
    script = textwrap.dedent(run_block)

    fixtures = {
        "commit_manifest.json": {},
        "state.json": {"date": "2026-08-28", "gate": "Green"},
        "v38-strict-loo-live.json": {
            "status": "READY",
            "asof": "2026-08-28",
            "history_sessions": 21,
            "history_has_exact_20_session_base": True,
        },
        "v38-strict-loo-history.json": {
            "sessions": [{"asof": "2026-08-27"}, {"asof": "2026-08-28"}],
        },
        "tqqq-panic-state.json": {
            "live_generation_status": "DATA REQUIRED",
            "reason": "TEST_ROUTE_UNAVAILABLE",
            "asof": "2026-08-28",
        },
    }
    for name, payload in fixtures.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "command-center.html").write_text("legacy", encoding="utf-8")
    (tmp_path / "command-center_share.html").write_text("share", encoding="utf-8")
    summary = tmp_path / "summary.md"
    env = dict(os.environ, GITHUB_STEP_SUMMARY=str(summary))

    subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, check=True)
    rendered = summary.read_text(encoding="utf-8")
    assert "strict LOO status: READY" in rendered
    assert "strict LOO history_sessions: 21" in rendered
    assert "strict LOO latest saved date: 2026-08-28" in rendered
    assert "strict LOO exact t-20 snapshot: True" in rendered
    assert "TQQQ live_generation_status: DATA REQUIRED" in rendered
    assert "TQQQ reason: TEST_ROUTE_UNAVAILABLE" in rendered
    for phrase in (
        "strict LOO status",
        "strict LOO reason",
        "strict LOO history_sessions",
        "strict LOO computed_snapshot_count",
        "strict LOO PIT history start",
        "strict LOO latest saved date",
        "strict LOO exact t-20 snapshot",
        "TQQQ live_generation_status",
        "TQQQ reason",
        "TQQQ asof",
    ):
        assert phrase in workflow


def test_workflow_verified_pit_bootstrap_guard_executes_without_fetch_when_persisted(tmp_path):
    workflow = Path(".github/workflows/dashboard.yml").read_text(encoding="utf-8")
    section = workflow.split("      - name: Prepare verified PIT taxonomy bootstrap", 1)[1]
    run_block = section.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
    script = textwrap.dedent(run_block)
    history = {
        "taxonomy_snapshots": [{
            "effective_asof": "2026-06-22",
            "source": "git:79073ffd9742102c2b6e9f72d349801a10e126db:sector_snapshot.json",
            "taxonomy_sha256": "dfa417586b4de5436cbfc64f2df5098ca9fd8081f235efe4b4f276b870b83e39",
            "s2t": {"AAA": ["Theme"]},
        }]
    }
    (tmp_path / "v38-strict-loo-history.json").write_text(json.dumps(history), encoding="utf-8")
    completed = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, text=True,
        capture_output=True, check=True,
    )
    assert "already persisted" in completed.stdout


def test_companion_reads_legacy_without_rewriting_and_fails_closed_for_attack_theme(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    for i in range(40):
        det[f"T{i}"] = eligible_row(v50=5 if i < 26 else -5)
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
    assert state["ranking"]["missing_theme_policy"] == "NEUTRAL_50_AT_FINAL_SCORE_ONLY"
    assert state["candidates"][0]["peer_only_status"] == "DATA_REQUIRED"
    assert state["candidates"][0]["candidate_excluded_from_return"] is None
    assert state["candidates"][0]["peer_theme"] is None


def test_companion_selective_uses_rs189_and_never_theme_approximation(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    for i in range(40):
        det[f"T{i}"] = eligible_row(v50=5 if i < 22 else -5, rs189=99 - i / 10)
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)
    state = build_state(source)
    assert state["market"]["mode"] == "SELECTIVE"
    assert state["ranking"]["mode"] == "RS189_ONLY"
    assert state["candidates"][0]["final_rank"] == 1
    checks = state["candidates"][0]["eligibility_checks"]
    assert checks["price_gte_5"] and checks["dollar_volume_gte_10m"]
    assert checks["sma50_gt_sma200"] and checks["close_gt_sma200"]
    assert checks["rs189_gte_85"] and checks["rs63_gte_85"]
    assert not checks["biotech_industry_excluded"]


def test_companion_tqqq_schema_separates_current_hierarchy_floor_and_allocation(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Yellow"}
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, {})
    state = build_state(source)
    assert state["normal_tqqq"]["underlying_target_pct"] is None
    assert state["panic_tqqq"]["candidate"] == "M30_TOUCH30_F80_D10"
    assert state["panic_tqqq"]["floor_pct_when_active"] == 80
    assert state["panic_tqqq"]["entry_requires_mc57_gte"] == 20
    assert state["panic_tqqq"]["allocation_priority"].startswith("GROSS100 LIVE")
    assert state["gross100_allocation"]["run_id"] == 33405477190


def test_companion_coverage_guard_stops_new_entries(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": {"v50": 1 if i < 10 else None} for i in range(40)}
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)
    state = build_state(source)
    assert state["market"]["mode"] == "STOP"
    assert not state["market"]["coverage_ok"]


def test_companion_structural_bio_filter_ignores_legacy_theme_label(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    base = eligible_row(sth="臨床段階・中小型バイオ")
    det = {
        "SMALLBIO": dict(base), "SMALLPHARMA": dict(base),
        "BIGBIO": dict(base), "MISSINGREV": dict(base), "LABELONLY": dict(base),
    }
    det.update({f"T{i}": eligible_row() for i in range(35)})
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)
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


def test_companion_uses_universe_csv_structural_clinical_fields(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {name: eligible_row(sth="臨床段階・中小型バイオ") for name in (
        "SMALLBIO", "SMALLPHARMA", "BIGBIO", "MISSINGREV",
    )}
    det.update({f"T{i}": eligible_row() for i in range(36)})
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)
    universe = tmp_path / "universe.csv"
    with universe.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["シンボル", "時価総額", "業種", "売上高TTM"])
        writer.writeheader()
        writer.writerows([
            {"シンボル": "SMALLBIO", "時価総額": 2e9, "業種": "Biotechnology", "売上高TTM": 20e6},
            {"シンボル": "SMALLPHARMA", "時価総額": 3e9, "業種": "Pharmaceuticals: Other", "売上高TTM": 40e6},
            {"シンボル": "BIGBIO", "時価総額": 12e9, "業種": "Biotechnology", "売上高TTM": 10e6},
            {"シンボル": "MISSINGREV", "時価総額": 2e9, "業種": "Biotechnology", "売上高TTM": ""},
        ])
    state = build_state(source, universe_path=universe)
    got = {row["ticker"]: row for row in state["candidates"]}
    assert "SMALLBIO" not in got and "SMALLPHARMA" not in got
    assert "BIGBIO" in got and "MISSINGREV" in got


def test_attack_strict_loo_uses_s2t_memberships_and_full_universe_before_top50(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": eligible_row(rs189=90 + i / 100, sth="DISPLAY") for i in range(60)}
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)
    sector = {"s2t": {ticker: ["A", "B"] for ticker in det}}
    loo = {"status": "READY", "asof": "2026-08-28", "candidates": {}}
    for ticker in det:
        loo["candidates"][ticker] = {"status": "READY", "history_sessions": 21, "themes": {
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


def test_attack_eligible_ticker_absent_from_s2t_uses_neutral50_only_at_final_score(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": eligible_row(rs189=90 + i / 100) for i in range(40)}
    missing_ticker = "T39"
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)

    memberships = {ticker: ["A"] for ticker in det if ticker != missing_ticker}
    loo = {
        "status": "READY",
        "asof": "2026-08-28",
        "history_sessions": 21,
        "history_has_exact_20_session_base": True,
        "candidates": {},
    }
    for ticker in memberships:
        loo["candidates"][ticker] = {
            "status": "READY",
            "history_sessions": 21,
            "themes": {
                "A": {
                    "theme_rs63_pct": 60,
                    "acceleration20_pct": 60,
                    "breadth21_pct": 60,
                    "candidate_excluded_from_return": True,
                    "candidate_excluded_from_acceleration": True,
                    "candidate_excluded_from_breadth21": True,
                }
            },
        }

    sector_path, loo_path = tmp_path / "sector.json", tmp_path / "loo.json"
    sector_path.write_text(json.dumps({"s2t": memberships}), encoding="utf-8")
    loo_path.write_text(json.dumps(loo), encoding="utf-8")
    state = build_state(source, sector_snapshot_path=sector_path, strict_loo_path=loo_path)

    rows = {row["ticker"]: row for row in state["candidates"]}
    missing = rows[missing_ticker]
    assert state["ranking"]["strict_loo_live_status"] == "READY"
    assert state["ranking"]["mode"] == "ATTACK_FINAL_RANK"
    assert missing["theme_memberships"] == []
    assert missing["peer_theme"] is None
    assert missing["peer_theme_score"] is None
    assert missing["peer_only_status"] == "LOO_READY_NO_VALID_THEME"
    assert missing["attack_score"] == 0.70 * missing["rs189"] + 0.30 * 50
    assert missing["final_rank"] is not None


def test_attack_strict_loo_stale_or_data_required_route_fails_closed(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": eligible_row() for i in range(40)}
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)
    sector = tmp_path / "sector.json"
    sector.write_text(json.dumps({"s2t": {ticker: ["A"] for ticker in det}}), encoding="utf-8")
    for payload in (
        {"status": "DATA REQUIRED", "asof": "2026-08-28", "candidates": {}},
        {"status": "READY", "asof": "2026-08-27", "candidates": {}},
    ):
        loo = tmp_path / "loo.json"
        loo.write_text(json.dumps(payload), encoding="utf-8")
        state = build_state(source, sector_snapshot_path=sector, strict_loo_path=loo)
        assert state["ranking"]["strict_loo_live_status"] == "DATA REQUIRED"
        assert state["ranking"]["mode"] == "RS189 PREVIEW ONLY / ATTACK FINAL RANK DATA REQUIRED"


def test_tqqq_ready_route_populates_current30_stage56_and_gross100(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Yellow"}
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, {})
    panic = tmp_path / "tqqq-panic-state.json"
    panic.write_text(json.dumps({
        "asof": "2026-08-28",
        "live_generation_status": "READY",
        "current30": {
            "status": "READY", "underlying_target_pct": 90,
            "risk_lock": False, "slow_lock": False, "fast_lock": False,
            "mc_lock": False, "sleeve": "GB",
        },
        "underlying_target_pct": 90,
        "requested_target_pct": 90,
        "vix_close": 25,
        "qqq_sma50_atr_deviation": -0.6,
        "qqq_drawdown10": -0.03,
        "seed_age_sessions": 4,
        "rsi4h": 29,
        "prior_rsi4h": 31,
        "mc57": 40,
        "active": True,
        "held_sessions": 2,
        "reset_desired_pct": 8,
        "normal_stock_desired_pct": 50,
        "sleeve_live_status": "READY",
        "sleeve_live_reason": None,
    }), encoding="utf-8")
    sleeve = tmp_path / "v38-sleeve-state.json"
    sleeve.write_text(json.dumps({
        "schema": "v38-sleeve-live-1", "asof": "2026-08-28", "status": "READY",
        "normal_stock": {"status": "READY", "strategy": "PEAK30_PART25_R3", "desired_pct": 50, "position_count": 6, "positions": [], "pending": {}},
        "rsi_reset": {"status": "READY", "strategy": "RS63_TOP3_RISE30_SIGTOP3", "desired_pct": 8,
                      "position_count": 1, "positions": [{"symbol": "AAA"}],
                      "monitor": [{"symbol": "AAA", "status": "ACTIVE_POSITION", "current_rsi14": 32.0}],
                      "monitor_summary": {"active_positions": 1, "watch_count": 1}},
    }), encoding="utf-8")
    state = build_state(source, tqqq_panic_path=panic, sleeve_state_path=sleeve)
    assert state["normal_tqqq"]["status"] == "READY"
    assert state["normal_tqqq"]["underlying_target_pct"] == 90
    assert state["panic_tqqq"]["status"] == "READY / ACTIVE"
    assert state["panic_tqqq"]["requested_target_pct"] == 90
    gross = state["gross100_allocation"]
    assert gross["status"].endswith("LIVE ALLOCATION READY")
    assert gross["reset_allocated_pct"] == 8
    assert gross["tqqq_protected_pct"] == 80
    assert gross["normal_stock_allocated_pct"] == 12
    assert gross["tqqq_extra_pct"] == 0
    assert gross["gross_allocated_pct"] == 100
    assert gross["adoption_status"] == "ADOPTED_FINAL_SPEC_20260901"
    assert state["panic_reset"]["status"] == "READY / LIVE"
    assert state["panic_reset"]["monitor"][0]["symbol"] == "AAA"
    assert state["normal_stock_sleeve"]["position_count"] == 6


def test_tqqq_stale_route_is_data_required_and_not_used_for_gross(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Yellow"}
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, {})
    panic = tmp_path / "tqqq-panic-state.json"
    panic.write_text(json.dumps({
        "asof": "2026-08-27", "live_generation_status": "READY",
        "current30": {"status": "READY", "underlying_target_pct": 90},
        "underlying_target_pct": 90, "requested_target_pct": 90,
        "reset_desired_pct": 8, "normal_stock_desired_pct": 50,
    }), encoding="utf-8")
    state = build_state(source, tqqq_panic_path=panic)
    assert state["normal_tqqq"]["underlying_target_pct"] is None
    assert state["panic_tqqq"]["status"] == "DATA REQUIRED"
    assert state["gross100_allocation"]["gross_allocated_pct"] is None


def test_audited_companion_leads_with_action_and_never_labels_stop_watchlist_as_buy():
    html = Path("command-center-v38.html").read_text(encoding="utf-8")
    assert "TODAY'S ACTION" in html
    assert "今は買わない" in html
    assert "復帰条件成立前は買いません" in html
    assert "再開時にまず見る銘柄" in html
    assert "どちらも復帰条件成立前は買いシグナルではありません" in html
    assert "今は買わない" in html
    assert "Rotationは現時点では正式順位に加点しません" in html
    assert "ルール解説" in html
    assert "RSI30接近" in html
    assert "戦略モデルの目標配分（実保有とは別）" in html
    assert "RS63_TOP3_RISE30_SIGTOP3" in html
    assert "表示帯は売買ルールではない" in html


def _write_ready_sleeve(path, *, normal_desired, reset_desired=0):
    path.write_text(json.dumps({
        "schema": "v38-sleeve-live-1",
        "asof": "2026-08-28",
        "status": "READY",
        "normal_stock": {
            "status": "READY", "strategy": "PEAK30_PART25_R3",
            "desired_pct": normal_desired, "position_count": 0,
            "positions": [], "pending": {},
        },
        "rsi_reset": {
            "status": "READY", "strategy": "RS63_TOP3_RISE30_SIGTOP3",
            "desired_pct": reset_desired, "position_count": 0,
            "positions": [], "monitor": [], "monitor_summary": {},
        },
    }), encoding="utf-8")


def _write_ready_tqqq(path, *, native, requested, normal_desired, reset_desired=0):
    path.write_text(json.dumps({
        "asof": "2026-08-28",
        "live_generation_status": "READY",
        "current30": {
            "status": "READY", "underlying_target_pct": native,
            "risk_lock": native == 0, "slow_lock": False,
            "fast_lock": False, "mc_lock": False, "sleeve": "TEST",
        },
        "underlying_target_pct": native,
        "requested_target_pct": requested,
        "active": False,
        "reset_desired_pct": reset_desired,
        "normal_stock_desired_pct": normal_desired,
        "sleeve_live_status": "READY",
        "sleeve_live_reason": None,
    }), encoding="utf-8")


def test_companion_caps_raw_normal_desired_at_70_before_gross100(tmp_path):
    source = tmp_path / "legacy.html"
    write_legacy(source, {"asof": "2026-08-28", "color": "Yellow"}, {})
    panic = tmp_path / "tqqq.json"
    sleeve = tmp_path / "sleeve.json"
    _write_ready_tqqq(panic, native=0, requested=0, normal_desired=85.955)
    _write_ready_sleeve(sleeve, normal_desired=85.955)

    state = build_state(source, tqqq_panic_path=panic, sleeve_state_path=sleeve)
    gross = state["gross100_allocation"]
    assert gross["normal_stock_standalone_desired_pct"] == 85.955
    assert gross["normal_stock_portfolio_desired_pct"] == 70
    assert gross["normal_stock_allocated_pct"] == 70
    assert gross["normal_stock_max_pct"] == 70
    assert gross["tqqq_selective_fill_pct"] == 0
    assert gross["gross_allocated_pct"] == 70
    assert state["normal_stock_sleeve"]["portfolio_desired_pct"] == 70


def test_companion_selective_fill_uses_idle_cash_and_never_overrides_native_zero(tmp_path):
    det = {f"T{i}": eligible_row(v50=5 if i < 26 else -5) for i in range(40)}
    source = tmp_path / "legacy.html"
    write_legacy(source, {"asof": "2026-08-28", "color": "Green"}, det)
    panic = tmp_path / "tqqq.json"
    sleeve = tmp_path / "sleeve.json"
    _write_ready_sleeve(sleeve, normal_desired=40)

    _write_ready_tqqq(panic, native=30, requested=30, normal_desired=40)
    filled = build_state(source, tqqq_panic_path=panic, sleeve_state_path=sleeve)
    gross = filled["gross100_allocation"]
    assert filled["market"]["mode"] == "ATTACK"
    assert gross["selective_fill_rule"] == "SELECTIVE_FILL_NO_ZERO_OVERRIDE"
    assert gross["selective_fill_eligible"] is True
    assert gross["base_gross_allocated_pct"] == 70
    assert round(gross["tqqq_selective_fill_pct"], 10) == 30
    assert round(gross["tqqq_allocated_pct"], 10) == 60
    assert gross["normal_stock_allocated_pct"] == 40
    assert round(gross["gross_allocated_pct"], 10) == 100

    _write_ready_tqqq(panic, native=0, requested=0, normal_desired=40)
    locked = build_state(source, tqqq_panic_path=panic, sleeve_state_path=sleeve)
    locked_gross = locked["gross100_allocation"]
    assert locked_gross["native_tqqq_target_pct"] == 0
    assert locked_gross["selective_fill_eligible"] is False
    assert locked_gross["tqqq_selective_fill_pct"] == 0
    assert locked_gross["tqqq_allocated_pct"] == 0
    assert locked_gross["normal_stock_allocated_pct"] == 40
    assert locked_gross["gross_allocated_pct"] == 40


def test_stop_state_precomputes_both_selective_and_attack_reopening_routes(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Yellow"}
    det = {f"T{i}": eligible_row(rs189=99-i/10, rs=99-i/10, v50=5) for i in range(40)}
    source = tmp_path / "legacy.html"
    write_legacy(source, calc, det)
    sector = tmp_path / "sector.json"
    sector.write_text(json.dumps({"s2t": {ticker: [] for ticker in det}}), encoding="utf-8")
    loo = tmp_path / "loo.json"
    loo.write_text(json.dumps({
        "status": "READY", "asof": "2026-08-28", "history_sessions": 21,
        "history_has_exact_20_session_base": True, "candidates": {}
    }), encoding="utf-8")
    state = build_state(source, sector_snapshot_path=sector, strict_loo_path=loo)
    assert state["market"]["mode"] == "STOP"
    assert state["ranking"]["selective_reopen_top4"] == ["T0", "T1", "T2", "T3"]
    assert len(state["ranking"]["attack_reopen_top12"]) == 12
    rows = {row["ticker"]: row for row in state["candidates"]}
    assert rows["T0"]["selective_watch_rank"] == 1
    assert rows["T0"]["attack_watch_rank"] is not None
