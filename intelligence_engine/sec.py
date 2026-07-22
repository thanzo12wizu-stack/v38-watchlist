from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .models import FundamentalSnapshot

US_GAAP_TAGS={
"revenue":("RevenueFromContractWithCustomerExcludingAssessedTax","Revenues","SalesRevenueNet"),
"eps":("EarningsPerShareDiluted","EarningsPerShareBasicAndDiluted"),
"gross_profit":("GrossProfit",),"operating_income":("OperatingIncomeLoss",),
"operating_cash_flow":("NetCashProvidedByUsedInOperatingActivities",),
"capex":("PaymentsToAcquirePropertyPlantAndEquipment",),
"shares":("WeightedAverageNumberOfDilutedSharesOutstanding",),}
IFRS_TAGS={
"revenue":("Revenue",),"eps":("DilutedEarningsLossPerShare","BasicAndDilutedEarningsLossPerShare"),
"gross_profit":("GrossProfit",),"operating_income":("ProfitLossFromOperatingActivities","OperatingProfitLoss"),
"operating_cash_flow":("CashFlowsFromUsedInOperatingActivities",),
"capex":("PurchaseOfPropertyPlantAndEquipment",),"shares":("WeightedAverageNumberOfDilutedSharesOutstanding",),}

@dataclass(frozen=True)
class FactPoint:
    start: date|None; end: date; value: float; form: str; filed: date|None
    accession: str|None; frame: str|None; fy: int|None; fp: str|None
    @property
    def duration_days(self)->int|None:
        return (self.end-self.start).days if self.start else None

def _d(v:Any)->date|None:
    if not v:return None
    try:return date.fromisoformat(str(v)[:10])
    except ValueError:return None

def _namespace(facts:dict[str,Any]):
    if "us-gaap" in facts:return "us-gaap",facts["us-gaap"],US_GAAP_TAGS
    if "ifrs-full" in facts:return "ifrs-full",facts["ifrs-full"],IFRS_TAGS
    return None,{},{}

def _points(ns:dict[str,Any],tags:Iterable[str])->list[FactPoint]:
    out=[]
    for tag in tags:
        units=(ns.get(tag) or {}).get("units") or {}
        vals=units.get("USD") or units.get("USD/shares") or units.get("shares") or (next(iter(units.values())) if units else [])
        for r in vals:
            try:v=float(r["val"]); end=_d(r.get("end"))
            except (KeyError,TypeError,ValueError):continue
            if end is None:continue
            out.append(FactPoint(_d(r.get("start")),end,v,str(r.get("form") or ""),_d(r.get("filed")),r.get("accn"),r.get("frame"),r.get("fy"),r.get("fp")))
    dedup={}
    for p in sorted(out,key=lambda x:(x.filed or date.min,x.end)):dedup[(p.start,p.end,p.form)]=p
    return list(dedup.values())

def _quarters(points:list[FactPoint])->list[FactPoint]:
    valid=[p for p in points if p.form in {"10-Q","10-K","20-F","6-K"} and p.start and p.duration_days is not None]
    direct=[p for p in valid if 70<=int(p.duration_days)<=120]
    by_end={p.end:p for p in direct}
    for cum in sorted([p for p in valid if 150<=int(p.duration_days)<=310],key=lambda p:p.end):
        previous=[p for p in direct if p.start==cum.start and p.end<cum.end]
        if not previous or cum.end in by_end:continue
        base=max(previous,key=lambda p:p.end)
        by_end[cum.end]=FactPoint(base.end,cum.end,cum.value-base.value,cum.form,cum.filed,cum.accession,cum.frame,cum.fy,cum.fp)
    return sorted(by_end.values(),key=lambda p:p.end)

def _growth(vals:list[FactPoint]):
    if not vals:return None,None,None
    latest=vals[-1].value
    if len(vals)<5:return latest,None,None
    yoy=latest/vals[-5].value-1 if vals[-5].value else None
    prev=vals[-2].value/vals[-6].value-1 if len(vals)>=6 and vals[-6].value else None
    return latest,yoy,(yoy-prev if yoy is not None and prev is not None else None)

def parse_companyfacts(payload:dict[str,Any])->FundamentalSnapshot:
    standard,ns,tags=_namespace(payload.get("facts") or {})
    if not standard:return FundamentalSnapshot()
    s={k:_quarters(_points(ns,v)) for k,v in tags.items()}
    revenue,ry,ra=_growth(s.get("revenue",[])); eps,ey,ea=_growth(s.get("eps",[]))
    gp=s.get("gross_profit",[]); op=s.get("operating_income",[]); ocf=s.get("operating_cash_flow",[]); capex=s.get("capex",[]); shares=s.get("shares",[])
    gm=gp[-1].value/revenue if gp and revenue not in (None,0) else None
    om=op[-1].value/revenue if op and revenue not in (None,0) else None
    gmd=omd=None
    revs=s.get("revenue",[])
    if len(gp)>=5 and len(revs)>=5 and revs[-5].value:gmd=gm-gp[-5].value/revs[-5].value if gm is not None else None
    if len(op)>=5 and len(revs)>=5 and revs[-5].value:omd=om-op[-5].value/revs[-5].value if om is not None else None
    fcf=fcy=None
    if ocf:
        cap={p.end:p.value for p in capex}
        fs=[FactPoint(p.start,p.end,p.value-abs(cap.get(p.end,0)),p.form,p.filed,p.accession,p.frame,p.fy,p.fp) for p in ocf]
        fcf,fcy,_=_growth(fs)
    sy=shares[-1].value/shares[-5].value-1 if len(shares)>=5 and shares[-5].value else None
    vals=[ry,ra,ey,ea,gmd,omd,fcy,sy]
    dates=[p.filed for points in s.values() for p in points if p.filed]
    return FundamentalSnapshot(revenue,ry,ra,eps,ey,ea,gm,gmd,om,omd,fcf,fcy,sy,sum(v is not None for v in vals)/len(vals),standard,max(dates).isoformat() if dates else None)

def load_companyfacts(path:Path)->FundamentalSnapshot:
    return parse_companyfacts(json.loads(path.read_text(encoding="utf-8")))
