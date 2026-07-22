from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

EXTERNAL_DATA_POLICY_VERSION = "1.0.0"


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists(): return pd.DataFrame()
    if path.suffix.lower() == ".json":
        payload=json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload,dict):
            payload=payload.get("records") or payload.get("data") or payload.get("items") or []
        return pd.DataFrame(payload)
    return pd.read_csv(path)


def _norm_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty: return frame
    cols={str(c).strip().lower():c for c in frame.columns}
    source=next((cols[x] for x in ("ticker","symbol","ティッカー","シンボル") if x in cols),None)
    if source is None: return pd.DataFrame()
    out=frame.rename(columns={source:"ticker"}).copy()
    out["ticker"]=out["ticker"].astype(str).str.upper().str.strip()
    return out[out["ticker"].ne("") & out["ticker"].ne("NAN")]


def _latest_by_ticker(frame: pd.DataFrame, date_names: tuple[str,...]) -> dict[str,dict]:
    frame=_norm_ticker(frame)
    if frame.empty: return {}
    cols={str(c).strip().lower():c for c in frame.columns}
    date_col=next((cols[n] for n in date_names if n in cols),None)
    if date_col is not None:
        frame["_date"]=pd.to_datetime(frame[date_col],errors="coerce")
        frame=frame.sort_values(["ticker","_date"])
    return {str(t):g.iloc[-1].drop(labels=["_date"],errors="ignore").to_dict() for t,g in frame.groupby("ticker")}


def load_external_layer(root: Path) -> dict[str,Any]:
    root=Path(root)
    earnings=_latest_by_ticker(_read_table(root/"earnings_calendar.csv"),("earnings_date","date","report_date"))
    revisions=_latest_by_ticker(_read_table(root/"estimate_revisions.csv"),("asof","date","updated_at"))
    guidance=_latest_by_ticker(_read_table(root/"guidance.csv"),("date","asof","issued_at"))
    news=_norm_ticker(_read_table(root/"news.csv"))
    insider=_latest_by_ticker(_read_table(root/"insider.csv"),("transaction_date","date","filed_at"))
    holdings13f=_norm_ticker(_read_table(root/"holdings_13f.csv"))
    return {"earnings":earnings,"revisions":revisions,"guidance":guidance,"news":news,"insider":insider,"holdings_13f":holdings13f}


def _num(value):
    x=pd.to_numeric(value,errors="coerce")
    return None if pd.isna(x) else float(x)


def build_external_records(tickers: list[str], layer: dict[str,Any], today: pd.Timestamp|None=None) -> list[dict]:
    today=(today or pd.Timestamp.utcnow()).tz_localize(None).normalize()
    news=layer.get("news") if isinstance(layer.get("news"),pd.DataFrame) else pd.DataFrame()
    f13=layer.get("holdings_13f") if isinstance(layer.get("holdings_13f"),pd.DataFrame) else pd.DataFrame()
    records=[]
    for ticker in tickers:
        e=(layer.get("earnings") or {}).get(ticker,{})
        r=(layer.get("revisions") or {}).get(ticker,{})
        g=(layer.get("guidance") or {}).get(ticker,{})
        i=(layer.get("insider") or {}).get(ticker,{})
        earnings_date=pd.to_datetime(e.get("earnings_date") or e.get("date") or e.get("report_date"),errors="coerce")
        days_to=int((earnings_date.normalize()-today).days) if pd.notna(earnings_date) else None
        eps_rev=_num(r.get("eps_revision_30d_pct") or r.get("eps_revision_pct") or r.get("revision_pct"))
        rev_rev=_num(r.get("revenue_revision_30d_pct") or r.get("revenue_revision_pct"))
        guide_dir=str(g.get("direction") or g.get("guidance_direction") or "UNKNOWN").upper()
        nrows=news[news["ticker"].eq(ticker)] if not news.empty and "ticker" in news else pd.DataFrame()
        if not nrows.empty:
            date_col=next((c for c in nrows.columns if str(c).lower() in {"date","published_at","timestamp"}),None)
            if date_col is not None:
                nrows=nrows.assign(_d=pd.to_datetime(nrows[date_col],errors="coerce")).sort_values("_d",ascending=False)
            nrows=nrows.head(10)
        event_types=[]
        for _,row in nrows.iterrows():
            text=" ".join(str(row.get(c,"")) for c in nrows.columns).lower()
            if any(k in text for k in ("merger","acquisition","acquire","m&a")): event_types.append("M&A")
            elif any(k in text for k in ("contract","award","order","deal")): event_types.append("CONTRACT")
            elif any(k in text for k in ("guidance","outlook","forecast")): event_types.append("GUIDANCE")
            else: event_types.append("NEWS")
        frows=f13[f13["ticker"].eq(ticker)] if not f13.empty and "ticker" in f13 else pd.DataFrame()
        institutional_holders=int(frows["manager"].nunique()) if not frows.empty and "manager" in frows else int(len(frows))
        ownership_change=_num(frows["position_change_pct"].median()) if not frows.empty and "position_change_pct" in frows else None
        insider_type=str(i.get("transaction_type") or i.get("type") or "UNKNOWN").upper()
        insider_value=_num(i.get("transaction_value") or i.get("value"))
        warnings=[]
        positives=[]
        if days_to is not None and -3 <= days_to <= 3: warnings.append("earnings_window")
        if eps_rev is not None and eps_rev <= -3: warnings.append("eps_revisions_down")
        if guide_dir in {"DOWN","LOWERED","NEGATIVE"}: warnings.append("guidance_cut")
        if insider_type in {"SALE","SELL"} and insider_value and insider_value >= 1_000_000: warnings.append("large_insider_sale")
        if eps_rev is not None and eps_rev >= 3: positives.append("eps_revisions_up")
        if rev_rev is not None and rev_rev >= 2: positives.append("revenue_revisions_up")
        if guide_dir in {"UP","RAISED","POSITIVE"}: positives.append("guidance_raised")
        if insider_type in {"PURCHASE","BUY"}: positives.append("insider_buy")
        records.append({"ticker":ticker,"earnings_date":earnings_date.date().isoformat() if pd.notna(earnings_date) else None,"days_to_earnings":days_to,"eps_revision_30d_pct":eps_rev,"revenue_revision_30d_pct":rev_rev,"guidance_direction":guide_dir,"news_count":int(len(nrows)),"event_types":sorted(set(event_types)),"insider_transaction_type":insider_type,"insider_transaction_value":insider_value,"institutional_holder_count":institutional_holders,"institutional_position_change_pct":ownership_change,"warnings":warnings,"positives":positives,"coverage":{"earnings":bool(e),"revisions":bool(r),"guidance":bool(g),"news":not nrows.empty,"insider":bool(i),"holdings_13f":not frows.empty}})
    return records


def apply_external_context(candidates:list[dict], records:list[dict]) -> list[dict]:
    lookup={r["ticker"]:r for r in records}; out=[]
    for item in candidates:
        rec=dict(item); ext=lookup.get(rec.get("ticker"),{})
        rec["external_data"]=ext
        rec["warnings"]=list(dict.fromkeys(list(rec.get("warnings") or [])+list(ext.get("warnings") or [])))
        if "earnings_window" in rec["warnings"]: rec["actionable"]=False
        out.append(rec)
    return out
