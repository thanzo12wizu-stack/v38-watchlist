#!/usr/bin/env python3
"""Build standalone Options Intelligence from read-only upstream V38 artifacts.

This is deliberately downstream-only. It reads Dashboard / Rotation / Options outputs,
never writes back to them, and writes only options_intelligence*. Direction is an
interpretable research bias, not an observed dealer-position or trade-side signal.
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

POSITIONING = Path(os.environ.get("V38_OPT_JSON", "options_positioning.json"))
DETAIL_HISTORY = Path(os.environ.get("V38_OPT_HISTORY", "options_history.csv"))
SCAN_HISTORY = Path(os.environ.get("V38_OPT_SCAN_HISTORY", "options_scan_history.csv"))
UNIVERSE = Path(os.environ.get("V38_UNIVERSE_CSV", "universe.csv"))
STATE = Path(os.environ.get("V38_STATE_JSON", "state.json"))
LEADERS = Path(os.environ.get("V38_OPT_LEADERS_JSON", "rotation/data/rotation-theme56-stock-context.json"))
OUT_JSON = Path(os.environ.get("V38_OPT_INTEL_JSON", "options_intelligence.json"))
OUT_HISTORY = Path(os.environ.get("V38_OPT_INTEL_HISTORY", "options_intelligence_history.csv"))
TAPE_JSON = Path(os.environ.get("V38_OPT_TAPE_JSON", "options_tape.json"))

SIGNALS = ("ACCELERATION", "SUPPORTIVE", "BREAKOUT WATCH", "NEUTRAL", "HEADWIND", "DATA LOW")
DIRECTIONS = ("UP", "DOWN", "RANGE", "VOLATILE", "UNKNOWN")


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _read_csv(path: Path):
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _day(v):
    return str(v or "")[:10]


def _boolish(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "y")


def _age_days(day: str, today: str):
    try:
        return max(0, (datetime.fromisoformat(today) - datetime.fromisoformat(day)).days)
    except Exception:
        return None


def _latest_two(rows):
    grouped = defaultdict(list)
    for row in rows:
        tk = str(row.get("ticker") or "").strip().upper()
        if tk:
            grouped[tk].append(row)
    out = {}
    for tk, vals in grouped.items():
        by_date = {}
        for row in vals:
            by_date[_day(row.get("date"))] = row
        ordered = [by_date[k] for k in sorted(by_date) if k]
        out[tk] = (ordered[-1], ordered[-2] if len(ordered) >= 2 else None) if ordered else (None, None)
    return out


def _state_context():
    try:
        raw = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return {"session_date": _day(raw.get("date")), "gate": raw.get("gate"),
            "mri": _f(raw.get("mri")), "source": str(STATE)}


def _universe_meta():
    out = {}
    for row in _read_csv(UNIVERSE):
        tk = str(row.get("シンボル") or row.get("ticker") or "").strip().upper()
        if not tk:
            continue
        out[tk] = {"name": row.get("名称") or row.get("name") or "",
                   "sector": row.get("セクター") or row.get("sector") or "",
                   "industry": row.get("業種") or row.get("industry") or "",
                   "price": _f(row.get("価格") or row.get("price")),
                   "change_pct": _f(row.get("価格変動 %, 1日") or row.get("change_pct")),
                   "volume": _f(row.get("出来高, 1日") or row.get("volume")),
                   "security_type": str(row.get("証券種別") or row.get("security_type") or "").lower()}
    return out


def _leader_score(x):
    def n(key, default=50.0):
        v = _f(x.get(key)); return default if v is None else v
    acc = _f(x.get("slow_acceleration"))
    if acc is None:
        acc = _f(x.get("acceleration")) or 0.0
    score = .36*n("strength") + .25*n("rs189") + .20*n("rs63") + .11*n("rs21") + .08*max(0, min(100, 50+acc))
    if str(x.get("role") or "").upper() == "LEADER": score += 3
    if str(x.get("group_phase") or "").upper() in ("LEADING", "EMERGING"): score += 3
    if "BREAKOUT" in str(x.get("breakout_status") or "").upper(): score += 3
    return max(0, min(100, int(round(score))))


def _leader_map():
    try:
        root = json.loads(LEADERS.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    out = {}
    def walk(node, ctx=None):
        ctx = dict(ctx or {})
        if isinstance(node, list):
            for v in node: walk(v, ctx)
            return
        if not isinstance(node, dict): return
        if node.get("etf"): ctx["etf"] = node.get("etf")
        if node.get("label"): ctx["theme"] = node.get("label")
        sym = node.get("symbol")
        if isinstance(sym, str) and (node.get("role") or node.get("strength") is not None or node.get("rs189") is not None or node.get("stock_rank_within_group") is not None):
            tk = sym.strip().upper()
            candidate = {"ticker": tk, "name": node.get("name") or "", "leader_score": _leader_score(node),
                         "strength": _f(node.get("strength")), "rs189": _f(node.get("rs189")),
                         "rs63": _f(node.get("rs63")), "rs21": _f(node.get("rs21")),
                         "role": node.get("role"), "group": node.get("group") or ctx.get("theme") or "",
                         "group_phase": node.get("group_phase"), "breakout_status": node.get("breakout_status"),
                         "etf": ctx.get("etf") or ""}
            if tk and (tk not in out or candidate["leader_score"] > out[tk]["leader_score"]): out[tk] = candidate
        for k, v in node.items():
            if k not in ("symbol", "name") and isinstance(v, (dict, list)): walk(v, ctx)
    walk(root)
    meta = {"generated_at": root.get("leadership_generated_at"), "market": root.get("leadership_market") or {}, "source": str(LEADERS)} if isinstance(root, dict) else {}
    return out, meta


def _hist_obs(row, source="HISTORY"):
    if not row: return None
    is_scan = source == "SCAN"
    em = {
        "expected_move": _f(row.get("expected_move")),
        "expected_move_pct": _f(row.get("expected_move_pct")),
        "expected_move_method": row.get("expected_move_method"),
        "expected_low": _f(row.get("expected_low")),
        "expected_high": _f(row.get("expected_high")),
    }
    return {"date": _day(row.get("date")),
            "price_session_date": _day(row.get("price_session_date") or row.get("date")),
            "expected_session_date": _day(row.get("expected_session_date") or (row.get("date") if is_scan else "")),
            "history_session_date": _day(row.get("history_session_date")),
            "price_source": row.get("price_source"), "options_observed_at": row.get("observed_at"),
            "expiry": row.get("expiry"), "spot": _f(row.get("spot")), "atr14": _f(row.get("atr14")),
            "call_wall": _f(row.get("call_wall")), "put_wall": _f(row.get("put_wall")),
            "gamma_flip": _f(row.get("gamma_flip")), "net_gex": _f(row.get("net_gex")),
            "regime": str(row.get("regime") or "UNKNOWN"), "confidence": str(row.get("confidence") or "").upper(),
            "total_oi": _f(row.get("total_oi")), "n_strikes": _f(row.get("n_strikes")),
            "call_oi": _f(row.get("call_oi")), "put_oi": _f(row.get("put_oi")),
            "detail": False, "stale": False,
            "session_consistent": _boolish(row.get("session_consistent")) if is_scan else False,
            "time_quality": "SCAN_PENDING_VERIFY" if is_scan else "UNVERIFIED_HISTORY",
            "expected_move": em if any(v not in (None, "") for v in em.values()) else None}


def _current_obs(rec, asof):
    if not isinstance(rec, dict): return None
    exp_key = rec.get("selected_expiry") or rec.get("nearest")
    exp = (rec.get("expiries") or {}).get(exp_key) if exp_key else {}
    em = rec.get("expected_move") or {k: (exp or {}).get(k) for k in (
        "expected_move", "expected_move_pct", "expected_move_method", "expected_low", "expected_high",
        "atm_iv", "straddle_move", "straddle_move_pct", "iv_1sigma_move", "iv_1sigma_move_pct")}
    return {"date": _day(rec.get("price_session_date") or rec.get("asof") or asof),
            "price_session_date": _day(rec.get("price_session_date") or rec.get("asof") or asof),
            "expected_session_date": _day(rec.get("expected_session_date")), "history_session_date": _day(rec.get("history_session_date")),
            "tech_session_date": _day(rec.get("tech_session_date")), "session_consistent": bool(rec.get("session_consistent")),
            "price_source": rec.get("price_source") or rec.get("source"), "options_observed_at": rec.get("options_observed_at") or rec.get("asof") or asof,
            "oi_observed_at": rec.get("oi_observed_at"), "oi_basis": rec.get("oi_basis"), "expiry": exp_key,
            "spot": _f(rec.get("spot")), "atr14": _f(rec.get("atr14")), "call_wall": _f((rec.get("call_wall") or {}).get("px")),
            "put_wall": _f((rec.get("put_wall") or {}).get("px")), "gamma_flip": _f((rec.get("gamma_flip") or {}).get("px")),
            "net_gex": _f(rec.get("net_gex")), "regime": str(rec.get("regime") or "UNKNOWN"), "confidence": str(rec.get("confidence") or "").upper(),
            "total_oi": _f((exp or {}).get("total_oi")), "n_strikes": _f((exp or {}).get("n_strikes")), "call_oi": _f((exp or {}).get("call_oi")),
            "put_oi": _f((exp or {}).get("put_oi")), "call_wall_share": _f((exp or {}).get("call_wall_share")),
            "put_wall_share": _f((exp or {}).get("put_wall_share")), "call_wall_vs_second": _f((exp or {}).get("call_wall_vs_second")),
            "put_wall_vs_second": _f((exp or {}).get("put_wall_vs_second")), "call_walls": (exp or {}).get("call_walls") or [],
            "put_walls": (exp or {}).get("put_walls") or [], "refresh_failed": bool(rec.get("refresh_failed")), "stale": bool(rec.get("stale")),
            "tech": rec.get("tech") or {}, "detail": True, "expected_move": em, "upstream_change_pct": _f(rec.get("upstream_change_pct"))}


def _regime_for(spot, flip, atr):
    if spot is None or flip is None: return "UNKNOWN"
    if atr and atr > 0 and abs(spot-flip)/atr <= 1.0: return "NEAR_FLIP"
    return "POSITIVE_GAMMA" if spot > flip else "NEGATIVE_GAMMA"


def _multi_expiry(rec):
    if not isinstance(rec, dict): return None
    spot, atr = _f(rec.get("spot")), _f(rec.get("atr14")); regimes=[]
    for exp in (rec.get("expiries") or {}).values(): regimes.append(_regime_for(spot, _f((exp or {}).get("gamma_flip")), atr))
    if not regimes: return None
    c=Counter(regimes); return {"count":len(regimes),"positive":c.get("POSITIVE_GAMMA",0),"near":c.get("NEAR_FLIP",0),"negative":c.get("NEGATIVE_GAMMA",0),"unknown":c.get("UNKNOWN",0)}


def _crossed_previous_call(prev, cur):
    if not prev: return False
    ps, pcw, cs = prev.get("spot"), prev.get("call_wall"), cur.get("spot")
    return None not in (ps,pcw,cs) and ps < pcw and cs > pcw*1.002


def _crossed_previous_put(prev, cur):
    if not prev: return False
    ps, ppw, cs = prev.get("spot"), prev.get("put_wall"), cur.get("spot")
    return None not in (ps,ppw,cs) and ps > ppw and cs < ppw*0.998


def _dist_atr(level, spot, atr):
    if level is None or spot is None or not atr or atr <= 0: return None
    return (level-spot)/atr


def _classify(cur, prev=None, multi=None, age=None):
    spot, atr = cur.get("spot"), cur.get("atr14"); cw,pw,gf=cur.get("call_wall"),cur.get("put_wall"),cur.get("gamma_flip")
    conf=str(cur.get("confidence") or "").upper(); reg=cur.get("regime") or _regime_for(spot,gf,atr)
    if cur.get("stale") or spot is None or conf=="LOW" or (age is not None and age>18): return "DATA LOW",0,["データ量または鮮度が不足"]
    ca,pa=_dist_atr(cw,spot,atr),_dist_atr(pw,spot,atr); br=_crossed_previous_call(prev,cur); score=50; reasons=[]
    if reg=="POSITIVE_GAMMA": score+=18; reasons.append("Gamma Flip上")
    elif reg=="NEGATIVE_GAMMA": score-=28; reasons.append("Gamma Flip下の増幅側")
    elif reg=="NEAR_FLIP": score-=4; reasons.append("Gamma Flip近辺")
    if pa is not None and pa<0 and abs(pa)<=2.2: score+=10; reasons.append("Put支持候補が近い")
    if ca is not None:
        if 0<ca<=1.2: score+=4; reasons.append("Call Wall接近")
        elif ca>1.2: score+=6; reasons.append("上側Wallまで余地")
    if _f(cur.get("net_gex")) is not None and cur.get("net_gex")>0: score+=5; reasons.append("Net GEXプラス")
    if conf in ("HIGH","OK","MEDIUM"): score+=4
    if multi and multi.get("positive",0)>multi.get("negative",0): score+=5; reasons.append("複数満期もFlip上側優勢")
    if br: score+=18; reasons.append("前回Call Wallを突破")
    score=max(0,min(100,int(round(score))))
    if br and reg!="NEGATIVE_GAMMA": return "ACCELERATION",score,reasons
    if reg=="NEGATIVE_GAMMA": return "HEADWIND",score,reasons
    if reg in ("POSITIVE_GAMMA","NEAR_FLIP") and ca is not None and 0<ca<=1.2: return "BREAKOUT WATCH",score,reasons
    if reg=="POSITIVE_GAMMA": return "SUPPORTIVE",score,reasons
    return "NEUTRAL",score,reasons


def _time_quality(cur, session_date, source):
    if not cur: return "PERIOD_UNAVAILABLE"
    if cur.get("refresh_failed") or cur.get("stale"): return "STALE"
    if source not in ("DETAIL", "SCAN"): return "UNVERIFIED_HISTORY"
    pday = _day(cur.get("price_session_date"))
    expected = _day(cur.get("expected_session_date") or session_date)
    if not cur.get("session_consistent"): return "MISMATCH"
    if session_date and pday != session_date: return "MISMATCH"
    if expected and pday != expected: return "MISMATCH"
    if source == "SCAN" and (cur.get("spot") is None or str(cur.get("confidence") or "").upper() == "LOW"):
        return "LOW_QUALITY"
    return "VERIFIED"


def _direction_bias(cur, prev=None, multi=None, meta=None, leader=None, time_quality="UNKNOWN"):
    meta=meta or {}; leader=leader or {}; spot,atr=cur.get("spot"),cur.get("atr14")
    if time_quality!="VERIFIED" or spot is None or str(cur.get("confidence") or "").upper()=="LOW":
        return {"direction":"UNKNOWN","score":50,"confidence":0,"reasons":["同一セッションの価格/Options整合を確認できない"],"volatility":"UNKNOWN"}
    score=50; reasons=[]; gf,pw,cw=cur.get("gamma_flip"),cur.get("put_wall"),cur.get("call_wall"); tech=cur.get("tech") or {}
    if gf is not None:
        d=(spot-gf)/(atr or max(spot*.02,.01))
        if d>0.35: score+=10; reasons.append("終値がGamma Flip上")
        elif d<-0.35: score-=10; reasons.append("終値がGamma Flip下")
        else: reasons.append("Gamma Flip近辺")
    ema=_f(tech.get("21EMA")); vwap=_f(tech.get("63VWAP"))
    if ema is not None: score += 8 if spot>ema else -8; reasons.append("21EMA上" if spot>ema else "21EMA下")
    if vwap is not None: score += 5 if spot>vwap else -5; reasons.append("63VWAP上" if spot>vwap else "63VWAP下")
    chg=_f(meta.get("change_pct"))
    if chg is not None:
        if chg>=2: score+=5; reasons.append("当日モメンタム上")
        elif chg<=-2: score-=5; reasons.append("当日モメンタム下")
    up=_dist_atr(cw,spot,atr); down=None if pw is None or not atr else (spot-pw)/atr
    if up is not None and down is not None and up>0 and down>0:
        ratio=up/max(down,.05)
        if ratio>=1.4: score+=10; reasons.append("上側余地が下側リスクより広い")
        elif ratio<=0.7: score-=10; reasons.append("上側Wallが近く下側余地が広い")
        elif ratio>=1.15: score+=4
        elif ratio<=.87: score-=4
    if _crossed_previous_call(prev,cur): score+=12; reasons.append("前回Call Wall突破")
    if _crossed_previous_put(prev,cur): score-=12; reasons.append("前回Put Wall割れ")
    if multi:
        if multi.get("positive",0)>multi.get("negative",0): score+=6; reasons.append("複数満期でFlip上が多数")
        elif multi.get("negative",0)>multi.get("positive",0): score-=6; reasons.append("複数満期でFlip下が多数")
    ls=_f(leader.get("leader_score"))
    if ls is not None:
        if ls>=75: score+=6; reasons.append("Leadership上位")
        elif ls>=60: score+=3
        elif ls<40: score-=3
    score=max(0,min(100,int(round(score))))
    reg=str(cur.get("regime") or "UNKNOWN")
    if score>=68: direction="UP"
    elif score<=32: direction="DOWN"
    elif 44<=score<=56 and reg=="POSITIVE_GAMMA": direction="RANGE"
    else: direction="VOLATILE" if reg in ("NEGATIVE_GAMMA","NEAR_FLIP") else "RANGE"
    conf=max(20,min(95,int(round(45+abs(score-50)*1.35+(8 if str(cur.get("confidence") or "").upper()=="HIGH" else 0)))))
    em=(cur.get("expected_move") or {}); ep=_f(em.get("expected_move_pct"))
    if ep is None: vol="EXPANSION" if reg=="NEGATIVE_GAMMA" else "UNKNOWN"
    elif ep>=.08: vol="HIGH"
    elif ep>=.04: vol="MEDIUM"
    else: vol="LOW"
    if reg=="NEGATIVE_GAMMA" and vol in ("LOW","MEDIUM"): vol="EXPANSION"
    return {"direction":direction,"score":score,"confidence":conf,"reasons":reasons,"volatility":vol}


def _plan(cur, signal):
    spot=cur.get("spot"); cw,pw,gf=cur.get("call_wall"),cur.get("put_wall"),cur.get("gamma_flip")
    if signal=="ACCELERATION": entry="突破済みWallが支持へ変わるか確認。高値追いより初押し優先。"
    elif signal=="BREAKOUT WATCH" and cw is not None: entry=f"Call Wall {cw:.2f} を終値突破し、次の足でも維持できれば加速候補。"
    elif signal=="SUPPORTIVE": entry=f"Gamma Flip {gf:.2f} 付近への押しで反発確認を優先。" if gf is not None and spot is not None and gf<spot else (f"Put Wall {pw:.2f} 付近の反発確認を優先。" if pw is not None else "押し目反発を優先。")
    elif signal=="HEADWIND": entry=f"Gamma Flip {gf:.2f} の奪回待ち。" if gf is not None else "新規追随は見送り。"
    else: entry="Gamma Flipから方向が離れるまで待つ。"
    invalid="明確な無効化水準なし"
    if gf is not None and spot is not None and gf<spot:
        invalid=f"Gamma Flip {gf:.2f} 終値割れで構造悪化"
        if pw is not None and pw<spot: invalid+=f"、Put Wall {pw:.2f} 割れで支持シナリオ失効"
    elif gf is not None and spot is not None and gf>spot: invalid=f"Gamma Flip {gf:.2f} を奪回できない間は上方向シナリオ保留"
    elif pw is not None and spot is not None and pw<spot: invalid=f"Put Wall {pw:.2f} 終値割れで支持シナリオ失効"
    return {"entry":entry,"invalid":invalid,"target":f"次のCall Wall {cw:.2f}" if cw is not None else "上側Call Wallなし"}


def _direction_comment(cur, direction, leader=None):
    spot=cur.get("spot"); gf,pw,cw=cur.get("gamma_flip"),cur.get("put_wall"),cur.get("call_wall"); em=cur.get("expected_move") or {}
    move=_f(em.get("expected_move")); ep=_f(em.get("expected_move_pct")); method=em.get("expected_move_method")
    prefix={"UP":"オプション配置は上方向優位。","DOWN":"オプション配置は下方向優位。","RANGE":"現状はレンジ寄り。","VOLATILE":"方向は混在、値幅拡大に注意。","UNKNOWN":"時間整合を確認できず方向判定を保留。"}.get(direction,"")
    bits=[]
    if gf is not None and spot is not None: bits.append(f"基準終値{spot:.2f}はFlip {gf:.2f}の{'上' if spot>gf else '下'}")
    if pw is not None: bits.append(f"下はPut Wall {pw:.2f}")
    if cw is not None: bits.append(f"上はCall Wall {cw:.2f}")
    if move is not None and ep is not None: bits.append(f"{cur.get('expiry') or ''}までの織込み値幅は約±{move:.2f}（{ep*100:.1f}%、{method}）")
    if leader and _f(leader.get("leader_score")) is not None and leader["leader_score"]>=70: bits.append("Leadershipも上位")
    return prefix + (" ".join(bits) + "。" if bits else "")


def _load_tape():
    if not TAPE_JSON.is_file(): return {}
    try:
        raw=json.loads(TAPE_JSON.read_text(encoding="utf-8")); return raw.get("tickers",raw) if isinstance(raw,dict) else {}
    except Exception: return {}


def build():
    now=datetime.now(timezone.utc).replace(microsecond=0); today=now.date().isoformat(); state=_state_context(); session_date=state.get("session_date") or today
    positioning={}; asof=""; quality={}
    if POSITIONING.is_file():
        raw=json.loads(POSITIONING.read_text(encoding="utf-8")); positioning=raw.get("tickers") or {}; asof=raw.get("asof") or ""; quality=raw.get("quality") or {}; session_date=_day(raw.get("session_date")) or session_date
    dh=_latest_two(_read_csv(DETAIL_HISTORY)); sh=_latest_two(_read_csv(SCAN_HISTORY)); meta=_universe_meta(); leaders,leader_meta=_leader_map(); tape=_load_tape()
    tickers=set(meta)|set(dh)|set(sh)|set(positioning)|set(leaders); records=[]
    for tk in sorted(tickers):
        detailed=positioning.get(tk)
        if detailed:
            cur=_current_obs(detailed,asof); prev=_hist_obs((dh.get(tk) or (None,None))[1]); source="DETAIL"
        else:
            latest,previous=sh.get(tk) or dh.get(tk) or (None,None); source="SCAN" if tk in sh else "HISTORY"; cur=_hist_obs(latest,source); prev=_hist_obs(previous,source)
        if not cur: continue
        age=_age_days(cur.get("price_session_date") or cur.get("date"),today); multi=_multi_expiry(detailed); tq=_time_quality(cur,session_date,source)
        signal,score,reasons=_classify(cur,prev,multi,age)
        if tq!="VERIFIED": signal,score="DATA LOW",0; reasons=["同一セッションの価格とOptionsを確認できない"]
        leader=leaders.get(tk); direction=_direction_bias(cur,prev,multi,meta.get(tk),leader,tq)
        rec={"ticker":tk,"name":(meta.get(tk) or {}).get("name",leader.get("name","") if leader else ""),"sector":(meta.get(tk) or {}).get("sector",""),"industry":(meta.get(tk) or {}).get("industry",""),
             "source":source,"age_days":age,"time_quality":tq,"session_date":session_date,"signal":signal,"score":score,"reasons":reasons,"current":cur,"previous":prev,"multi_expiry":multi,
             "direction":direction,"analysis":_direction_comment(cur,direction["direction"],leader),"plan":_plan(cur,signal),"leader":leader,"tape":tape.get(tk) if isinstance(tape,dict) else None,
             "trade_direction_available":bool(isinstance(tape,dict) and tape.get(tk)),
             "limitations":["OI/IVは観測するがproviderのOI更新時刻は非開示","約定方向が無いためPut売り/Call買いは断定しない"]}
        records.append(rec)
    records.sort(key=lambda r:(0 if r["time_quality"]=="VERIFIED" else 1, -r["direction"]["confidence"], -abs(r["direction"]["score"]-50), -r["score"], r["ticker"]))
    sc=Counter(r["signal"] for r in records); dc=Counter(r["direction"]["direction"] for r in records)
    payload={"schema_version":"2.0","generated_at":now.isoformat().replace("+00:00","Z"),"session_date":session_date,"positioning_asof":asof,"quality":quality,"state":state,"leadership":leader_meta,
             "method":"research_direction_bias_not_v38_ranking","upstream_read_only":[str(STATE),str(UNIVERSE),str(LEADERS)],"trade_tape":"optional_options_tape_json" if tape else "unavailable_from_current_provider",
             "summary":{"coverage":len(records),**{s:sc.get(s,0) for s in SIGNALS},**{f"DIR_{d}":dc.get(d,0) for d in DIRECTIONS}},"records":records}
    OUT_JSON.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8"); _append_history(records,session_date); return payload


def _append_history(records, session_date):
    fields=["date","ticker","signal","score","direction","direction_score","direction_confidence","expected_move_pct","spot","atr14","call_wall","put_wall","gamma_flip","net_gex","regime","confidence","source","time_quality"]
    merged={}
    if OUT_HISTORY.is_file():
        for row in _read_csv(OUT_HISTORY):
            key=(row.get("date",""),row.get("ticker",""));
            if all(key): merged[key]=row
    for rec in records:
        if rec.get("time_quality")!="VERIFIED": continue
        cur=rec["current"]; em=cur.get("expected_move") or {}; d=rec["direction"]
        row={"date":session_date,"ticker":rec["ticker"],"signal":rec["signal"],"score":rec["score"],"direction":d["direction"],"direction_score":d["score"],"direction_confidence":d["confidence"],"expected_move_pct":em.get("expected_move_pct"),
             "spot":cur.get("spot"),"atr14":cur.get("atr14"),"call_wall":cur.get("call_wall"),"put_wall":cur.get("put_wall"),"gamma_flip":cur.get("gamma_flip"),"net_gex":cur.get("net_gex"),"regime":cur.get("regime"),"confidence":cur.get("confidence"),"source":rec["source"],"time_quality":rec["time_quality"]}
        merged[(session_date,rec["ticker"])]=row
    with OUT_HISTORY.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader()
        for key in sorted(merged): w.writerow({k:merged[key].get(k,"") for k in fields})


def main():
    p=build(); print(json.dumps({"coverage":p["summary"]["coverage"],"summary":p["summary"]},ensure_ascii=False))


if __name__=="__main__": main()
