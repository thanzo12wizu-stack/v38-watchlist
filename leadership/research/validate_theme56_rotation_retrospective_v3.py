from __future__ import annotations

import math
import pandas as pd
import validate_theme56_rotation_retrospective as base


def strict_eventize(panel: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    z=panel.assign(_s=mask.fillna(False).to_numpy(bool)); rows=[]
    for _,g in z.groupby('ticker',sort=False):
        g=g.sort_values('date').reset_index(drop=True); prev=False; last=-10**9
        for i,r in g.iterrows():
            active=bool(r['_s'])
            if active and not prev and i-last>=base.COOLDOWN:
                rows.append(r.drop(labels=['_s']).to_dict()); last=i
            prev=active
    return pd.DataFrame(rows)


def fixed_theme_components(close:pd.DataFrame,volume:pd.DataFrame,members:list[str],min_cov=.60)->pd.DataFrame:
    members=[s for s in members if s in close.columns and s in volume.columns]; n=len(members)
    if n<5:return pd.DataFrame(index=close.index)
    c=close[members]; v=volume[members]; need=max(5,math.ceil(n*min_cov))
    ema21=c.ewm(span=21,adjust=False,min_periods=15).mean(); sma50=c.rolling(50,min_periods=35).mean()
    b21=100*base.coverage_mean((c>ema21).where(c.notna()&ema21.notna()),n,min_cov)
    b50=100*base.coverage_mean((c>sma50).where(c.notna()&sma50.notna()),n,min_cov)
    ret=c.pct_change(fill_method=None); valid=ret.notna(); cnt=valid.sum(axis=1)
    ad=((ret.gt(0).sum(axis=1)-ret.lt(0).sum(axis=1))/cnt.replace(0,pd.NA)).where(cnt>=need)
    ad20=(50*(1+ad.rolling(20,min_periods=15).mean())).clip(0,100)
    signed=v.where(ret>0,-v.where(ret<0,0)).where(valid&v.notna()); obv=signed.fillna(0).cumsum(); obd=obv-obv.shift(20)
    obv20=100*base.coverage_mean((obd>0).where(obd.notna()),n,min_cov)
    up=v.where(ret>0,0).where(valid&v.notna()).sum(axis=1,min_count=1); dn=v.where(ret<0,0).where(valid&v.notna()).sum(axis=1,min_count=1)
    u20=up.rolling(20,min_periods=15).sum(); d20=dn.rolling(20,min_periods=15).sum(); uvd=(u20/d20.replace(0,pd.NA)).where(cnt.rolling(20,min_periods=15).median()>=need)
    out={'breadth21':b21,'breadth50':b50,'ad20':ad20,'obv20':obv20,'uvdv20':uvd}
    for h in (5,10,20):
        valid_h=c.notna()&c.shift(h).notna(); rr=c/c.shift(h)-1; positive=rr.gt(0).where(valid_h)
        out[f'pos{h}']=100*base.coverage_mean(positive,n,min_cov)
    return pd.DataFrame(out)


def fast_parent_map(etf_close:pd.DataFrame)->pd.DataFrame:
    themes=[c for c in etf_close.columns if c not in {'SPY',*base.SECTORS}]; sectors=[c for c in base.SECTORS if c in etf_close]
    rets=etf_close.pct_change(fill_method=None); ret20=etf_close.pct_change(20,fill_method=None); rows=[]
    for t in themes:
        corr=pd.DataFrame({s:rets[t].rolling(126,min_periods=90).corr(rets[s]) for s in sectors})
        parent=corr.idxmax(axis=1); best=corr.max(axis=1)
        tmp=pd.DataFrame({'date':etf_close.index,'ticker':t,'parent':parent,'parent_corr126':best})
        gaps=[]
        for dt,p in zip(tmp.date,tmp.parent):
            gaps.append(ret20.at[dt,t]-ret20.at[dt,p] if isinstance(p,str) and p in ret20.columns and pd.notna(ret20.at[dt,t]) and pd.notna(ret20.at[dt,p]) else float('nan'))
        tmp['theme_parent_ret20_gap']=gaps; rows.append(tmp)
    return pd.concat(rows,ignore_index=True) if rows else pd.DataFrame(columns=['date','ticker','parent','parent_corr126','theme_parent_ret20_gap'])

base.eventize=strict_eventize
base.theme_components=fixed_theme_components
base.parent_map=fast_parent_map

if __name__=='__main__': base.main()
