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
import os, sys, json, math, csv, time, random
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
SCAN_STATE  = os.environ.get("V38_OPT_SCAN_STATE", "options_scan_state.json")
SCAN_BUDGET = int(os.environ.get("V38_OPT_SCAN_BUDGET", "60"))
SCAN_REFRESH_DAYS = int(os.environ.get("V38_OPT_SCAN_REFRESH_DAYS", "14"))
FETCH_ATTEMPTS = int(os.environ.get("V38_OPT_FETCH_ATTEMPTS", "3"))
RETRY_BASE_SECONDS = float(os.environ.get("V38_OPT_RETRY_BASE_SECONDS", "2"))
MIN_REFRESH_RATIO = float(os.environ.get("V38_OPT_MIN_REFRESH_RATIO", "0.35"))
CACHE_STALE_DAYS = int(os.environ.get("V38_OPT_STALE_DAYS", "3"))
STRIKE_PCT = float(os.environ.get("V38_OPT_STRIKE_PCT", "0.30"))  # 表示レンジ Spot±30%
RISK_FREE  = float(os.environ.get("V38_OPT_RF", "0.042"))
REFERENCE_TICKERS = ("SPY", "QQQ", "IWM", "TQQQ", "SOXL")

# --- 品質フィルタ（実測でIV=0.00001・bid=ask=0 の行が混ざる）-------------------
MIN_IV, MAX_IV = 0.02, 4.0
MIN_OI_TOTAL   = 500      # 満期あたりの合計OIがこれ未満なら LOW CONFIDENCE
MIN_STRIKES    = 8


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _age_days(ts, now=None):
    try:
        current = pd.Timestamp(now or _now())
        observed = pd.Timestamp(ts)
        current = current.tz_convert("UTC") if current.tzinfo is not None else current.tz_localize("UTC")
        observed = observed.tz_convert("UTC") if observed.tzinfo is not None else observed.tz_localize("UTC")
        return max(0, int((current - observed).total_seconds() // 86400))
    except Exception:
        return None


def _fallback_record(cache_path, attempted_at, exc):
    """取得失敗と経過日数を分離する。3日以内の前回値まで即staleにはしない。"""
    try:
        rec = json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        return None
    age = _age_days(rec.get("asof"), attempted_at)
    rec["refresh_failed"] = True
    rec["refresh_attempted_at"] = attempted_at
    rec["refresh_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    rec["stale"] = age is None or age > CACHE_STALE_DAYS
    return rec


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
    return d[["strike", "openInterest", "impliedVolatility", "volume", "bid", "ask", "kind"]]


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


def _wall_concentration(g, kind, spot=None):
    """Directional side-GEX share at the displayed wall and its lead over #2."""
    sub = g[g["kind"] == kind].groupby("strike")["gex"].sum().abs().sort_values(ascending=False)
    if spot is not None and not sub.empty:
        spot = float(spot)
        sub = sub[sub.index > spot] if kind == "C" else sub[sub.index < spot]
    if sub.empty or float(sub.sum()) <= 0:
        return None, None
    share = float(sub.iloc[0] / sub.sum())
    lead = float(sub.iloc[0] / sub.iloc[1]) if len(sub) >= 2 and float(sub.iloc[1]) > 0 else None
    return share, lead


def _data_confidence(total_oi, n_strikes, call_oi, put_oi):
    """Data-depth label only; it is not a claim that a wall will hold."""
    reasons = []
    if total_oi < MIN_OI_TOTAL:
        reasons.append("合計OI不足")
    if n_strikes < MIN_STRIKES:
        reasons.append("ストライク不足")
    if min(call_oi, put_oi) <= 0:
        reasons.append("片側データ不足")
    if reasons:
        return "LOW", reasons

    balance = min(call_oi, put_oi) / max(call_oi, put_oi) if max(call_oi, put_oi) > 0 else 0.0
    if total_oi >= 5_000 and n_strikes >= 20 and min(call_oi, put_oi) >= 250 and balance >= 0.05:
        return "HIGH", ["両側のOIとストライク数が十分"]
    return "MEDIUM", ["最低品質を通過。複数満期・価格反応で確認"]


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
    call_oi = float(chain.loc[chain["kind"] == "C", "openInterest"].sum())
    put_oi = float(chain.loc[chain["kind"] == "P", "openInterest"].sum())
    n_strikes = int(chain["strike"].nunique())
    call_share, call_lead = _wall_concentration(g, "C", spot=spot)
    put_share, put_lead = _wall_concentration(g, "P", spot=spot)
    data_confidence, quality_reasons = _data_confidence(
        total_oi, n_strikes, call_oi, put_oi
    )
    return dict(
        expiry=str(expiry), dte=int(round(T * 365)),
        call_wall=(cw[0]["strike"] if cw else None),
        put_wall=(pw[0]["strike"] if pw else None),
        gamma_flip=flip,
        net_gex=float(g["gex"].sum()),
        call_walls=cw, put_walls=pw,
        total_oi=total_oi, n_strikes=n_strikes,
        call_oi=call_oi, put_oi=put_oi,
        call_wall_share=call_share, put_wall_share=put_share,
        call_wall_vs_second=call_lead, put_wall_vs_second=put_lead,
        confidence=data_confidence, quality_reasons=quality_reasons,
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
    def atr_units(level):
        if level is None or not atr:
            return None
        return round(abs(level - spot) / atr, 1)
    e = {}
    e["call_wall"] = (
        "現値より上で、コールのOI×推定Gammaが最も集中する価格。"
        "上値抵抗になり得るが、ディーラーの実ポジションを観測したものではない。"
        + (f"現値から{(cw/spot-1)*100:+.1f}%、{atr_units(cw)} ATR。" if cw else ""))
    e["put_wall"] = (
        "現値より下で、プットのOI×推定Gammaが最も集中する価格。"
        "下値支持になり得るが、割れだけで下落加速を断定しない。"
        + (f"現値から{(pw/spot-1)*100:+.1f}%、{atr_units(pw)} ATR。" if pw else ""))
    e["gamma_flip"] = (
        "Callをプラス、Putをマイナスと置いた簡易GEXモデルのゼロ交点。"
        "上は安定側、下は増幅側という推定で、実ディーラーGammaではない。"
        + (f"現値から{(gf/spot-1)*100:+.1f}%。" if gf else ""))
    e["net_gex"] = ("簡易符号仮定によるProxy。プラスは抑制側、マイナスは増幅側の推定。"
                    f"現在 {net/1e6:+.0f}M。")
    e["regime"] = {
        "POSITIVE_GAMMA": "安定側の推定。レンジ内で往復しやすい可能性があるが、"
                          "Put GEX集中帯での実際の反応を確認する。",
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
        requested = [t.strip().upper() for t in TICKERS_ENV.split(",") if t.strip()]
        return list(dict.fromkeys(list(REFERENCE_TICKERS) + requested))
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
    # Yahooのオプション系統が生きているかを最初に判定できるよう、流動性の高いETFを先頭へ。
    return list(dict.fromkeys(list(REFERENCE_TICKERS) + out))


def _expiry_dte(expiry, asof):
    try:
        base = pd.Timestamp(asof)
        base = base.tz_convert(None) if base.tzinfo is not None else base
        return int((pd.Timestamp(expiry).normalize() - base.normalize()).days)
    except Exception:
        return None


def _select_expiries(expiries, asof, limit=MAX_EXPIRY, include_nearest=True):
    """最短だけで枠を使い切らず、DTE 7〜24日の14日前後を必ず優先する。"""
    dated = [(str(exp), _expiry_dte(exp, asof)) for exp in (expiries or [])]
    dated = [(exp, dte) for exp, dte in dated if dte is not None and dte >= 0]
    dated.sort(key=lambda x: (x[1], x[0]))
    if not dated or limit <= 0:
        return []
    selected = []
    if include_nearest:
        selected.append(dated[0][0])
    swing = sorted((x for x in dated if 7 <= x[1] <= 24),
                   key=lambda x: (abs(x[1] - 14), x[1], x[0]))
    for exp, _dte in swing:
        if exp not in selected:
            selected.append(exp)
        if len(selected) >= limit:
            return selected
    for exp, _dte in dated:
        if exp not in selected:
            selected.append(exp)
        if len(selected) >= limit:
            break
    return selected


def _build_record_once(yf, tk, asof):
    y = yf.Ticker(tk)
    px = y.history(period="1mo", auto_adjust=False)
    if px is None or px.empty:
        raise RuntimeError("no price")
    spot = float(px["Close"].iloc[-1])
    tr = pd.concat([px["High"] - px["Low"],
                    (px["High"] - px["Close"].shift()).abs(),
                    (px["Low"] - px["Close"].shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    exps = _select_expiries(list(y.options or []), asof, MAX_EXPIRY, include_nearest=True)
    if not exps:
        raise RuntimeError("no option expiries returned")
    per, expiry_errors = {}, []
    for e in exps:
        try:
            ch = y.option_chain(e)
            r = analyse_expiry(ch.calls, ch.puts, spot, e, asof)
            if r:
                per[e] = r
        except Exception as exc:
            expiry_errors.append(f"{e}:{type(exc).__name__}")
    if not per:
        tail = " (" + ",".join(expiry_errors[:3]) + ")" if expiry_errors else ""
        raise RuntimeError("no usable expiry" + tail)
    agg_net = sum(v["net_gex"] for v in per.values())
    nearest_expiry = sorted(per)[0]
    swing_expiries = [e for e in per if 7 <= (_expiry_dte(e, asof) or -999) <= 24]
    selected_expiry = (min(swing_expiries, key=lambda e: abs(_expiry_dte(e, asof) - 14))
                       if swing_expiries else nearest_expiry)
    focus = per[selected_expiry]
    selection_basis = "swing" if selected_expiry in swing_expiries else "nearest"
    tech = tech_levels(px)
    cw, pw, gf = focus["call_wall"], focus["put_wall"], focus["gamma_flip"]
    return dict(
        ticker=tk, asof=asof, spot=round(spot, 2), atr14=round(atr, 4),
        tech={k: round(v, 2) for k, v in tech.items()},
        confluence=dict(
            call_wall=confluence(cw, tech, spot, atr),
            put_wall=confluence(pw, tech, spot, atr),
            gamma_flip=confluence(gf, tech, spot, atr)),
        range_pos=position_in_range(spot, pw, cw),
        explain=explain(spot, cw, pw, gf, focus["net_gex"], atr,
                        regime(spot, gf, atr)),
        source="yfinance", basis="positioning_proxy_not_observed_dealer_gamma",
        oi_basis="provider_open_interest_update_time_unavailable",
        nearest=nearest_expiry, selected_expiry=selected_expiry,
        selection_basis=selection_basis,
        call_wall=dist_block(cw, spot, atr),
        put_wall=dist_block(pw, spot, atr),
        gamma_flip=dist_block(gf, spot, atr),
        net_gex=round(focus["net_gex"], 2), net_gex_all=round(agg_net, 2),
        regime=regime(spot, gf, atr), confidence=focus["confidence"],
        expiries=per, stale=False, refresh_failed=False,
        refresh_attempted_at=asof)


def _fetch_record(yf, tk, asof, sleep_fn=time.sleep):
    """Yahooの一時的な空レスポンス/429を短い指数バックオフで再試行する。"""
    last = None
    for attempt in range(max(1, FETCH_ATTEMPTS)):
        try:
            return _build_record_once(yf, tk, asof)
        except Exception as exc:
            last = exc
            if attempt + 1 < max(1, FETCH_ATTEMPTS):
                delay = RETRY_BASE_SECONDS * (2 ** attempt) + random.uniform(0.0, 0.5)
                sys.stderr.write(
                    f"[opt] {tk} retry {attempt + 1}/{FETCH_ATTEMPTS - 1} "
                    f"after {type(exc).__name__}: {str(exc)[:90]}\n")
                sleep_fn(delay)
    raise last or RuntimeError("unknown options fetch failure")


def _refresh_gate(requested, refreshed):
    ratio = (float(refreshed) / float(requested)) if requested else 1.0
    return ratio >= MIN_REFRESH_RATIO, ratio


def _scan_state_from_files():
    state = {}
    try:
        raw = json.load(open(SCAN_STATE, encoding="utf-8"))
        if isinstance(raw, dict):
            state = raw
    except Exception:
        pass
    # 既存scan履歴を初期stateとして取り込み、過去602銘柄を未取得扱いへ戻さない。
    try:
        for row in csv.DictReader(open(SCAN_HIST, encoding="utf-8-sig")):
            tk = str(row.get("ticker") or "").strip().upper()
            day = row.get("date")
            if tk and day and day >= str((state.get(tk) or {}).get("checked_at") or "")[:10]:
                state[tk] = dict(checked_at=day, status="ok")
    except Exception:
        pass
    return state


def _scan_targets(tickers, state, today, budget, exclude=None):
    exclude = set(exclude or [])
    due = []
    for i, tk in enumerate(dict.fromkeys(tickers or [])):
        if tk in exclude:
            continue
        rec = state.get(tk) if isinstance(state, dict) else None
        if not isinstance(rec, dict) or not rec.get("checked_at"):
            due.append((0, -10 ** 6, i, tk))
            continue
        age = _age_days(rec.get("checked_at"), today)
        status = str(rec.get("status") or "error")
        ttl = 30 if status in ("no_options", "insufficient") else (
            3 if status in ("rate_limited", "error") else SCAN_REFRESH_DAYS)
        if age is None or age >= ttl:
            due.append((1, -(age if age is not None else 10 ** 6), i, tk))
    return [tk for _p, _age, _i, tk in sorted(due)][:max(0, int(budget))]


def scan_universe(exclude=None):
    """全銘柄を少量ずつローテーションし、成功/対象外/失敗をstateへ残す。"""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor
    try:
        tks = [str(r[list(r)[0]]).strip().upper()
               for r in csv.DictReader(open(UNIVERSE_CSV, encoding="utf-8-sig"))]
        tks = [t for t in tks if t and t.replace(".", "").replace("-", "").isalnum()]
    except Exception as exc:
        sys.stderr.write(f"[opt-scan] universe読み込み失敗: {type(exc).__name__}\n")
        return [], dict(requested=0, ok=0, no_options=0, failed=0)
    asof = _now()
    state = _scan_state_from_files()
    targets = _scan_targets(tks, state, asof, SCAN_BUDGET, exclude=exclude)

    def failure_status(exc):
        msg = (type(exc).__name__ + " " + str(exc)).lower()
        return "rate_limited" if any(x in msg for x in ("ratelimit", "too many", "429")) else "error"

    def one(tk):
        try:
            y = yf.Ticker(tk)
            # 広域側も最短満期でなく2週間スイングに近い1本を保存する。
            exps = _select_expiries(list(y.options or []), asof, 1, include_nearest=False)
            if not exps:
                return tk, "no_options", None, "no option expiries"
            px = y.history(period="1mo", auto_adjust=False)
            if px is None or px.empty:
                return tk, "error", None, "no price"
            spot = float(px["Close"].iloc[-1])
            tr = pd.concat([px["High"] - px["Low"],
                            (px["High"] - px["Close"].shift()).abs(),
                            (px["Low"] - px["Close"].shift()).abs()], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
            ch = y.option_chain(exps[0])
            r = analyse_expiry(ch.calls, ch.puts, spot, exps[0], asof)
            if not r:
                return tk, "insufficient", None, "no usable expiry"
            gf = r["gamma_flip"]
            row = dict(date=asof[:10], ticker=tk, expiry=r["expiry"], spot=round(spot, 4),
                       atr14=round(atr, 4),
                       call_wall=r["call_wall"], put_wall=r["put_wall"], gamma_flip=gf,
                       net_gex=round(r["net_gex"], 2),
                       call_wall_pct=(round(r["call_wall"] / spot - 1, 5) if r["call_wall"] else None),
                       put_wall_pct=(round(r["put_wall"] / spot - 1, 5) if r["put_wall"] else None),
                       flip_pct=(round(gf / spot - 1, 5) if gf else None),
                       total_oi=int(r["total_oi"]), n_strikes=r["n_strikes"],
                       regime=regime(spot, gf, atr), confidence=r["confidence"])
            return tk, "ok", row, ""
        except Exception as exc:
            return tk, failure_status(exc), None, f"{type(exc).__name__}: {str(exc)[:120]}"

    t0, rows, attempted = time.time(), [], 0
    counts = dict(requested=len(targets), ok=0, no_options=0, insufficient=0,
                  rate_limited=0, failed=0)
    # 10件ずつ確認し、半数以上がrate-limitなら残りを叩かず次回へ回す。
    for start in range(0, len(targets), 10):
        batch = targets[start:start + 10]
        with ThreadPoolExecutor(max_workers=max(1, min(SCAN_WORKERS, len(batch)))) as ex:
            batch_results = list(ex.map(one, batch))
        attempted += len(batch_results)
        for tk, status, row, err in batch_results:
            if status == "ok":
                rows.append(row)
                counts["ok"] += 1
            elif status in ("no_options", "insufficient", "rate_limited"):
                counts[status] += 1
            else:
                counts["failed"] += 1
            state[tk] = dict(checked_at=asof, status=status, error=err or None)
        if sum(1 for _tk, status, _row, _err in batch_results if status == "rate_limited") >= max(2, len(batch) // 2):
            sys.stderr.write("[opt-scan] rate-limit circuit opened; remaining names deferred\n")
            break
    with open(SCAN_STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, sort_keys=True)
    counts["attempted"] = attempted
    sys.stderr.write(
        "[opt-scan] attempted=%d/%d ok=%d no_options=%d insufficient=%d rate_limited=%d failed=%d %.0fs\n"
        % (attempted, len(targets), counts["ok"], counts["no_options"],
           counts["insufficient"], counts["rate_limited"], counts["failed"], time.time() - t0))
    return rows, counts


def main():
    import yfinance as yf
    os.makedirs(CACHE_DIR, exist_ok=True)
    tickers = load_tickers()
    asof = _now()
    results, hist_rows = {}, []
    refreshed = fallback = missing = 0
    failed_probes = set()
    provider_circuit = False
    for tk in tickers:
        cache_path = os.path.join(CACHE_DIR, f"{tk}.json")
        try:
            if provider_circuit:
                raise RuntimeError("provider circuit open after reference ETF failures")
            rec = _fetch_record(yf, tk, asof)
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, ensure_ascii=False)
            refreshed += 1
        except Exception as exc:
            sys.stderr.write(f"[opt] {tk} failed: {type(exc).__name__} {exc}\n")
            if tk in REFERENCE_TICKERS[:3]:
                failed_probes.add(tk)
                if all(x in failed_probes for x in REFERENCE_TICKERS[:3]):
                    provider_circuit = True
                    sys.stderr.write("[opt] provider circuit opened after SPY/QQQ/IWM failures\n")
            rec = _fallback_record(cache_path, asof, exc)
            if rec is None:
                missing += 1
                continue
            fallback += 1
        results[tk] = rec
        # 前回値フォールバックを「本日の観測」として履歴へ混ぜない。
        if not rec.get("refresh_failed"):
            hist_rows.append(dict(
                date=asof[:10], ticker=tk,
                expiry=rec.get("selected_expiry") or rec.get("nearest"), spot=rec.get("spot"),
                call_wall=(rec.get("call_wall") or {}).get("px"),
                put_wall=(rec.get("put_wall") or {}).get("px"),
                gamma_flip=(rec.get("gamma_flip") or {}).get("px"),
                net_gex=rec.get("net_gex"),
                call_wall_pct=(rec.get("call_wall") or {}).get("pct"),
                put_wall_pct=(rec.get("put_wall") or {}).get("pct"),
                flip_pct=(rec.get("gamma_flip") or {}).get("pct"),
                regime=rec.get("regime"), confidence=rec.get("confidence"),
                stale=False))
        time.sleep(0.4)

    gate_ok, refresh_ratio = _refresh_gate(len(tickers), refreshed)
    quality = dict(requested=len(tickers), refreshed=refreshed, fallback=fallback,
                   missing=missing, refresh_ratio=round(refresh_ratio, 4),
                   min_refresh_ratio=MIN_REFRESH_RATIO,
                   provider_circuit_open=provider_circuit, gate_ok=gate_ok)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(dict(asof=asof, source="yfinance",
                       basis="positioning_proxy_not_observed_dealer_gamma",
                       oi_basis="provider_open_interest_update_time_unavailable",
                       quality=quality, tickers=results), fh, ensure_ascii=False)

    if hist_rows:
        cols = list(hist_rows[0].keys())
        new = not os.path.exists(HIST_CSV)
        with open(HIST_CSV, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            if new:
                w.writeheader()
            for r in hist_rows:
                w.writerow(r)
    sys.stderr.write(
        "[opt] quality requested=%d refreshed=%d fallback=%d missing=%d ratio=%.1f%%\n"
        % (len(tickers), refreshed, fallback, missing, refresh_ratio * 100.0))
    sys.stderr.write(f"[opt] wrote {len(results)} tickers -> {OUT_JSON}\n")

    if not gate_ok:
        sys.stderr.write(
            "::error::Options refresh degraded: %d/%d fresh (%.1f%%), required %.1f%%. "
            "Previous committed snapshot is preserved.\n"
            % (refreshed, len(tickers), refresh_ratio * 100.0, MIN_REFRESH_RATIO * 100.0))
        return 2

    # --- 広域銘柄を少量ずつ蓄積。詳細対象との重複は避ける。------------------
    if SCAN_ALL:
        srows, _scan_quality = scan_universe(exclude=tickers)
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
