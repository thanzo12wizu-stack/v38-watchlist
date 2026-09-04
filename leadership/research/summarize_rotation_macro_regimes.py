from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np

PAIRS=[('DGS2_HIGH_GE4','DGS2_LOW_LT4'),('DGS2_RISING_25BP','DGS2_FALLING_25BP'),('DGS10_HIGH_GE4','DGS10_LOW_LT4'),('DGS10_RISING_25BP','DGS10_FALLING_25BP'),('CURVE_INVERTED','CURVE_POSITIVE'),('REAL10_HIGH_GE1P5','REAL10_LOW_LT1P5'),('NFCI_TIGHT','NFCI_LOOSE'),('FED_BALANCE_RISING','FED_BALANCE_FALLING'),('HY_OAS_HIGH_GE4P5','HY_OAS_LOW_LT4P5'),('VIX_HIGH_GE20','VIX_LOW_LT20'),('SPY_UPTREND','SPY_DOWNTREND'),('QQQ_UPTREND','QQQ_DOWNTREND'),('MARKET_INTERNAL_STRONG','MARKET_INTERNAL_WEAK'),('MARKET_BREADTH_STRONG','MARKET_BREADTH_WEAK')]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--report',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    r=json.loads(a.report.read_text()); out={}
    for name,s in r['signals'].items():
        sign=s['expected_sign']; rows=[]
        for x,y in PAIRS:
            if x not in s['regimes'] or y not in s['regimes']: continue
            for h in ('20','40'):
                A=s['regimes'][x][h]; B=s['regimes'][y][h]
                if A['n']>=8 and B['n']>=8 and A['mean'] is not None and B['mean'] is not None:
                    rows.append({'pair':[x,y],'horizon':int(h),'a_n':A['n'],'a_mean':A['mean'],'b_n':B['n'],'b_mean':B['mean'],'both_expected_sign':bool(A['mean']*sign>0 and B['mean']*sign>0)})
        out[name]={'eligible_comparisons':len(rows),'stable_comparisons':int(sum(z['both_expected_sign'] for z in rows)),'stable_fraction':None if not rows else float(np.mean([z['both_expected_sign'] for z in rows])),'details':rows}
    a.output.write_text(json.dumps({'schema':1,'minimum_n_each_side':8,'summary':out},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:{'eligible':v['eligible_comparisons'],'stable_fraction':v['stable_fraction']} for k,v in out.items()},indent=2))
if __name__=='__main__':main()
