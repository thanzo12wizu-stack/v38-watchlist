from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

PROVIDER_POLICY_VERSION = "1.0.0"


def _write(frame: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def refresh_external_data(tickers: list[str], root: Path) -> dict:
    earnings=[]; revisions=[]; guidance=[]; news=[]; insider=[]; holdings=[]; coverage={}
    now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    for ticker in sorted(set(tickers)):
        cov={"earnings":False,"revisions":False,"guidance":False,"news":False,"insider":False,"13f":False}
        try:
            obj=yf.Ticker(ticker)
            cal=obj.calendar
            if isinstance(cal,dict):
                values=cal.get("Earnings Date") or cal.get("EarningsDate") or []
                if not isinstance(values,(list,tuple)): values=[values]
                for value in values:
                    if value is not None: earnings.append({"ticker":ticker,"event_date":pd.Timestamp(value).date().isoformat(),"source":"yfinance","fetched_at":now})
                cov["earnings"]=bool(values)
            ana=getattr(obj,"earnings_estimate",None)
            rev=getattr(obj,"revenue_estimate",None)
            for kind,frame in (("eps",ana),("revenue",rev)):
                if isinstance(frame,pd.DataFrame) and not frame.empty:
                    for period,row in frame.iterrows():
                        revisions.append({"ticker":ticker,"metric":kind,"period":str(period),"current":row.get("avg"),"revision_7d":row.get("growth"),"source":"yfinance","fetched_at":now})
                    cov["revisions"]=True
            for item in obj.news or []:
                content=item.get("content") or item
                title=str(content.get("title") or "")
                summary=str(content.get("summary") or content.get("description") or "")
                text=(title+" "+summary).lower()
                event_type="M&A" if any(x in text for x in ("acquire","acquisition","merger","buyout")) else "CONTRACT" if any(x in text for x in ("contract","award","order","partnership")) else "GUIDANCE" if "guidance" in text else "NEWS"
                published=content.get("pubDate") or content.get("providerPublishTime")
                news.append({"ticker":ticker,"published_at":published,"headline":title,"summary":summary,"event_type":event_type,"source":"yfinance","fetched_at":now})
                if event_type=="GUIDANCE": guidance.append({"ticker":ticker,"published_at":published,"direction":"UNKNOWN","text":title,"source":"yfinance","fetched_at":now})
            cov["news"]=bool(obj.news); cov["guidance"]=any(x["ticker"]==ticker for x in guidance)
            tx=getattr(obj,"insider_transactions",None)
            if isinstance(tx,pd.DataFrame) and not tx.empty:
                for _,row in tx.head(100).iterrows(): insider.append({"ticker":ticker,"filed_at":row.get("Start Date"),"insider":row.get("Insider"),"transaction":row.get("Transaction"),"shares":row.get("Shares"),"value":row.get("Value"),"source":"yfinance","fetched_at":now})
                cov["insider"]=True
            ih=getattr(obj,"institutional_holders",None)
            if isinstance(ih,pd.DataFrame) and not ih.empty:
                for _,row in ih.iterrows(): holdings.append({"ticker":ticker,"holder":row.get("Holder"),"shares":row.get("Shares"),"date_reported":row.get("Date Reported"),"pct_out":row.get("% Out"),"value":row.get("Value"),"source":"yfinance","fetched_at":now})
                cov["13f"]=True
        except Exception:
            pass
        coverage[ticker]=cov
    _write(pd.DataFrame(earnings),root/"earnings_calendar.csv")
    _write(pd.DataFrame(revisions),root/"estimate_revisions.csv")
    _write(pd.DataFrame(guidance),root/"guidance.csv")
    _write(pd.DataFrame(news),root/"news.csv")
    _write(pd.DataFrame(insider),root/"insider.csv")
    _write(pd.DataFrame(holdings),root/"holdings_13f.csv")
    pd.DataFrame([{"ticker":k,**v,"fetched_at":now} for k,v in coverage.items()]).to_csv(root/"provider_coverage.csv",index=False)
    return {"tickers":len(coverage),"coverage":coverage,"provider":"yfinance","fetched_at":now}


def main():
    p=argparse.ArgumentParser();p.add_argument("--universe",default="universe.csv");p.add_argument("--root",default="data/external");a=p.parse_args()
    frame=pd.read_csv(a.universe); col=next(c for c in frame.columns if str(c).lower() in {"ticker","symbol","ティッカー","シンボル"})
    print(refresh_external_data(frame[col].dropna().astype(str).str.upper().tolist(),Path(a.root)))

if __name__=="__main__": main()
