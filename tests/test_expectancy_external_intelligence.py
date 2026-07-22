from pathlib import Path

import numpy as np
import pandas as pd

from intelligence_engine.expectancy import build_expectancy, calibrate_candidates
from intelligence_engine.external_data import apply_external_context, build_external_records, load_external_layer


def _prices(start=100.0, drift=.001, n=300):
    idx=pd.date_range("2024-01-01",periods=n,freq="B")
    close=start*np.cumprod(np.full(n,1+drift))
    return pd.DataFrame({"open":close*.999,"high":close*1.01,"low":close*.99,"close":close,"volume":np.linspace(1_000_000,2_000_000,n)},index=idx)


def test_expectancy_builds_point_in_time_stats():
    prices={"QQQ":_prices(drift=.0005),"AAA":_prices(drift=.0015),"BBB":_prices(drift=-.0002)}
    result=build_expectancy(prices,min_samples=2,stride=5)
    assert result["status"] == "OK"
    assert result["sample_count"] > 0
    assert {r["horizon"] for r in result["setup_stats"]} == {5,10,21}
    out=calibrate_candidates([{"ticker":"AAA","setup":"WATCH","score_entry":50}],result)
    assert "expectancy" in out[0]
    assert set(out[0]["expectancy"]) == {"5","10","21"}


def test_external_layer_normalizes_and_blocks_earnings_window(tmp_path:Path):
    root=tmp_path/"external"; root.mkdir()
    pd.DataFrame([{"ticker":"AAA","earnings_date":"2026-07-23"}]).to_csv(root/"earnings_calendar.csv",index=False)
    pd.DataFrame([{"ticker":"AAA","asof":"2026-07-20","eps_revision_30d_pct":4.0}]).to_csv(root/"estimate_revisions.csv",index=False)
    pd.DataFrame([{"ticker":"AAA","date":"2026-07-20","direction":"RAISED"}]).to_csv(root/"guidance.csv",index=False)
    pd.DataFrame([{"ticker":"AAA","date":"2026-07-20","headline":"Wins major contract"}]).to_csv(root/"news.csv",index=False)
    pd.DataFrame([{"ticker":"AAA","transaction_date":"2026-07-19","transaction_type":"BUY","transaction_value":100000}]).to_csv(root/"insider.csv",index=False)
    pd.DataFrame([{"ticker":"AAA","manager":"Fund A","position_change_pct":12}]).to_csv(root/"holdings_13f.csv",index=False)
    layer=load_external_layer(root)
    records=build_external_records(["AAA"],layer,today=pd.Timestamp("2026-07-22"))
    rec=records[0]
    assert rec["days_to_earnings"] == 1
    assert "earnings_window" in rec["warnings"]
    assert "eps_revisions_up" in rec["positives"]
    assert "CONTRACT" in rec["event_types"]
    assert rec["institutional_holder_count"] == 1
    out=apply_external_context([{"ticker":"AAA","actionable":True,"warnings":[]}],records)
    assert out[0]["actionable"] is False


def test_external_layer_missing_files_is_safe(tmp_path:Path):
    layer=load_external_layer(tmp_path)
    records=build_external_records(["AAA"],layer,today=pd.Timestamp("2026-07-22"))
    assert records[0]["coverage"] == {"earnings":False,"revisions":False,"guidance":False,"news":False,"insider":False,"holdings_13f":False}
