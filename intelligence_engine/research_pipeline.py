from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .pipeline import load_universe
from .prices import load_price_map
from .research_contracts import RESEARCH_POLICY_VERSION, RESEARCH_SCHEMA_VERSION, ResearchConfig, ResearchManifest
from .research_engine import add_research_scores, build_signal_pool, rank_signals
from .research_expectancy import build_research_expectancy
from .research_financials import build_financial_snapshots, merge_financial_snapshots
from .research_labels import attach_forward_labels
from .research_prices import build_price_panel
from .research_providers import NullEstimateProvider, NullEventProvider, NullOwnershipProvider, SecCompanyFactsProvider
from .research_storage import load_dataset, storage_bytes, upsert_year_partitions, write_json


def _latest_date(prices: dict[str,pd.DataFrame], ticker: str="QQQ") -> pd.Timestamp:
    frame=prices.get(ticker)
    if frame is None or frame.empty: raise RuntimeError(f"{ticker} price history is required")
    index=pd.to_datetime(frame.index,errors="coerce")
    if getattr(index,"tz",None) is not None: index=index.tz_convert(None)
    latest=pd.Timestamp(index.max()).normalize()
    if pd.isna(latest): raise RuntimeError(f"{ticker} price history has no valid date")
    return latest


def _date_range(prices,config,*,mode,year,start,end,existing_signals):
    latest=_latest_date(prices); resolved_end=min(pd.Timestamp(end).normalize(),latest) if end else latest
    if year is not None: return pd.Timestamp(year,1,1),min(pd.Timestamp(year,12,31),resolved_end)
    if start: resolved_start=pd.Timestamp(start).normalize()
    elif mode=="incremental" and not existing_signals.empty and "date" in existing_signals:
        previous=pd.to_datetime(existing_signals["date"],errors="coerce").max(); resolved_start=resolved_end if pd.isna(previous) else min(resolved_end,pd.Timestamp(previous).normalize()+pd.Timedelta(days=1))
    else: resolved_start=pd.Timestamp(config.cutoff(resolved_end.date()))
    return resolved_start,resolved_end


def _load_facts(provider: SecCompanyFactsProvider, tickers: list[str]) -> pd.DataFrame:
    frames=[]
    for ticker in tickers:
        history=provider.history(ticker)
        if not history.empty: frames.append(history)
    return pd.concat(frames,ignore_index=True,sort=False) if frames else pd.DataFrame()


def _compact_columns(frame: pd.DataFrame) -> pd.DataFrame:
    columns=["ticker","date","sector","industry","market_cap","price","adr_pct","dollar_volume_20d","volume_ratio_20d","distance_52w_high_pct","pivot_20d","distance_pivot_pct","stop_ema21_low","stop_sma10","stop_risk_pct","reward_risk_raw","extension_atr","supply_risk_raw","hard_block","setup","entry_state","candidate_archetype","financial_phase","rs_archetype","fundamental_quality","fundamental_change","leadership_quality","entry_quality","risk_fit","research_confidence","base_composite","hard_blocks","latest_filing_date","available_at","fundamental_evidence_count","fundamental_confidence","eps_yoy","eps_acceleration","revenue_yoy","revenue_acceleration","gross_margin_delta","operating_margin_delta","free_cash_flow_yoy","fcf_margin","shares_yoy","pct_rs_raw_63","pct_rs_raw_126","pct_rs_raw_189","rs63_rank_change_21d","rs126_rank_change_21d","rs189_rank_change_21d","rs126_top20_persistence_63d","market_regime","days_to_earnings"]
    return frame[[column for column in columns if column in frame.columns]].copy()


def _regime_series(panel: pd.DataFrame, qqq: pd.DataFrame) -> pd.Series:
    qclose=pd.to_numeric(qqq["close"] if "close" in qqq else qqq.iloc[:,0],errors="coerce"); qclose.index=pd.to_datetime(qclose.index,errors="coerce"); qclose=qclose.sort_index()
    points=(qclose>qclose.rolling(20).mean()).astype(int)+(qclose>qclose.rolling(50).mean()).astype(int)+(qclose>qclose.rolling(200).mean()).astype(int)
    return panel["date"].map(points.map({3:"BLUE",2:"GREEN",1:"YELLOW",0:"RED"}))


def _research_summary(rankings: pd.DataFrame, expectancy: dict[str,Any], manifest: dict[str,Any]) -> dict[str,Any]:
    latest_date=pd.to_datetime(rankings.get("date"),errors="coerce").max() if not rankings.empty else pd.NaT
    latest=rankings[pd.to_datetime(rankings["date"],errors="coerce")==latest_date] if pd.notna(latest_date) else rankings.head(0)
    columns=["ticker","research_rank","candidate_archetype","financial_phase","rs_archetype","entry_state","decision_status","composite_rank_score","fundamental_quality","fundamental_change","leadership_quality","entry_quality","risk_fit","research_confidence","expected_edge_10d","expectancy_status","expectancy_samples","setup","price","pivot_20d","stop_ema21_low","stop_sma10","stop_risk_pct","reward_risk_raw","hard_blocks"]
    return {"schema_version":RESEARCH_SCHEMA_VERSION,"policy_version":RESEARCH_POLICY_VERSION,"generated_at":manifest.get("generated_at"),"latest_date":latest_date.date().isoformat() if pd.notna(latest_date) else None,"manifest":manifest,"expectancy_status":expectancy.get("status"),"rankings":latest[[column for column in columns if column in latest.columns]].head(100).to_dict(orient="records")}


def _attach_to_index(index_path: Path, summary: dict[str,Any]) -> None:
    if not index_path.exists(): return
    try: payload=json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return
    if not isinstance(payload,dict): return
    payload["research"]={"schema_version":summary.get("schema_version"),"policy_version":summary.get("policy_version"),"latest_date":summary.get("latest_date"),"manifest":summary.get("manifest"),"rankings":summary.get("rankings")}
    write_json(index_path,payload)


def build(*,universe_path:Path,price_path:Path,sec_dir:Path,root:Path,mode:str="incremental",years:int=5,year:int|None=None,start:str|None=None,end:str|None=None,stride:int=1,max_daily_signals:int=300,min_samples:int=40)->dict[str,Any]:
    generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    config=ResearchConfig(root=root,years=years,stride=max(1,stride),max_daily_signals=max_daily_signals,min_samples=min_samples)
    universe=load_universe(universe_path).reset_index(drop=True); prices=load_price_map(price_path); existing_signals=load_dataset(root,"signals")
    range_start,range_end=_date_range(prices,config,mode=mode,year=year,start=start,end=end,existing_signals=existing_signals)
    if range_start>range_end: range_start=range_end
    panel=build_price_panel(prices,universe,start=range_start,end=range_end,stride=config.stride)
    if panel.empty: raise RuntimeError("research price panel is empty")
    panel["market_regime"]=_regime_series(panel,prices["QQQ"])
    tickers=sorted(panel["ticker"].astype(str).unique()); fundamental_provider=SecCompanyFactsProvider(sec_dir); estimate_provider=NullEstimateProvider(); event_provider=NullEventProvider(); ownership_provider=NullOwnershipProvider()
    facts=_load_facts(fundamental_provider,tickers); snapshots=build_financial_snapshots(facts); panel=merge_financial_snapshots(panel,snapshots)
    scored=add_research_scores(panel); signals=build_signal_pool(scored,max_daily_signals=config.max_daily_signals); compact_signals=_compact_columns(signals)
    facts_result=upsert_year_partitions(root,"facts",facts,date_column="available_at",keys=("ticker","metric","period_end","available_at","accession"),retention_years=config.years,reference_date=range_end) if not facts.empty else {"rows":0,"partitions":0}
    signals_result=upsert_year_partitions(root,"signals",compact_signals,date_column="date",keys=("ticker","date","candidate_archetype","setup"),retention_years=config.years,reference_date=range_end)
    all_signals=load_dataset(root,"signals"); labelled=attach_forward_labels(all_signals,prices,horizons=config.horizons); ready_mask=pd.Series(False,index=labelled.index)
    for horizon in config.horizons:
        column=f"outcome_ready_{horizon}"
        if column in labelled: ready_mask|=labelled[column].fillna(False).astype(bool)
    ready_outcomes=labelled[ready_mask].copy()
    outcomes_result=upsert_year_partitions(root,"outcomes",ready_outcomes,date_column="date",keys=("ticker","date","candidate_archetype","setup"),retention_years=config.years,reference_date=range_end) if not ready_outcomes.empty else {"rows":0,"partitions":0}
    all_outcomes=load_dataset(root,"outcomes"); expectancy=build_research_expectancy(all_outcomes,horizons=config.horizons,min_samples=config.min_samples,bootstrap_samples=config.bootstrap_samples,seed=config.seed); ranked=rank_signals(all_signals,expectancy)
    ranking_result=upsert_year_partitions(root,"rankings",ranked,date_column="date",keys=("ticker","date","candidate_archetype","setup"),retention_years=config.years,reference_date=range_end) if not ranked.empty else {"rows":0,"partitions":0}
    warnings=[]
    if storage_bytes(root)>85*1024*1024: warnings.append("research_store_above_85mb_split_encryption_recommended")
    manifest=ResearchManifest(generated_at=generated_at,mode=mode,start_date=range_start.date().isoformat(),end_date=range_end.date().isoformat(),years_retained=config.years,price_rows=int(len(panel)),fact_rows=int(facts_result.get("rows",0)),signal_rows=int(len(all_signals)),outcome_rows=int(len(all_outcomes)),ranking_rows=int(len(ranked)),tickers=int(panel["ticker"].nunique()),data_provider={"price":"configured_price_cache","fundamental":fundamental_provider.name,"estimate":estimate_provider.name,"event":event_provider.name,"ownership":ownership_provider.name},warnings=warnings).to_dict()
    summary=_research_summary(ranked,expectancy,manifest); write_json(root/"manifest.json",manifest); write_json(root/"expectancy.json",expectancy); write_json(root/"current_rankings.json",summary); _attach_to_index(root.parent/"index.json",summary)
    return {**manifest,"facts_partitions":facts_result.get("partitions",0),"signals_partitions":signals_result.get("partitions",0),"outcomes_partitions":outcomes_result.get("partitions",0),"rankings_partitions":ranking_result.get("partitions",0),"storage_bytes":storage_bytes(root),"expectancy_status":expectancy.get("status")}


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--universe",default="universe.csv"); parser.add_argument("--prices",default="prices.pkl"); parser.add_argument("--sec-dir",default="data/sec_companyfacts"); parser.add_argument("--root",default="data/intelligence/research"); parser.add_argument("--mode",choices=("incremental","backfill"),default="incremental"); parser.add_argument("--years",type=int,default=5); parser.add_argument("--year",type=int,default=None); parser.add_argument("--start",default=None); parser.add_argument("--end",default=None); parser.add_argument("--stride",type=int,default=1); parser.add_argument("--max-daily-signals",type=int,default=300); parser.add_argument("--min-samples",type=int,default=40); args=parser.parse_args()
    result=build(universe_path=Path(args.universe),price_path=Path(args.prices),sec_dir=Path(args.sec_dir),root=Path(args.root),mode=args.mode,years=max(1,args.years),year=args.year,start=args.start,end=args.end,stride=max(1,args.stride),max_daily_signals=max(25,args.max_daily_signals),min_samples=max(10,args.min_samples)); print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
