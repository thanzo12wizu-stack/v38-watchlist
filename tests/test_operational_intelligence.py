import json
from pathlib import Path

import pandas as pd

from intelligence_engine.operational_pipeline import build_quality_report, build_robust_expectancy, detect_leader_transitions, freeze_snapshot, settle_outcomes
from intelligence_engine.portfolio import build_portfolio_doctor


def _prices(start="2026-01-01", periods=40, base=100):
    idx=pd.date_range(start,periods=periods,freq="B")
    return pd.DataFrame({"close":[base+i for i in range(periods)]},index=idx)


def test_snapshot_is_immutable_and_outcomes_settle(tmp_path):
    index={"manifest":{"asof":"2026-01-02"},"entry_candidates":[{"ticker":"AAA","setup":"PULLBACK"}],"market_state":{"regime":"BLUE"}}
    ledger=tmp_path/"obs"
    assert freeze_snapshot(index,ledger)["status"]=="CREATED"
    assert freeze_snapshot(index,ledger)["status"]=="EXISTS"
    result=settle_outcomes(ledger,{"AAA":_prices(),"QQQ":_prices(base=90)})
    assert result["settled"]==3
    payload=json.loads((ledger/"2026-01-02.json").read_text())
    assert set(payload["outcomes"]["AAA"]["horizons"])=={"5","10","21"}


def test_robust_expectancy_cuts_and_bootstrap(tmp_path):
    ledger=tmp_path/"obs";ledger.mkdir()
    for i in range(45):
        payload={"asof":f"2025-01-{(i%28)+1:02d}","market_state":{"regime":"GREEN"},"entry_candidates":[{"ticker":f"T{i}","setup":"PULLBACK","sector":"Tech","theme":"AI"}],"outcomes":{f"T{i}":{"horizons":{"5":{"excess_return":.01 if i%3 else -.01}}}}}
        (ledger/f"{i}.json").write_text(json.dumps(payload))
    result=build_robust_expectancy(ledger)
    assert result["status"]=="OK"
    assert result["rankings"][0]["qualified"] is True
    assert result["rankings"][0]["bootstrap_mean_ci95"] is not None


def test_leader_transition_and_quality(tmp_path):
    history=tmp_path/"history";history.mkdir()
    prior={"asof":"2026-01-01","stocks":[{"ticker":"OLD","features":{"pct_rs_raw_63":99}}],"theme_intelligence":[{"theme":"AI","score":50,"phase":"IMPROVING"}]}
    (history/"2026-01-01.json").write_text(json.dumps(prior))
    current={"stocks":[{"ticker":"NEW","features":{"pct_rs_raw_63":100}}],"theme_intelligence":[{"theme":"AI","score":70,"phase":"LEADING"}],"manifest":{"universe_count":2,"price_covered_count":2},"entry_candidates":[{"ticker":"NEW"}]}
    tr=detect_leader_transitions(current,history)
    assert "NEW" in tr["changes"]["rs63"]["new_top10"]
    quality=build_quality_report(current,{"QQQ":_prices(periods=5)},tmp_path)
    assert "price_coverage_low" not in quality["warnings"]


def test_portfolio_live_rules():
    positions=pd.DataFrame([{"ticker":"AAA","weight":.08,"cost_basis":100,"entry_date":"2026-01-01","stop_method":"21EMA_LOW","entry_stage":1,"first_pivot_date":"2026-01-01","second_pivot_date":None,"partial_taken":False}])
    scored=pd.DataFrame([{"ticker":"AAA","price":130,"stop_ema21_low":110,"stop_sma10":115,"adr_pct":4,"sector":"Tech","theme":"AI","setup":"PULLBACK"}])
    result=build_portfolio_doctor(positions,scored,{"AAA":_prices()}, {"regime":"BLUE","entry_gate":"ALLOW"})
    row=result["positions"][0]
    assert row["partial_take_due"] is True
    assert row["action"]=="EXIT"
    assert result["market_exposure_cap"]==1.0
