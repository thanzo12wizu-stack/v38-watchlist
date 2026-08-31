import json
from pathlib import Path

from build_v38_companion import build_state


def _legacy(path: Path, color: str, breadth_up: int = 24, total: int = 40):
    calc = {"asof": "2026-08-28", "color": color}
    det = {}
    for i in range(total):
        det[f"T{i}"] = {
            "px": 100, "dvol": 20, "ma5020": True, "v200": 5,
            "v50": 5 if i < breadth_up else -5,
            "rs189": 90 + i / 100, "rs": 90, "sth": "DISPLAY",
        }
    path.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8",
    )
    return det


def _loo_inputs(tmp_path: Path, det: dict):
    sector = {"s2t": {ticker: ["A"] for ticker in det}}
    loo = {
        "status": "READY", "asof": "2026-08-28", "history_sessions": 21,
        "history_has_exact_20_session_base": True, "candidates": {},
    }
    for i, ticker in enumerate(det):
        loo["candidates"][ticker] = {
            "status": "READY", "history_sessions": 21,
            "themes": {"A": {
                "theme_rs63_pct": 55 + i / 2,
                "acceleration20_pct": 60,
                "breadth21_pct": 65,
                "candidate_excluded_from_return": True,
                "candidate_excluded_from_acceleration": True,
                "candidate_excluded_from_breadth21": True,
            }},
        }
    sector_path, loo_path = tmp_path / "sector.json", tmp_path / "loo.json"
    sector_path.write_text(json.dumps(sector), encoding="utf-8")
    loo_path.write_text(json.dumps(loo), encoding="utf-8")
    return sector_path, loo_path


def test_stop_has_full_universe_reopening_watch_rank_without_entry_signal(tmp_path):
    legacy = tmp_path / "legacy.html"
    det = _legacy(legacy, "Yellow")
    sector, loo = _loo_inputs(tmp_path, det)
    state = build_state(legacy, sector_snapshot_path=sector, strict_loo_path=loo)

    assert state["market"]["mode"] == "STOP"
    assert state["market"]["new_entry_limit"] == 0
    assert state["ranking"]["attack_watch_status"] == "READY"
    assert state["ranking"]["attack_watch_semantics"] == "WATCH_ONLY_OUTSIDE_ATTACK; NEVER_OVERRIDES_MARKET_MODE"
    assert state["ranking"]["full_eligible_count"] == 40
    assert state["candidates"][0]["attack_watch_rank"] == 1
    assert state["candidates"][0]["attack_watch_score"] is not None
    assert state["candidates"][0]["attack_score"] is None
    assert state["candidates"][0]["final_rank"] is None


def test_attack_execution_rank_still_uses_same_watch_score(tmp_path):
    legacy = tmp_path / "legacy.html"
    det = _legacy(legacy, "Green", breadth_up=28)
    sector, loo = _loo_inputs(tmp_path, det)
    state = build_state(legacy, sector_snapshot_path=sector, strict_loo_path=loo)

    assert state["market"]["mode"] == "ATTACK"
    assert state["ranking"]["mode"] == "ATTACK_FINAL_RANK"
    assert state["candidates"][0]["final_rank"] == 1
    assert state["candidates"][0]["attack_score"] == state["candidates"][0]["attack_watch_score"]
    assert state["candidates"][0]["attack_watch_rank"] == 1


def test_reader_ui_has_rule_explanation_and_rotation_guardrail():
    html = Path("command-center-v38.html").read_text(encoding="utf-8")
    for text in (
        "候補ランキング", "ルール解説", "まず全体像",
        "WHEN=NQSAR+Breadth / WHAT=正式V38順位 / WHERE=Rotation参考",
        "Rotationは現時点では正式順位に加点しません",
        "再開時ウォッチ順位", "今は買わない",
    ):
        assert text in html
    assert 'href="rotation/"' in html
    assert 'src="command-center.html"' in html
