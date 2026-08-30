import json
from pathlib import Path

from build_v38_companion import build_state


def _eligible(rs189, rs63=90, v50=1):
    return {
        "px": 100, "dvol": 20, "ma5020": True, "v200": 5, "v50": v50,
        "rs189": rs189, "rs": rs63, "sth": "Display Theme",
    }


def test_attack_uses_exact_loo_final_rank_before_top50(tmp_path: Path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    # 60%+ breadth and >50 eligible stocks prove ranking occurs before top50 slicing.
    for i in range(60):
        det[f"T{i:02d}"] = _eligible(99 - i * 0.1, v50=1 if i < 40 else -1)
    source = tmp_path / "command-center.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")

    # Give T55 a very strong valid peer score so it must outrank higher-RS stocks.
    stocks = {
        f"T{i:02d}": {"memberships": 1, "valid_memberships": 1, "selected": {
            "theme": "Theme A", "theme_rs63_pct": 50, "theme_acceleration_pct": 50,
            "theme_breadth21": 50, "peer_theme_score": 50,
        }} for i in range(60)
    }
    stocks["T55"]["selected"] = {
        "theme": "Theme Z", "theme_rs63_pct": 100, "theme_acceleration_pct": 100,
        "theme_breadth21": 100, "peer_theme_score": 100,
    }
    (tmp_path / "loo-theme-live.json").write_text(json.dumps({
        "schema": "v38-loo-theme-live-1", "status": "LIVE_CURRENT_TAXONOMY",
        "asof": "2026-08-28", "taxonomy": "CURRENT_S2T_NOT_PIT",
        "coverage": {"themes": 20, "scored_stocks": 60}, "stocks": stocks,
    }), encoding="utf-8")

    state = build_state(source)
    assert state["market"]["mode"] == "ATTACK"
    assert state["ranking"]["mode"] == "LOO_THEME30_LIVE_CURRENT_TAXONOMY"
    assert state["ranking"]["candidate_list_semantics"] == "EXECUTABLE_ATTACK_FINAL_RANK_CURRENT_TAXONOMY"
    assert state["candidates"][0]["ticker"] == "T55"
    assert state["candidates"][0]["final_rank"] == 1
    assert state["candidates"][0]["peer_theme"] == "Theme Z"
    assert state["candidates"][0]["candidate_excluded_from_return"] is True
    assert state["candidates"][0]["taxonomy_status"] == "CURRENT_S2T_NOT_PIT"


def test_stale_or_partial_loo_never_unlocks_attack_rank(tmp_path: Path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": _eligible(90, v50=1) for i in range(40)}
    source = tmp_path / "command-center.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    (tmp_path / "loo-theme-live.json").write_text(json.dumps({
        "schema": "v38-loo-theme-live-1", "status": "PARTIAL_SMOKE_ONLY",
        "asof": "2026-08-28", "taxonomy": "CURRENT_S2T_NOT_PIT", "stocks": {},
    }), encoding="utf-8")
    state = build_state(source)
    assert state["ranking"]["mode"] == "LOO_THEME30_DATA_REQUIRED"
    assert all(row["final_rank"] is None for row in state["candidates"])
