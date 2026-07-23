from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .research_prices import classify_rs_archetype


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _weighted(values: dict[str, Any], weights: dict[str, float]) -> tuple[float | None, float]:
    available = []
    total = sum(max(0.0, float(weight)) for weight in weights.values())
    for key, weight in weights.items():
        value = _num(values.get(key))
        if value is not None and weight > 0:
            available.append((value, float(weight)))
    if not available:
        return None, 0.0
    used = sum(weight for _, weight in available)
    return sum(value * weight for value, weight in available) / used, used / total if total else 0.0


def _rank_pct(frame: pd.DataFrame, column: str, *, invert: bool = False) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    if invert:
        values = -values
    return frame.assign(_value=values).groupby("date", dropna=False)["_value"].rank(pct=True) * 100.0


def _financial_phase(row: pd.Series) -> str:
    evidence = _num(row.get("fundamental_evidence_count")) or 0
    confidence = _num(row.get("fundamental_confidence")) or 0
    eps_yoy = _num(row.get("eps_yoy")); revenue_yoy = _num(row.get("revenue_yoy"))
    eps_acc = _num(row.get("eps_acceleration")); revenue_acc = _num(row.get("revenue_acceleration"))
    quality_values = [_num(row.get(name)) for name in ("gross_margin_delta", "operating_margin_delta", "free_cash_flow_yoy")]
    quality_values = [value for value in quality_values if value is not None]
    quality = float(np.mean(quality_values)) if quality_values else None
    dilution = _num(row.get("shares_yoy"))
    if evidence < 2 or confidence < .25: return "DATA_INSUFFICIENT"
    if dilution is not None and dilution > .08: return "DILUTING"
    growth_values = [value for value in (eps_yoy, revenue_yoy) if value is not None]
    acceleration_values = [value for value in (eps_acc, revenue_acc) if value is not None]
    growth = float(np.mean(growth_values)) if growth_values else None
    acceleration = float(np.mean(acceleration_values)) if acceleration_values else None
    if growth is not None and growth > .20 and acceleration is not None and acceleration > 0 and (quality is None or quality >= 0): return "ACCELERATING"
    if growth is not None and growth > .10 and (quality is None or quality >= 0): return "COMPOUNDING"
    if acceleration is not None and acceleration > 0 and (growth is None or growth <= .10): return "INFLECTING"
    if growth is not None and growth < 0 and acceleration is not None and acceleration < 0: return "DECELERATING"
    if quality is not None and quality < 0: return "MARGIN_PRESSURE"
    return "STABLE"


def _entry_state(row: pd.Series) -> str:
    setup = str(row.get("setup") or "WATCH")
    if bool(row.get("hard_block")) or setup == "AVOID": return "BROKEN"
    if setup == "EXTENDED": return "EXTENDED"
    if setup == "BREAKOUT": return "TRIGGERED"
    if setup in {"PRE_BREAKOUT", "PULLBACK"}: return "READY"
    return "EARLY"


def _candidate_archetype(row: pd.Series) -> str:
    phase = str(row.get("financial_phase") or "DATA_INSUFFICIENT")
    rs = str(row.get("rs_archetype") or "UNCLASSIFIED")
    setup = str(row.get("setup") or "WATCH")
    r63 = _num(row.get("pct_rs_raw_63")); r189 = _num(row.get("pct_rs_raw_189"))
    story_change = _num(row.get("fundamental_change")); quality = _num(row.get("fundamental_quality"))
    if phase in {"DECELERATING", "MARGIN_PRESSURE", "DILUTING"} or rs == "FADING_LEADER": return "DETERIORATION_ALERT"
    if phase in {"INFLECTING", "ACCELERATING"} and rs in {"NEW_LEADER", "ACCELERATING_LEADER"}: return "EMERGING_LEADER"
    if phase == "COMPOUNDING" and rs == "ESTABLISHED_LEADER" and (quality is None or quality >= 60): return "QUALITY_COMPOUNDER"
    if phase in {"ACCELERATING", "INFLECTING"} and setup in {"PRE_BREAKOUT", "BREAKOUT"} and (r63 is None or r63 >= 70): return "FUNDAMENTAL_BREAKOUT"
    if rs == "REACCELERATING" and phase in {"ACCELERATING", "COMPOUNDING", "STABLE"}: return "REACCELERATION"
    if phase == "INFLECTING" and r63 is not None and r63 >= 60 and (r189 is None or r189 < 70): return "TURNAROUND"
    if story_change is not None and story_change >= 70 and r63 is not None and r63 >= 70: return "EMERGING_LEADER"
    return "NONE"


def add_research_scores(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty: return panel.copy()
    out = panel.copy(); out["date"] = pd.to_datetime(out["date"], errors="coerce")
    rank_specs = {"eps_yoy":False,"revenue_yoy":False,"eps_acceleration":False,"revenue_acceleration":False,"gross_margin_delta":False,"operating_margin_delta":False,"free_cash_flow_yoy":False,"fcf_margin":False,"shares_yoy":True,"trend_alignment":False,"contraction_score_raw":False,"pivot_quality_raw":False,"participation_score_raw":False,"reward_risk_raw":False,"stop_risk_pct":True,"extension_atr":True,"supply_risk_raw":True}
    for column, invert in rank_specs.items():
        if column in out: out[f"pct_{column}"] = _rank_pct(out, column, invert=invert)
    out["financial_phase"] = out.apply(_financial_phase, axis=1); out["rs_archetype"] = out.apply(classify_rs_archetype, axis=1); out["entry_state"] = out.apply(_entry_state, axis=1)
    def score(row: pd.Series) -> pd.Series:
        fq,qc=_weighted({"eps":row.get("pct_eps_yoy"),"revenue":row.get("pct_revenue_yoy"),"gross":row.get("pct_gross_margin_delta"),"operating":row.get("pct_operating_margin_delta"),"fcf":row.get("pct_free_cash_flow_yoy"),"fcf_margin":row.get("pct_fcf_margin"),"dilution":row.get("pct_shares_yoy")},{"eps":.18,"revenue":.17,"gross":.12,"operating":.16,"fcf":.16,"fcf_margin":.11,"dilution":.10})
        fc,cc=_weighted({"eps_acc":row.get("pct_eps_acceleration"),"revenue_acc":row.get("pct_revenue_acceleration"),"gross_delta":row.get("pct_gross_margin_delta"),"operating_delta":row.get("pct_operating_margin_delta"),"fcf":row.get("pct_free_cash_flow_yoy")},{"eps_acc":.30,"revenue_acc":.25,"gross_delta":.15,"operating_delta":.20,"fcf":.10})
        lq,lc=_weighted({"rs63":row.get("pct_rs_raw_63"),"rs126":row.get("pct_rs_raw_126"),"rs189":row.get("pct_rs_raw_189"),"persistence":row.get("rs126_top20_persistence_63d"),"sector":row.get("sector_rank_pct"),"industry":row.get("industry_rank_pct"),"resilience":row.get("pct_downside_resilience_21d")},{"rs63":.16,"rs126":.20,"rs189":.20,"persistence":.18,"sector":.08,"industry":.10,"resilience":.08})
        eq,ec=_weighted({"trend":row.get("pct_trend_alignment"),"contraction":row.get("pct_contraction_score_raw"),"pivot":row.get("pct_pivot_quality_raw"),"participation":row.get("pct_participation_score_raw"),"rr":row.get("pct_reward_risk_raw"),"stop":row.get("pct_stop_risk_pct"),"extension":row.get("pct_extension_atr"),"supply":row.get("pct_supply_risk_raw")},{"trend":.20,"contraction":.18,"pivot":.20,"participation":.10,"rr":.14,"stop":.08,"extension":.06,"supply":.04})
        rf,rc=_weighted({"stop":row.get("pct_stop_risk_pct"),"extension":row.get("pct_extension_atr"),"supply":row.get("pct_supply_risk_raw"),"liquidity":row.get("pct_dollar_volume_20d")},{"stop":.35,"extension":.25,"supply":.20,"liquidity":.20})
        conf=float(np.mean([qc,cc,lc,ec,_num(row.get("fundamental_confidence")) or 0.0]))
        return pd.Series({"fundamental_quality":fq,"fundamental_change":fc,"leadership_quality":lq,"entry_quality":eq,"risk_fit":rf,"research_confidence":conf})
    out=pd.concat([out,out.apply(score,axis=1)],axis=1); out["candidate_archetype"]=out.apply(_candidate_archetype,axis=1)
    return out


def _hard_blocks(row: pd.Series) -> list[str]:
    blocks=[]
    if bool(row.get("hard_block")): blocks.append("LONG_TREND_BROKEN")
    stop=_num(row.get("stop_risk_pct")); rr=_num(row.get("reward_risk_raw")); days=_num(row.get("days_to_earnings"))
    if stop is not None and stop>12: blocks.append("STOP_TOO_WIDE")
    if rr is not None and rr<1.2: blocks.append("REWARD_RISK_LOW")
    if str(row.get("financial_phase")) in {"DECELERATING","MARGIN_PRESSURE","DILUTING"}: blocks.append("FUNDAMENTAL_DETERIORATION")
    if str(row.get("rs_archetype")) in {"FADING_LEADER","FALSE_LEADERSHIP"}: blocks.append("LEADERSHIP_RISK")
    if days is not None and -3<=days<=3: blocks.append("EARNINGS_WINDOW")
    return blocks


def build_signal_pool(scored: pd.DataFrame, max_daily_signals: int = 300) -> pd.DataFrame:
    if scored.empty: return scored.copy()
    work=scored.copy(); work["hard_blocks"]=work.apply(_hard_blocks,axis=1)
    work["base_composite"]=work.apply(lambda row:_weighted({"fundamental_quality":row.get("fundamental_quality"),"fundamental_change":row.get("fundamental_change"),"leadership_quality":row.get("leadership_quality"),"entry_quality":row.get("entry_quality")},{"fundamental_quality":.30,"fundamental_change":.25,"leadership_quality":.30,"entry_quality":.15})[0],axis=1)
    selected=work[(work["candidate_archetype"]!="NONE")|(pd.to_numeric(work["base_composite"],errors="coerce")>=70)].copy()
    if selected.empty: return selected
    selected=selected.sort_values(["date","base_composite","research_confidence","ticker"],ascending=[True,False,False,True])
    return selected.groupby("date",group_keys=False).head(max_daily_signals).reset_index(drop=True)


def _expectancy_lookup(expectancy: dict[str,Any]|None) -> dict[tuple[str,str,int],dict[str,Any]]:
    lookup={}
    if not expectancy: return lookup
    for row in expectancy.get("groups",[]):
        if row.get("group_type")=="archetype_setup": lookup[(str(row.get("candidate_archetype")),str(row.get("setup")),int(row.get("horizon") or 0))]=row
    return lookup


def rank_signals(signals: pd.DataFrame, expectancy: dict[str,Any]|None=None) -> pd.DataFrame:
    if signals.empty: return signals.copy()
    lookup=_expectancy_lookup(expectancy); out=signals.copy(); edges=[]; statuses=[]; samples=[]
    for _,row in out.iterrows():
        match=lookup.get((str(row.get("candidate_archetype")),str(row.get("setup")),10))
        if match is None: edges.append(None); statuses.append("UNAVAILABLE"); samples.append(0)
        else: edges.append(_num(match.get("mean_excess_return"))); statuses.append(str(match.get("qualification") or "EXPLORATORY")); samples.append(int(match.get("samples") or 0))
    out["expected_edge_10d"]=edges; out["expectancy_status"]=statuses; out["expectancy_samples"]=samples
    def final(row:pd.Series)->pd.Series:
        base=_num(row.get("base_composite")) or 0; edge=_num(row.get("expected_edge_10d")); adjustment=0
        if edge is not None and row.get("expectancy_status")=="QUALIFIED": adjustment=float(np.clip(edge*500,-10,10))
        elif edge is not None and row.get("expectancy_status")=="PROMISING": adjustment=float(np.clip(edge*250,-5,5))
        risk=(_num(row.get("risk_fit")) or 50)/100; conf=float(np.clip(_num(row.get("research_confidence")) or 0,0,1)); score=(base+adjustment)*(.80+.20*risk)*(.80+.20*conf)
        blocks=row.get("hard_blocks") if isinstance(row.get("hard_blocks"),list) else []; state=str(row.get("entry_state") or "EARLY")
        status="AVOID" if blocks else ("ACTIONABLE" if state in {"READY","TRIGGERED"} else "READY")
        return pd.Series({"composite_rank_score":float(np.clip(score,0,100)),"decision_status":status})
    out=pd.concat([out,out.apply(final,axis=1)],axis=1); out=out.sort_values(["date","composite_rank_score","research_confidence","ticker"],ascending=[True,False,False,True]); out["research_rank"]=out.groupby("date").cumcount()+1
    return out.reset_index(drop=True)
