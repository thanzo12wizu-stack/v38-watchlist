#!/usr/bin/env python3
"""Options Positioning / GEX Wall — V38 別モジュール

設計思想（別途合意済み）に従う:
  - 表示ロジックとデータ取得を分離する。ここは取得と計算だけを行い、JSONを吐く。
  - Dealer Gamma の観測値ではなく Positioning Proxy であることをJSON側にも明示する。
  - 売買シグナルは出さない。Wall位置・距離・regime までに留める。
  - Option取得の失敗で本体ビルドを落とさない（本スクリプトは独立プロセス）。
  - 毎日 history に追記して、後から支持抵抗として本当に効くかを検証できる形にする。

出力:
  options_positioning.json   最新スナップショット（満期別 + 集約）
  options_history.csv        日次追記（検証用）
  options_cache/<TK>.json    取得失敗時のフォールバック
"""
import os, sys, json, math, csv, time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

OUT_JSON   = os.environ.get("V38_OPT_JSON", "options_positioning.json")
HIST_CSV   = os.environ.get("V38_OPT_HISTORY", "options_history.csv")
CACHE_DIR  = os.environ.get("V38_OPT_CACHE", "options_cache")
STATE_JSON = os.environ.get("V38_STATE_JSON", "state.json")
TICKERS_ENV= os.environ.get("V38_OPT_TICKERS", "")
MAX_EXPIRY = int(os.environ.get("V38_OPT_MAX_EXPIRY", "4"))   # 近い順に何本の満期を見るか
# 表示は少数精鋭、履歴は全銘柄。検証に必要なサンプル数は表示対象だけでは足りない。
SCAN_ALL    = os.environ.get("V38_OPT_SCAN_ALL", "0") == "1"
UNIVERSE_CSV= os.environ.get("V38_UNIVERSE_CSV", "universe.csv")
SCAN_HIST   = os.environ.get("V38_OPT_SCAN_HISTORY", "options_scan_history.csv")
SCAN_WORKERS= int(os.environ.get("V38_OPT_SCAN_WORKERS", "8"))
TARGETS_JSON= os.environ.get("V38_OPT_TARGETS", "options_targets.json")
STRIKE_PCT = float(os.environ.get("V38_OPT_STRIKE_PCT", "0.30"))  # 表示レンジ Spot±30%
RISK_FREE  = float(os.environ.get("V38_OPT_RF", "0.042"))

# --- 品質フィルタ（実測でIV=0.00001・bid=ask=0 の行が混ざる）-------------------
MIN_IV, MAX_IV = 0.02, 4.0
MIN_OI_TOTAL   = 500      # 満期あたりの合計OIがこれ未満なら LOW CONFIDENCE
MIN_STRIKES    = 8


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def bs_gamma(S, K, T, sigma, r=RISK_FREE):
    """Black-Scholes gamma。IVから再計算する（provider gammaは持たない）。"""
    if not (S > 0 and K > 0 and T > 0 and sigma > 0):
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        return math.exp(-0.5 * d1 * d1) / (S * sigma * math.sqrt(2 * math.pi * T))
    except Exception:
        return 0.0


def _clean(df, kind):
    if df is None or len(df) == 0:
        return pd.DataFrame()
    d = df.copy()
    for c in ("strike", "openInterest", "impliedVolatility", "volume", "bid", "ask"):
        if c not in d.columns:
            d[c] = np.nan
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[(d["strike"] > 0) & (d["openInterest"].fillna(0) > 0)]
    d = d[d["impliedVolatility"].between(MIN_IV, MAX_IV)]
    # bid=ask=0 かつ出来高なしは板が無い行。gammaを歪めるので落とす。
    dead = (d["bid"].fillna(0) <= 0) & (d["ask"].fillna(0) <= 0) & (d["volume"].fillna(0) <= 0)
    d = d[~dead]
    d["kind"] = kind
    return d[["strike", "openInterest", "impliedVolatility", "volume", "kind"]]


def gex_by_strike(chain, spot, T):
    """Strike別 Dollar GEX。call=+ / put=- の簡易sign convention（Proxy）。"""
    rows = []
    for _, r in chain.iterrows():
        g = bs_gamma(spot, float(r["strike"]), T, float(r["impliedVolatility"]))
        dollar = g * float(r["openInterest"]) * 100.0 * spot * spot * 0.01
        rows.append((float(r["strike"]), dollar if r["kind"] == "C" else -dollar, r["kind"]))
    if not rows:
        return pd.DataFrame(columns=["strike", "gex", "kind"])
    return pd.DataFrame(rows, columns=["strike", "gex", "kind"])


def aggregate_profile(chain, spot, T, lo, hi, n=61):
    """Spotを動かしながらgammaを再計算した price-dependent aggregate GEX。
       Gamma Flip は Strike別netのゼロクロスではなく、この曲線のゼロ交点で求める。"""
    xs = np.linspace(lo, hi, n)
    ys = []
    K = chain["strike"].to_numpy(float)
    OI = chain["openInterest"].to_numpy(float)
    IV = chain["impliedVolatility"].to_numpy(float)
    SG = np.where(chain["kind"].to_numpy() == "C", 1.0, -1.0)
    for S in xs:
        g = np.array([bs_gamma(S, k, T, v) for k, v in zip(K, IV)])
        ys.append(float(np.sum(g * OI * 100.0 * S * S * 0.01 * SG)))
    ys = np.array(ys)
    flip = None
    for i in range(1, len(xs)):
        if ys[i - 1] == 0 or ys[i - 1] * ys[i] < 0:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            flip = float(x0 - y0 * (x1 - x0) / (y1 - y0)) if y1 != y0 else float(x0)
            break
    return xs, ys, flip


def top_walls(g, kind, n=3, spot=None):
    """Return directional walls only.

    Call resistance must be above spot and Put support must be below spot.
    Wrong-side concentrations can be pins, but must not be labelled as a wall.
    """
    sub = g[g["kind"] == kind].groupby("strike")["gex"].sum()
    if spot is not None and not sub.empty:
        spot = float(spot)
        sub = sub[sub.index > spot] if kind == "C" else sub[sub.index < spot]
    if sub.empty:
        return []
    sub = sub.abs().sort_values(ascending=False).head(n)
    return [dict(strike=float(k), gex=float(v)) for k, v in sub.items()]


def analyse_expiry(calls, puts, spot, expiry, asof):
    c, p = _clean(calls, "C"), _clean(puts, "P")
    chain = pd.concat([c, p], ignore_index=True)
    if chain.empty:
        return None
    lo_k, hi_k = spot * (1 - STRIKE_PCT), spot * (1 + STRIKE_PCT)
    chain = chain[chain["strike"].between(lo_k, hi_k)]
    if len(chain) < MIN_STRIKES:
        return None
    # asofはUTC aware、expiryはnaive。tzを外して差を取る（混ぜると TypeError）。
    _a = pd.Timestamp(asof)
    _a = (_a.tz_convert(None) if _a.tzinfo is not None else _a).normalize()
    T = max((pd.Timestamp(expiry) - _a).days, 0) / 365.0
    T = max(T, 1.0 / 365.0)
    g = gex_by_strike(chain, spot, T)
    xs, ys, flip = aggregate_profile(chain, spot, T, lo_k, hi_k)
    cw = top_walls(g, "C", spot=spot); pw = top_walls(g, "P", spot=spot)
    total_oi = float(chain["openInterest"].sum())
    return dict(
        expiry=str(expiry), dte=int(round(T * 365)),
        call_wall=(cw[0]["strike"] if cw else None),
        put_wall=(pw[0]["strike"] if pw else None),
        gamma_flip=flip,
        net_gex=float(g["gex"].sum()),
        call_walls=cw, put_walls=pw,
        total_oi=total_oi, n_strikes=int(chain["strike"].nunique()),
        confidence=("LOW" if (total_oi < MIN_OI_TOTAL or chain["strike"].nunique() < MIN_STRIKES)
                    else "OK"),
        strikes=[dict(k=float(k), call=float(v[v["kind"] == "C"]["gex"].sum()),
                      put=float(v[v["kind"] == "P"]["gex"].sum()))
                 for k, v in g.groupby("strike")],
        profile=dict(x=[round(float(v), 4) for v in xs],
                     y=[round(float(v), 2) for v in ys]),
    )


def dist_block(level, spot, atr):
    if level is None or not spot:
        return dict(px=None, pct=None, atr=None)
    return dict(px=round(float(level), 2),
                pct=round(float(level) / float(spot) - 1.0, 5),
                atr=(round((float(level) - float(spot)) / float(atr), 2)
                     if atr and atr > 0 else None))


def regime(spot, flip, atr):
    if flip is None or not spot:
        return "UNKNOWN"
    if atr and atr > 0:
        d = abs(spot - flip) / atr
        if d <= 1.0:
            return "NEAR_FLIP"
    return "POSITIVE_GAMMA" if spot > flip else "NEGATIVE_GAMMA"



# ─────────────────────────────────────────────────────────────────────────────
# 実用化レイヤー: 数字だけでは使えないので、初心者にも読める説明と、
# 既存テクニカル（21EMA/50MA/63VWAP）との重なりを同じ場所で出す。
# 売買シグナル（BUY/SELL）は出さない。出すのは「どこが効きやすいか」「今どこにいるか」まで。
def tech_levels(px):
    """21EMA / 50MA / 63日VWAP。オプション水準と重なるかを見るために同じ足から計算する。"""
    c = px["Close"].astype(float)
    out = {}
    try:
        out["21EMA"] = float(c.ewm(span=21, adjust=False).mean().iloc[-1])
    except Exception:
        pass
    try:
        if len(c) >= 50:
            out["50MA"] = float(c.rolling(50).mean().iloc[-1])
    except Exception:
        pass
    try:
        n = min(63, len(px))
        tp = (px["High"] + px["Low"] + px["Close"]).astype(float) / 3.0
        v = px["Volume"].astype(float)
        out["63VWAP"] = float((tp.iloc[-n:] * v.iloc[-n:]).sum() / max(v.iloc[-n:].sum(), 1))
    except Exception:
        pass
    return out


def confluence(level, tech, spot, atr):
    """価格差が max(0.5%, 0.35ATR) 以内なら「重なり」。一致とは言い切らない。"""
    if level is None or not spot:
        return []
    tol = max(spot * 0.005, (atr or 0) * 0.35)
    hits = []
    for name, v in (tech or {}).items():
        if v and abs(v - level) <= tol:
            hits.append(dict(name=name, px=round(v, 2),
                             diff=round(v / level - 1.0, 4)))
    return hits


def explain(spot, cw, pw, gf, net, atr, reg):
    """初心者向けの言葉。専門用語を出したら必ず意味を添える。"""
    def days(level):
        if level is None or not atr:
            return None
        return round(abs(level - spot) / atr, 1)
    e = {}
    e["call_wall"] = (
        "コール（買う権利）の建玉が最も積み上がっている価格。"
        "売り手がここを守ろうとするので上値が重くなりやすい。"
        + (f"現値から{(cw/spot-1)*100:+.1f}%、いつもの値動き{days(cw)}日分。" if cw else ""))
    e["put_wall"] = (
        "プット（売る権利）の建玉が最も積み上がっている価格。"
        "下値の支えになりやすい。割ると下げが速くなりやすい。"
        + (f"現値から{(pw/spot-1)*100:+.1f}%、いつもの値動き{days(pw)}日分。" if pw else ""))
    e["gamma_flip"] = (
        "値動きの性質が変わる境目。"
        "この上では値動きが落ち着きやすく、下では荒れやすい。"
        + (f"現値から{(gf/spot-1)*100:+.1f}%。" if gf else ""))
    e["net_gex"] = ("プラスなら値動きを抑える力が優勢、マイナスなら増幅する力が優勢。"
                    f"現在 {net/1e6:+.0f}M。")
    e["regime"] = {
        "POSITIVE_GAMMA": "落ち着きやすい局面。レンジ内で往復しやすく、"
                          "Put Wall付近の押し目が拾われやすい。",
        "NEGATIVE_GAMMA": "荒れやすい局面。同じ損切り幅でも刈られやすいので、"
                          "サイズを小さくするか損切りを広く取る判断が要る。",
        "NEAR_FLIP": "境目にいる。どちらにも振れやすく、方向が決まるまで待つ選択肢もある。",
        "UNKNOWN": "判定不能。",
    }.get(reg, "")
    return e


def position_in_range(spot, pw, cw):
    """Put Wall〜Call Wall のどこにいるか（0%=Put Wall, 100%=Call Wall）。"""
    if pw is None or cw is None or cw <= pw:
        return None
    return round(max(0.0, min(1.0, (spot - pw) / (cw - pw))) * 100, 1)


def load_tickers():
    if TICKERS_ENV.strip():
        return [t.strip().upper() for t in TICKERS_ENV.split(",") if t.strip()]
    out = []
    try:
        st = json.load(open(STATE_JSON, encoding="utf-8"))
        for k in ("picks", "hold"):
            for t in (st.get(k) or []):
                if isinstance(t, str) and t.upper() not in out:
                    out.append(t.upper())
    except Exception:
        pass
    # 本体が吐いた候補（発火前ボード・エントリー候補）を合流。無ければ無視。
    try:
        for t in (json.load(open(TARGETS_JSON, encoding="utf-8")) or []):
            if isinstance(t, str) and t.upper() not in out:
                out.append(t.upper())
    except Exception:
        pass
    for t in ("SPY", "QQQ", "IWM", "TQQQ", "SOXL"):
        if t not in out:
            out.append(t)
    return out


def scan_universe():
    """履歴用の全銘柄スキャン。表示はせず、1銘柄1行のサマリーだけ残す。
       Strike別の明細は保存しない（年59万行になるため）。"""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor
    try:
        tks = [str(r[list(r)[0]]).strip().upper()
               for r in csv.DictReader(open(UNIVERSE_CSV, encoding="utf-8-sig"))]
        tks = [t for t in tks if t and t.replace(".", "").replace("-", "").isalnum()]
    except Exception as exc:
        sys.stderr.write(f"[opt-scan] universe読み込み失敗: {type(exc).__name__}\n")
        return []
    asof = _now()
    def one(tk):
        try:
            y = yf.Ticker(tk)
            exps = list(y.options or [])[:1]        # 履歴用は最近満期1本のみ
            if not exps:
                return None
            px = y.history(period="1mo", auto_adjust=False)
            if px is None or px.empty:
                return None
            spot = float(px["Close"].iloc[-1])
            tr = pd.concat([px["High"] - px["Low"],
                            (px["High"] - px["Close"].shift()).abs(),
                            (px["Low"] - px["Close"].shift()).abs()], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
            ch = y.option_chain(exps[0])
            r = analyse_expiry(ch.calls, ch.puts, spot, exps[0], asof)
            if not r:
                return None
            gf = r["gamma_flip"]
            return dict(date=asof[:10], ticker=tk, expiry=r["expiry"], spot=round(spot, 4),
                        atr14=round(atr, 4),
                        call_wall=r["call_wall"], put_wall=r["put_wall"], gamma_flip=gf,
                        net_gex=round(r["net_gex"], 2),
                        call_wall_pct=(round(r["call_wall"] / spot - 1, 5) if r["call_wall"] else None),
                        put_wall_pct=(round(r["put_wall"] / spot - 1, 5) if r["put_wall"] else None),
                        flip_pct=(round(gf / spot - 1, 5) if gf else None),
                        total_oi=int(r["total_oi"]), n_strikes=r["n_strikes"],
                        regime=regime(spot, gf, atr), confidence=r["confidence"])
        except Exception:
            return None
    t0 = time.time(); rows = []
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as ex:
        for res in ex.map(one, tks):
            if res:
                rows.append(res)
    sys.stderr.write("[opt-scan] %d/%d銘柄 %.0fs\n" % (len(rows), len(tks), time.time() - t0))
    return rows


def main():
    import yfinance as yf
    os.makedirs(CACHE_DIR, exist_ok=True)
    tickers = load_tickers()
    asof = _now()
    results, hist_rows = {}, []
    for tk in tickers:
        cache_path = os.path.join(CACHE_DIR, f"{tk}.json")
        try:
            y = yf.Ticker(tk)
            px = y.history(period="1mo", auto_adjust=False)
            if px is None or px.empty:
                raise RuntimeError("no price")
            spot = float(px["Close"].iloc[-1])
            tr = pd.concat([px["High"] - px["Low"],
                            (px["High"] - px["Close"].shift()).abs(),
                            (px["Low"] - px["Close"].shift()).abs()], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
            exps = list(y.options or [])[:MAX_EXPIRY]
            per = {}
            for e in exps:
                try:
                    ch = y.option_chain(e)
                    r = analyse_expiry(ch.calls, ch.puts, spot, e, asof)
                    if r:
                        per[e] = r
                except Exception as exc:
                    sys.stderr.write(f"[opt] {tk} {e}: {type(exc).__name__}\n")
            if not per:
                raise RuntimeError("no usable expiry")
            # 集約: 満期を単純合算（DTE weightingは後で検証できるよう生値を残す）
            agg_net = sum(v["net_gex"] for v in per.values())
            first = per[sorted(per)[0]]
            _tech = tech_levels(px)
            _cw, _pw, _gf = first["call_wall"], first["put_wall"], first["gamma_flip"]
            rec = dict(
                ticker=tk, asof=asof, spot=round(spot, 2), atr14=round(atr, 4),
                tech={k: round(v, 2) for k, v in _tech.items()},
                confluence=dict(
                    call_wall=confluence(_cw, _tech, spot, atr),
                    put_wall=confluence(_pw, _tech, spot, atr),
                    gamma_flip=confluence(_gf, _tech, spot, atr)),
                range_pos=position_in_range(spot, _pw, _cw),
                explain=explain(spot, _cw, _pw, _gf, first["net_gex"], atr,
                                regime(spot, _gf, atr)),
                source="yfinance", basis="positioning_proxy_not_observed_dealer_gamma",
                nearest=first["expiry"],
                call_wall=dist_block(first["call_wall"], spot, atr),
                put_wall=dist_block(first["put_wall"], spot, atr),
                gamma_flip=dist_block(first["gamma_flip"], spot, atr),
                net_gex=round(first["net_gex"], 2),
                net_gex_all=round(agg_net, 2),
                regime=regime(spot, first["gamma_flip"], atr),
                confidence=first["confidence"],
                expiries=per, stale=False)
            json.dump(rec, open(cache_path, "w"), ensure_ascii=False)
        except Exception as exc:
            sys.stderr.write(f"[opt] {tk} failed: {type(exc).__name__} {exc}\n")
            try:
                rec = json.load(open(cache_path, encoding="utf-8"))
                rec["stale"] = True
            except Exception:
                continue
        results[tk] = rec
        hist_rows.append(dict(
            date=asof[:10], ticker=tk, expiry=rec.get("nearest"), spot=rec.get("spot"),
            call_wall=(rec.get("call_wall") or {}).get("px"),
            put_wall=(rec.get("put_wall") or {}).get("px"),
            gamma_flip=(rec.get("gamma_flip") or {}).get("px"),
            net_gex=rec.get("net_gex"),
            call_wall_pct=(rec.get("call_wall") or {}).get("pct"),
            put_wall_pct=(rec.get("put_wall") or {}).get("pct"),
            flip_pct=(rec.get("gamma_flip") or {}).get("pct"),
            regime=rec.get("regime"), confidence=rec.get("confidence"),
            stale=rec.get("stale")))
        time.sleep(0.4)

    json.dump(dict(asof=asof, source="yfinance",
                   basis="positioning_proxy_not_observed_dealer_gamma",
                   tickers=results), open(OUT_JSON, "w"), ensure_ascii=False)

    if hist_rows:
        cols = list(hist_rows[0].keys())
        new = not os.path.exists(HIST_CSV)
        with open(HIST_CSV, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            if new:
                w.writeheader()
            for r in hist_rows:
                w.writerow(r)
    sys.stderr.write(f"[opt] wrote {len(results)} tickers -> {OUT_JSON}\n")

    # --- 履歴用の全銘柄スキャン（表示には使わない）-------------------------
    if SCAN_ALL:
        srows = scan_universe()
        if srows:
            cols = list(srows[0].keys())
            new = not os.path.exists(SCAN_HIST)
            with open(SCAN_HIST, "a", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                if new:
                    w.writeheader()
                for r in srows:
                    w.writerow(r)
            sys.stderr.write(f"[opt-scan] appended {len(srows)} rows -> {SCAN_HIST}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
