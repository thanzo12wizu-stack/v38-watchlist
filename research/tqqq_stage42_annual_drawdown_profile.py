from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse Stage41 construction only through its historical-target setup; do not run MC body.
src=Path('research/tqqq_stage41_vix_throttle.py').read_text()
prefix=src.split("PER=[('2011-2015'")[0]
exec(compile(prefix,'stage41-prefix','exec'),globals())

print('\n=== STAGE42 ANNUAL DRAWDOWN PROFILE ===',flush=True)

curA=current_trace(A)
S37={'name':'S37','base':.80,'bull':1.00,'cond':'A2_MC35'}
targets42={
    'CURRENT': curA['target'].copy(),
    'BUYHOLD': np.ones(len(A['ret']),float),
    'STAGE37_80_100': make_target(A,S37,curA),
    'STAGE38': stage38_target(A,curA),
    'V24_C40': target41(A,VIXLVL,{'name':'V24_C40_H40','vix':24.,'cap':.40,'cap2':.40},curA),
    'V24_C50': target41(A,VIXLVL,{'name':'V24_C50_H50','vix':24.,'cap':.50,'cap2':.50},curA),
    'V24_C60': target41(A,VIXLVL,{'name':'V24_C60_H60','vix':24.,'cap':.60,'cap2':.60},curA),
}

rows=[]; summaries=[]; episodes=[]
for nm,t in targets42.items():
    model,sr,eff=from_target(A,t,COST)
    pre=account_end(A['ret'],t,COST,0.,DTS)
    aft=account_end(A['ret'],t,COST,TAX,DTS)
    r=np.nan_to_num(np.asarray(sr,float),nan=0.0)
    # Overall drawdown dates using continuous equity.
    eq=np.cumprod(1+r); pk=np.maximum.accumulate(eq); dd=eq/pk-1
    tr=int(np.argmin(dd)); pki=int(np.argmax(eq[:tr+1]))
    rec=''
    for j in range(tr+1,len(eq)):
        if eq[j]>=eq[pki]: rec=str(pd.Timestamp(DTS.iloc[j]).date()); break
    episodes.append({'candidate':nm,'peak':str(pd.Timestamp(DTS.iloc[pki]).date()),'trough':str(pd.Timestamp(DTS.iloc[tr]).date()),'recovery':rec,'overall_mdd':float(dd[tr])})

    for y in sorted(np.unique(YY)):
        ids=np.flatnonzero(YY==y)
        if len(ids)<20: continue
        ry=r[ids]
        # Reset peak at Jan-1/start-of-year so this measures the worst peak-to-trough event inside each calendar year.
        ey=np.concatenate([[1.0],np.cumprod(1+ry)])
        py=np.maximum.accumulate(ey); ddy=ey/py-1
        maxdd=float(np.min(ddy))
        avgdd=float(np.mean(ddy[1:]))
        meddd=float(np.median(ddy[1:]))
        negshare=float(np.mean(ddy[1:]<0))
        yrret=float(ey[-1]-1)
        tloc=int(np.argmin(ddy))-1
        trough_date=str(pd.Timestamp(DTS.iloc[ids[max(0,tloc)]]).date())
        rows.append({'candidate':nm,'year':int(y),'year_return':yrret,'max_drawdown':maxdd,'avg_daily_drawdown':avgdd,'median_daily_drawdown':meddd,'share_days_below_peak':negshare,'trough_date':trough_date})

    g=pd.DataFrame([x for x in rows if x['candidate']==nm])
    summaries.append({
        'candidate':nm,
        'pre_cagr':pre['cagr'],'tax_cagr':aft['cagr'],'overall_mdd':pre['mdd'],
        'avg_annual_maxdd':float(g.max_drawdown.mean()),
        'median_annual_maxdd':float(g.max_drawdown.median()),
        'p25_annual_maxdd':float(g.max_drawdown.quantile(.25)),
        'worst_annual_maxdd':float(g.max_drawdown.min()),
        'avg_annual_daily_dd':float(g.avg_daily_drawdown.mean()),
        'median_annual_daily_dd':float(g.avg_daily_drawdown.median()),
        'avg_share_days_below_peak':float(g.share_days_below_peak.mean()),
        'years_mdd_10plus':int((g.max_drawdown<=-.10).sum()),
        'years_mdd_20plus':int((g.max_drawdown<=-.20).sum()),
        'years_mdd_30plus':int((g.max_drawdown<=-.30).sum()),
        'avg_exposure':model['avg_exp'],'turnover':model['turnover'],
    })

ANNUAL=pd.DataFrame(rows); SUMMARY=pd.DataFrame(summaries); EP=pd.DataFrame(episodes)
ANNUAL.to_csv('tqqq_stage42_annual_drawdowns.csv',index=False)
SUMMARY.to_csv('tqqq_stage42_summary.csv',index=False)
EP.to_csv('tqqq_stage42_mdd_episodes.csv',index=False)
print('\n=== SUMMARY ===')
print(SUMMARY.to_string(index=False))
print('\n=== MDD EPISODES ===')
print(EP.to_string(index=False))
print('\n=== ANNUAL MAX DD ===')
print(ANNUAL.pivot(index='year',columns='candidate',values='max_drawdown').to_string())
Path('tqqq_stage42_summary.json').write_text(json.dumps({'summary':SUMMARY.to_dict('records'),'episodes':EP.to_dict('records'),'annual':ANNUAL.to_dict('records'),'definitions':{'annual_max_drawdown':'Worst peak-to-trough drawdown within each calendar year, with peak reset to 1.0 at the start of each year.','avg_daily_drawdown':'Mean daily distance below the running calendar-year peak.','dd_basis':'Pre-tax strategy return after 5bp one-way turnover costs; tax CAGR uses the Stage36 20.315% annual realized-gain model.'}},ensure_ascii=False,indent=2,default=str))
