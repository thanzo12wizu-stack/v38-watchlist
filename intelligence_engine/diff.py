from __future__ import annotations
from typing import Any

def compare_stock(previous:dict[str,Any],current:dict[str,Any])->dict[str,Any]:
    tracked=["score_candidate","score_emerging","score_compounder","score_breakout","score_momentum","score_fundamental","score_improvement","eps_yoy","eps_acceleration","revenue_yoy","revenue_acceleration","gross_margin_delta","operating_margin_delta"]
    changes={}
    for key in tracked:
        old,new=previous.get(key),current.get(key)
        if isinstance(old,(int,float)) and isinstance(new,(int,float)):
            delta=float(new)-float(old)
            if abs(delta)>1e-12:changes[key]={"from":old,"to":new,"delta":delta}
        elif old!=new:changes[key]={"from":old,"to":new}
    return {"ticker":current.get("ticker"),"changed":bool(changes),"changes":changes}
