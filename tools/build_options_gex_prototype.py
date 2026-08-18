#!/usr/bin/env python3
"""Standalone Options GEX prototype with static HTML/SVG output.
The HTML intentionally requires no JavaScript so iOS/Quick Look previews render it.
"""
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf


def bs_gamma(spot: float, strike: float, t_years: float, vol: float, r: float = 0.043) -> float:
    if spot <= 0 or strike <= 0 or t_years <= 0 or vol <= 0 or not math.isfinite(vol):
        return 0.0
    d1=(math.log(spot/strike)+(r+0.5*vol*vol)*t_years)/(vol*math.sqrt(t_years))
    return math.exp(-0.5*d1*d1)/math.sqrt(2*math.pi)/(spot*vol*math.sqrt(t_years))


def price_from_ticker(t: yf.Ticker) -> float:
    try:
        p=float(t.fast_info['last_price'])
        if math.isfinite(p) and p>0: return p
    except Exception:
        pass
    h=t.history(period='5d', auto_adjust=False)
    if h.empty: raise RuntimeError('Could not obtain underlying price')
    return float(h['Close'].dropna().iloc[-1])


def load_chain(symbol: str, expiry: str|None=None):
    t=yf.Ticker(symbol); spot=price_from_ticker(t); expiries=list(t.options)
    if not expiries: raise RuntimeError(f'No option expirations returned for {symbol}')
    expiry=expiry or expiries[0]
    if expiry not in expiries: raise RuntimeError(f'Expiration {expiry} not available. First expirations: {expiries[:8]}')
    chain=t.option_chain(expiry)
    exp_dt=datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
    dte=max((exp_dt-datetime.now(timezone.utc)).total_seconds()/86400+0.75,1/24); ty=dte/365
    frames=[]
    for side,df in [('call',chain.calls.copy()),('put',chain.puts.copy())]:
        if df.empty: continue
        df['side']=side
        df['openInterest']=pd.to_numeric(df.get('openInterest'),errors='coerce').fillna(0.0)
        df['impliedVolatility']=pd.to_numeric(df.get('impliedVolatility'),errors='coerce')
        df['strike']=pd.to_numeric(df['strike'],errors='coerce')
        df=df.dropna(subset=['strike','impliedVolatility'])
        df['gamma']=[bs_gamma(spot,float(k),ty,float(iv)) for k,iv in zip(df['strike'],df['impliedVolatility'])]
        df['gex']=df['gamma']*df['openInterest']*100*spot*spot*0.01
        if side=='put': df['gex']*=-1
        frames.append(df[['strike','side','openInterest','impliedVolatility','gamma','gex']])
    if not frames: raise RuntimeError('Option chain returned no usable rows')
    return spot,expiry,pd.concat(frames,ignore_index=True)


def aggregate_by_strike(df):
    p=df.pivot_table(index='strike',columns='side',values='gex',aggfunc='sum',fill_value=0.0)
    for c in ('call','put'):
        if c not in p.columns: p[c]=0.0
    p=p.reset_index().sort_values('strike'); p['net']=p['call']+p['put']; return p


def gamma_profile(df, expiry, lo, hi, points=161):
    exp_dt=datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
    dte=max((exp_dt-datetime.now(timezone.utc)).total_seconds()/86400+0.75,1/24); ty=dte/365
    rows=list(df.itertuples(index=False)); out=[]
    for s in np.linspace(lo,hi,points):
        total=0.0
        for r in rows:
            g=bs_gamma(float(s),float(r.strike),ty,float(r.impliedVolatility))
            v=g*float(r.openInterest)*100*float(s)*float(s)*0.01
            total += v if r.side=='call' else -v
        out.append({'spot':round(float(s),4),'gex':float(total)})
    return out


def find_flip(profile, spot):
    crosses=[]
    for a,b in zip(profile,profile[1:]):
        ya,yb=a['gex'],b['gex']
        if ya==0: crosses.append(a['spot'])
        elif ya*yb<0: crosses.append(a['spot']+(b['spot']-a['spot'])*(-ya)/(yb-ya))
    return min(crosses,key=lambda x:abs(x-spot)) if crosses else None


def payload(symbol, expiry, strike_pct=.35):
    spot,expiry,raw=load_chain(symbol,expiry); lo,hi=spot*(1-strike_pct),spot*(1+strike_pct)
    raw=raw[(raw['strike']>=lo)&(raw['strike']<=hi)].copy(); agg=aggregate_by_strike(raw)
    if agg.empty: raise RuntimeError('No strikes in requested range')
    cw=agg.loc[agg['call'].idxmax()]; pw=agg.loc[agg['put'].idxmin()]
    prof=gamma_profile(raw,expiry,float(agg['strike'].min()),float(agg['strike'].max()))
    return {'symbol':symbol.upper(),'spot':spot,'expiry':expiry,'updated_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'call_wall':float(cw['strike']),'put_wall':float(pw['strike']),'gamma_flip':find_flip(prof,spot),'net_gex':float(agg['net'].sum()),
            'sign_model':'calls_positive_puts_negative','units':'USD gamma exposure per 1% underlying move',
            'strikes':[{'strike':float(r.strike),'call':float(r.call),'put':float(r.put),'net':float(r.net)} for r in agg.itertuples(index=False)],'profile':prof}


def money(n):
    if n is None: return '—'
    a=abs(n); s='-' if n<0 else ''
    if a>=1e9: return f'{s}${a/1e9:.2f}B'
    if a>=1e6: return f'{s}${a/1e6:.2f}M'
    return f'{s}${a:,.0f}'


def render_svg(d, W=1000, H=520):
    strikes=d['strikes']; profile=d['profile']; xs=[r['strike'] for r in strikes]
    vals=[abs(v) for r in strikes for v in (r['call'],r['put'])]; pvals=[abs(r['gex']) for r in profile]
    xmin,xmax=min(xs),max(xs); ymax=max(max(vals),1); pymax=max(max(pvals),1); l,r,t,b=70,30,35,55
    X=lambda x:l+(x-xmin)/(xmax-xmin)*(W-l-r); Y=lambda y:t+(ymax-y)/(2*ymax)*(H-t-b); YP=lambda y:t+(pymax-y)/(2*pymax)*(H-t-b)
    out=[]
    for q in (0,.5,1):
        yy=t+q*(H-t-b); out.append(f'<line x1="{l}" y1="{yy:.1f}" x2="{W-r}" y2="{yy:.1f}" stroke="#243044"/>')
    out.append(f'<line x1="{l}" y1="{Y(0):.1f}" x2="{W-r}" y2="{Y(0):.1f}" stroke="#546176"/>')
    bw=max(3,(W-l-r)/len(strikes)*.56); y0=Y(0)
    for q in strikes:
        xx=X(q['strike'])-bw/2
        if q['call']>0:
            yy=Y(q['call']); out.append(f'<rect x="{xx:.1f}" y="{yy:.1f}" width="{bw:.1f}" height="{y0-yy:.1f}" fill="#19c58b"/>')
        if q['put']<0:
            yy=Y(q['put']); out.append(f'<rect x="{xx:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{yy-y0:.1f}" fill="#ff4d6d"/>')
    pts=' '.join(f'{X(q["spot"]):.1f},{YP(q["gex"]):.1f}' for q in profile)
    out.append(f'<polyline points="{pts}" fill="none" stroke="#5d8cff" stroke-width="3"/>')
    labels=[(d['spot'],'#c9d3df',f'Spot {d["spot"]:.2f}','8 6'),(d['gamma_flip'],'#ff922b',f'Flip {d["gamma_flip"]:.2f}' if d['gamma_flip'] is not None else 'Flip',''),(d['call_wall'],'#19c58b','Call Wall','4 5'),(d['put_wall'],'#ff4d6d','Put Wall','4 5')]
    for x,col,label,dash in labels:
        if x is None: continue
        xx=X(x); da=f' stroke-dasharray="{dash}"' if dash else ''
        out.append(f'<line x1="{xx:.1f}" y1="{t}" x2="{xx:.1f}" y2="{H-b}" stroke="{col}" stroke-width="2"{da}/><text x="{xx+5:.1f}" y="{t+16}" fill="{col}" font-size="13">{label}</text>')
    out.append(f'<text x="{l}" y="{H-18}" fill="#8c9aae" font-size="13">{xmin:.0f}</text><text x="{W-r-28}" y="{H-18}" fill="#8c9aae" font-size="13">{xmax:.0f}</text>')
    return ''.join(out)


def render_html(d):
    svg=render_svg(d)
    def f(x): return '—' if x is None else f'${x:,.2f}'
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{d['symbol']} Options GEX</title><style>
:root{{--bg:#0b0f17;--panel:#121824;--line:#243044;--text:#edf2f7;--muted:#8c9aae}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:20px}}.top{{display:flex;justify-content:space-between;gap:12px;align-items:end;flex-wrap:wrap}}.title{{font-size:28px;font-weight:800}}.muted{{color:var(--muted)}}.spot{{font-size:22px;font-weight:800}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:18px}}.kpi,.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px}}.kpi{{padding:12px}}.kpi b{{display:block;font-size:19px;margin-top:5px}}.card{{padding:16px;margin-top:16px}}svg{{width:100%;height:auto;display:block}}.legend{{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px}}.dot{{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px}}.note{{color:var(--muted);font-size:12px;line-height:1.5;margin-top:12px}}@media(max-width:800px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.title{{font-size:23px}}}}
</style></head><body><div class="wrap"><div class="top"><div><div class="title">{d['symbol']} Options Positioning</div><div class="muted">Expiration {d['expiry']} · {d['updated_utc']}</div></div><div class="spot">Spot {f(d['spot'])}</div></div><div class="kpis"><div class="kpi"><span class="muted">Call Wall</span><b>{f(d['call_wall'])}</b></div><div class="kpi"><span class="muted">Put Wall</span><b>{f(d['put_wall'])}</b></div><div class="kpi"><span class="muted">Gamma Flip</span><b>{f(d['gamma_flip'])}</b></div><div class="kpi"><span class="muted">Net GEX</span><b>{money(d['net_gex'])}</b></div></div><div class="card"><h2>Gamma Exposure</h2><svg viewBox="0 0 1000 520" role="img" aria-label="Gamma exposure by strike">{svg}</svg><div class="legend"><span><i class="dot" style="background:#19c58b"></i>Call</span><span><i class="dot" style="background:#ff4d6d"></i>Put</span><span><i class="dot" style="background:#5d8cff"></i>Aggregate GEX profile</span><span><i class="dot" style="background:#ff922b"></i>Gamma Flip</span></div><div class="note">Static SVG: no JavaScript required, so iOS/Quick Look can render the values and chart.</div></div></div></body></html>'''


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--ticker',default='MSTR'); ap.add_argument('--expiry',default=None); ap.add_argument('--strike-pct',type=float,default=.35); ap.add_argument('--out',default='options-gex-prototype.html'); ap.add_argument('--json-out',default='data/options_gex_prototype.json'); a=ap.parse_args()
    d=payload(a.ticker,a.expiry,a.strike_pct); Path(a.json_out).parent.mkdir(parents=True,exist_ok=True); Path(a.json_out).write_text(json.dumps(d,indent=2),encoding='utf-8'); Path(a.out).write_text(render_html(d),encoding='utf-8')
    print(json.dumps({k:d[k] for k in ['symbol','spot','expiry','call_wall','put_wall','gamma_flip','net_gex']},indent=2))

if __name__=='__main__': main()
