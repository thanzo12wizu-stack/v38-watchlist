from __future__ import annotations
import argparse,json
from pathlib import Path

def query(index_path:Path,sector:str|None=None,min_candidate:float|None=None,sort:str="score_candidate",limit:int=20)->list[dict]:
    rows=json.loads(index_path.read_text(encoding="utf-8")).get("stocks",[])
    if sector:rows=[r for r in rows if str(r.get("sector","")).lower()==sector.lower()]
    if min_candidate is not None:rows=[r for r in rows if isinstance(r.get("score_candidate"),(int,float)) and r["score_candidate"]>=min_candidate]
    rows.sort(key=lambda r:(r.get(sort) is not None,r.get(sort,float("-inf"))),reverse=True)
    return rows[:limit]

def main():
    p=argparse.ArgumentParser(); p.add_argument("--index",default="data/intelligence/index.json"); p.add_argument("--sector"); p.add_argument("--min-candidate",type=float); p.add_argument("--sort",default="score_candidate"); p.add_argument("--limit",type=int,default=20); a=p.parse_args()
    print(json.dumps(query(Path(a.index),a.sector,a.min_candidate,a.sort,a.limit),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
