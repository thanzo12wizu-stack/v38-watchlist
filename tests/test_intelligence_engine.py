import json
import pickle
from pathlib import Path

import pandas as pd

from intelligence_engine.forward_validation import evaluate_snapshot, summarize_by_score_bucket
from intelligence_engine.leadership import add_leader_scores
from intelligence_engine.pipeline import load_universe
from intelligence_engine.prices import _split_yfinance_download
from intelligence_engine.release_check import run as run_release_check
from intelligence_engine.score_policy import SCORE_POLICY_VERSION, validate_score_policy
from intelligence_engine.scoring import score_universe
from intelligence_engine.sec import parse_companyfacts
from intelligence_engine.sector_rotation import build_sector_rotation
from intelligence_engine.validate_inputs import inspect_inputs
from intelligence_engine.validate_outputs import validate


def test_score_universe_prefers_multi_factor_leader():
    frame = pd.DataFrame([
        {"ticker":"A","sector":"Tech","industry":"Semi","rs_raw_63":.5,"rs_raw_126":.6,"rs_raw_189":.7,"rs_raw_252":.8,"rs_change_raw_63":.2,"rs_change_raw_126":.2,"rs_change_raw_189":.1,"eps_yoy":.8,"eps_acceleration":.3,"revenue_yoy":.5,"revenue_acceleration":.2,"gross_margin_delta":.02,"operating_margin_delta":.03,"free_cash_flow_yoy":.5,"shares_yoy":-.01,"volume_ratio_20d":1.5,"distance_52w_high_pct":-2},
        {"ticker":"B","sector":"Tech","industry":"Semi","rs_raw_63":.1,"rs_raw_126":.1,"rs_raw_189":.1,"rs_raw_252":.1,"rs_change_raw_63":-.1,"rs_change_raw_126":-.1,"rs_change_raw_189":-.1,"eps_yoy":-.2,"eps_acceleration":-.2,"revenue_yoy":-.1,"revenue_acceleration":-.1,"gross_margin_delta":-.02,"operating_margin_delta":-.03,"free_cash_flow_yoy":-.4,"shares_yoy":.1,"volume_ratio_20d":.8,"distance_52w_high_pct":-30},
    ])
    scored = score_universe(frame).set_index("ticker")
    assert scored.loc["A", "score_candidate"] > scored.loc["B", "score_candidate"]
    assert 0 <= scored.loc["A", "score_confidence"] <= 1


def fact(val, start, end, form="10-Q", filed="2026-05-01"):
    return {"val": val, "start": start, "end": end, "form": form, "filed": filed, "accn": "x"}


def test_companyfacts_derives_single_quarter_from_cumulative():
    revenue = [
        fact(100, "2024-01-01", "2024-03-31"),
        fact(220, "2024-01-01", "2024-06-30"),
        fact(130, "2024-07-01", "2024-09-30"),
        fact(140, "2024-10-01", "2024-12-31", "10-K"),
        fact(150, "2025-01-01", "2025-03-31"),
        fact(330, "2025-01-01", "2025-06-30"),
    ]
    payload = {"facts":{"us-gaap":{"RevenueFromContractWithCustomerExcludingAssessedTax":{"units":{"USD":revenue}}}}}
    snap = parse_companyfacts(payload)
    assert snap.revenue == 180
    assert snap.revenue_yoy == .5


def test_input_diagnostics_accept_repository_style_mapping(tmp_path):
    universe_path = tmp_path / "universe.csv"
    prices_path = tmp_path / "prices.pkl"
    pd.DataFrame({"Ticker": ["AAA", "QQQ"]}).to_csv(universe_path, index=False)
    frame = pd.DataFrame({
        "Close": range(1, 31),
        "High": range(2, 32),
        "Low": range(0, 30),
        "Volume": [1_000_000] * 30,
    })
    with prices_path.open("wb") as handle:
        pickle.dump({"AAA": frame, "QQQ": frame}, handle)
    report = inspect_inputs(universe_path, prices_path)
    assert report["compatible"] is True
    assert report["prices"]["shape"] == "mapping"


def test_load_universe_accepts_japanese_columns(tmp_path):
    path = tmp_path / "universe.csv"
    pd.DataFrame({"シンボル": ["nvda", "AMD"], "セクター": ["Technology", "Technology"], "時価総額": [1, 2]}).to_csv(path, index=False)
    result = load_universe(path)
    assert list(result.index) == ["NVDA", "AMD"]
    assert result.loc["NVDA", "sector"] == "Technology"
    assert result.loc["AMD", "market_cap"] == 2


def test_split_yfinance_multiindex_field_first():
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAA", "QQQ"]])
    raw = pd.DataFrame([[1, 2, 2, 3, 0, 1, 1.5, 2.5, 100, 200]], columns=columns)
    result = _split_yfinance_download(raw, ["AAA", "QQQ"])
    assert set(result) == {"AAA", "QQQ"}
    assert result["AAA"]["close"].iloc[0] == 1.5


def test_output_contract_rejects_duplicate_tickers(tmp_path):
    root = tmp_path / "intelligence"
    root.mkdir()
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "generated_at": "2026-07-22T00:00:00Z",
        "stocks": [
            {"ticker": "AAA", "scores": {"candidate": 80}, "features": {}, "confidence": 80},
            {"ticker": "AAA", "scores": {"candidate": 70}, "features": {}, "confidence": 70},
        ],
    }
    (root / "index.json").write_text(json.dumps(payload), encoding="utf-8")
    errors = validate(root)
    assert "duplicate ticker: AAA" in errors


def test_forward_validation_uses_last_price_on_or_before_asof():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    prices = {
        "AAA": pd.DataFrame({"Close": [10, 11, 12, 13, 14, 15, 16, 17]}, index=dates),
        "QQQ": pd.DataFrame({"Close": [100, 101, 102, 103, 104, 105, 106, 107]}, index=dates),
    }
    result = evaluate_snapshot(
        [{"ticker": "AAA", "scores": {"candidate": 90}, "confidence": 80}],
        prices,
        "2026-01-03",
        horizons=(2,),
    )
    assert result.loc[0, "return_2d"] == 14 / 12 - 1
    assert result.loc[0, "benchmark_return_2d"] == 104 / 102 - 1


def test_score_bucket_summary_reports_excess_win_rate():
    evaluated = pd.DataFrame({
        "scores": [{"candidate": 10}, {"candidate": 20}, {"candidate": 80}, {"candidate": 90}],
        "excess_return_21d": [-0.02, -0.01, 0.03, 0.05],
    })
    summary = summarize_by_score_bucket(evaluated, "candidate", 21, buckets=2)
    assert list(summary["count"]) == [2, 2]
    assert list(summary["win_rate"]) == [0.0, 1.0]


def test_score_policy_is_versioned_and_balanced():
    assert SCORE_POLICY_VERSION == "1.0.0"
    assert validate_score_policy() == []


def test_release_check_passes_repository_root():
    assert run_release_check(Path(".")) == []


def test_leader_score_rewards_persistence_and_acceleration():
    frame = pd.DataFrame([
        {"ticker":"A","sector":"Tech","industry":"Semi","rs_raw_63":.5,"rs_raw_126":.6,"rs_raw_189":.7,"rs_change_raw_63":.2,"rs_change_raw_126":.2,"distance_52w_high_pct":-2,"dollar_volume_20d":50_000_000,"sector_rank_pct":.9,"industry_rank_pct":.9},
        {"ticker":"B","sector":"Tech","industry":"Semi","rs_raw_63":.1,"rs_raw_126":.1,"rs_raw_189":.1,"rs_change_raw_63":-.1,"rs_change_raw_126":-.1,"distance_52w_high_pct":-30,"dollar_volume_20d":10_000_000,"sector_rank_pct":.9,"industry_rank_pct":.9},
    ])
    scored = add_leader_scores(frame).set_index("ticker")
    assert scored.loc["A", "score_leader"] > scored.loc["B", "score_leader"]
    assert scored.loc["A", "leader_rank_pct"] > scored.loc["B", "leader_rank_pct"]


def test_sector_rotation_prefers_strong_accelerating_sector():
    frame = pd.DataFrame([
        {"ticker":"A1","sector":"A","rs_raw_63":.5,"rs_raw_126":.6,"rs_raw_189":.7,"rs_change_raw_63":.2,"rs_change_raw_126":.2,"score_leader":.9,"leader_rank_pct":1.0},
        {"ticker":"A2","sector":"A","rs_raw_63":.4,"rs_raw_126":.5,"rs_raw_189":.6,"rs_change_raw_63":.1,"rs_change_raw_126":.1,"score_leader":.8,"leader_rank_pct":.8},
        {"ticker":"B1","sector":"B","rs_raw_63":-.1,"rs_raw_126":0,"rs_raw_189":.1,"rs_change_raw_63":-.2,"rs_change_raw_126":-.1,"score_leader":.2,"leader_rank_pct":.2},
        {"ticker":"B2","sector":"B","rs_raw_63":-.2,"rs_raw_126":-.1,"rs_raw_189":0,"rs_change_raw_63":-.2,"rs_change_raw_126":-.2,"score_leader":.1,"leader_rank_pct":0},
    ])
    rotation = build_sector_rotation(frame)
    assert rotation[0]["sector"] == "A"
    assert rotation[0]["score_rotation"] > rotation[1]["score_rotation"]
    assert rotation[0]["leaders"][0] == "A1"
