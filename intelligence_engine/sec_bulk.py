from __future__ import annotations

import argparse,json,os,urllib.request,zipfile
from pathlib import Path

SEC_BULK_URL="https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
TICKER_MAP_URL="https://www.sec.gov/files/company_tickers.json"

def _request(url:str):
    ua=os.environ.get("SEC_USER_AGENT","v38-watchlist research contact@example.com")
    return urllib.request.Request(url,headers={"User-Agent":ua,"Accept-Encoding":"gzip, deflate"})

def download(url:str,target:Path):
    target.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(_request(url),timeout=120) as r,target.open("wb") as out:
        while True:
            chunk=r.read(1024*1024)
            if not chunk:break
            out.write(chunk)

def ticker_to_cik():
    with urllib.request.urlopen(_request(TICKER_MAP_URL),timeout=60) as r:raw=json.load(r)
    return {str(v["ticker"]).upper():int(v["cik_str"]) for v in raw.values()}

def extract_selected(zip_path:Path,output_dir:Path,tickers:set[str]):
    mapping=ticker_to_cik(); reverse={c:t for t,c in mapping.items() if t in tickers}; output_dir.mkdir(parents=True,exist_ok=True); written=0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            base=Path(name).name
            if not base.startswith("CIK") or not base.endswith(".json"):continue
            try:cik=int(base[3:-5])
            except ValueError:continue
            ticker=reverse.get(cik)
            if ticker:
                (output_dir/f"{ticker}.json").write_bytes(zf.read(name)); written+=1
    return {"requested":len(tickers),"matched":len(reverse),"written":written}

def main():
    import pandas as pd
    p=argparse.ArgumentParser(); p.add_argument("--universe",default="universe.csv"); p.add_argument("--zip",default="data/sec/companyfacts.zip"); p.add_argument("--output",default="data/sec_companyfacts"); p.add_argument("--skip-download",action="store_true"); a=p.parse_args()
    u=pd.read_csv(a.universe); col="ticker" if "ticker" in u.columns else "symbol"; tickers=set(u[col].astype(str).str.upper().str.strip()); zp=Path(a.zip)
    if not a.skip_download:download(SEC_BULK_URL,zp)
    print(json.dumps(extract_selected(zp,Path(a.output),tickers),indent=2))
if __name__=="__main__":main()
