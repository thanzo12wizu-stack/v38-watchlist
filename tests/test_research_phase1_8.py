from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from intelligence_engine.research_engine import add_research_scores, build_signal_pool, rank_signals
from intelligence_engine.research_expectancy import build_research_expectancy
from intelligence_engine.research_financials import build_financial_snapshots, extract_companyfacts_history, merge_financial_snapshots
from intelligence_engine.research_labels import attach_forward_labels
from intelligence_engine.research_prices import build_price_panel
from intelligence_engine.research_storage import load_dataset, upsert_year_partitions


def _companyfacts() -> dict:
    def row(start, end, value, filed, form="10-Q"):
        return {"start": start, "end": end, "val": value, "filed": filed, "form": form, "accn": f"{end}-{filed}"}
    return {"facts":{"us-gaap":{
        "RevenueFromContractWithCustomerExcludingAssessedTax":{"units":{"USD":[
            row("2023-01-01","2023-03-31",100,"2023-05-01"),row("2023-01-01","2023-06-30",220,"2023-08-01"),row("2023-01-01","2023-09-30",360,"2023-11-01"),row("2023-10-01","2023-12-31",160,"2024-02-01","10-K"),row("2024-01-01","2024-03-31",150,"2024-05-01"),row("2024-01-01","2024-06-30",330,"2024-08-01")]}},
        "EarningsPerShareDiluted":{"units":{"USD/shares":[
            row("2023-01-01","2023-03-31",1.0,"2023-05-01"),row("2023-04-01","2023-06-30",1.2,"2023-08-01"),row("2023-07-01","2023-09-30",1.4,"2023-11-01"),row("2023-10-01","2023-12-31",1.6,"2024-02-01","10-K"),row("2024-01-01","2024-03-31",1.8,"2024-05-01"),row("2024-04-01","2024-06-30",2.0,"2024-08-01")]}},
        "GrossProfit":{"units":{"USD":[row("2023-01-01","2023-03-31",50,"2023-05-01"),row("2023-04-01","2023-06-30",62,"2023-08-01"),row("2023-07-01","2023-09-30",74,"2023-11-01"),row("2023-10-01","2023-12-31",88,"2024-02-01","10-K"),row("2024-01-01","2024-03-31",90,"2024-05-01"),row("2024-04-01","2024-06-30",112,"2024-08-01")]}},
        "OperatingIncomeLoss":{"units":{"USD":[row("2023-01-01","2023-03-31",20,"2023-05-01"),row("2023-04-01","2023-06-30",24,"2023-08-01"),row("2023-07-01","2023-09-30",28,"2023-11-01"),row("2023-10-01","2023-12-31",32,"2024-02-01","10-K"),row("2024-01-01","2024-03-31",38,"2024-05-01"),row("2024-04-01","2024-06-30",45,"2024-08-01")]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding":{"units":{"shares":[row("2023-01-01","2023-03-31",100,"2023-05-01"),row("2023-04-01","2023-06-30",101,"2023-08-01"),row("2023-07-01","2023-09-30",102,"2023-11-01"),row("2023-10-01","2023-12-31",103,"2024-02-01","10-K"),row("2024-01-01","2024-03-31",104,"2024-05-01"),row("2024-04-01","2024-06-30",105,"2024-08-01")]}}
    }}}


def _prices(seed: int, drift: float, periods: int = 700) -> pd.DataFrame:
    rng=np.random.default_rng(seed); dates=pd.bdate_range("2022-01-03",periods=periods); returns=rng.normal(drift,.012,periods); close=50*np.exp(np.cumsum(returns)); high=close*(1+rng.uniform(.002,.02,periods)); low=close*(1-rng.uniform(.002,.02,periods))
    return pd.DataFrame({"open":close,"high":high,"low":low,"close":close,"volume":rng.integers(1_000_000,3_000_000,periods)},index=dates)


def test_companyfacts_point_in_time_and_cumulative_derivation():
    facts=extract_companyfacts_history(_companyfacts(),ticker="TEST"); q2=facts[(facts.metric=="revenue")&(facts.period_end==pd.Timestamp("2023-06-30"))]
    assert len(q2)==1 and q2.iloc[0].value==120 and bool(q2.iloc[0].derived_quarter)
    snapshots=build_financial_snapshots(facts); before=snapshots[snapshots.available_at<=pd.Timestamp("2024-04-01")].iloc[-1]; after=snapshots[snapshots.available_at==pd.Timestamp("2024-05-01")].iloc[-1]
    assert pd.isna(before.eps_yoy) and after.eps_yoy==.8
    panel=pd.DataFrame({"ticker":["TEST","TEST"],"date":pd.to_datetime(["2024-04-15","2024-05-02"])}); merged=merge_financial_snapshots(panel,snapshots)
    assert pd.isna(merged.iloc[0].eps_yoy) and merged.iloc[1].eps_yoy==.8


def test_price_rs_financial_archetype_and_ranking():
    prices={"QQQ":_prices(1,.0002),"FAST":_prices(2,.0012),"SLOW":_prices(3,-.0001)}; universe=pd.DataFrame({"ticker":["FAST","SLOW"],"sector":["Tech","Tech"],"industry":["Software","Software"],"market_cap":[1e10,2e10]})
    panel=build_price_panel(prices,universe,start=pd.Timestamp("2024-01-01"),end=pd.Timestamp("2024-12-31")); latest=panel[panel.date==panel.date.max()].copy()
    latest["eps_yoy"]=[.5 if ticker=="FAST" else -.2 for ticker in latest.ticker]; latest["revenue_yoy"]=[.35 if ticker=="FAST" else -.1 for ticker in latest.ticker]; latest["eps_acceleration"]=[.2 if ticker=="FAST" else -.1 for ticker in latest.ticker]; latest["revenue_acceleration"]=[.1 if ticker=="FAST" else -.1 for ticker in latest.ticker]
    latest["gross_margin_delta"]=[.03,-.02]; latest["operating_margin_delta"]=[.04,-.03]; latest["free_cash_flow_yoy"]=[.4,-.2]; latest["fcf_margin"]=[.2,-.1]; latest["shares_yoy"]=[.01,.12]; latest["fundamental_evidence_count"]=8; latest["fundamental_confidence"]=1.0
    scored=add_research_scores(latest); fast=scored.set_index("ticker").loc["FAST"]; slow=scored.set_index("ticker").loc["SLOW"]
    assert fast.fundamental_quality>slow.fundamental_quality and slow.financial_phase in {"DILUTING","DECELERATING","MARGIN_PRESSURE"}
    ranked=rank_signals(build_signal_pool(scored,max_daily_signals=10),{"groups":[]}); assert not ranked.empty and ranked.iloc[0].ticker=="FAST"


def test_labels_expectancy_and_storage_retention(tmp_path: Path):
    prices={"QQQ":_prices(1,.0002),"FAST":_prices(2,.0012)}; dates=prices["FAST"].index[300:500:5]
    signals=pd.DataFrame({"ticker":"FAST","date":dates,"candidate_archetype":"EMERGING_LEADER","setup":"PRE_BREAKOUT","market_regime":"GREEN","rs_archetype":"ACCELERATING_LEADER","financial_phase":"ACCELERATING","pct_rs_raw_63":90.0,"eps_yoy":.4,"stop_risk_pct":5.0,"reward_risk_raw":3.0,"stop_ema21_low":prices["FAST"].loc[dates,"close"].to_numpy()*.95,"pivot_20d":prices["FAST"].loc[dates,"close"].to_numpy()*1.02})
    outcomes=attach_forward_labels(signals,prices); assert outcomes["outcome_ready_63"].any(); expectancy=build_research_expectancy(outcomes,min_samples=10,bootstrap_samples=50)
    assert expectancy["status"]=="OK" and any(row["group_type"]=="archetype_setup" for row in expectancy["groups"])
    root=tmp_path/"research"; old=signals.head(1).copy(); old["date"]=pd.Timestamp("2019-01-02"); current=signals.head(2).copy(); current["date"]=pd.to_datetime(["2024-01-02","2025-01-02"])
    upsert_year_partitions(root,"signals",pd.concat([old,current]),date_column="date",keys=("ticker","date"),retention_years=5,reference_date=pd.Timestamp("2025-12-31")); stored=load_dataset(root,"signals")
    assert set(pd.to_datetime(stored.date).dt.year)=={2024,2025}
