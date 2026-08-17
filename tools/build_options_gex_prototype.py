#!/usr/bin/env python3
"""Standalone Options GEX wall prototype.

Proof-of-concept only: does not modify the existing dashboard.
Data source: yfinance/Yahoo options chain. Gamma is recomputed with Black-Scholes
from Yahoo implied volatility; OI is multiplied by 100 shares/contract.

Dealer-sign convention is intentionally simple: calls +, puts -. This is useful
for testing support/resistance geometry but is NOT a direct observation of dealer
inventory. If we later adopt this in production, the sign model and data source
should be configurable and validated.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import yfinance as yf

N = NormalDist()


def bs_gamma(spot: float, strike: float, t_years: float, vol: float, r: float = 0.043) -> float:
    if spot <= 0 or strike <= 0 or t_years <= 0 or vol <= 0 or not math.isfinite(vol):
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return pdf / (spot * vol * math.sqrt(t_years))


def price_from_ticker(t: yf.Ticker) -> float:
    # fast_info is preferred; history is a robust fallback.
    try:
        p = float(t.fast_info["last_price"])
        if math.isfinite(p) and p > 0:
            return p
    except Exception:
        pass
    h = t.history(period="5d", auto_adjust=False)
    if h.empty:
        raise RuntimeError("Could not obtain underlying price")
    return float(h["Close"].dropna().iloc[-1])


def load_chain(symbol: str, expiry: str | None = None) -> tuple[float, str, pd.DataFrame]:
    t = yf.Ticker(symbol)
    spot = price_from_ticker(t)
    expiries = list(t.options)
    if not expiries:
        raise RuntimeError(f"No option expirations returned for {symbol}")
    if expiry is None:
        expiry = expiries[0]
    if expiry not in expiries:
        raise RuntimeError(f"Expiration {expiry} not available. First expirations: {expiries[:8]}")

    chain = t.option_chain(expiry)
    now = datetime.now(timezone.utc)
    exp_dt = datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
    # Use end of U.S. option day approximately; 1 day floor avoids expiry-day singularity.
    dte = max((exp_dt - now).total_seconds() / 86400.0 + 0.75, 1.0 / 24.0)
    t_years = dte / 365.0

    frames = []
    for side, df in (("call", chain.calls.copy()), ("put", chain.puts.copy())):
        if df.empty:
            continue
        df["side"] = side
        df["openInterest"] = pd.to_numeric(df.get("openInterest"), errors="coerce").fillna(0.0)
        df["impliedVolatility"] = pd.to_numeric(df.get("impliedVolatility"), errors="coerce")
        df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
        df = df.dropna(subset=["strike", "impliedVolatility"])
        df["gamma"] = [bs_gamma(spot, float(k), t_years, float(iv)) for k, iv in zip(df["strike"], df["impliedVolatility"])]
        # Dollar gamma for a 1% move in underlying.
        df["gex"] = df["gamma"] * df["openInterest"] * 100.0 * spot * spot * 0.01
        if side == "put":
            df["gex"] *= -1.0
        frames.append(df[["strike", "side", "openInterest", "impliedVolatility", "gamma", "gex"]])
    if not frames:
        raise RuntimeError("Option chain returned no usable rows")
    return spot, expiry, pd.concat(frames, ignore_index=True)


def aggregate_by_strike(df: pd.DataFrame) -> pd.DataFrame:
    p = df.pivot_table(index="strike", columns="side", values="gex", aggfunc="sum", fill_value=0.0)
    for c in ("call", "put"):
        if c not in p.columns:
            p[c] = 0.0
    p = p.reset_index().sort_values("strike")
    p["net"] = p["call"] + p["put"]
    return p


def gamma_profile(df: pd.DataFrame, spot: float, expiry: str, lo: float, hi: float, points: int = 161) -> list[dict]:
    now = datetime.now(timezone.utc)
    exp_dt = datetime.fromisoformat(expiry).replace(tzinfo=timezone.utc)
    dte = max((exp_dt - now).total_seconds() / 86400.0 + 0.75, 1.0 / 24.0)
    t_years = dte / 365.0
    levels = np.linspace(lo, hi, points)
    out = []
    rows = list(df.itertuples(index=False))
    for s in levels:
        total = 0.0
        for row in rows:
            g = bs_gamma(float(s), float(row.strike), t_years, float(row.impliedVolatility))
            val = g * float(row.openInterest) * 100.0 * float(s) * float(s) * 0.01
            total += val if row.side == "call" else -val
        out.append({"spot": round(float(s), 4), "gex": float(total)})
    return out


def find_flip(profile: list[dict], spot: float) -> float | None:
    crosses = []
    for a, b in zip(profile, profile[1:]):
        ya, yb = a["gex"], b["gex"]
        if ya == 0:
            crosses.append(a["spot"])
        elif ya * yb < 0:
            x = a["spot"] + (b["spot"] - a["spot"]) * (-ya) / (yb - ya)
            crosses.append(float(x))
    return min(crosses, key=lambda x: abs(x - spot)) if crosses else None


def payload(symbol: str, expiry: str | None, strike_pct: float = 0.35) -> dict:
    spot, expiry, raw = load_chain(symbol, expiry)
    lo, hi = spot * (1.0 - strike_pct), spot * (1.0 + strike_pct)
    raw = raw[(raw["strike"] >= lo) & (raw["strike"] <= hi)].copy()
    agg = aggregate_by_strike(raw)
    if agg.empty:
        raise RuntimeError("No strikes in requested range")

    call_wall_row = agg.loc[agg["call"].idxmax()]
    put_wall_row = agg.loc[agg["put"].idxmin()]
    prof = gamma_profile(raw, spot, expiry, float(agg["strike"].min()), float(agg["strike"].max()))
    flip = find_flip(prof, spot)
    net_gex = float(agg["net"].sum())

    return {
        "symbol": symbol.upper(),
        "spot": spot,
        "expiry": expiry,
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "call_wall": float(call_wall_row["strike"]),
        "put_wall": float(put_wall_row["strike"]),
        "gamma_flip": flip,
        "net_gex": net_gex,
        "sign_model": "calls_positive_puts_negative",
        "units": "USD gamma exposure per 1% underlying move",
        "strikes": [
            {"strike": float(r.strike), "call": float(r.call), "put": float(r.put), "net": float(r.net)}
            for r in agg.itertuples(index=False)
        ],
        "profile": prof,
    }


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Options GEX Prototype</title>
<style>
:root{--bg:#0b0f17;--panel:#121824;--line:#243044;--text:#edf2f7;--muted:#8c9aae;--green:#19c58b;--red:#ff4d6d;--blue:#5d8cff;--orange:#ff922b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1180px;margin:auto;padding:20px}.top{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}.title{font-size:28px;font-weight:800}.muted{color:var(--muted)}.spot{font-size:22px;font-weight:750}.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-top:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.kpi{background:#0e1420;border:1px solid var(--line);border-radius:10px;padding:12px}.kpi b{font-size:19px;display:block;margin-top:4px}canvas{width:100%;height:460px}.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px}.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px}.levels{display:grid;gap:10px}.level{display:flex;justify-content:space-between;padding:12px;border-bottom:1px solid var(--line)}.tag{padding:3px 7px;border-radius:7px;font-size:12px;background:#182235}.note{font-size:12px;line-height:1.6;color:var(--muted);margin-top:12px}@media(max-width:800px){.grid{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}canvas{height:380px}}
</style></head><body><div class="wrap">
<div class="top"><div><div class="title" id="title"></div><div class="muted" id="updated"></div></div><div class="spot" id="spot"></div></div>
<div class="kpis" style="margin-top:18px"><div class="kpi"><span class="muted">Call Wall</span><b id="cw"></b></div><div class="kpi"><span class="muted">Put Wall</span><b id="pw"></b></div><div class="kpi"><span class="muted">Gamma Flip</span><b id="gf"></b></div><div class="kpi"><span class="muted">Net GEX</span><b id="ng"></b></div></div>
<div class="grid"><div class="card"><h2>Gamma Exposure</h2><canvas id="chart"></canvas><div class="legend"><span><i class="dot" style="background:var(--green)"></i>Call</span><span><i class="dot" style="background:var(--red)"></i>Put</span><span><i class="dot" style="background:var(--blue)"></i>Aggregate GEX profile</span><span><i class="dot" style="background:var(--orange)"></i>Gamma Flip</span></div></div>
<div class="card"><h2>Key levels</h2><div class="levels" id="levels"></div><div class="note">Prototype sign convention: call gamma + / put gamma -. This is a positioning proxy, not observed dealer inventory. Use it first as a level map; validate predictive value before wiring it into Setup scores.</div></div></div>
</div><script>
const D=__DATA__;
const f=n=>n==null?'—':n.toLocaleString(undefined,{maximumFractionDigits:2});
const fm=n=>{if(n==null)return '—';let a=Math.abs(n);return (n<0?'-':'')+(a>=1e9?'$'+(a/1e9).toFixed(2)+'B':a>=1e6?'$'+(a/1e6).toFixed(2)+'M':'$'+a.toFixed(0))};
title.textContent=D.symbol+' Options Positioning'; updated.textContent='Expiration '+D.expiry+' · '+D.updated_utc; spot.textContent='Spot $'+f(D.spot); cw.textContent='$'+f(D.call_wall); pw.textContent='$'+f(D.put_wall); gf.textContent=D.gamma_flip?'$'+f(D.gamma_flip):'—'; ng.textContent=fm(D.net_gex);
levels.innerHTML=[['CALL WALL',D.call_wall,'Primary call concentration'],['SPOT',D.spot,'Current underlying'],['PUT WALL',D.put_wall,'Primary put concentration'],['GAMMA FLIP',D.gamma_flip,'Nearest zero-crossing of modeled aggregate GEX']].map(x=>`<div class="level"><div><span class="tag">${x[0]}</span><div class="muted" style="margin-top:6px">${x[2]}</div></div><b>${x[1]==null?'—':'$'+f(x[1])}</b></div>`).join('');
const c=document.getElementById('chart'),ctx=c.getContext('2d');function draw(){const dpr=devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);const pad={l:62,r:18,t:26,b:46};const xs=D.strikes.map(x=>x.strike),vals=D.strikes.flatMap(x=>[x.call,x.put]),pvals=D.profile.map(x=>x.gex);const xmin=Math.min(...xs),xmax=Math.max(...xs),ymax=Math.max(1,...vals.map(Math.abs));const pymax=Math.max(1,...pvals.map(Math.abs));const X=x=>pad.l+(x-xmin)/(xmax-xmin)*(w-pad.l-pad.r),Y=y=>pad.t+(ymax-y)/(2*ymax)*(h-pad.t-pad.b),YP=y=>pad.t+(pymax-y)/(2*pymax)*(h-pad.t-pad.b);ctx.strokeStyle='#243044';ctx.lineWidth=1;[0,.5,1].forEach(t=>{let y=pad.t+t*(h-pad.t-pad.b);ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke()});ctx.strokeStyle='#546176';ctx.beginPath();ctx.moveTo(pad.l,Y(0));ctx.lineTo(w-pad.r,Y(0));ctx.stroke();const bw=Math.max(2,(w-pad.l-pad.r)/D.strikes.length*.56);D.strikes.forEach(r=>{ctx.fillStyle='#19c58b';let y=Y(r.call);ctx.fillRect(X(r.strike)-bw/2,y,bw,Y(0)-y);ctx.fillStyle='#ff4d6d';y=Y(r.put);ctx.fillRect(X(r.strike)-bw/2,Y(0),bw,y-Y(0))});ctx.strokeStyle='#5d8cff';ctx.lineWidth=2.3;ctx.beginPath();D.profile.forEach((r,i)=>{let x=X(r.spot),y=YP(r.gex);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();function vline(x,color,dash,label){if(x==null)return;ctx.strokeStyle=color;ctx.setLineDash(dash);ctx.beginPath();ctx.moveTo(X(x),pad.t);ctx.lineTo(X(x),h-pad.b);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle=color;ctx.font='12px sans-serif';ctx.fillText(label,X(x)+4,pad.t+13)}vline(D.spot,'#c9d3df',[6,5],'Spot '+f(D.spot));vline(D.gamma_flip,'#ff922b',[],'Flip '+f(D.gamma_flip));vline(D.call_wall,'#19c58b',[3,4],'Call Wall');vline(D.put_wall,'#ff4d6d',[3,4],'Put Wall');ctx.fillStyle='#8c9aae';ctx.font='12px sans-serif';ctx.fillText(f(xmin),pad.l,h-16);ctx.fillText(f(xmax),w-pad.r-30,h-16)}draw();addEventListener('resize',draw);
</script></body></html>'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="MSTR")
    ap.add_argument("--expiry", default=None)
    ap.add_argument("--out", default="options-gex-prototype.html")
    ap.add_argument("--json-out", default="data/options_gex_prototype.json")
    ap.add_argument("--strike-pct", type=float, default=0.35)
    a = ap.parse_args()
    d = payload(a.ticker, a.expiry, a.strike_pct)
    Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json_out).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(a.out).write_text(HTML.replace("__DATA__", json.dumps(d, ensure_ascii=False)), encoding="utf-8")
    print(json.dumps({k: d[k] for k in ("symbol", "spot", "expiry", "call_wall", "put_wall", "gamma_flip", "net_gex")}, indent=2))


if __name__ == "__main__":
    main()
