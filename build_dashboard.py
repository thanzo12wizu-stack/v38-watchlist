#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Command Center — dashboard builder (最終確定 2026-07-05)
  A. 個別スリーブ(70%): N=12, 189日RS上位 × 50日SMA>200日SMA × 出来高金額$10M/日 × 株価$5以上,
     各1/12均等(テーマ上限なし)。継続=50>200日SMA&189日RS上位24(2N)。週足SARはアブレーションで撤廃・クールダウンなし。
     選定除外: リーダー外(63日RS<85 or 200MA下)と小型創薬(サブテーマ=臨床段階・中小型バイオ)は外す(大手バイオ/製薬/GLP-1/手術ロボは対象)。出遅れ(業種内−20%)は買う(タグのみ・2026-07-07方針変更)。
              ※ユニバース段階でも時価総額<$100億のヘルスケアは除外済み(二重の網)。除外株はRS順に表示だけ残す(強さ確認用・買わない)。
     急落局面(20日安値割れ or 5日−15%)は直近5日にセリングクライマックス(RVOL≥2.5&日足−5%)があれば満額解禁,
     無ければ一服待ち=見送り(枠は現金・繰上げなし・次回再判定)。
     出口(確定2026-07-07): 初期ストップmax(10日安値×0.998,21EMA×0.99)→+3Rで1/3利確(建値移動なし)→残りは10日安値割れで全売り。
     期中退出の空き枠は再投下せず現金で持ち隔週(月曜)トゥルーアップで吸収。銘柄入替は定例月曜のみ(赤明け即再選定はしない)。
  B. レバスリーブ(30%): TQQQ:SOXL=50:50, SOXX MA50<100でSOXL→TQQQ, NQ4色ゲート。配分=個別70/レバ30/現金0。
  C. NQ 4色ゲート(即応・確認日数ゼロ): 個別 青100/緑100/黄=新規停止・保有はトレール15%継続/赤0(撤退), レバ 青100/緑50/黄0/赤0。執行は翌寄り。
  D. 地合いスコア=14指標加重和(raw 0-100, 表示専用・ゲート不関与)。先導株の強さ温度計/センチメント/レバ環境も表示専用。
     ※先導株温度計は非対称: 左端(枯渇)のみNQ底に中央値18日先行(的中6割)/右端(過熱)は先取りせず。露出は動かさない。
  E. 7 tabs (マーケット/ピックアップ/ポートフォリオ/配分/ウォッチ/業種RS/ルール) + 今日の運用ヘッダ + 隔週リバランス点検（月曜）。
  ※全数字はグロス・生存バイアス上限。信頼区間は対指数の相対優位。NQは手動(TradingView)が真。

Data: live yfinance (CI) or cached prices.pkl for local preview.
Run:  python3 build_dashboard.py            -> render HTML + selftest
      python3 build_dashboard.py --diag     -> print computed numbers, no HTML
      python3 build_dashboard.py --selftest -> render + assert
"""
import sys, os, json, csv, pickle, warnings, time, datetime as dt
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

CACHE        = os.environ.get("V38_CACHE",        "/home/claude/bt/prices.pkl")
UNIVERSE_CSV = os.environ.get("V38_UNIVERSE_CSV", "/mnt/project/universe.csv")
SECTOR_JSON  = os.environ.get("V38_SECTOR_JSON",  "/mnt/project/sector_snapshot.json")
OUT_HTML     = os.environ.get("V38_OUT_HTML",     "/mnt/user-data/outputs/V38_Command_Center.html")

N_PORT = 12
# テーマ上限は撤廃（リーダーを189日RS上位から純粋に採用・同一テーマに偏り得る）
CHIP_CAP = 8                   # max chips shown per setup/state list (rest folded to +N件)
RS_LB = 189                    # ranking lookback (trading days) ≒9ヶ月モメンタム (研究で確定の最適)
CHART_LB = 504                 # 全トレンドグラフの表示期間を統一（≒2年・エクイティは別）
DVOL_FLOOR = 10e6              # 出来高金額フロア: 20日平均$vol≥$10M (取れる中型+/小型蜃気楼を除外・確定値)
ALLOC = (70, 30, 0)            # 個別 / レバ / 現金 (確定 2026-07-02)
# industries excluded from sector-RS (binary-event noise); editable blacklist
SECTOR_BLACKLIST_KEYS = ("biotech", "pharmaceutic", "drug")

# ----------------------------------------------------------------------------- inputs
def load_inputs(use_cache=True):
    # BOM除去(utf-8-sig)＋列名ゆらぎ吸収: Ticker/Symbol/ticker/symbol いずれでも読む
    rows = list(csv.DictReader(open(UNIVERSE_CSV, encoding="utf-8-sig")))
    if not rows:
        raise SystemExit(f"[FATAL] universe CSV が空です: {UNIVERSE_CSV}")
    cols0 = {c.lower().strip(): c for c in rows[0].keys()}
    # 英語列名 + TradingView日本語エクスポート(シンボル/名称)の両対応
    tcol = (cols0.get("ticker") or cols0.get("symbol") or cols0.get("yf_ticker")
            or cols0.get("シンボル") or cols0.get("ティッカー") or cols0.get("銘柄"))
    ncol = (cols0.get("name") or cols0.get("company") or cols0.get("description")
            or cols0.get("名称") or cols0.get("銘柄名"))
    if not tcol:
        raise SystemExit(f"[FATAL] universe CSV にティッカー列(Ticker/Symbol/シンボル)が見つかりません。実際の列={list(rows[0].keys())}")
    names = {}
    order = []
    for r in rows:
        b = (r.get(tcol) or "").strip()
        if not b:
            continue
        names[b] = (r.get(ncol) or "").strip() if ncol else ""
        order.append(b)
    if not order:
        raise SystemExit(f"[FATAL] universe から銘柄を1つも読めませんでした(列={list(rows[0].keys())}, 行数={len(rows)})")
    # --- ユニバース整形: TradingViewエクスポートの不適格銘柄を除去 ---
    #   ① 優先株/特殊記号(JPM/PM等・yfinance非対応)  ② 優先株/ワラント/権利/ユニット(名称)
    #   ③ 重複クラス株(同一時価総額)は出来高$最大の1つだけ残す(GOOGL残/GOOG除外)
    #   ※ADR(TSM/ASML)とDepository ADR単体は残す。BRK.B等の'.'はyfで'-'変換済み。
    import re as _re, math as _math
    ccol = cols0.get("時価総額") or cols0.get("market cap") or cols0.get("mktcap")
    vcol = cols0.get("出来高, 1日") or cols0.get("出来高") or cols0.get("volume")
    pcol = cols0.get("価格") or cols0.get("price") or cols0.get("close")
    scol = cols0.get("セクター") or cols0.get("sector")
    def _num(r, c):
        try: return float(r.get(c, "") or "nan")
        except Exception: return float("nan")
    row_by_t = {}
    for r in rows:
        tt = (r.get(tcol) or "").strip()
        if tt: row_by_t[tt] = r
    _pfd = _re.compile(r"\bPfd\b|Preferred|Warrant|\bRight(s)?\b|\bUnit(s)?\b|Subordinated Notes", _re.I)
    # 小型バイオ除外: ヘルスケア系セクター かつ 時価総額<$100億 = 投機的小型創薬/バイオ。
    #   大手ヘルスケア(LLY/JNJ/ISRG/VRTX等 $100億超)は残す(モメンタムで来れば拾う)。思想: テック主導の順張り。
    _HC = ("ヘルスケアテクノロジー", "ヘルスケアサービス")
    _BIO_CAP = 10e9
    d_bio = 0
    survivors = []
    for b in order:
        if "/" in b or " " in b:        # 優先株・特殊記号
            continue
        r = row_by_t.get(b, {})
        nm = (r.get(ncol) or "") if ncol else ""
        if nm and _pfd.search(nm):      # 優先株/ワラント/権利/ユニット
            continue
        if scol:                        # 小型バイオ除外
            sec = (r.get(scol) or "").strip()
            mc_ = _num(r, ccol)
            if sec in _HC and not _math.isnan(mc_) and mc_ < _BIO_CAP:
                d_bio += 1; continue
        survivors.append(b)
    # 重複クラス株: 時価総額でグループ化し出来高$最大のみ残す
    if ccol:
        from collections import defaultdict as _dd
        grp = _dd(list); singles = []
        for b in survivors:
            r = row_by_t.get(b, {}); mc = _num(r, ccol)
            (grp[round(mc)].append(b) if not _math.isnan(mc) else singles.append(b))
        cleaned = list(singles)
        for mc, g in grp.items():
            if len(g) == 1:
                cleaned.append(g[0]); continue
            def _dollar_vol(b):
                r = row_by_t.get(b, {})
                dv = _num(r, vcol) * _num(r, pcol) if (vcol and pcol) else 0
                return dv if not _math.isnan(dv) else 0
            cleaned.append(sorted(g, key=_dollar_vol, reverse=True)[0])
        # 元の順序を保つ
        keep_set = set(cleaned)
        survivors = [b for b in survivors if b in keep_set]
    dropped_n = len(order) - len(survivors)
    order = survivors
    names = {b: names.get(b, "") for b in order}
    sys.stderr.write(f"[universe] 整形: {dropped_n}除外 → {len(order)}銘柄(優先株/特殊記号/重複クラス株/小型バイオ{d_bio}を除去)\n")
    sj = json.load(open(SECTOR_JSON))
    s2i = sj.get("s2i", {})            # symbol -> industry (EN)
    s2t = sj.get("s2t", {})            # symbol -> [theme, microtheme]
    e2j = sj.get("e2j", {})            # industry EN -> JA
    if use_cache and os.path.exists(CACHE):
        pk = pickle.load(open(CACHE, "rb"))
    else:
        pk = fetch_live(order)          # CI path: no pre-existing cache
    return names, order, s2i, s2t, e2j, pk["W"], pk["macro"], pk["asof"]

# ----------------------------------------------------------------------------- live fetch (CI)
MACRO_TICKERS = ["^VIX", "^VIX3M", "^VVIX", "^VXN", "QQQ", "QQQE", "SPY", "HYG", "LQD",
                 "RSP", "IWM", "^TNX", "^FVX", "^TYX",
                 # equal-weight sector ETFs (Invesco) for market-representative sector RS
                 "RSPN", "RSPT", "RSPF", "RSPM", "RSPU", "RSPD",
                 "RSPH", "RSPR", "RSPS", "RSPG", "RSPC",
                 # sentiment sleeve: tail-hedge index + 3x lever pairs (crowd heat)
                 "^SKEW", "TQQQ", "SQQQ", "SOXL", "SOXS",
                 # leverage-sleeve env: semis index (trend/vol) + semis ETF (RRG)
                 "SOXX", "SMH"]

def _extract(df, tickers, minbars=30):
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    multi = isinstance(df.columns, pd.MultiIndex)
    need = ["Open", "High", "Low", "Close", "Volume"]
    for t in tickers:
        try:
            sub = df[t] if multi else df
            if sub is None or sub.dropna(how="all").empty:
                continue
            if not all(c in sub.columns for c in need):
                continue
            s = sub[need].dropna(how="all")
            if len(s) < minbars:
                continue
            out[t] = s
        except Exception:
            continue
    return out

def fetch_live(order, period="3y", chunk=100, retries=3):
    """Fetch the full universe + macro live (GitHub Actions path, no cache).
    Mirrors the resumable fetch but in one process. Universe is keyed by base
    ticker; '/' tickers are skipped (yfinance chokes on them)."""
    import yfinance as yf
    # order(load_inputsで列名・BOM吸収済み)をそのまま使う。CSV再読込はしない。
    # yfinance対応: '.'→'-'(BRK.B→BRK-B)、'/'含みはスキップ。
    pairs = []                                   # (base, yf_symbol)
    for b in order:
        b = (b or "").strip()
        if not b or "/" in b:
            continue
        y = b.replace(".", "-")
        pairs.append((b, y))
    y2b = {y: b for b, y in pairs}   # yf_symbol(-) -> base(.)
    yfs = [y for _, y in pairs]
    sys.stderr.write("[fetch_live] universe=%d, fetching in chunks of %d...\n" % (len(pairs), chunk))

    store = {}
    for i in range(0, len(yfs), chunk):
        ch = yfs[i:i + chunk]
        for attempt in range(retries):
            try:
                df = yf.download(ch, period=period, progress=False, auto_adjust=True,
                                 group_by="ticker", threads=True)
                got = _extract(df, ch)
                store.update(got)
                missing = [t for t in ch if t not in store]
                # one retry pass only for the still-missing names (handles partial 429s)
                if missing and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                break
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))      # exponential-ish backoff
                    continue
                sys.stderr.write("  chunk err (gave up): %s\n" % repr(e)[:80])
        sys.stderr.write("  %d/%d  have=%d\n" % (min(i + chunk, len(yfs)), len(yfs), len(store)))

    def wide(field):
        cols = {y2b.get(y, y): df[field] for y, df in store.items()}
        return pd.DataFrame(cols).sort_index()
    W = {f: wide(f) for f in ["Open", "High", "Low", "Close", "Volume"]}

    sys.stderr.write("[fetch_live] fetching macro...\n")
    macro = {}
    try:
        md = yf.download(MACRO_TICKERS, period=period, progress=False,
                         auto_adjust=True, group_by="ticker", threads=True)
        macro = _extract(md, MACRO_TICKERS, minbars=20)
    except Exception:
        pass
    for m in [x for x in MACRO_TICKERS if x not in macro]:   # per-ticker fallback
        try:
            macro.update(_extract(yf.download([m], period=period, progress=False,
                                              auto_adjust=True), [m], minbars=20))
        except Exception:
            pass
    sys.stderr.write("[fetch_live] universe cols=%d  macro=%d/%d (VVIX=%s VIX3M=%s)\n" % (
        W["Close"].shape[1], len(macro), len(MACRO_TICKERS),
        "^VVIX" in macro, "^VIX3M" in macro))
    return {"W": W, "macro": macro, "asof": str(pd.Timestamp.now("UTC"))}

def theme_of(t, s2t):
    v = s2t.get(t)
    if isinstance(v, list) and v:
        return v[0]
    if isinstance(v, str) and v.strip():
        return v.strip()
    return "その他"

def subtheme_of(t, s2t, fallback="その他"):
    """Specific sub-theme (量子/メモリ/AI GPU等). Falls back to `fallback` when absent."""
    v = s2t.get(t)
    if isinstance(v, list) and len(v) >= 2 and v[1] and v[1] not in ("?", ""):
        return v[1]
    return fallback

# ----------------------------------------------------------------------------- per-ticker metrics
def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def weekly_sar_bullish(h, l, c):
    """Wilder Parabolic SAR on W-FRI weekly bars. Return True if current bar bullish."""
    df = pd.DataFrame({"High": h, "Low": l, "Close": c}).dropna()
    if len(df) < 15:
        return np.nan
    w = df.resample("W-FRI").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()
    if len(w) < 10:
        return np.nan
    H = w["High"].values; L = w["Low"].values
    af0, step, afmax = 0.02, 0.02, 0.20
    up = w["Close"].values[1] >= w["Close"].values[0]
    sar = L[0] if up else H[0]
    ep = H[0] if up else L[0]
    af = af0
    for i in range(1, len(w)):
        prev = sar
        sar = prev + af * (ep - prev)
        if up:
            sar = min(sar, L[i-1], L[i-2] if i >= 2 else L[i-1])
            if H[i] > ep:
                ep = H[i]; af = min(af + step, afmax)
            if L[i] < sar:
                up = False; sar = ep; ep = L[i]; af = af0
        else:
            sar = max(sar, H[i-1], H[i-2] if i >= 2 else H[i-1])
            if L[i] < ep:
                ep = L[i]; af = min(af + step, afmax)
            if H[i] > sar:
                up = True; sar = ep; ep = H[i]; af = af0
    return bool(up)

def weinstein_stage(c):
    """週足×30週MAのステージ判定（1=底固め/移行、2=上昇、3=天井圏、4=下降）。
    判定: 価格が30週MAの上か下 × 30週MAの向き（4週前比）。
    ステージ2内は「ベース数」を概算（高値から8%以上・4週以上の調整→新高値で1本消化）。"""
    try:
        w = c.resample("W-FRI").last().dropna()
    except Exception:
        return None
    if len(w) < 36:
        return None
    ma = w.rolling(30).mean()
    n = len(w)
    st = [0] * n
    for i in range(n):
        mi = ma.iloc[i]
        if i < 30 or mi != mi:
            continue
        rising = mi >= float(ma.iloc[i - 4]) if i >= 34 else True
        above = float(w.iloc[i]) > float(mi)
        st[i] = 2 if (above and rising) else 1 if above else 3 if rising else 4
    cur = st[-1]
    if cur == 0:
        return None
    k = 0
    for i in range(n - 1, -1, -1):
        if st[i] == cur:
            k += 1
        else:
            break
    base, forming = None, False
    if cur == 2:
        i0 = n - k
        peak = float(w.iloc[i0]); base = 0; inb = False; bw = 0
        for i in range(i0, n):
            px = float(w.iloc[i])
            if px >= peak:
                if inb and bw >= 4:
                    base += 1
                inb, bw, peak = False, 0, px
            else:
                if px / peak - 1 <= -0.08:
                    inb = True
                if inb:
                    bw += 1
        forming = bool(inb and bw >= 4)
    return dict(wst=int(cur), wstw=int(k), wsb=(int(base) if base is not None else None), wsbf=forming)

def guard_last_bar(W):
    """A5/当日部分バー対策: 直近バーの銘柄数が「20日中央値の50%未満」なら最終バーを捨てて前日で計算。
       取得途中の部分バー(6/18事故)やザラ場中実行での未確定足がclose/RS/SAR/21EMAに混入するのを構造的に防ぐ。"""
    C = W.get("Close")
    if C is None or getattr(C, "shape", (0,))[0] < 25:
        return W
    try:
        cnt = C.notna().sum(axis=1)
        med = float(cnt.iloc[-21:-1].median())
        if med > 0 and float(cnt.iloc[-1]) < 0.5 * med:
            sys.stderr.write("[guard] 最終バー %s は銘柄数 %d < 50%%×中央値 %.0f → 除外し前日で計算\n"
                             % (str(C.index[-1].date()), int(cnt.iloc[-1]), med))
            return {k: (v.iloc[:-1] if hasattr(v, "iloc") else v) for k, v in W.items()}
    except Exception as e:
        sys.stderr.write("[guard] last-bar check failed: %r\n" % repr(e)[:80])
    return W

def compute_metrics(W, order, s2i=None):
    C, O, H, L, V = W["Close"], W["Open"], W["High"], W["Low"], W["Volume"]
    idx = C.index
    recs = []
    for t in order:
        if t not in C.columns:
            continue
        c = C[t].dropna()
        if len(c) < 60:
            continue
        h = H[t].reindex(c.index); l = L[t].reindex(c.index); v = V[t].reindex(c.index)
        close = c.iloc[-1]; prev = c.iloc[-2] if len(c) >= 2 else np.nan
        sma50  = c.rolling(50).mean().iloc[-1]  if len(c) >= 50  else np.nan
        sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else np.nan
        sma21  = c.iloc[-21:].mean()
        ema21  = ema(c, 21).iloc[-1]
        ret63  = close / c.iloc[-64] - 1 if len(c) >= 64 else np.nan
        ret189 = close / c.iloc[-190] - 1 if len(c) >= 190 else np.nan         # 189d(≒9mo) momentum — PRIMARY 選定指標
        ret189_l5 = c.iloc[-6] / c.iloc[-195] - 1 if len(c) >= 195 else np.nan   # 189d momentum as of ~5営業日前 (RSランクΔ用)
        ret63_l1 = c.iloc[-22] / c.iloc[-85] - 1 if len(c) >= 85 else np.nan   # 63d RS as of ~21d ago(1ヶ月前)
        ret63_l2 = c.iloc[-43] / c.iloc[-106] - 1 if len(c) >= 106 else np.nan # 63d RS as of ~42d ago
        ret63_w1 = c.iloc[-6] / c.iloc[-69] - 1 if len(c) >= 69 else np.nan    # 63d RS as of ~5d ago(先週)
        ret63_w2 = c.iloc[-11] / c.iloc[-74] - 1 if len(c) >= 74 else np.nan   # 63d RS as of ~10d ago(2週間前)
        ret21  = close / c.iloc[-22] - 1 if len(c) >= 22 else np.nan
        ret20  = close / c.iloc[-21] - 1 if len(c) >= 21 else np.nan
        ret5   = close / c.iloc[-6]  - 1 if len(c) >= 6  else np.nan
        lo20d  = float(c.iloc[-21:-1].min()) if len(c) >= 21 else np.nan   # 前日までの20日安値（当日除く）
        lo20_break = bool(close <= lo20d) if lo20d == lo20d else False     # 急落局面: 20日安値割れ
        lo10   = float(c.iloc[-10:].min()) if len(c) >= 10 else np.nan     # 10日安値（トレール用・終値ベース）
        # セリングクライマックス(投げ)= 直近5日にRVOL≥2.5 かつ 日足-5%超 → 売り手枯渇で解禁
        capit5 = False
        try:
            if len(c) >= 55:
                r1_5 = c.pct_change().iloc[-5:]
                vr_5 = (v.reindex(c.index) / v.reindex(c.index).rolling(50).mean()).iloc[-5:]
                capit5 = bool(((r1_5 < -0.05) & (vr_5 >= 2.5)).any())
        except Exception:
            capit5 = False
        hi40   = h.iloc[-40:].max()                       # procedure HIGH_LB=40
        pb     = close / hi40 - 1 if hi40 and not np.isnan(hi40) else np.nan
        adr    = float((h.iloc[-20:] / l.iloc[-20:] - 1).mean())
        maxabs1d = float(c.pct_change().iloc[-200:].abs().max()) if len(c) >= 2 else np.nan  # A1: 分割/データ異常検知
        win = c.iloc[-252:] if len(c) >= 30 else c
        hi52 = win.max(); dist52 = close / hi52 - 1
        lo52 = win.min()
        pos52 = (close - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else np.nan
        vol = v.iloc[-1]; vol20 = v.rolling(20).mean().iloc[-1] if len(v) >= 20 else np.nan
        vol50 = v.iloc[-50:].mean() if len(v) >= 50 else np.nan
        rvol = float(vol / vol50) if vol50 and not np.isnan(vol50) and vol50 > 0 else np.nan
        vol10 = v.iloc[-10:].mean() if len(v) >= 10 else np.nan          # 出来高の枯れ: 直近10日平均/50日平均
        vdry = float(vol10 / vol50) if (vol50 and vol50 > 0 and not np.isnan(vol50) and not np.isnan(vol10)) else np.nan
        dvol = close * (vol20 if not np.isnan(vol20) else vol)
        # bollinger width (20) + its 126d percentile (vol contraction)
        m20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
        bbw_series = (4 * sd20) / m20
        bbw = bbw_series.iloc[-1]
        tailbw = bbw_series.dropna().iloc[-126:]
        bbw_pct = (tailbw < bbw).mean() * 100 if len(tailbw) >= 20 else np.nan
        sar_bull = weekly_sar_bullish(h, l, c)
        wsx = weinstein_stage(c) or {}
        recs.append(dict(
            t=t, close=close, prev=prev,
            pchg=(close/prev - 1) if prev and not np.isnan(prev) else np.nan,
            sma50=sma50, sma200=sma200, ema21=ema21, sma21=sma21,
            vs50=(close/sma50 - 1) if sma50 and not np.isnan(sma50) else np.nan,
            vs200=(close/sma200 - 1) if sma200 and not np.isnan(sma200) else np.nan,
            dma21=(close/sma21 - 1) if sma21 and not np.isnan(sma21) else np.nan,
            dma50=(close/sma50 - 1) if sma50 and not np.isnan(sma50) else np.nan,
            hi40=hi40, pb=pb, adr=adr, ret5=ret5, ret20=ret20, rvol=rvol, vdry=vdry, lo20_break=lo20_break, capit5=capit5,
            maxabs1d=maxabs1d, lo10=lo10,
            ret63=ret63, ret189=ret189, ret189_l5=ret189_l5, ret21=ret21, hi52=hi52, dist52=dist52, pos52=pos52,
            ret63_l1=ret63_l1, ret63_l2=ret63_l2, ret63_w1=ret63_w1, ret63_w2=ret63_w2,
            vol=vol, vol20=vol20, dvol=dvol,
            volx=(vol/vol20) if vol20 and not np.isnan(vol20) and vol20 > 0 else np.nan,
            bbw=bbw, bbw_pct=bbw_pct, sar_bull=sar_bull,
            wst=wsx.get("wst"), wstw=wsx.get("wstw"),
            wsb=wsx.get("wsb"), wsbf=(1 if wsx.get("wsbf") else 0),
        ))
    df = pd.DataFrame(recs).set_index("t")
    # A1 分割アーティファクト・ガード: 直近200日の単日変化率>150%はスプリット/データ異常のゴースト
    #   （CHRD +80,376% 等）。RSランキングから除外＝RS=NaNで選定・リーダー判定から自然脱落。
    df["split_suspect"] = (df["maxabs1d"] > 1.50).fillna(False)
    # A2 プール内RS: RSは「非サスペクト × 株価≥$5 × 20日$出来高≥$10M」内の順位で付ける。
    #   RS85 の意味が微小株で希釈されるのを解消＝リーダー判定/選定の母集団を統一（バグ⑤も解消）。
    #   プール外は RS=NaN → 選定・リーダーから自然脱落。順位の相対順は保たれるので採用12の並びは不変。
    _pool = (~df["split_suspect"]) & (df["close"] >= 5) & (df["dvol"] >= DVOL_FLOOR)
    df["rs_pool"] = _pool
    def _rk(col):                                         # トレーダブル母集団内でのみ百分位付け
        return df[col].where(_pool).rank(pct=True) * 100
    # RS percentile from 63d return (0-100), instantaneous for monitoring + 短期スキャナー
    df["rs"] = _rk("ret63")
    # 189d RS percentile (0-100) — PRIMARY selection metric (研究で確定: 9ヶ月モメンタムが最適)
    df["rs189"] = _rk("ret189")
    # RSランクΔ: 約1週間前の189日RSランクとの差（ローテーション初動の検知・表示のみ）
    df["rs189_d"] = df["rs189"] - (df["ret189_l5"].where(_pool).rank(pct=True) * 100)
    # smoothed 63d RS = mean of 3 RS-percentile snapshots (今/~21d前/~42d前) — 参考表示のみ(選定には未使用)
    r0 = df["ret63"].where(_pool).rank(pct=True)
    r1 = df["ret63_l1"].where(_pool).rank(pct=True)
    r2 = df["ret63_l2"].where(_pool).rank(pct=True)
    df["rs_smooth"] = pd.concat([r0, r1, r2], axis=1).mean(axis=1, skipna=True) * 100
    df["rs_l1"] = r1 * 100          # 約21日前(1ヶ月前)の63日RSランク
    df["rs_w1"] = _rk("ret63_w1") if "ret63_w1" in df else df["rs_l1"]  # 先週(~5d前)
    df["rs_w2"] = _rk("ret63_w2") if "ret63_w2" in df else df["rs_l1"]  # 2週間前(~10d前)
    # 業種内相対: 銘柄の63日リターン − 自業種(適格銘柄)の63日リターン平均。
    # <−0.20(自業種より20%以上出遅れ)=「出遅れ株」→選定除外(検証: 図の相場サイクル理論に整合・検問5/6通過)。
    df["sec_rel"] = np.nan
    try:
        if s2i:
            elig = (df["sma50"] > df["sma200"]) & (df["dvol"] >= DVOL_FLOOR) & (df["close"] >= 5)
            ind = pd.Series({t: s2i.get(t, "NA") for t in df.index}).reindex(df.index)
            r63v = df["ret63"].where(elig)
            sec_mean = r63v.groupby(ind).transform("mean")
            df["sec_rel"] = df["ret63"] - sec_mean          # >0=業種内で強い(先導) / <0=出遅れ
    except Exception as e:
        print("[warn] sec_rel calc failed:", e)
        df["sec_rel"] = np.nan
    return df, idx[-1]

# ----------------------------------------------------------------------------- market-cap tiers
def cap_tier(mc):
    """Return (key, label, rank). <1B=極小(板薄), 1-3B=小型, 3-10B=中型, 10-100B=大型, >100B=超大型."""
    if mc is None or (isinstance(mc, float) and np.isnan(mc)) or mc <= 0:
        return ("none", "—", -1)
    b = mc / 1e9
    if b < 1:   return ("micro", "極小", 0)
    if b < 3:   return ("small", "小型", 1)
    if b < 10:  return ("mid",   "中型", 2)
    if b < 100: return ("large", "大型", 3)
    return ("mega", "超大型", 4)

def fmt_cap(mc):
    if mc is None or (isinstance(mc, float) and np.isnan(mc)) or mc <= 0:
        return "—"
    b = mc / 1e9
    if b >= 1000: return f"${b/1000:.2f}T"
    if b >= 1:    return f"${b:.1f}B"
    return f"${mc/1e6:.0f}M"

def load_market_caps(valid, live):
    """Read committed mktcap.json → {ticker: marketCap}. In live mode, refresh
    missing entries (bounded per run) and write back. Degrades gracefully if absent."""
    import json
    paths = [os.environ.get("V38_MKTCAP_JSON"),
             os.path.join(os.path.dirname(CACHE), "mktcap.json"),
             "/mnt/project/mktcap.json", "mktcap.json"]
    path = next((p for p in paths if p and os.path.exists(p)), None)
    cache = {}
    if path:
        try: cache = json.load(open(path))
        except Exception: cache = {}
    if live:
        try:
            import yfinance as yf, time
            todo = [t for t in valid if t not in cache][:400]   # bounded per build
            t0 = time.time()
            for t in todo:
                if time.time() - t0 > 240:
                    break
                try:
                    mc = yf.Ticker(t).info.get("marketCap")
                    cache[t] = mc if isinstance(mc, (int, float)) else None
                except Exception:
                    cache[t] = None
            outp = path or os.environ.get("V38_MKTCAP_JSON") or os.path.join(os.path.dirname(CACHE), "mktcap.json")
            try: json.dump(cache, open(outp, "w"))
            except Exception: pass
        except Exception:
            pass
    return {t: cache.get(t) for t in valid}

# ----------------------------------------------------------------------------- Market-status engine (C)
STATUS_DEF = [
    # key, weight, lo, hi, group  (lo->0, hi->1; VIX family は hi<lo = 反転)
    # --- トレンド: 時価加重(megacap) + 等加重(broad market) を並列に ---
    ("qqq_50",   8, -0.03, 0.10, "trend"),   # 時価加重NDX 短期
    ("qqq_200",  6, -0.05, 0.10, "trend"),   # 時価加重NDX 長期
    ("spy_200",  5, -0.05, 0.10, "trend"),   # 時価加重S&P 長期
    ("rsp_50",   8, -0.03, 0.07, "trend"),   # 等加重S&P トレンド=平均的銘柄が上か(短期)
    ("rsp_200",  5, -0.05, 0.10, "trend"),   # 等加重S&P トレンド(長期)
    ("qqqe_50",  6, -0.03, 0.09, "trend"),   # 等加重NDX トレンド
    # --- ボラ ---
    ("vix",     12, 25.0, 13.0,  "vol"),
    ("vix_ratio", 6, 1.05, 0.95, "vol"),
    ("vvix",     4, 120.0, 80.0, "vol"),
    # --- クレジット ---
    ("hyglqd_20", 10, 0.98, 1.02, "credit"),
    ("hyglqd_5d",  7, -0.02, 0.02, "credit"),
    # --- ブレッドス(乖離・比率) ---
    ("rsp_spy_20",  8, 0.98, 1.02, "breadth"),   # 等加重S&P / 時価加重 の細り
    ("qqqe_qqq_20", 7, 0.98, 1.02, "breadth"),   # 等加重NDX / 時価加重 の細り
    ("iwm_spy_20",  8, 0.98, 1.02, "breadth"),   # 小型 / 大型
]
# 群合計: trend 38 / vol 22 / credit 17 / breadth 23 = 100

def clamp01(x):
    return np.clip(x, 0.0, 1.0)

# A-1/★2 共有：VIX/VVIX の分位適応バンド（トレーリング約1年）
VOL_WIN, VOL_MINP = 252, 120

def mri_frame(macro):
    cl = lambda k: macro[k]["Close"] if k in macro else None
    have = {k: (cl(k) is not None) for k in
            ["QQQ","QQQE","SPY","^VIX","^VIX3M","^VVIX","HYG","LQD","RSP","IWM"]}
    base = pd.DataFrame({k: cl(k) for k in ["QQQ","QQQE","SPY","HYG","LQD","RSP","IWM"] if cl(k) is not None})
    base["VIX"] = cl("^VIX")
    if cl("^VIX3M") is not None: base["VIX3M"] = cl("^VIX3M")
    if cl("^VVIX") is not None:  base["VVIX"]  = cl("^VVIX")
    base = base.sort_index().ffill().dropna(how="any")
    qqq, spy = base["QQQ"], base["SPY"]
    hyglqd = base["HYG"] / base["LQD"]
    rspspy = base["RSP"] / base["SPY"]
    iwmspy = base["IWM"] / base["SPY"]
    vals = pd.DataFrame(index=base.index)
    vals["qqq_50"]  = qqq / qqq.rolling(50).mean() - 1
    vals["qqq_200"] = qqq / qqq.rolling(200).mean() - 1
    vals["spy_50"]  = spy / spy.rolling(50).mean() - 1
    vals["spy_200"] = spy / spy.rolling(200).mean() - 1
    vals["vix"]     = base["VIX"]
    vals["vix_ratio"] = (base["VIX"] / base["VIX3M"]) if "VIX3M" in base else np.nan
    vals["vvix"]    = base["VVIX"] if "VVIX" in base else np.nan
    vals["hyglqd_20"] = hyglqd / hyglqd.rolling(20).mean()
    vals["hyglqd_5d"] = hyglqd / hyglqd.shift(5) - 1
    vals["rsp_spy_20"] = rspspy / rspspy.rolling(20).mean()
    vals["iwm_spy_20"] = iwmspy / iwmspy.rolling(20).mean()
    if "QQQE" in base:                       # P4: 等加重ナスダック(QQQE)/QQQ の細り検知
        qqqeqqq = base["QQQE"] / base["QQQ"]
        vals["qqqe_qqq_20"] = qqqeqqq / qqqeqqq.rolling(20).mean()
    else:
        vals["qqqe_qqq_20"] = np.nan
    # 等加重指数そのもののトレンド（broad market が上向きか）— トレンド群へ
    if "RSP" in base:
        rsp_px = base["RSP"]
        vals["rsp_50"]  = rsp_px / rsp_px.rolling(50).mean() - 1
        vals["rsp_200"] = rsp_px / rsp_px.rolling(200).mean() - 1
    else:
        vals["rsp_50"] = np.nan; vals["rsp_200"] = np.nan
    if "QQQE" in base:
        qqqe_px = base["QQQE"]
        vals["qqqe_50"] = qqqe_px / qqqe_px.rolling(50).mean() - 1
    else:
        vals["qqqe_50"] = np.nan

    dropped = []
    active = []
    for key, w, lo, hi, grp in STATUS_DEF:
        if vals[key].dropna().empty:
            dropped.append(key)
        else:
            active.append((key, w, lo, hi, grp))
    tot_w = sum(w for _, w, _, _, _ in active)
    # A-1: VIX/VVIX は固定絶対値ではなくトレーリング約1年の分位でバンドを適応化
    #      （高ボラ常態化でvol柱が万年弱気になるのを防ぐ・反転方向は維持）。
    #      生値 vals["vix"]/["vvix"] は表示用に保持し、スコアだけ分位ベースに置換。
    def _score_series(key, lo, hi):
        if key in ("vix", "vvix"):
            s = vals[key]
            q_bear = s.rolling(VOL_WIN, min_periods=VOL_MINP).quantile(0.85)  # 高ボラ端→score0
            q_bull = s.rolling(VOL_WIN, min_periods=VOL_MINP).quantile(0.15)  # 低ボラ端→score1
            return clamp01((s - q_bear) / (q_bull - q_bear))
        return clamp01((vals[key] - lo) / (hi - lo))
    # status time series (renormalized to 100 over active weights)
    contrib = pd.DataFrame(index=vals.index)
    score01 = {}
    for key, w, lo, hi, grp in active:
        score01[key] = _score_series(key, lo, hi)
        contrib[key] = w * score01[key]
    mri = contrib.sum(axis=1) / tot_w * 100.0
    mri = mri.dropna()
    # latest breakdown
    last = vals.iloc[-1]
    breakdown = []
    for key, w, lo, hi, grp in active:
        sc = score01[key].iloc[-1]
        sc01 = float(sc) if pd.notna(sc) else 0.5
        breakdown.append(dict(key=key, w=w, group=grp, raw=float(last[key]),
                              pts=w * sc01, ptsmax=w, frac=sc01))
    return mri, breakdown, dropped, active, vals

def mri_auxiliary(mri, vals, metrics):
    cur = float(mri.iloc[-1])
    ma10 = mri.rolling(10).mean()
    slope_dir = "→"
    if len(ma10.dropna()) >= 3:
        d = ma10.iloc[-1] - ma10.iloc[-3]
        slope_dir = "↑" if d > 0.4 else ("↓" if d < -0.4 else "→")
    last = vals.iloc[-1]
    # ★2: VIX/VVIX は A-1スコアと同じ分位基準でフラグ点灯（固定20/100だと高ボラ常態化で万年点灯）
    def qx(k):
        try:
            return float(vals[k].rolling(VOL_WIN, min_periods=VOL_MINP).quantile(0.85).iloc[-1])
        except Exception:
            return np.nan
    vix_hi, vvix_hi = qx("vix"), qx("vvix")
    # 11 bearish conditions (labeled, for display of which are lit) — all independent of the status score itself
    bvals = [
        ("QQQ<50MA",     last["qqq_50"]  < 0),
        ("QQQ<200MA",    last["qqq_200"] < 0),
        ("SPY<50MA",     last["spy_50"]  < 0),
        ("SPY<200MA",    last["spy_200"] < 0),
        ("VIX高位(1年85%ile超)",  (last["vix"] > vix_hi) if vix_hi == vix_hi else False),
        ("VIX逆転(>3M)",  last.get("vix_ratio", np.nan) > 1.00),
        ("VVIX高位(1年85%ile超)", (last.get("vvix", np.nan) > vvix_hi) if vvix_hi == vvix_hi else False),
        ("クレジット悪化", last["hyglqd_20"] < 1.0),
        ("クレジット5日↓", last["hyglqd_5d"] < 0),
        ("ブレッドス↓",   last["rsp_spy_20"] < 1.0),
        ("小型株劣後",    last["iwm_spy_20"] < 1.0),
    ]
    bear_flags = [(lab, bool(v == True)) for lab, v in bvals]
    bear_n = int(sum(1 for _, v in bear_flags if v))
    # A-3: ヘッドラインを約3日平滑（バンドのラベル判定用・数字自体は生のcurを表示）
    hl = float(mri.tail(3).mean()) if len(mri) >= 1 else cur
    # peak decline from trailing 20d status high
    hi20 = mri.iloc[-20:].max() if len(mri) >= 5 else cur
    drop = hi20 - cur
    if drop < 3:    peak = "通常"
    elif drop < 7:  peak = "注意"
    elif drop < 12: peak = "減速"
    else:           peak = "深押し"
    return dict(cur=cur, hl=hl, slope=slope_dir, bear_n=bear_n, bear_flags=bear_flags,
                peak=peak, drop=drop, hi20=hi20)

def mri_band(v):
    if v >= 75: return ("強気（過熱・反落注意⚠）", "ovh")
    if v >= 60: return ("強気", "bull")
    if v >= 45: return ("中立", "neu")
    if v >= 30: return ("弱含み", "weak")
    return ("弱気", "bear")

# ----------------------------------------------------------------------------- NQ-SAR signal (leverage sleeve; logic hidden, only color+判定 shown)
# Authoritative source = sar_state.txt (committed by the TradingView->Pipedream
# webhook on every OniMine color flip). Falls back to the OniMine state embedded
# in a local NQ export, then to a safe default.
SAR_STATE_PATH = os.environ.get("V38_SAR_STATE", "sar_state.txt")
NQ_EXPORT_CANDIDATES = [
    os.environ.get("V38_NQ_EXPORT", ""),
    "/mnt/project/CME_MINI_DL_NQ1___1D_3.csv",
    "/mnt/project/CME_MINI_DL_NQ1___1D.csv",
]
# color -> (color label, trend judgment, sub descriptor, css class) — public-facing, logic hidden
# Severity (strong bull -> strong bear): Blue > Green > Yellow > Red
#   2軸FSM: close vs PSAR(0.02/0.02/0.08) = 強気/弱気側。緑黄=移行・青赤=確定。
#   昇格(緑→青/黄→赤)= RSI閾値 + SAR転換から2バー以上 + 反スパイク。降格= 21EMA即時。
SAR_JUDGMENT = {
    "Blue":   ("Blue",   "強い上昇", "継続",     "sar-blue"),
    "Green":  ("Green",  "上昇(中位)", "中立",     "sar-green"),
    "Yellow": ("Yellow", "弱含み",   "警戒",     "sar-yellow"),
    "Red":    ("Red",    "下落",     "回避",     "sar-red"),
}
_SAR_ID2COLOR = {1: "Blue", 2: "Yellow", 3: "Red", 4: "Green"}

def _norm_color(s):
    if not s:
        return None
    s = str(s).strip()
    s = s[:1].upper() + s[1:].lower()
    return s if s in SAR_JUDGMENT else None

def _sar_from_nq():
    """Deep fallback: latest OniMine EXP_STATE_ID from a local NQ export (if present)."""
    for p in NQ_EXPORT_CANDIDATES:
        if p and os.path.exists(p):
            try:
                df = pd.read_csv(p)
                col = [c for c in df.columns if "EXP_STATE_ID" in c]
                if not col:
                    continue
                sid = int(df[col[0]].dropna().iloc[-1])
                return _SAR_ID2COLOR.get(sid)
            except Exception:
                continue
    return None

def _psar(h, l, c, step=0.02, mx=0.20):
    """Wilder Parabolic SAR (AF 0.02 step, 0.20 max)."""
    n = len(c); sar = np.zeros(n); bull = True; af = step; ep = l[0]; sar[0] = l[0]
    for i in range(1, n):
        sar[i] = sar[i-1] + af*(ep - sar[i-1])
        if bull:
            if l[i] < sar[i]:
                bull = False; sar[i] = ep; ep = l[i]; af = step
            elif h[i] > ep:
                ep = h[i]; af = min(af+step, mx)
        else:
            if h[i] > sar[i]:
                bull = True; sar[i] = ep; ep = h[i]; af = step
            elif l[i] < ep:
                ep = l[i]; af = min(af+step, mx)
    return sar

def _onimine_state(C, sar, ema21, rsi):
    """復元したOniMine 4色FSMを系列に適用し最終色を返す（OOS≈96%）。
    2軸: close vs PSAR=強気側(青/緑)/弱気側(黄/赤)。緑黄=移行・青赤=確定。
    昇格= RSI閾値 かつ SAR転換から2バー以上 かつ 反スパイク。降格=21EMA割れ/超えで即時。"""
    n = len(C)
    above = C > sar
    state = "Green" if above[0] else "Yellow"     # ウォームアップ種（1年分で自己補正）
    bsu = bsd = 99                                 # bars since SAR flip up / down
    prev_rsi = None
    for i in range(n):
        bsu = 0 if (i > 0 and above[i] and not above[i-1]) else bsu + 1
        bsd = 0 if (i > 0 and (not above[i]) and above[i-1]) else bsd + 1
        drsi = (rsi[i] - prev_rsi) if prev_rsi is not None else 0.0
        if above[i]:                               # 強気側: 青/緑
            if state == "Blue":
                state = "Green" if C[i] < ema21[i] else "Blue"            # 降格(21EMA割れ)
            else:
                state = "Blue" if (rsi[i] > 52 and bsu >= 2 and drsi <= 3.0) else "Green"
        else:                                      # 弱気側: 黄/赤
            if state == "Red":
                state = "Yellow" if rsi[i] > 50 else "Red"               # 降格: RSI>50 (Pine準拠)
            else:
                state = "Red" if (rsi[i] < 47 and bsd >= 2 and drsi >= -3.0) else "Yellow"
        prev_rsi = rsi[i]
    return state

def _estimate_sar_from_live():
    """ライブNQ=Fから復元FSMでOniMine色を推定（PSAR方向×確信度・OOS≈96%）。失敗時None。
    PSAR(0.02/0.02/0.08)・RSI Wilder14・21EMAの3本でFSMを駆動。"""
    try:
        import yfinance as yf
        df = yf.download("NQ=F", period="1y", interval="1d",
                         auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 60:
            return None
        H, L, C = df["High"].values, df["Low"].values, df["Close"].values
        sar = _psar(H, L, C, step=0.02, mx=0.08)                  # OniMineと同じSAR
        ema21 = df["Close"].ewm(span=21, adjust=False).mean().values
        d = df["Close"].diff()
        up = d.clip(lower=0); dn = -d.clip(upper=0)
        ru = up.ewm(alpha=1/14, adjust=False).mean()              # Wilder RSI14
        rd = dn.ewm(alpha=1/14, adjust=False).mean()
        rsi = (100 - 100/(1 + ru/rd)).values
        return _onimine_state(C, sar, ema21, rsi)
    except Exception:
        return None

def read_sar_state():
    """Return (color, source). file(確定) -> live estimate(推定) -> None(無判定/gray)."""
    for p in [SAR_STATE_PATH, "/mnt/project/sar_state.txt",
              os.path.join(os.path.dirname(CACHE), "sar_state.txt")]:
        if p and os.path.exists(p):
            c = _norm_color(open(p).read())
            if c:
                return c, "file"
    c = _estimate_sar_from_live()
    if c:
        return c, "estimate"
    return None, "none"

# ----------------------------------------------------------------------------- sentiment (群衆温度計・表示専用)
# 原則: センチメントは「極値でのみ」逆張りシグナル。中間帯はノイズ。MRIと同じ思想で
# 固定閾値でなくトレーリング分位でスコア化し、合成0-100を「群衆温度計」として表示する。
# ゲート・銘柄選定には一切関与しない（D柱と同じ表示専用）。II/AAIIは手動参照。
def _roll_pct(s, win=504, minp=120):
    """系列の各時点値の、トレーリングwin内パーセンタイル(0-100)。既定は約2年
    （データがある範囲で自動的に最長化・min_periods到達後から算出）。"""
    s = pd.Series(s).dropna()
    if len(s) < max(minp, 20):
        return pd.Series(dtype=float)
    try:
        return s.rolling(win, min_periods=minp).rank(pct=True) * 100
    except Exception:                                   # 古いpandasフォールバック
        return s.rolling(win, min_periods=minp).apply(
            lambda a: float((a[:-1] <= a[-1]).mean()) * 100, raw=True)

def fetch_fng():
    """CNN Fear & Greed（合成7要素・0-100）＋equity Put/Call の履歴。失敗時{}。"""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0 (v38-dashboard)"})
        d = json.loads(urllib.request.urlopen(req, timeout=12).read())
        def ts(key):
            out = []
            for p in (d.get(key) or {}).get("data", []):
                try:
                    out.append((pd.Timestamp(int(p["x"]), unit="ms").normalize(),
                                float(p["y"])))
                except Exception:
                    continue
            return out
        return {"fng": ts("fear_and_greed_historical"), "pc": ts("put_call_options")}
    except Exception as e:
        sys.stderr.write("[senti] CNN F&G fetch failed: %r\n" % repr(e)[:90])
        return {}

def fetch_naaim():
    """NAAIM Exposure Index（週次・実弾エクスポージャー -200..+200）。CSVリンクをページから発見。失敗時[]。"""
    try:
        import urllib.request, re as _re
        req = urllib.request.Request("https://naaim.org/programs/naaim-exposure-index/",
                                     headers={"User-Agent": "Mozilla/5.0 (v38-dashboard)"})
        page = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
        mm = _re.search(r'href="([^"]+\.csv[^"]*)"', page, _re.I)
        if not mm:
            return []
        url = mm.group(1)
        if url.startswith("/"):
            url = "https://naaim.org" + url
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=12).read()
        rows = []
        for ln in raw.decode("utf-8", "ignore").splitlines()[1:]:
            parts = [x.strip() for x in ln.split(",")]
            if len(parts) < 2:
                continue
            try:
                rows.append((pd.Timestamp(parts[0]).normalize(), float(parts[1])))
            except Exception:
                continue
        rows.sort()
        return rows
    except Exception as e:
        sys.stderr.write("[senti] NAAIM fetch failed: %r\n" % repr(e)[:90])
        return []

def build_sentiment(macro, W, live=True):
    """群衆温度計: レバETF資金熱・パラボリック銘柄率(自前) + F&G・P/C(CNN) + NAAIM。
    各指標をトレーリング分位0-100(高=強欲)に正規化し、利用可能なものの平均を合成。"""
    parts = {}          # key -> 日次percentile系列(0-100)
    rows = []           # 表示行 (label, rawtxt, pct, in_composite, note)
    flags = []          # (label, on) 双方向の極値フラグ
    avail = []

    # ライブ時はセンチメント銘柄だけ5年ヒストリーを追加取得（分位の基準期間を長期化）
    macro = dict(macro)
    if live:
        try:
            import yfinance as yf
            _st = ["TQQQ", "SQQQ", "SOXL", "SOXS", "^SKEW"]
            hist = yf.download(_st, period="5y", progress=False,
                               auto_adjust=True, group_by="ticker", threads=True)
            for _t in _st:
                try:
                    _df = hist[_t].dropna()
                    _cur = macro.get(_t)
                    if len(_df) > (len(_cur) if _cur is not None else 0):
                        macro[_t] = _df
                except Exception:
                    continue
        except Exception:
            pass

    def dv(k):
        d = macro.get(k)
        if d is None or "Volume" not in d:
            return None
        s = (d["Close"] * d["Volume"]).dropna()
        return s if len(s) > 60 else None

    # 1) レバETF資金熱: ブル3x売買代金 / (ブル+ベア3x) の5日平均 → 分位
    try:
        bulls = [x for x in (dv("TQQQ"), dv("SOXL")) if x is not None]
        bears = [x for x in (dv("SQQQ"), dv("SOXS")) if x is not None]
        if bulls and bears:
            b = pd.concat(bulls, axis=1).sum(axis=1)
            s = pd.concat(bears, axis=1).sum(axis=1)
            ratio = (b / (b + s)).rolling(5).mean().dropna()
            p = _roll_pct(ratio)
            if len(p.dropna()):
                parts["lever"] = p
                cur_r, cur_p = float(ratio.iloc[-1]), float(p.dropna().iloc[-1])
                rows.append(("レバETF資金熱", f"ブル比率 {cur_r*100:.0f}%", cur_p, True,
                             "TQQQ+SOXL÷(ブル+ベア3x)売買代金・5日平均"))
                flags.append(("レバ熱 過熱", cur_p >= 90))
                flags.append(("レバ資金 退避", cur_p <= 10))
                avail.append("レバ熱")
    except Exception:
        pass

    # 2) パラボリック銘柄率: 200日線+45%超の銘柄割合（ユニバース） → 分位
    try:
        C = W["Close"]
        ma200 = C.rolling(200, min_periods=200).mean()
        ok = ma200.notna()
        denom = ok.sum(axis=1).replace(0, np.nan)
        par = (((C >= ma200 * 1.45) & ok).sum(axis=1) / denom * 100).dropna()
        p = _roll_pct(par, win=756, minp=60)
        if len(p.dropna()):
            parts["parab"] = p
            cur_r, cur_p = float(par.iloc[-1]), float(p.dropna().iloc[-1])
            rows.append(("パラボリック銘柄率", f"{cur_r:.1f}%", cur_p, True,
                         "200日線から+45%超で走る銘柄の割合（ユニバース）"))
            flags.append(("パラボ乱舞", cur_p >= 90))
            avail.append("パラボ率")
    except Exception:
        pass

    ext = fetch_fng() if live else {}
    # 3) CNN Fear & Greed（それ自体が0-100の強欲スケール）
    fng = ext.get("fng") or []
    if len(fng) >= 30:
        s = pd.Series({d: v for d, v in fng}).sort_index()
        parts["fng"] = s        # 生値がそのまま0-100
        cur = float(s.iloc[-1])
        lab = ("Extreme Greed" if cur >= 75 else "Greed" if cur >= 55 else
               "Neutral" if cur >= 45 else "Fear" if cur >= 25 else "Extreme Fear")
        rows.append(("CNN Fear & Greed", f"{cur:.0f}（{lab}）", cur, True, "7要素合成・CNN公表値"))
        flags.append(("F&G 極端な強欲", cur >= 75))
        flags.append(("F&G 極端な恐怖", cur <= 25))
        avail.append("F&G")

    # 4) Put/Call（equity）: 低いほど強欲 → 分位を反転
    pc = ext.get("pc") or []
    if len(pc) >= 60:
        s = pd.Series({d: v for d, v in pc}).sort_index().rolling(10).mean().dropna()
        p = _roll_pct(s)
        if len(p.dropna()):
            parts["pc"] = 100 - p
            cur_r, cur_p = float(s.iloc[-1]), float(100 - p.dropna().iloc[-1])
            rows.append(("Put/Call（10日平均）", f"{cur_r:.2f}", cur_p, True,
                         "低いほどコール偏重＝強欲（分位反転）"))
            flags.append(("コール偏重 極端", cur_p >= 90))
            avail.append("P/C")

    # 5) NAAIM（実弾。95超=全力ロング常態 / 30割れ=投げ）
    naaim = fetch_naaim() if live else []
    if len(naaim) >= 52:
        s = pd.Series({d: v for d, v in naaim}).sort_index()
        p = _roll_pct(s, win=260, minp=52)          # 週次≒5年分位
        if len(p.dropna()):
            parts["naaim"] = p
            cur_r, cur_p = float(s.iloc[-1]), float(p.dropna().iloc[-1])
            rows.append(("NAAIM エクスポージャー", f"{cur_r:.0f}", cur_p, True,
                         "アクティブ運用者の実際の株式露出（週次）"))
            flags.append(("NAAIM 全力(≥95)", cur_r >= 95))
            flags.append(("NAAIM 投げ(≤30)", cur_r <= 30))
            avail.append("NAAIM")

    # 6) SKEW（参考・合成外）: テールヘッジ需要
    try:
        sk = macro.get("^SKEW")
        if sk is not None:
            s = sk["Close"].dropna()
            p = _roll_pct(s)
            if len(p.dropna()):
                rows.append(("SKEW（参考）", f"{float(s.iloc[-1]):.0f}", float(p.dropna().iloc[-1]),
                             False, "テールリスクの保険需要・解釈が割れるため合成外"))
    except Exception:
        pass

    if not parts:
        return None
    # 合成: 日次に整列してffill→平均
    base_idx = None
    for k in ("parab", "lever"):
        if k in parts:
            base_idx = parts[k].dropna().index
            break
    if base_idx is None:
        base_idx = sorted(set().union(*[set(p.dropna().index) for p in parts.values()]))
        base_idx = pd.DatetimeIndex(base_idx)
    aligned = pd.DataFrame({k: p.reindex(base_idx).ffill() for k, p in parts.items()})
    comp = aligned.mean(axis=1, skipna=True).dropna()
    if not len(comp):
        return None
    cur = float(comp.iloc[-1])
    flags.insert(0, ("群衆 過熱（合成≥85）", cur >= 85))
    flags.insert(1, ("群衆 総悲観（合成≤15）", cur <= 15))
    band = ("過熱🔥" if cur >= 85 else "強欲寄り" if cur >= 65 else
            "中立" if cur >= 35 else "弱気寄り" if cur > 15 else "総悲観🧊")
    ts = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in comp.iloc[-CHART_LB:].items()]
    return dict(cur=cur, band=band, rows=rows, flags=flags, ts=ts, avail=avail)

def _svg_senti(ts):
    """センチメント推移: マーケットステータス推移と同じ幾何・ゾーン塗り（0-100固定・極値のみ着色）。"""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; n = len(ys)
    Wd, Ht, pad = 680, 180, 6
    def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
    def Y(v): return pad + (1 - v/100) * (Ht - 2*pad)
    zones = [(0,15,"#38bdf8"),(15,35,"#22c55e"),(35,65,"#64748b"),(65,85,"#f59e0b"),(85,100,"#ef4444")]
    zr = "".join(f'<rect x="{pad}" y="{Y(z1):.1f}" width="{Wd-2*pad}" '
                 f'height="{max(0.0,Y(z0)-Y(z1)):.1f}" fill="{zc}" opacity="0.07"/>' for z0,z1,zc in zones)
    gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="#1c2533" stroke-width="1"/>'
                 f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g}</text>'
                 for g in (15,50,85))
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i,v in enumerate(ys))
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">{zr}{gl}'
            f'<polyline points="{pts}" fill="none" stroke="#f472b6" stroke-width="2"/>'
            f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="#f472b6"/></svg>')

def _sentiment_card(senti):
    if not senti:
        return ('<div class="card"><h2>センチメント（群衆温度計）</h2>'
                '<div class="sub">データ取得不可（レバETF・CNN F&amp;G・NAAIMのいずれも利用できず）。'
                'II/AAIIは手動参照。</div></div>')
    cur = senti["cur"]
    col = "#fca5a5" if cur >= 85 else "#fdba74" if cur >= 65 else "#9fb0c5" if cur >= 35 else "#7dd3fc" if cur > 15 else "#7ff0a8"
    comp_rows = []
    for lab, raw, pct, in_comp, note in senti["rows"]:
        tag = "" if in_comp else '<span class="sn-ref">参考</span>'
        comp_rows.append(
            f'<div class="mrow"><span class="mk2">{lab}{tag}</span>'
            f'<span class="mraw">{raw}</span>'
            f'<span class="mbar"><i style="width:{max(0,min(100,pct)):.0f}%;background:#f472b6"></i></span>'
            f'<span class="mpts">{pct:.0f}</span></div>'
            f'<div class="sn-note">{note}</div>')
    lit = [l for l, on in senti["flags"] if on]
    off = [l for l, on in senti["flags"] if not on]
    chips = ("".join(f'<span class="bfl on">{l}</span>' for l in lit)
             + "".join(f'<span class="bfl off">{l}</span>' for l in off))
    return (
        f'<div class="card"><h2>センチメント（群衆温度計）</h2>'
        f'<div class="sub">利用ソース: {", ".join(senti["avail"])}・各指標を<b>トレーリング約2年（NAAIMは約5年）</b>の分位0-100（高=強欲）に正規化して平均。'
        f'<b>逆張りが効くのは極値のみ</b>（過熱≥85／総悲観≤15）・中間帯はノイズ。<b>表示専用・ゲート非関与</b></div>'
        + "".join(comp_rows)
        + f'<div class="bflags" style="margin-top:8px">{chips}</div>'
        + f'<div class="chart">{_svg_senti(senti["ts"])}'
        + (f'<div class="cap cap-c"><span style="color:{col};font-weight:700">現在 {cur:.0f}（{senti["band"]}）</span></div>'
           f'{_date_axis(senti["ts"])}' if senti.get("ts") else "")
        + '</div>'
        f'<div class="note">過熱＝即売りではない（強いトレンド中の過熱は正常）。実用は2つだけ: '
        f'<b>総悲観×FTD点灯＝仕込み</b>／<b>過熱×売り抜け日の積み上がり＝新規を絞る</b>。</div></div>')

# ----------------------------------------------------------------------------- equity curve (口座の21EMAルール)
# 「自分のエクイティカーブにMAを引け」: EC<21EMAは システム×相場 の相性悪化シグナル。
# 新規を止めサイズを落とす根拠にする（Minervini/系統トレーダーの定番・表示専用）。
def load_equity():
    """equity.csv: date,equity[,us_pct]。us_pct(米株比率%)は任意列・無い行はNaN。"""
    paths = [os.environ.get("V38_EQUITY_CSV"), "/mnt/project/equity.csv",
             os.path.join(os.path.dirname(CACHE), "equity.csv"), "equity.csv"]
    p = next((x for x in paths if x and os.path.exists(x)), None)
    if not p:
        return None
    rows = []
    import re as _re_eq
    _n_comma = 0; _n_space = 0
    try:
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            # カンマ／タブ／空白 いずれの区切りでも読む（貼り付け時の体裁ズレを吸収）
            parts = [x for x in _re_eq.split(r"[,\t\s]+", ln) if x != ""]
            if len(parts) < 2:
                continue
            if parts[0].lower() in ("date", "日付"):   # ヘッダ行はスキップ
                continue
            # 既存ファイルが使っている区切りを集計（コピー時に合わせる用）
            if "," in ln:
                _n_comma += 1
            elif ("\t" in ln) or (" " in ln):
                _n_space += 1
            try:
                d = pd.Timestamp(parts[0]).normalize()
                v = float(parts[1].replace("¥", "").replace("$", "").replace("_", "").replace(",", ""))
            except Exception:
                continue
            up = np.nan
            if len(parts) >= 3 and parts[2] != "":
                try:
                    up = float(parts[2].replace("%", ""))
                except Exception:
                    up = np.nan
            rows.append((d, v, up))
    except Exception:
        return None
    if len(rows) < 5:
        return None
    s = pd.Series({d: v for d, v, _ in rows}).sort_index()
    s.attrs["us_pct"] = pd.Series({d: u for d, v, u in rows}).sort_index()
    # 既存の主流な区切り（多数決・同数/空はカンマ）→ コピーボタンがこれに合わせる
    s.attrs["delim"] = " " if _n_space > _n_comma else ","
    return s

def build_equity_view(s):
    if s is None or len(s) < 5:
        return None
    ema21 = s.ewm(span=21, adjust=False).mean()
    last, e = float(s.iloc[-1]), float(ema21.iloc[-1])
    above = last >= e
    below_n = 0
    for v, m in zip(s.values[::-1], ema21.values[::-1]):
        if v < m:
            below_n += 1
        else:
            break
    peak = float(s.cummax().iloc[-1])
    dd = last / peak - 1
    n = min(len(s), 130)
    ts = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.iloc[-n:].items()]
    ets = [float(v) for v in ema21.iloc[-n:].values]
    # 露出（米株比率%）: 任意3列目。記録がある点だけ (index位置, 値) で持つ
    ups = []
    up_s = s.attrs.get("us_pct")
    if up_s is not None:
        tail = up_s.iloc[-n:]
        ups = [(i, float(v)) for i, v in enumerate(tail.values) if v == v]
    r20 = last / float(s.iloc[-min(len(s), 21)]) - 1
    return dict(last=last, ema=e, above=above, below_n=below_n, dd=dd, peak=peak,
                gap=last / e - 1, ts=ts, ets=ets, ups=ups, r20=r20, n=len(s),
                delim=s.attrs.get("delim", ","),
                d0=str(s.index[0].date()), d1=str(s.index[-1].date()))

def _svg_two(ys1, ys2, accent="#7ff0a8", accent2="#fbbf24", gid="eq"):
    n = len(ys1)
    Wd, Ht, pad = 680, 200, 6
    allv = list(ys1) + list(ys2)
    lo, hi = min(allv), max(allv)
    rng_ = (hi - lo) or 1
    lo -= rng_ * 0.06; hi += rng_ * 0.06; rng_ = hi - lo
    def X(i): return pad + i * (Wd - 2 * pad) / max(1, n - 1)
    def Y(v): return pad + (1 - (v - lo) / rng_) * (Ht - 2 * pad)
    p1 = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys1))
    p2 = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys2))
    area = (f"M{X(0):.1f},{Y(ys1[0]):.1f} "
            + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys1))
            + f" L{X(n-1):.1f},{Ht-pad:.1f} L{X(0):.1f},{Ht-pad:.1f} Z")
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{accent}" stop-opacity="0.30"/>'
            f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/></linearGradient></defs>'
            f'<path d="{area}" fill="url(#{gid})"/>'
            f'<polyline points="{p2}" fill="none" stroke="{accent2}" stroke-width="2" stroke-dasharray="5,4"/>'
            f'<polyline points="{p1}" fill="none" stroke="{accent}" stroke-width="2.2"/>'
            f'<circle cx="{X(n-1):.1f}" cy="{Y(ys1[-1]):.1f}" r="3.5" fill="{accent}"/></svg>')

def build_equity_attrib(s, macro):
    """下げの要因分解: 記録区間ごとに 実際 = 露出×市場(QQQ円建て) + 残差 に分解。
    市場代理=QQQ×USDJPY(円建て・記録日asof)。露出=us_pct(直前既知値をcarry)。"""
    if s is None or len(s) < 5:
        return None
    up = s.attrs.get("us_pct")
    if up is None or up.dropna().empty:
        return None
    q = macro.get("QQQ")
    if q is None:
        return None
    qc = q["Close"].dropna()
    fx = None
    try:
        import yfinance as yf
        fdf = yf.download("JPY=X", period="6mo", progress=False, auto_adjust=True)
        fc = fdf["Close"].dropna()
        if isinstance(fc, pd.DataFrame):
            fc = fc.iloc[:, 0]
        if len(fc) > 20:
            fx = fc
    except Exception:
        fx = None
    bench = qc.copy()
    if fx is not None:
        b = pd.concat([qc.rename("q"), fx.rename("f")], axis=1).sort_index().ffill().dropna()
        bench = b["q"] * b["f"]
    bench = bench.sort_index()
    def bench_at(d):
        sub = bench[bench.index <= d]
        return float(sub.iloc[-1]) if len(sub) else None
    w_ff = up.ffill()
    dates = list(s.index)
    def window(dates_w):
        act = mkt = full = 0.0; wsum = 0.0; n = 0; nskip = 0
        for a, b_ in zip(dates_w[:-1], dates_w[1:]):
            e0, e1 = float(s[a]), float(s[b_])
            r_act = e1 / e0 - 1
            w = w_ff.get(a, np.nan)
            b0, b1 = bench_at(a), bench_at(b_)
            if b0 is None or b1 is None or not (w == w):
                nskip += 1
                continue
            r_b = b1 / b0 - 1
            act += r_act; mkt += (w / 100.0) * r_b; full += r_b
            wsum += w; n += 1
        if n == 0:
            return None
        return dict(act=act, mkt=mkt, full100=full, saved=mkt - full,
                    resid=act - mkt, w_avg=wsum / n, n=n, nskip=nskip)
    peak_d = s.idxmax()
    peak_i = dates.index(peak_d)
    out = dict(full=window(dates), fx_ok=fx is not None,
               peak_date=str(peak_d.date()))
    out["peak"] = window(dates[peak_i:]) if peak_i < len(dates) - 1 else None
    return out

def _attrib_html(at):
    if not at or not at.get("peak"):
        return ""
    p = at["peak"]
    def pct(x): return f"{x*100:+.1f}%"
    def cls(x): return "pos" if x >= 0 else "neg"
    fxn = "" if at["fx_ok"] else "（為替取得不可・USD建て近似）"
    return (
        f'<div class="attrib"><div class="attrib-h">下げの要因分解（ピーク {at["peak_date"]} 以降・QQQ円建て代理{fxn}）</div>'
        f'<div class="attrib-g">'
        f'<span class="atk">実際</span><b class="{cls(p["act"])}">{pct(p["act"])}</b>'
        f'<span class="atk">＝ 市場<span class="atsub">露出{p["w_avg"]:.0f}%加味</span></span><b class="{cls(p["mkt"])}">{pct(p["mkt"])}</b>'
        f'<span class="atk">＋ 銘柄・その他</span><b class="{cls(p["resid"])}">{pct(p["resid"])}</b></div>'
        f'<div class="attrib-g"><span class="atk">常時100%なら</span><b class="{cls(p["full100"])}">{pct(p["full100"])}</b>'
        f'<span class="atk">→ 露出調整の効果</span><b class="{cls(p["saved"])}">{pct(p["saved"])}</b></div>'
        f'<div class="mut" style="font-size:10.5px;margin-top:3px">記録日ベースの近似。市場=各区間の露出×QQQ円建てリターンの積上げ。'
        f'残差=銘柄選択・レバ・為替タイミング等。露出調整の効果プラス＝薄くして回避できた分。</div></div>')

def _svg_expo(ups, n):
    """露出バンド: 米株比率%(0-100)の棒。記録がある点のみ描画。"""
    if not ups:
        return ""
    Wd, Ht, pad = 680, 64, 6
    def X(i): return pad + i * (Wd - 2 * pad) / max(1, n - 1)
    bw = max(3.0, (Wd - 2 * pad) / max(1, n - 1) * 0.55)
    bars = ""
    for i, v in ups:
        h = max(1.5, v / 100 * (Ht - 14))
        col = "#38bdf8" if v >= 60 else "#7dd3fc" if v >= 25 else "#334155"
        bars += f'<rect x="{X(i)-bw/2:.1f}" y="{Ht-6-h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="1.5" fill="{col}"/>'
    grid = (f'<line x1="{pad}" y1="{Ht-6}" x2="{Wd-pad}" y2="{Ht-6}" stroke="#233046" stroke-width="1"/>'
            f'<line x1="{pad}" y1="{Ht-6-(Ht-14)}" x2="{Wd-pad}" y2="{Ht-6-(Ht-14)}" stroke="#1b2536" stroke-width="1" stroke-dasharray="3,4"/>'
            f'<text x="{Wd-pad-2}" y="{Ht-6-(Ht-14)+10}" fill="#5b6b82" font-size="10" text-anchor="end">100%</text>'
            f'<text x="{Wd-pad-2}" y="{Ht-9}" fill="#5b6b82" font-size="10" text-anchor="end">0%</text>')
    return f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none" style="display:block;margin-top:2px">{grid}{bars}</svg>'

def _equity_card(eq, at=None):
    setup = (
        '<div class="card"><h2>エクイティカーブ×21EMA（未設定）</h2>'
        '<div class="sub">口座資産の推移に21EMAを引き、割れたら新規停止・サイズ半減の判断材料にする（表示専用）。</div>'
        '<div class="note">有効化: リポジトリに <b>equity.csv</b> を置く。記録は<b onclick="goTab(\'t-alloc\')" style="cursor:pointer;text-decoration:underline">配分タブ「エクイティ記録」</b>の📋ボタンで1行コピー→貼り付け。'
        '形式は1行1記録の「date,equity」または「date,equity,米株比率%」（カンマ区切り推奨・空白区切りも可）。新しい行は<b>末尾</b>に足す（並び順は自動整列するので前後しても可）。週1記録でも機能する。<br>'
        '<span class="mut">例:<br>date,equity<br>2026-06-30,10250000<br>2026-07-01,10180000</span></div></div>')
    if not eq:
        return setup
    if eq["above"]:
        st_txt, st_cls = "21EMA上 ・ 通常運転", "st-good"
        rule = "エクイティカーブは21EMAの上。システムと相場の相性は正常。ルール通り継続。"
    else:
        st_txt, st_cls = f"⚠ 21EMA割れ（連続{eq['below_n']}記録）", "st-bad"
        rule = (f"<b>エクイティカーブが21EMAを下回っている（連続{eq['below_n']}記録・乖離{eq['gap']*100:+.1f}%）。</b>"
                "システムと今の相場の相性が悪化しているサイン。新規エントリー見送り・サイズ半減を検討し、"
                "カーブが21EMAを回復するまで守りを優先（出血を止める）。表示専用の推奨でありゲートとは独立。")
    ys = [v for _, v in eq["ts"]]
    svg = _svg_two(ys, eq["ets"])
    expo = _svg_expo(eq.get("ups") or [], len(ys))
    expo_html = ""
    if expo:
        lastu = eq["ups"][-1][1]
        expo_html = (f'{expo}<div class="cap"><span class="mut">米株比率（青=高露出・空欄の日は非表示）</span>'
                     f'<span style="color:#7dd3fc;font-weight:700">直近 {lastu:.0f}%</span></div>')
    return (
        f'<div class="card"><h2>エクイティカーブ×21EMA</h2>'
        f'<div class="sub">口座資産（equity.csv・{eq["n"]}記録）と、その21EMA（記録点ベース）。追記は<b onclick="goTab(\'t-alloc\')" style="cursor:pointer;text-decoration:underline">配分タブ「エクイティ記録」</b>から。'
        f'カーブ自体をトレードする: <b>EC&lt;21EMA＝守り、EC&gt;21EMA＝通常</b></div>'
        f'<div class="eqrow"><span class="dd"><span class="st {st_cls}">{st_txt}</span></span>'
        f'<span class="eqkv">乖離 <b class="{"pos" if eq["gap"]>=0 else "neg"}">{eq["gap"]*100:+.1f}%</b></span>'
        f'<span class="eqkv">高値からDD <b class="{"pos" if eq["dd"]>=-0.001 else "neg"}">{eq["dd"]*100:+.1f}%</b></span>'
        f'<span class="eqkv">直近21記録 <b class="{"pos" if eq["r20"]>=0 else "neg"}">{eq["r20"]*100:+.1f}%</b></span></div>'
        f'<div class="chart">{svg}'
        f'<div class="cap"><span>{eq["ts"][0][0]}</span>'
        f'<span style="color:#7ff0a8;font-weight:700">実線=口座 ・ 破線=21EMA</span>'
        f'<span>{eq["ts"][-1][0]}</span></div>'
        f'{expo_html}</div>'
        f'{_attrib_html(at)}'
        f'<div class="note">{rule} 露出バンドが高いまま資産が下がっていれば相場要因、露出が低いのに下がっていれば為替・記録タイミング要因の切り分けに使える。</div></div>')

# ----------------------------------------------------------------------------- state persistence + changelog + holdings trail
def load_state():
    paths = [os.environ.get("V38_STATE_JSON"), os.path.join(os.path.dirname(CACHE), "state.json"),
             "/mnt/project/state.json", "state.json"]
    p = next((x for x in paths if x and os.path.exists(x)), None)
    if not p:
        return {}
    try:
        return json.load(open(p))
    except Exception:
        return {}

def save_state(st):
    outp = (os.environ.get("V38_STATE_JSON")
            or os.path.join(os.path.dirname(CACHE), "state.json"))
    try:
        json.dump(st, open(outp, "w"), ensure_ascii=False)
    except Exception:
        pass

def _summ(st):
    return dict(date=st.get("date"), gate=st.get("gate"), mri=st.get("mri"),
                bear_lit=st.get("bear_lit", []), senti_flags=st.get("senti_flags", []),
                picks=st.get("picks", []),
                soxl_band=st.get("soxl_band"), turnover=st.get("turnover"), updown=st.get("updown"))

def track_holdings(prev, picks, color, asof_date, m=None):
    """state.jsonの建値・ピークを引き継ぎ、実効拘束線（max(建値×0.75, ピーク×tf)）距離とヒートを計算。
       バグ②修正: 今日のトップ12から順位落ちした保有も、継続条件（50>200MA & 189日RS上位2N）を満たす限り
       出口監視に残す（月曜まで売らない）。継続を割ったら追跡終了＝売却済み扱いで自然にhold落ち。"""
    today = str(asof_date)
    tf = 0.85 if color == "Yellow" else 0.70
    prev_hold = (prev or {}).get("hold", {}) or {}
    pick_set = {t for t, _, _ in picks}
    hold, hv, losses, carry = {}, {}, [], []

    def _process(t, px, ema21=None, lo10=None):
        ph = prev_hold.get(t) or {}
        try:
            ed = str(ph.get("ed") or today)
            ep = float(ph.get("ep", px))
            peak = max(float(ph.get("peak", px)), px)
        except Exception:
            ed, ep, peak = today, px, px
        # 出口（2026-07-07確定）: トレール = max(10日安値×0.998, 21EMA×0.99)。21EMA×0.93は出口から撤去。
        lo_stop = (float(lo10) * 0.998) if (lo10 is not None and lo10 == lo10 and float(lo10) > 0) else 0.0
        ema_stop = (float(ema21) * 0.99) if (ema21 is not None and ema21 == ema21 and float(ema21) > 0) else 0.0
        stop = max(lo_stop, ema_stop)
        if stop <= 0:
            stop = ep * 0.90        # データ欠落時のフォールバック
        # 初期ストップ（建て時に確定）→ R と +3R 目標。istop は state に保存し引き継ぐ。
        istop = float(ph.get("istop") or stop)
        R = ep - istop
        t3 = ep + 3.0 * R if R > 0 else None                 # +3R で 1/3 利確（建値移動なし）
        hit3 = bool(t3 is not None and px >= t3)
        dist = px / stop - 1 if stop > 0 else np.nan
        try:
            days = int(np.busday_count(np.datetime64(pd.Timestamp(ed).date()),
                                       np.datetime64(pd.Timestamp(today).date()))) + 1
        except Exception:
            days = 1
        _which = "10日安値" if (stop == lo_stop and lo_stop > 0) else ("21EMA" if ema_stop > 0 else "—")
        hold[t] = dict(ed=ed, ep=round(ep, 4), peak=round(peak, 4), istop=round(istop, 4))
        hv[t] = dict(days=days, stop=stop, dist=dist, which=_which,
                     istop=istop, t3=t3, hit3=hit3, R=R)
        if px > 0:
            losses.append(max(0.0, (px - stop) / px))

    for t, _, r in picks:
        try:
            px = float(r["close"])
        except Exception:
            continue
        _process(t, px, r.get("ema21"), r.get("lo10"))
    # 順位落ち保有の追跡（継続条件を満たす前回保有をpicks外でも残す）
    if m is not None and prev_hold is not None and getattr(m, "index", None) is not None:
        try:
            rs189s = m["rs189"].dropna().sort_values(ascending=False)
            thr2n = float(rs189s.iloc[2 * N_PORT - 1]) if len(rs189s) >= 2 * N_PORT else -1.0
        except Exception:
            thr2n = -1.0
        for t in list(prev_hold.keys()):
            if t in pick_set or t not in m.index:
                continue
            row = m.loc[t]
            s50 = row.get("sma50"); s200 = row.get("sma200"); rs189 = row.get("rs189")
            cont = (pd.notna(s50) and pd.notna(s200) and s50 > s200
                    and pd.notna(rs189) and rs189 >= thr2n)
            if not cont:
                continue                   # 継続割れ=月曜に売却→追跡終了
            try:
                px = float(row.get("close"))
            except Exception:
                continue
            _process(t, px, row.get("ema21"), row.get("lo10"))
            carry.append(t)
    heat = (float(np.mean(losses)) * ALLOC[0] / 100.0) if losses else None
    return hold, hv, heat, tf, carry

def build_changelog(prev, color, aux, senti, picks, asof_date,
                    soxl_ok=None, turnover_dir=None, updown_reg=None):
    """前回（別日）比の変化リスト。(lines, ref_date, major)を返す。"""
    today = str(asof_date)
    base = prev if (prev and prev.get("date") and prev["date"] != today) else (prev or {}).get("prevday")
    if not base or not base.get("date"):
        return [], None, False
    ch, major = [], False
    pg, cg = base.get("gate"), color
    if pg and cg and pg != cg:
        ch.append(f'NQ色 <b>{_COLOR_JP.get(pg, pg)}→{_COLOR_JP.get(cg, cg)}</b> → 翌寄りで露出調整')
        major = True
    try:
        dm = float(aux["cur"]) - float(base.get("mri", aux["cur"]))
        if abs(dm) >= 3:
            ch.append(f'地合いスコア <b>{base.get("mri"):.0f}→{aux["cur"]:.0f}</b>（{dm:+.0f}）')
    except Exception:
        pass
    pt, ct = set(base.get("picks") or []), {t for t, _, _ in picks}
    inn, out = sorted(ct - pt), sorted(pt - ct)
    if inn:
        ch.append("ポートフォリオ IN: <b>" + " ".join(inn) + "</b>")
        major = True
    if out:
        ch.append("ポートフォリオ OUT: <b>" + " ".join(out) + "</b>")
        major = True
    pb = set(base.get("bear_lit") or [])
    cb = {lab for lab, on in aux.get("bear_flags", []) if on}
    nb, cbk = sorted(cb - pb), sorted(pb - cb)
    if nb:
        ch.append("ベア警戒 新点灯: " + "・".join(nb))
        major = True
    if cbk:
        ch.append("ベア警戒 消灯: " + "・".join(cbk))
    ps = set(base.get("senti_flags") or [])
    cs = {l for l, on in (senti or {}).get("flags", []) if on}
    ns = sorted(cs - ps)
    if ns:
        ch.append("センチメント 新点灯: " + "・".join(ns))
        major = True
    # SOXL投入帯の切替（配分計算にも自動連動）
    if soxl_ok is not None:
        cur_band = "投入帯" if soxl_ok else "帯外"
        prev_band = base.get("soxl_band")
        if prev_band and prev_band != cur_band:
            if soxl_ok:
                ch.append("SOXL投入帯に入った → 段階投入 解禁（1/3ずつ）")
            else:
                ch.append("SOXL投入帯を外れた → 新規停止・全額TQQQ")
            major = True
    # 売買代金レジーム（拡大/縮小の転換のみ）
    pt2 = base.get("turnover")
    if pt2 and turnover_dir and pt2 != turnover_dir and turnover_dir in ("拡大", "縮小"):
        ch.append(f'売買代金 <b>{pt2}→{turnover_dir}</b>' + ("（参加が厚く）" if turnover_dir == "拡大" else "（参加細り・要注意）"))
        if turnover_dir == "縮小":
            major = True
    # 集積/分散レジーム（O'Neil式）
    pu = base.get("updown")
    if pu and updown_reg and pu != updown_reg:
        lab = "集積（買い集め優勢）" if updown_reg == "accum" else "分散（売り抜け優勢）"
        ch.append(f"集積/分散が <b>{lab}</b> に転換")
        major = True
    return ch, base.get("date"), major

def _changelog_card(ch, ref):
    if ref is None:
        body = '<div class="sub">初回記録。次回ビルドから前回比の変化をここに表示する。</div>'
    elif not ch:
        body = f'<div class="sub">前回（{ref}）から重要な変化なし。保有維持・トレール/ストップのみ対応。</div>'
    else:
        body = ('<ul class="chlog">' + "".join(f"<li>{x}</li>" for x in ch) + "</ul>"
                + f'<div class="note">比較基準: {ref}</div>')
    return f'<div class="card ch-card"><h2>前回からの変化</h2>{body}</div>'

def post_webhook(lines, color):
    url = os.environ.get("V38_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK")
    if not url or not lines:
        return
    try:
        import urllib.request, re as _re
        txt = ("【V38】NQ:" + (_COLOR_JP.get(color, "—") if color else "—") + "\n"
               + "\n".join("・" + _re.sub("<[^>]+>", "", x) for x in lines))
        req = urllib.request.Request(url, data=json.dumps({"content": txt[:1900]}).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "v38-dashboard"})
        urllib.request.urlopen(req, timeout=8)
        sys.stderr.write("[webhook] sent %d lines\n" % len(lines))
    except Exception as e:
        sys.stderr.write("[webhook] failed: %r\n" % repr(e)[:90])

def append_log_csv(asof_date, color, aux, senti, picks):
    p = os.environ.get("V38_LOG_CSV") or os.path.join(os.path.dirname(CACHE), "daily_log.csv")
    today = str(asof_date)
    try:
        rows = []
        if os.path.exists(p):
            rows = [ln for ln in open(p).read().splitlines()
                    if ln and not ln.startswith(today + ",") and not ln.startswith("date,")]
        line = ",".join([today, color or "", f"{aux['cur']:.1f}", str(aux["bear_n"]),
                         (f"{senti['cur']:.1f}" if senti else ""),
                         " ".join(t for t, _, _ in picks)])
        open(p, "w").write("\n".join(["date,gate,mri,bear_n,senti,picks"] + rows + [line]) + "\n")
    except Exception as e:
        sys.stderr.write("[log] failed: %r\n" % repr(e)[:90])

# ----------------------------------------------------------------------------- portfolio correlation / effective N
def portfolio_corr(W, tickers):
    try:
        cols = [t for t in tickers if t in W["Close"].columns]
        if len(cols) < 3:
            return None
        r = W["Close"][cols].pct_change().iloc[-60:]
        cm = r.corr().values
        n = cm.shape[0]
        iu = np.triu_indices(n, 1)
        rho = float(np.nanmean(cm[iu]))
        neff = n / (1 + (n - 1) * max(rho, 0.0))
        return dict(rho=rho, neff=neff, n=n)
    except Exception:
        return None

# ----------------------------------------------------------------------------- earnings dates (保有+控えのみ・キャッシュ)
def load_earnings(tickers, live):
    paths = [os.environ.get("V38_ER_JSON"), os.path.join(os.path.dirname(CACHE), "earnings.json")]
    p = next((x for x in paths if x and os.path.exists(x)), None)
    cache = {}
    if p:
        try:
            cache = json.load(open(p))
        except Exception:
            cache = {}
    if live:
        try:
            import yfinance as yf, time as _t
            today = pd.Timestamp.today().normalize()
            def stale(t):
                try:
                    return pd.Timestamp(cache.get(t)) < today
                except Exception:
                    return True
            todo = [t for t in tickers if stale(t)][:40]
            t0 = _t.time()
            for t in todo:
                if _t.time() - t0 > 120:
                    break
                try:
                    cal = yf.Ticker(t).calendar
                    d = None
                    if isinstance(cal, dict):
                        ds = cal.get("Earnings Date") or []
                        d = ds[0] if ds else None
                    elif cal is not None and hasattr(cal, "loc"):
                        try:
                            d = cal.loc["Earnings Date"][0]
                        except Exception:
                            d = None
                    if d is not None:
                        cache[t] = str(pd.Timestamp(d).date())
                except Exception:
                    continue
            outp = p or os.environ.get("V38_ER_JSON") or os.path.join(os.path.dirname(CACHE), "earnings.json")
            try:
                json.dump(cache, open(outp, "w"))
            except Exception:
                pass
        except Exception:
            pass
    return cache

def _er_badge(t, er, asof_bar):
    try:
        d = pd.Timestamp((er or {}).get(t))
        n = (d.normalize() - pd.Timestamp(asof_bar).normalize()).days
        if 0 <= n <= 8:
            return f'<span class="erb">決算{"当日" if n == 0 else f"{n}日"}</span>'
    except Exception:
        pass
    return ""

def _risk_note(mkt):
    """ポートフォリオ・ヒート（全トレール同時発動の想定毀損）＋相関・実効N。"""
    heat, corr = mkt.get("heat"), mkt.get("corr")
    bits = []
    if heat is not None:
        hcls = "neg" if heat >= 0.12 else ("mut" if heat >= 0.07 else "pos")
        bits.append(f'ポートフォリオ・ヒート: 全トレール同時発動で想定 <b class="{hcls}">−{heat*100:.1f}%</b>（NAV比・個別スリーブ{ALLOC[0]}%換算）')
    if corr:
        ccls = "neg" if corr["rho"] >= 0.65 else ("mut" if corr["rho"] >= 0.45 else "pos")
        bits.append(f'60日ペア相関 平均 <b class="{ccls}">{corr["rho"]:.2f}</b> → 実効銘柄数 <b>{corr["neff"]:.1f}</b>/{corr["n"]}'
                    f'（相関が高いほど「{corr["n"]}銘柄」でなく単一ベータに近づく）')
    if not bits:
        return ""
    return '<div class="note risknote">' + '<br>'.join(bits) + '</div>'

def _rs_arrow(d, th=2):
    """RSランクの変化矢印（ローテーション初動の可視化）。th=表示閾値。"""
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return ""
    if d >= th:
        return f'<span class="rsd up">▲{d:.0f}</span>'
    if d <= -th:
        return f'<span class="rsd dn">▼{abs(d):.0f}</span>'
    return '<span class="rsd fl">·</span>'

def _adr_badge(adr):
    """ADR(20日平均日中値幅%)が最適レンジ 3.5〜8% の外なら印。低=鈍い/高=荒い。表示のみ・選定は非連動。"""
    if adr is None or (isinstance(adr, float) and adr != adr):
        return ""
    a = adr * 100.0
    if a < 3.5:
        return f'<span class="adrb adr-lo" title="ADRが低い＝値幅が小さく伸びにくい">ADR {a:.1f}%↓</span>'
    if a > 8.0:
        return f'<span class="adrb adr-hi" title="ADRが高い＝値幅が荒くストップに掛かりやすい">ADR {a:.1f}%↑</span>'
    return ""

def _noise_badge(adr, dist, horizon=21):
    """出口線が実現ボラ(ADR)の約1ヶ月1σ想定変動より内側なら「出口ノイズ内」印（=タイトで振り落とされやすい）。"""
    if adr is None or adr != adr or dist is None or dist != dist:
        return ""
    em = float(adr) * 0.55 * float(np.sqrt(horizon))          # ~1ヶ月 1σ（ADR実現ボラ）
    if float(dist) < em:
        return ('<span class="adrb adr-hi" '
                'title="出口線が想定変動(1σ)の内側＝通常のノイズで振り落とされやすい">出口ノイズ内</span>')
    return ""

def _entry_badge(rs, close, ema21):
    """RS階層別エントリー枠（21EMAからの距離ゾーン×RS階層の妥当性）。
       検証(2026-07-07): RS97+はゾーン内(−1〜+4%)が最良+0.53R・伸びを追うと最低+0.32R→枠を広げない。
       RS90-97はゾーン優先。RS75-90は位置ほぼ不問(+0.46〜0.54R)。低リスク/タイトストップ要件は不変。"""
    try:
        rs = float(rs); close = float(close); ema21 = float(ema21)
    except Exception:
        return ""
    if not (ema21 > 0) or rs != rs:
        return ""
    d = close / ema21 - 1
    pos = ("21EMA下" if d < -0.01 else "ゾーン内" if d <= 0.04 else
           "やや伸び" if d <= 0.07 else "伸び切り" if d <= 0.12 else "過伸長")
    note = ""
    if d > 0.12:                                    # 過伸長はどの階層でも見送り寄り
        cls, mark = "ent-warn", "△"
    elif rs >= 97:                                  # 最強クラス: ゾーン内が最良・伸びは追わない
        if -0.01 <= d <= 0.04:
            cls, mark, note = "ent-good", "◎", "最良帯"
        elif d > 0.04:
            cls, mark, note = "ent-bad", "×", "RS97+は追わない"
        else:
            cls, mark = "ent-ok", "○"
    elif rs >= 90:                                  # ゾーン優先
        cls, mark = ("ent-good", "◎") if (-0.01 <= d <= 0.04) else ("ent-ok", "○")
    else:                                           # RS75-90: 位置ほぼ不問
        cls, mark = ("ent-good", "◎") if (-0.01 <= d <= 0.04) else ("ent-ok", "○")
    tip = f"21EMA {d*100:+.0f}%・{pos}" + (f"・{note}" if note else "")
    return f'<span class="entb {cls}" title="{tip}">{mark} {pos}</span>'

# ----------------------------------------------------------------------------- セクターローテーション (RRG風・SPY相対)
# RRG ETFテーマ名 → 属するs2tサブテーマ(部分一致キーワード)。チップタップ展開用。
RRG_TO_SUB = {
    "半導体": ["半導体", "ファブレス", "パワー半導体", "アナログ", "EDA", "EMS", "電子製造受託"],
    "半導体装置": ["半導体製造装置", "製造装置"],
    "データセンター": ["データセンター", "AIサーバー", "冷却", "HPC"],
    "ソフトウェア": ["ソフトウェア", "SaaS"],
    "サイバー": ["サイバー"],
    "AI": ["AI GPU", "AIアナリティクス", "AIエッジ", "AIエンタープライズ", "AIデータ基盤", "AIハイパースケーラー", "AI光接続", "フォトニクス", "量子"],
    "バイオテック": ["バイオ"],
    "医療機器": ["医療機器"],
    "銀行": ["銀行"],
    "証券": ["証券", "資産運用"],
    "石油探査": ["E&P", "探査", "ミッドストリーム", "石油精製"],
    "油田": ["オイルフィールド", "石油機器", "石油装置"],
    "金鉱": ["金鉱"],
    "金属": ["金属", "レアアース", "チタン", "鉄鋼", "鉱業"],
    "ウラン": ["ウラン", "SMR", "原発", "原子力"],
    "防衛": ["防衛", "軍事"],
    "インフラ": ["インフラ", "電力設備", "送配電", "建設"],
    "運輸": ["海運", "トラック", "輸送", "航空"],
}

def build_theme_hierarchy(m, s2t):
    """大テーマ(表示名)→サブテーマ群のローテ+構成銘柄。RRGチップ(大テーマ)のjaキーと一致。
       全367サブテーマが必ず親を持つ(取りこぼしゼロ)。63×189日RS中央値で粒度統一。表示専用。"""
    from collections import defaultdict
    big = defaultdict(lambda: defaultdict(list))   # theme_disp -> subtheme -> [tickers]
    for t in m.index:
        v = s2t.get(t)
        if not v or len(v) < 2 or not v[0] or not v[1]:
            continue
        disp = v[0].split(". ", 1)[-1] if ". " in v[0] else v[0]
        big[disp][v[1]].append(t)
    def _agg(tickers):
        sub_m = m.loc[[t for t in tickers if t in m.index]]
        if len(sub_m) == 0:
            return None
        med63 = float(np.nanmedian(sub_m["rs"])) if "rs" in sub_m else np.nan
        med189 = float(np.nanmedian(sub_m["rs189"])) if "rs189" in sub_m else med63
        prev = float(np.nanmedian(sub_m["rs_l1"])) if "rs_l1" in sub_m else med63
        drs = (med63 - prev) if (med63 == med63 and prev == prev) else 0.0
        members = sorted(((t, float(m.at[t, "rs189"]) if ("rs189" in m.columns and t in m.index) else np.nan)
                          for t in tickers), key=lambda x: -(x[1] if x[1] == x[1] else -9))
        q = ("主導" if (med189 >= 60 and drs >= 0) else "弱化" if med189 >= 60 else
             "改善" if drs >= 0 else "停滞")
        return dict(rs=round(med189) if med189 == med189 else 0, drs=round(drs, 1), n=len(sub_m), q=q,
                    members=[{"t": t, "rs": round(r) if r == r else None} for t, r in members[:20]])
    out = {}
    for disp, subs in big.items():
        arr = []
        for sub, tks in subs.items():
            a = _agg(tks)
            if a:
                a["sub"] = sub
                arr.append(a)
        if arr:
            arr.sort(key=lambda z: -z["rs"])
            out[disp] = arr
    return out

def build_rrg_etf(macro, extras, win=63, mom=10, themes=None):
    """【大枠・市場全体】テーマETFのSPY相対力(63日基準)×その10日モメンタムで4象限。
       市場全体のセクター資金フローを見る古典的RRG。themes未指定なら主要18テーマ(RRG_THEMES)。"""
    b = macro.get("SPY")
    if b is None:
        return []
    bc = b["Close"].dropna()
    pts = []
    for tk, ja in (themes if themes is not None else RRG_THEMES):
        sc = extras.get(tk)
        if sc is None:
            d = macro.get(tk); sc = d["Close"] if d is not None else None
        if sc is None:
            continue
        sc = sc.dropna()
        r = (sc / bc).dropna()
        if len(r) < win + mom + 15:
            continue
        ratio = (100 * r / r.rolling(win).mean()).dropna()
        if len(ratio) < mom + 12:
            continue
        mser = (ratio / ratio.shift(mom) - 1) * 100
        x, y = float(ratio.iloc[-1]), float(mser.iloc[-1])
        q = "主導" if (x >= 100 and y >= 0) else "弱化" if x >= 100 else "改善" if y >= 0 else "停滞"
        recent = mser.iloc[-3:]; before = mser.iloc[-10:-3]
        cross = bool(len(recent) and len(before) and recent.gt(0).all() and before.le(0).any())
        pts.append(dict(tk=tk, ja=ja, x=x, y=y, q=q,
                        cross=(cross and q in ("改善", "主導")), semis=(tk == "SMH")))
    return pts

def build_rrg(m, s2t, win=63, mom=10):
    """s2t大テーマ15個を、構成銘柄のRS189中央値(横=強さ)×RSランクΔ中央値(縦=勢い)で4象限配置。
       ETF廃止・全銘柄集計。全367サブテーマが必ずどれかの大テーマに属する(取りこぼしゼロ)。
       x=RS189中央値(50が市場中央), y=約1週間のRSランク変化(資金の向き)。表示専用。"""
    from collections import defaultdict
    big = defaultdict(list)
    for t in m.index:
        v = s2t.get(t)
        if v and len(v) >= 1 and v[0]:
            big[v[0]].append(t)
    pts = []
    for theme, tickers in big.items():
        sub = m.loc[[t for t in tickers if t in m.index]]
        if len(sub) < 3:
            continue
        x = float(np.nanmedian(sub["rs189"])) if "rs189" in sub else np.nan
        # 勢い: 現RSランク中央値 − 約1週前RSランク中央値(rs189_dの中央値でも可)
        y = float(np.nanmedian(sub["rs189_d"])) if "rs189_d" in sub else 0.0
        if x != x:
            continue
        q = "主導" if (x >= 50 and y >= 0) else "弱化" if x >= 50 else "改善" if y >= 0 else "停滞"
        cross = bool(y >= 3 and q in ("改善", "主導"))   # 勢いが明確にプラス
        disp = theme.split(". ", 1)[-1] if ". " in theme else theme
        pts.append(dict(tk=theme, ja=disp, x=x, y=y, q=q, cross=cross,
                        semis=("半導体" in theme)))
    pts.sort(key=lambda p: -p["x"])
    return pts

_RRG_COL = {"主導": "#4ade80", "改善": "#60a5fa", "弱化": "#fbbf24", "停滞": "#f87171"}

def _rrg_svg(pts, cxv=50):
    """全テーマにラベルを付け、貪欲法でラベルの重なりを回避したSVGを返す。cxv=x軸中心(ETF=100/s2t=50)。"""
    if not pts or len(pts) < 4:
        return ""
    Wd, Ht, pad = 680, 400, 34
    xs = [p["x"] for p in pts]; ys = [p["y"] for p in pts]
    xr = max(8.0, max(abs(min(xs) - cxv), abs(max(xs) - cxv)) * 1.28)
    yr = max(1.5, max(abs(min(ys)), abs(max(ys))) * 1.28)
    def X(v): return pad + (v - (cxv - xr)) / (2 * xr) * (Wd - 2 * pad)
    def Y(v): return pad + (1 - (v + yr) / (2 * yr)) * (Ht - 2 * pad)
    cx, cy = X(cxv), Y(0)
    quads = (f'<rect x="{cx}" y="{pad}" width="{Wd-pad-cx:.0f}" height="{cy-pad:.0f}" fill="#22c55e" opacity="0.08"/>'
             f'<rect x="{pad}" y="{pad}" width="{cx-pad:.0f}" height="{cy-pad:.0f}" fill="#3b82f6" opacity="0.08"/>'
             f'<rect x="{cx}" y="{cy}" width="{Wd-pad-cx:.0f}" height="{Ht-pad-cy:.0f}" fill="#eab308" opacity="0.08"/>'
             f'<rect x="{pad}" y="{cy}" width="{cx-pad:.0f}" height="{Ht-pad-cy:.0f}" fill="#ef4444" opacity="0.08"/>')
    qlab = (f'<text x="{Wd-pad-6}" y="{pad+16}" fill="#4ade80" font-size="15" font-weight="800" text-anchor="end">主導</text>'
            f'<text x="{pad+6}" y="{pad+16}" fill="#60a5fa" font-size="15" font-weight="800">改善</text>'
            f'<text x="{Wd-pad-6}" y="{Ht-pad-8}" fill="#fbbf24" font-size="15" font-weight="800" text-anchor="end">弱化</text>'
            f'<text x="{pad+6}" y="{Ht-pad-8}" fill="#f87171" font-size="15" font-weight="800">停滞</text>')
    FS = 11.5; CH = FS * 1.02          # 1文字の概算幅（全角）
    placed = []                         # 配置済みラベルのbox [x0,y0,x1,y1]
    def overlaps(bx):
        for q in placed:
            if not (bx[2] < q[0] or bx[0] > q[2] or bx[3] < q[1] or bx[1] > q[3]):
                return True
        return False
    marks = ""; labels = ""
    # 主導→兆候→右にある順で優先配置（重要点を先に置いてズレを最小化）
    order_pts = sorted(pts, key=lambda p: (0 if p.get("semis") else 1 if p["q"] == "主導" or p.get("cross") else 2, -p["x"]))
    for p in order_pts:
        col = _RRG_COL.get(p["q"], "#9aa4b2")
        cxp, cyp = X(p["x"]), Y(p["y"])
        if p.get("cross"):
            marks += f'<circle cx="{cxp:.1f}" cy="{cyp:.1f}" r="10" fill="none" stroke="#fff" stroke-width="1.6" opacity="0.9"/>'
        if p.get("semis"):
            marks += (f'<rect x="{cxp-7:.1f}" y="{cyp-7:.1f}" width="14" height="14" rx="3" '
                      f'fill="{col}" stroke="#fff" stroke-width="2"/>')
            lw = len(p["ja"]) * (FS + 2)
            bx = [cxp - lw/2, cyp - 24, cxp + lw/2, cyp - 11]
            labels += f'<text x="{cxp:.1f}" y="{cyp-12:.1f}" fill="#fff" font-size="13" font-weight="900" text-anchor="middle">{p["ja"]}</text>'
            placed.append(bx); continue
        marks += f'<circle cx="{cxp:.1f}" cy="{cyp:.1f}" r="5" fill="{col}"/>'
        lw = len(p["ja"]) * CH
        # 候補配置: 上→下→右→左 の順で空きを探す
        cands = [(cxp, cyp - 9, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp, cyp + 16, "middle", cxp - lw/2, cxp + lw/2),
                 (cxp + 8, cyp + 4, "start", cxp + 8, cxp + 8 + lw),
                 (cxp - 8, cyp + 4, "end", cxp - 8 - lw, cxp - 8)]
        chosen = None
        for (tx, ty, anc, x0, x1) in cands:
            bx = [x0, ty - FS, x1, ty + 2]
            if not overlaps(bx):
                chosen = (tx, ty, anc, bx); break
        if chosen is None:
            tx, ty, anc, x0, x1 = cands[0]; chosen = (tx, ty, anc, [x0, ty - FS, x1, ty + 2])
        tx, ty, anc, bx = chosen
        placed.append(bx)
        lcol = "#dbe4ef" if (p["q"] == "主導" or p.get("cross")) else "#9fb0c5"
        fw = "800" if (p["q"] == "主導" or p.get("cross")) else "600"
        labels += f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{lcol}" font-size="{FS}" font-weight="{fw}" text-anchor="{anc}">{p["ja"]}</text>'
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="xMidYMid meet">{quads}'
            f'<line x1="{cx}" y1="{pad}" x2="{cx}" y2="{Ht-pad}" stroke="#2a3548" stroke-width="1"/>'
            f'<line x1="{pad}" y1="{cy}" x2="{Wd-pad}" y2="{cy}" stroke="#2a3548" stroke-width="1"/>'
            f'{qlab}{marks}{labels}'
            f'<text x="{Wd/2}" y="{Ht-6}" fill="#7d8da1" font-size="12" text-anchor="middle">→ SPYに対する相対力（右=強い）</text>'
            f'<text x="12" y="{Ht/2}" fill="#7d8da1" font-size="12" text-anchor="middle" transform="rotate(-90 12 {Ht/2})">↑ 相対力の勢い</text></svg>')

def _rrg_card(pts, pts_all=None, sub_data=None, cxv=50, title="テーマ・ローテーション（RS基準）", desc=None):
    if not pts or len(pts) < 4:
        return ""
    def seeds_html(ps):
        seeds = [p for p in ps if p["cross"]]
        return ('<div class="rrgseed">ローテの芽: ' + "・".join(f'<b>{p["ja"]}</b>' for p in seeds)
                + '（相対力の勢いがマイナス→プラスに転換）</div>') if seeds else ""
    def lists_html(ps, hier=None):
        import json as _j
        order = ["主導", "改善", "弱化", "停滞"]
        def chip(p):
            subs = (hier or {}).get(p["ja"])
            base = f'{p["ja"]}{"⚡" if p["cross"] else ""}'
            if not subs:
                return f'<span class="chip">{base}</span>'
            payload = _j.dumps({"theme": p["ja"], "subs": subs}, ensure_ascii=False).replace('"', "&quot;")
            return (f'<span class="chip chip-tap" data-hier="{payload}" onclick="showThemeHier(this)">'
                    f'{base}<span class="chip-arr">›</span></span>')
        return "".join(
            f'<div class="rrgq"><span class="rrgq-l" style="color:{_RRG_COL[q]}">{q}</span>'
            + ("".join(chip(p) for p in sorted([x for x in ps if x["q"] == q], key=lambda z: -z["x"])) or '<span class="empty">なし</span>')
            + '</div>' for q in order)
    has_all = bool(pts_all and len(pts_all) >= 4)
    # 主要16
    view16 = (f'<div class="rrgview" id="rrg-16">'
              f'<div class="chart" style="height:auto">{_rrg_svg(pts, cxv)}</div>{seeds_html(pts)}{lists_html(pts, sub_data)}</div>')
    # 全テーマ（あれば）
    view_all = ""
    if has_all:
        view_all = (f'<div class="rrgview" id="rrg-all" style="display:none">'
                    f'<div class="chart" style="height:auto">{_rrg_svg(pts_all, cxv)}</div>{seeds_html(pts_all)}{lists_html(pts_all, sub_data)}</div>')
    toggle = ""
    if has_all:
        toggle = ('<div class="rrgtog">'
                  '<button class="rtg on" id="rtg-16" onclick="rrgGran(16,this)">主要16</button>'
                  f'<button class="rtg" id="rtg-all" onclick="rrgGran(0,this)">全{len(pts_all)}テーマ</button>'
                  '</div>')
    _desc = desc or ('大テーマ15区分を構成銘柄のRSで配置(横=RS189中央値・50が市場中央／縦=RSランクの1週間変化＝資金の向き)。<b>改善→主導→弱化→停滞</b>の時計回りに循環。'
                     '<b>⚡＝勢いがプラス側</b>。■＝半導体。<b>› 付きチップをタップ→ニッチ業種と構成銘柄(全サブテーマ網羅)</b>。')
    return (f'<div class="card"><div class="hdr"><h2>{title}</h2>{toggle}</div>'
            f'<div class="sub">{_desc}</div>'
            f'{view16}{view_all}</div>')

# ----------------------------------------------------------------------------- 映え: レジームリボン / LED / ヒートマップ / 品質
# ----------------------------------------------------------------------------- レバレッジ・エントリー環境（表示専用・配分に非接続）
def build_lev_env(macro):
    """SOXX(半導体指数)のトレンドゲート状態＋実現ボラ分位。SOXLの新規サイズ判断の材料。
    ※Fable裁定: 表示専用。ボラは『可否』でなく『覚悟の目盛り』。強度スロットルも配分昇格しない。"""
    d = macro.get("SOXX")
    if d is None:
        return None
    c = d["Close"].dropna()
    if len(c) < 130:
        return None
    ma50 = c.rolling(50).mean(); ma100 = c.rolling(100).mean()
    up = bool(float(ma50.iloc[-1]) > float(ma100.iloc[-1]))
    gap = float(ma50.iloc[-1]) / float(ma100.iloc[-1]) - 1
    diff = (ma50 - ma100)
    streak = 0
    sign = 1 if up else -1
    for v in diff.iloc[::-1]:
        if v != v:
            break
        if (v > 0) == up:
            streak += 1
        else:
            break
    r = c.pct_change()
    vol20 = float((r.rolling(20).std() * np.sqrt(252)).iloc[-1])
    vser = (r.rolling(20).std() * np.sqrt(252)).dropna()
    vpct_ser = _roll_pct(vser, win=504, minp=120)
    vpct = float(vpct_ser.dropna().iloc[-1]) if len(vpct_ser.dropna()) else None
    if vpct is None:
        size, scls, snote = "—", "mut", "分位の履歴不足"
    elif vpct >= 75:
        size, scls, snote = "薄く（半分目安）", "neg", "荒れ帯。新規は枚数を半分に"
    elif vpct >= 50:
        size, scls, snote = "標準", "mut", "平常。無理に追わない"
    else:
        size, scls, snote = "フル（配分どおり）", "pos", "静穏。減衰リスクが最も低い帯"
    # SOXL投入帯（MAE実測: SOXXが50MAの+0〜3%上＝初期逆行が最も浅く−25%級の大事故が半減）
    px = float(c.iloc[-1]); m50 = float(ma50.iloc[-1])
    dist50 = px / m50 - 1 if m50 else 0.0
    above50 = px > m50
    if above50 and dist50 <= 0.03:
        entry_ok, entry_txt, entry_cls = True, "投入帯（50MA +0〜3%）", "pos"
        entry_note = "初期逆行(MAE)が最も浅い帯。段階投入で1/3ずつ。割れたら即撤退＝深傷回避"
    elif not above50:
        entry_ok, entry_txt, entry_cls = False, "50MA割れ＝TQQQのみ", "neg"
        entry_note = "リバウンド狙いに見えるがテール最悪(−25%級25%)。SOXLは入れない"
    else:
        entry_ok, entry_txt, entry_cls = False, f"50MAから+{dist50*100:.0f}%乖離＝待機", "mut"
        entry_note = "支持線が遠い＝invalidationが遠い。0〜+3%まで引きつけるかTQQQのみ"
    return dict(up=up, gap=gap, streak=streak, vol20=vol20, vpct=vpct,
                size=size, scls=scls, snote=snote,
                dist50=dist50, above50=above50, entry_ok=entry_ok,
                entry_txt=entry_txt, entry_cls=entry_cls, entry_note=entry_note)

def _lev_env_card(le, rrg):
    if not le:
        return ('<div class="card"><h2>レバレッジ・コンディション（SOXL）</h2>'
                '<div class="sub">SOXX(半導体指数)データ取得不可。</div></div>')
    semis = next((p for p in (rrg or []) if p.get("semis")), None)
    if semis:
        qcol = _RRG_COL.get(semis["q"], "#9aa4b2")
        rot = (f'<span class="le-rot" style="color:{qcol}">{semis["q"]}'
               + ('⚡' if semis.get("cross") else '') + '</span>')
        rot_note = {"主導": "強く、勢いも上", "改善": "勢いが上向き＝先回り候補",
                    "弱化": "強いが勢いは鈍化", "停滞": "弱く、勢いも下"}.get(semis["q"], "")
    else:
        rot, rot_note = '<span class="mut">—</span>', "SMH未取得"
    tcls = "st-good" if le["up"] else "st-bad"
    tchip = "追い風" if le["up"] else "逆風"
    tdet = (f'MA50&gt;MA100・連続{le["streak"]}日' if le["up"]
            else f'MA50&lt;MA100・連続{le["streak"]}日＝SOXL除外（全額TQQQ）の地合い')
    # SOXL投入帯（MAE実測ベース・50MAからの距離）
    _echip = "SOXL投入可" if le.get("entry_ok") else "TQQQのみ"
    _ecls = "st-good" if le.get("entry_ok") else "st-bad"
    entry_row = (
        f'<div class="le-row"><span class="le-k">投入帯</span>'
        f'<span class="st {_ecls}">{_echip}</span>'
        f'<span class="le-sub"><b class="{le.get("entry_cls","mut")}">{le.get("entry_txt","—")}</b>'
        f'（50MA距離 {le.get("dist50",0)*100:+.1f}%）</span></div>')
    vp = le["vpct"]
    meter = (f'<div class="sn-gauge le-vg"><i style="left:{max(0,min(100,vp or 0)):.1f}%"></i></div>'
             f'<div class="sn-gl"><span>静穏</span><span>平常</span><span>荒れ（薄く）</span></div>')
    return (
        f'<div class="card"><h2>レバレッジ・コンディション（SOXL）</h2>'
        f'<div class="sub">SOXLを新規で入れる時の環境チェック。<b>投入帯＝SOXXが50MAの+0〜3%上</b>のときだけ段階投入、それ以外はTQQQのみ（MAE実測でテール半減）。表示専用。</div>'
        f'<div class="le-row"><span class="le-k">トレンド</span>'
        f'<span class="st {tcls}">{tchip}</span>'
        f'<span class="le-sub">{tdet}</span></div>'
        + entry_row +
        f'<div class="le-row"><span class="le-k">ローテ</span>{rot}'
        f'<span class="le-sub">{rot_note}</span></div>'
        f'<div class="le-row"><span class="le-k">ボラ</span>'
        f'<span class="le-v">{le["vol20"]*100:.0f}%<span class="le-pct">（分位{vp:.0f}）</span></span>'
        f'<span class="le-size {le["scls"]}">サイズ: {le["size"]}</span></div>'
        f'{meter}'
        f'<div class="note">{le.get("entry_note","")}。{le["snote"]}。メーターは自動制御ではなく「枚数の覚悟」の目安。</div></div>')

_RB_CLS = {"Blue": "c-bl", "Green": "c-gr", "Yellow": "c-yl", "Red": "c-rd"}

def _ribbon(hist, n=60):
    if not hist:
        return ""
    seg = [hc for hc in hist if hc and len(hc) == 2][-n:]
    if len(seg) < 5:
        return ""
    cells = "".join(f'<span class="rb {_RB_CLS.get(c, "c-gr")}" title="{d} {c}"></span>' for d, c in seg)
    return (f'<div class="ribwrap"><div class="riblab">レジーム履歴 {seg[0][0]} → {seg[-1][0]}（記録{len(seg)}日）</div>'
            f'<div class="ribbon">{cells}</div></div>')

def _led(n, tot=11):
    cells = "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(tot))
    return f'<span class="led">{cells}</span>'

def _heatmap_card(ranks):
    recs = [x for x in ((ranks or {}).get("micro") or []) if x.get("w1") == x.get("w1")]
    if len(recs) < 4:
        recs = [x for x in ((ranks or {}).get("macro") or []) if x.get("w1") == x.get("w1")]
    if len(recs) < 4:
        return ""
    recs = sorted(recs, key=lambda x: -x["w1"])
    tiles = []
    for s in recs:
        v = max(-0.06, min(0.06, s["w1"]))
        a = abs(v) / 0.06 * 0.75 + 0.08
        bg = f"rgba(34,197,94,{a:.2f})" if v >= 0 else f"rgba(239,68,68,{a:.2f})"
        tiles.append(f'<div class="hm" style="background:{bg}"><span class="hm-n">{s["ja"]}<span class="hm-tk">{s["tk"]}</span></span>'
                     f'<span class="hm-v">{s["w1"]*100:+.1f}%</span></div>')
    return (f'<div class="card"><h2>セクター温度マップ（週間）</h2>'
            f'<div class="sub">セクター・テーマETFの1週騰落率・強い順（緑=上昇/赤=下落・濃さ=大きさ）</div>'
            f'<div class="hmgrid">{"".join(tiles)}</div></div>')

def _quality_card(q):
    if not q:
        return ""
    rows = [
        ("ユニバース", f'{q.get("uni_ok", 0)}/{q.get("uni_total", 0)} 銘柄'),
        ("分割サスペクト", (f'{q.get("split_suspect")}銘柄 除外' if q.get("split_suspect") else "0（クリーン）")),
        ("RSプール幅", f'{q.get("rs_pool", 0)}銘柄（非サスペクト×$5×$10M内で順位付け）'),
        ("NQ色ソース", {"file": "手動(TradingView)＝正", "estimate": "自動推定(FSM復元)", "none": "無判定"}.get(q.get("nq_src"), q.get("nq_src") or "—")),
        ("次回リバランス", q.get("next_rebal") or "—"),
        ("マクロ未取得", "・".join(q.get("macro_missing") or []) or "なし"),
        ("地合い除外指標", "・".join(q.get("mri_dropped") or []) or "なし"),
        ("センチメント源", "・".join(q.get("senti_src") or []) or "なし"),
        ("決算日キャッシュ", f'{q.get("er_n", 0)}銘柄'),
        ("エクイティCSV", "あり" if q.get("eq") else "未設定"),
        ("状態記録(前回)", str(q.get("state") or "初回")),
    ]
    kv = "".join(f'<div class="kv"><span class="k">{k}</span><span class="v" style="font-weight:600;font-size:11.5px">{v}</span></div>'
                 for k, v in rows)
    return (f'<div class="card"><h2>データ品質</h2>'
            f'<div class="sub">取得状況の自己申告（欠けがあれば数字を割り引いて読む）</div>{kv}</div>')

# ----------------------------------------------------------------------------- X投稿用シェアカード (1200x675)
def build_share_html(aux, sar, mkt, picks, senti, asof_disp):
    color = sar[0]
    hexes = {"Blue": "#1d4ed8", "Green": "#16a34a", "Yellow": "#ca8a04", "Red": "#dc2626"}
    glow = hexes.get(color, "#4b5563")
    cj = _COLOR_JP.get(color, "—")
    band_lab, _ = mri_band(aux["hl"])
    dd = mkt.get("distrib", {})
    ddtxt = " ・ ".join(f"{k} {v['n']}日" for k, v in dd.items()) or "—"
    ranks = [x for x in ((mkt.get("sector_ranks") or {}).get("micro") or []) if x.get("w1") == x.get("w1")]
    top3 = "、".join(s["ja"] for s in sorted(ranks, key=lambda x: -x["w1"])[:3]) or "—"
    chips = "".join(f'<span class="pk">{t}</span>' for t, _, _ in picks)
    seg = [hc for hc in (mkt.get("trend_hist") or []) if hc and len(hc) == 2][-60:]
    rib = "".join(f'<i style="background:{hexes.get(c, "#4b5563")}"></i>' for _, c in seg)
    sn = f'{senti["cur"]:.0f}（{senti["band"]}）' if senti else "—"
    return f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>V38 share</title><style>
body{{margin:0;background:#0b0f17;font-family:'Hiragino Sans','Noto Sans JP',sans-serif}}
.fr{{width:1200px;height:675px;box-sizing:border-box;padding:44px 56px;display:flex;flex-direction:column;
background:radial-gradient(1200px 500px at 80% -10%,{glow}33,transparent),#0b0f17;color:#e6edf3}}
.top{{display:flex;align-items:center;gap:22px}}
.gate{{font-size:56px;font-weight:900;color:#fff;background:{glow};border-radius:18px;padding:10px 34px;box-shadow:0 0 44px {glow}88}}
.ttl{{font-size:30px;font-weight:800;color:#9ecbff}} .asof{{margin-left:auto;font-size:20px;color:#7d8da1}}
.mid{{display:flex;gap:40px;align-items:center;margin:34px 0 8px}}
.mri{{font-size:120px;font-weight:900;line-height:1}} .mrs{{font-size:26px;color:#9fb0c5}}
.kv{{font-size:24px;color:#cbd5e1;line-height:1.9}} .kv b{{color:#fff}}
.rib{{display:flex;gap:2px;margin:22px 0 14px}} .rib i{{flex:1;height:22px;border-radius:3px}}
.pks{{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}}
.pk{{font-size:21px;font-weight:800;color:#9ecbff;background:#16243e;border-radius:9px;padding:5px 14px}}
.ft{{margin-top:auto;font-size:17px;color:#5b6b80}}</style></head><body><div class="fr">
<div class="top"><span class="gate">NQ {cj}</span><span class="ttl">V38 Command Center</span><span class="asof">{asof_disp}</span></div>
<div class="mid"><div><div class="mri">{aux['cur']:.0f}</div><div class="mrs">地合いスコア ・ {band_lab}</div></div>
<div class="kv">傾き <b>{aux['slope']}</b> ／ ベア警戒 <b>{aux['bear_n']}/11</b><br>売り抜け日 <b>{ddtxt}</b><br>群衆温度計 <b>{sn}</b><br>主導 <b>{top3}</b></div></div>
<div class="rib">{rib}</div>
<div class="pks">{chips}</div>
<div class="ft">レジーム履歴（直近{len(seg)}記録）・個人の研究用であり投資助言ではありません</div>
</div></body></html>"""

# ----------------------------------------------------------------------------- setups (D, all chips)
def build_setups(m):
    up200 = m["close"] > m["sma200"]
    up50  = m["close"] > m["sma50"]
    def names(mask):
        sub = m[mask].sort_values("rs", ascending=False)
        return list(sub.index)
    setups = {}
    setups["押し目"]    = names(up200 & up50 & (m["rs"] >= 88) &
                              ((m["close"]/m["ema21"]-1).abs() <= 0.025))
    setups["ブレイク近"] = names(up50 & (m["rs"] >= 88) & (m["dist52"] >= -0.02))
    setups["出来高急増"] = names(up50 & (m["pchg"] > 0) & (m["volx"] >= 2.5) & (m["rs"] >= 85))
    setups["モメンタム"] = names(up50 & (m["rs"] >= 92) & (m["ret21"] >= 0.15))
    setups["ボラ収縮"]  = names(up200 & (m["bbw_pct"] <= 15) & (m["vdry"] <= 0.85) & (m["rs"] >= 80))
    setups["深押し"]    = names(up200 & (m["dist52"] <= -0.15) & (m["rs"] >= 75))
    return setups

def build_buy_today(m, s2i, e2j, s2t, k=20, pick_set=None):
    """本日のピックアップ＝実用セットアップ・スクリーナー（裁量参考・ルール運用とは独立）。
    先導株(リーダー: RS≥85・200MA上)のうち更に厳選(RS90+・ステージ2上昇)を、ブレイク／保ち合い(出来高の枯れ)／押し目／新高値に分類。
    保ち合いは VCP的に「タイトさ bbw_pct」＋「出来高の枯れ vdry(10日平均/50日平均)」で検出。最大k銘柄。"""
    close = m["close"]; sma200 = m["sma200"]; sma50 = m["sma50"]
    base = ((close > sma50) & (sma50 > sma200) & (m["rs"] >= 90) & (m["rs189"] >= 85)
            & (m["close"] >= 5) & (m["dvol"] >= DVOL_FLOOR) & (m["dist52"] >= -0.20))
    # 強くウォッチ価値のあるものだけ: MA整列ステージ2 / RS63・RS189とも上位 / $10M以上 / 52週高値20%以内
    sub = m[base].copy()
    if sub.empty:
        return []

    def classify(r):
        d52 = r["dist52"]; pb = r["pb"]; rvol = r.get("rvol"); vdry = r.get("vdry")
        bbw = r.get("bbw_pct"); e21 = (r["close"]/r["ema21"]-1)*100 if r["ema21"] else 0.0
        dry    = (vdry is not None and vdry == vdry and vdry <= 0.90)
        tight  = (bbw  is not None and bbw  == bbw  and bbw  <= 40)
        vsurge = (rvol is not None and rvol == rvol and rvol >= 1.4)   # 一般則: ブレイクは平常比+40%以上
        if d52 >= -0.03 and vsurge:                       # 新高値圏＋出来高増＝ブレイク中
            return ("ブレイク", "st-break", 0)
        if d52 >= -0.15 and tight and dry and abs(e21) <= 8:   # 高値近く＋タイト＋枯れ＝仕込み
            return ("保ち合い", "st-base", 1)
        if -0.20 <= pb <= -0.06 and r["close"] > r["sma50"]:   # 上昇中に6〜20%押し
            return ("押し目", "st-pull", 2)
        if d52 >= -0.03:                                   # 新高値圏（伸び過ぎ等・様子見）
            return ("新高値", "st-high", 3)
        return (None, None, 9)

    ranked = []
    for t, r in sub.iterrows():
        tag, tcls, prio = classify(r)
        if tag is None:
            continue
        ranked.append((prio, -float(r["rs"]), t, r, tag, tcls))
    ranked.sort(key=lambda x: (x[0], x[1]))               # セットアップ優先→RS降順
    CAPS = {"ブレイク": k, "保ち合い": k, "押し目": 10, "新高値": 10}   # 主役は厚く・補助は薄く
    grp_cnt = {}
    selected = []
    for item in ranked:
        tag = item[4]
        lim = CAPS.get(tag, 10)
        if grp_cnt.get(tag, 0) >= lim:
            continue
        grp_cnt[tag] = grp_cnt.get(tag, 0) + 1
        selected.append(item)
    out = []
    for prio, _nr, t, r, tag, tcls in selected:
        ind = s2i.get(t); indja = e2j.get(ind, ind) if ind else "—"
        vdry = r.get("vdry"); rvol = r.get("rvol")
        pivot = float(r["hi40"]) if (r.get("hi40") and r["hi40"] == r["hi40"]) else float(r["close"])
        out.append(dict(t=t, rs=r["rs"], tag=tag, tcls=tcls,
                        theme=theme_of(t, s2t), ind=subtheme_of(t, s2t, indja),
                        tier_lab=r.get("tier_lab", "—"), tier_key=r.get("tier_key", "none"),
                        dvol=r.get("dvol"), pb=r.get("pb"), pos52=r.get("pos52"),
                        rvol=rvol, vdry=vdry,
                        dry=(vdry is not None and vdry == vdry and vdry <= 0.90),
                        pivot=pivot, stop=pivot * 0.93,   # 裁量エントリーの一般則: ピボット比-7%で損切り
                        held=(pick_set is not None and t in pick_set)))
    return out

def build_vcp(m, s2i, e2j, s2t, k=12):
    """圧縮コイル（VCP）ウォッチ: ステージ2上昇 × 高値圏 × ボラ収縮(BB幅126日下位) × 出来高の枯れ ×
       21EMA上(higher-lows) × ADR生存。締まりが強い順（＝コイルにエネルギーが溜まる順）。
       ★眼を鍛える/ウォッチ専用——VCPの機械エントリーフィルタは検証で全滅。仕掛けはブレイク実現を確認して裁量で。"""
    try:
        base = ((m["close"] > m["sma50"]) & (m["sma50"] > m["sma200"]) & (m["close"] >= m["ema21"])
                & (m["rs"] >= 80) & (m["close"] >= 5) & (m["dvol"] >= DVOL_FLOOR)
                & (m["dist52"] >= -0.20) & (m["bbw_pct"] <= 15)
                & (m["vdry"] <= 0.85) & (m["adr"] >= 0.03))
    except Exception:
        return []
    sub = m[base.fillna(False)].copy()
    if sub.empty:
        return []
    sub = sub.sort_values("bbw_pct", ascending=True)          # 締まり順（tightest coil first）
    out = []
    for t, r in sub.head(k).iterrows():
        ind = s2i.get(t); indja = e2j.get(ind, ind) if ind else "—"
        out.append(dict(t=t, rs=float(r["rs"]), bbw=float(r["bbw_pct"]),
                        vdry=r.get("vdry"), adr=float(r["adr"]), d52=float(r["dist52"]),
                        pb=r.get("pb"), dvol=r.get("dvol"),
                        theme=theme_of(t, s2t), ind=subtheme_of(t, s2t, indja),
                        tier_lab=r.get("tier_lab", "—"), tier_key=r.get("tier_key", "none")))
    return out

# ----------------------------------------------------------------------------- portfolio (A)
def build_betas(W, macro, window=120):
    """各銘柄の対QQQベータ（直近window日の日次リターン回帰 β=cov/var）。QQQ欠損時は空。"""
    spy = macro.get("QQQ")
    if spy is None:
        return pd.Series(dtype=float)
    closes = W.get("Close")
    if closes is None or closes.empty:
        return pd.Series(dtype=float)
    sret = spy["Close"].pct_change()
    rets = closes.pct_change().iloc[-window:]
    s = sret.reindex(rets.index)
    s_dm = s - s.mean()
    var_s = float((s_dm ** 2).mean())
    if not var_s or var_s != var_s:
        return pd.Series(dtype=float)
    cov = rets.sub(rets.mean()).mul(s_dm, axis=0).mean()          # 各銘柄のcov(ret,SPY)
    beta = cov / var_s
    return beta.replace([np.inf, -np.inf], np.nan)

def _beta_card(bv):
    if not bv:
        return ""
    def bcls(x): return "neg" if x >= 1.3 else "pos" if x <= 0.9 else "mut"
    p = bv["port"]
    read = ("市場より大きく動く（攻め）" if p >= 1.3 else "市場並み" if p >= 0.9 else "市場より穏やか")
    def grow(lbl, v, sub):
        return (f'<div class="bt-row"><span class="bt-k">{lbl}</span>'
                f'<b class="{bcls(v)}">{v:.2f}</b><span class="bt-s">{sub}</span></div>') if v is not None else ""
    return (
        f'<div class="card"><h2>マーケット感応度（β vs QQQ）</h2>'
        f'<div class="beta-hero"><div><div class="beta-big {bcls(p)}">{p:.2f}</div>'
        f'<div class="beta-lb">ポートβ（{bv["n"]}銘柄・等加重）</div></div>'
        f'<div class="beta-read">{read}<span class="mut">・QQQが1%動くと約{p:.1f}%</span></div></div>'
        f'<details class="beta-det"><summary>先導株・市場平均・出遅れ株のβ</summary>'
        f'<div class="bt-grid">'
        + grow("先導株（RS≥85）", bv["lead"], "サイクルの先頭・振れ大")
        + grow("市場平均（QQQ）", bv["mkt"], "基準=1.00")
        + grow("出遅れ株（RS≤20）", bv["lag"], "サイクルの後尾")
        + '<div class="mut" style="font-size:10.5px;margin-top:2px">直近120日の日次リターンをQQQに回帰。先導株ほどβが高い＝強気サイクルで先に大きく動く。</div>'
        + '</div></details></div>')

def build_beta_view(m, picks):
    """ポートβ（採用12銘柄の等加重平均）＋先導/市場平均/出遅れの群別β。"""
    if "beta" not in m.columns:
        return None
    b = m["beta"]
    pk = [t for t, _, _ in picks if t in b.index and b[t] == b[t]]
    port = float(np.mean([b[t] for t in pk])) if pk else None
    def grp(mask):
        v = b[mask & b.notna()]
        return float(v.mean()) if len(v) else None
    lead = grp(m["rs189"] >= 85)
    lag = grp(m["rs189"] <= 20)
    if port is None:
        return None
    return dict(port=port, lead=lead, mkt=1.00, lag=lag, n=len(pk))

def build_portfolio(m, s2t):
    # v2確定仕様の適格3条件: 50日SMA>200日SMA × 出来高金額$10M/日 × 株価$5以上（テーマ上限なし）
    # ※「週足SAR非弱気」はアブレーションで撤廃（撤廃版がCAGR+4.4pt/年・Sharpe+0.114・12/12サブサンプルで優位。
    #   代償: 最大DD −31.6→−35.0。危機はNQ4色ゲートが露出制御、平時は勝ち筋(押し目中の最強銘柄)の出禁だった）。
    # ※「終値>50日SMA」も検証外規則として同時削除済み。
    cand = m[(m["sma50"] > m["sma200"])
             & (m["dvol"] >= DVOL_FLOOR) & (m["close"] >= 5)].copy()
    cand = cand.sort_values("rs189", ascending=False)
    # 出遅れ株: 業種内相対 <−20%。※方針変更(2026-07-07): 出遅れも買う。フラグはタグ表示用に残すだけ。
    cand["laggard"] = False
    try:
        if "sec_rel" in cand.columns:
            cand["laggard"] = (cand["sec_rel"] < -0.20).fillna(False)
    except Exception as e:
        print("[warn] laggard flag failed:", e)
        cand["laggard"] = False
    # 思想的除外(バイオ/創薬): 選定から外す。candには excluded_theme フラグを残し表示する。
    cand["excluded_theme"] = [is_excluded_theme(t, s2t) for t in cand.index]
    # リーダー外除外: リーダー(63日RS≥85 かつ 200MA上)でない銘柄は買わない。
    #   RS189の適格を満たしても先導株でなければ選定対象外＝「上から順に、リーダーの中で12銘柄」。
    def _is_leader_row(t):
        try:
            return bool(leader_state(cand.loc[t])[0])
        except Exception:
            return False
    cand["nonleader"] = [not _is_leader_row(t) for t in cand.index]
    # プール = 小型創薬・リーダー外 を除いた上位RS189から N_PORT（出遅れは含める＝買う・タグのみ）。
    pool = cand[~(cand["excluded_theme"] | cand["nonleader"])]
    picks = [(t, theme_of(t, s2t), row) for t, row in pool.head(N_PORT).iterrows()]
    return picks, cand

# ----------------------------------------------------------------------------- leaders + ①〜⑤ states
# Canonical state machine + leader filter from v38_auto.py / SETUP_自動更新.md
# --- 思想的除外テーマ: モメンタム継続性が構造的に効かない業種(選定から外す・表示は残す) ---
#   バイオ/創薬/臨床段階は「治験結果で一夜に倍か半減」でトレンド追随が成立しない。
#   検証: 除外してもCAGR/Sharpe不変(55.9→55.9・te+0.01)=リターン犠牲ゼロで思想を通せる。
# バイオ除外はサブテーマ単位: ヘッドライン一発で±30%飛ぶ投機的小型創薬のみ外す。
# 大手バイオ/大手製薬/GLP-1/手術ロボ/医療機器等はモメンタムで来れば拾う(思想: 大型は別物)。
EXCLUDE_SUBTHEMES = ("臨床段階・中小型バイオ",)
def is_excluded_theme(t, s2t):
    v = s2t.get(t)
    if not isinstance(v, list) or len(v) < 2:
        return False
    sub = v[1] or ""
    return sub in EXCLUDE_SUBTHEMES

LEADER_RS = 85   # リーダー(=先導株)の唯一の定義: 63日RS≥85 かつ 200日線上。
                 # マーケットタブ「リーダー一覧」もピックアップの母集団もこの1定義を参照(重複定義なし)。
BUY_RS = 90                                           # 押し目シグナルは更に厳選: RS>=90
BUY_CAP = 12                                          # 表示上限
STATE_DEF = [("②", "新高値圏/継続", "s-go"),
             ("③", "押し目（形状・参考）", "s-shape"),
             ("①", "伸び過ぎ（待ち）", "s-wait"),
             ("④", "深押し/ベース", "s-deep"),
             ("⑤", "割れ/様子見", "s-break")]

def tag_state(r):
    """Exact replication of v38_auto.py tag(): ①〜⑤ in priority order."""
    dma50 = r["dma50"]; dma21 = r["dma21"]; pb = r["pb"]; ret5 = r["ret5"]
    if (pd.notna(dma50) and r["close"] < r["sma50"]) or (pd.notna(dma21) and dma21 < -0.06):
        return "⑤"
    if pd.notna(pb) and pb < -0.08:
        return "④"
    if (pd.notna(pb) and -0.08 <= pb <= -0.02 and pd.notna(dma21) and -0.05 <= dma21 <= 0.05
            and pd.notna(ret5) and ret5 > -0.03):
        return "③"
    if pd.notna(dma21) and dma21 > 0.10:
        return "①"
    return "②"

_STATE_LABEL = {c: l for c, l, _ in STATE_DEF}
_STATE_SHORT = {"②": "継続", "③": "押し目", "①": "伸び過ぎ", "④": "深押し", "⑤": "割れ"}

def _state_badge(code, nut, nucls, reason=""):
    """状態(①〜⑤)＋値動きニュアンス（堅調/急落中等）のバッジHTML。code空=リーダー外（理由付き）。"""
    nu = f' ・ <b class="{nucls}">{nut}</b>' if nut else ''
    if code:
        return f'<span class="stb stb-{code}">{code}{_STATE_SHORT.get(code,"")}{nu}</span>'
    why = ""
    if reason:
        if "200MA" in reason: why = "：200MA下"
        elif "RS" in reason:  why = "：RS&lt;85"
    return f'<span class="stb stb-none">リーダー外{why}{nu}</span>'

def leader_state(r):
    """RSリーダー判定（RS>=85 かつ 200MA上）と状態①〜⑤。Returns (is_leader, code, label, reason)."""
    rs = r.get("rs"); close = r.get("close"); sma200 = r.get("sma200")
    has_rs = rs is not None and not (isinstance(rs, float) and np.isnan(rs))
    above = close is not None and sma200 is not None and pd.notna(sma200) and close > sma200
    if has_rs and rs >= LEADER_RS and above:
        code = tag_state(r)
        return (True, code, _STATE_LABEL.get(code, ""), "")
    if not has_rs or rs < LEADER_RS:
        return (False, "", "", f"RS{LEADER_RS}未満（リーダー対象外）")
    return (False, "", "", "200MA下（リーダー対象外）")

def momentum_nuance(r):
    """同じ位置でも『堅調に止まっている』のか『急落中』なのかを区別。Returns (tag, note, cls)."""
    pchg = r.get("pchg"); ret5 = r.get("ret5"); adr = r.get("adr")
    if pchg is None or (isinstance(pchg, float) and np.isnan(pchg)):
        return ("", "", "mut")
    a = adr if (adr is not None and adr == adr and adr > 0) else 0.03
    r5 = ret5 if (ret5 is not None and ret5 == ret5) else 0.0
    if pchg <= -1.5 * a or (r5 <= -0.10 and pchg < 0):
        return ("急落中", "下げが速い（急落局面）。投げ（セリングクライマックス）を確認できるまで新規は一服待ち・保有は防御を", "neg")
    if pchg >= 1.0 * a:
        return ("反発中", "下げ止まって切り返し。押し目なら入りやすい局面", "pos")
    if pchg >= -0.5 * a and r5 > -0.05:
        return ("堅調", "値持ちが良く落ち着いた値動き・押しが浅い", "pos")
    return ("軟調", "じり安で方向感に乏しい・様子見", "mut")

def _leaders_watch_card(m, cap=80):
    """リーダー一覧（RS≥85 かつ 200MA上）をRS順のチップで。タップで詳細。ウォッチ用。（旧称「リーダー一覧」を統合）"""
    lead = m[(m["rs"] >= LEADER_RS) & (m["close"] > m["sma200"])].copy()
    if lead.empty:
        return ""
    lead = lead.sort_values("rs189", ascending=False)
    n = len(lead)
    chips = "".join(
        f'<span class="thstk" data-tk="{t}" onclick="thStk(this)">'
        f'<b>{t}</b><span class="thstk-rs">RS{int(round(float(r.get("rs189",0) or 0)))}</span></span>'
        for t, r in lead.head(cap).iterrows())
    more = f'<span class="thmore">+{n-cap}銘柄</span>' if n > cap else ""
    tks = " ".join(lead.head(cap).index.tolist())
    return (f'<div class="card"><h2>リーダー一覧 '
            f'<button class="copybtn" onclick="copyList(this)" data-list="{tks}">📋 コピー</button></h2>'
            f'<div class="sub">RS≥{LEADER_RS}（63日）かつ200日線上＝<b>リーダー</b>・{n}銘柄。ピックアップの候補もこの母集団から。RS強い順・タップで詳細。</div>'
            f'<div class="thstks">{chips}{more}</div></div>')

def build_leaders(m, s2i, e2j, s2t):
    """Leaders = RS>=85 & above 200MA, tagged with state ①〜⑤. Returns (by_state, buys)."""
    lead = m[(m["rs"] >= LEADER_RS) & (m["close"] > m["sma200"])].copy()
    if lead.empty:
        return {}, []
    lead["state"] = lead.apply(tag_state, axis=1)
    lead = lead.sort_values("rs", ascending=False)
    def info(t, r):
        th = theme_of(t, s2t)
        ind = s2i.get(t); indja = e2j.get(ind, ind) if ind else "—"
        nu_tag, _nun, nu_cls = momentum_nuance(r)
        return dict(t=t, rs=r["rs"], theme=th, ind=subtheme_of(t, s2t, indja), pb=r["pb"],
                    dma21=r["dma21"], ret20=r["ret20"], adr=r["adr"], rvol=r["rvol"],
                    close=r["close"], state=r["state"], nut=nu_tag, nucls=nu_cls,
                    tier_lab=r.get("tier_lab", "—"), tier_key=r.get("tier_key", "none"),
                    mcap=r.get("mcap"), dvol=r.get("dvol"))
    by_state = {}
    for code, _, _ in STATE_DEF:
        sub = lead[lead["state"] == code]
        by_state[code] = [info(t, r) for t, r in sub.iterrows()]
    # 本日◎押し目: state ③ かつ RS>=BUY_RS で厳選 (entry range + 初期ストップ; 利確はトレール)
    buys = []
    sub3 = lead[(lead["state"] == "③") & (lead["rs"] >= BUY_RS)].sort_values("rs", ascending=False)
    for t, r in sub3.head(BUY_CAP).iterrows():
        adr_d = r["close"] * r["adr"]
        lo = max(r["sma21"] - 0.5*adr_d, r["hi40"]*0.92)
        hiR = r["close"]
        if lo >= hiR:
            lo = hiR * 0.985
        mid = (lo + hiR) / 2
        d = info(t, r); d.update(lo=lo, hi=hiR, t15=mid*1.15, t30=mid*1.30)
        buys.append(d)
    return by_state, buys

# ----------------------------------------------------------------------------- sector RS
def build_sector_rs(m, s2i, e2j, s2t):
    """サブテーマ(s2t)単位で括る（量子/メモリ/AI GPU等を分離・銘柄選定とは独立の参考ランキング）。"""
    grp = {}
    sub_parent = {}
    for t in m.index:
        st = s2t.get(t)
        sth = st[1] if (isinstance(st, list) and len(st) >= 2 and st[1] and st[1] not in ("?", "")) else None
        if not sth:
            continue
        grp.setdefault(sth, []).append(t)
        if sth not in sub_parent and isinstance(st, list) and st[0]:
            sub_parent[sth] = st[0].split(". ", 1)[-1] if ". " in st[0] else st[0]
    recs = []
    for nm, tks in grp.items():
        if len(tks) < 2:                       # 少数でも可（ランキング参考用）
            continue
        sub = m.loc[tks]
        pairs = sorted(((t, float(sub.at[t, "rs"])) for t in tks),
                       key=lambda x: -(x[1] if x[1] == x[1] else -9))   # RS desc
        med63 = float(np.nanmedian(sub["rs"]))
        med189 = float(np.nanmedian(sub["rs189"])) if "rs189" in sub.columns else med63
        prev = float(np.nanmedian(sub["rs_l1"])) if "rs_l1" in sub.columns else med63
        # 定点比較: 現在のRS中央値 − 各時点のRS中央値（先週/2週前/1ヶ月前）
        _pw1 = float(np.nanmedian(sub["rs_w1"])) if "rs_w1" in sub.columns else med63
        _pw2 = float(np.nanmedian(sub["rs_w2"])) if "rs_w2" in sub.columns else med63
        _pm1 = prev
        d_w1 = (med63 - _pw1) if (med63 == med63 and _pw1 == _pw1) else 0.0   # 先週比
        d_w2 = (med63 - _pw2) if (med63 == med63 and _pw2 == _pw2) else 0.0   # 2週間前比
        d_m1 = (med63 - _pm1) if (med63 == med63 and _pm1 == _pm1) else 0.0   # 1ヶ月前比
        recs.append(dict(ja=nm, parent=sub_parent.get(nm, "—"), n=len(tks),
                         med=med63, med189=med189,
                         drs=(med63 - prev) if (med63 == med63 and prev == prev) else 0.0,
                         d_w1=d_w1, d_w2=d_w2, d_m1=d_m1,
                         d1=float(np.nanmedian(sub["pchg"])),
                         w1=float(np.nanmedian(sub["ret5"])),
                         m1=float(np.nanmedian(sub["ret21"])),
                         members=pairs))
    if not recs:
        return []
    df = pd.DataFrame(recs)
    # スコア = 63日RS(勢い) と 189日RS(持続) の中央値ランクを均等ブレンド → 0-100
    df["score"] = (df["med"].rank(pct=True) * 0.5 + df["med189"].rank(pct=True) * 0.5) * 100
    df = df.sort_values(["score", "med"], ascending=False).reset_index(drop=True)
    return df.to_dict("records")

# ----------------------------------------------------------------------------- テーマ・ドリルダウン（2階層: 中テーマ → 中の銘柄RSローテ）
def load_theme_map():
    """ticker→中テーマ の対応（committed JSON）。env V38_THEME_JSON→/mnt/project→同階層→カレント。"""
    import json as _j
    paths = [os.environ.get("V38_THEME_JSON"), "/mnt/project/theme_map.json",
             os.path.join(os.path.dirname(CACHE or "."), "theme_map.json"), "theme_map.json"]
    for p in paths:
        if p and os.path.exists(p):
            try:
                return _j.load(open(p, encoding="utf-8"))
            except Exception:
                pass
    return {}

def build_theme_drill(m, tmap, min_members=3):
    """中テーマ別に構成銘柄のRS189(強さ)とRSランクΔ(勢い)を集計。強い順。"""
    if not tmap or "rs189" not in m.columns:
        return []
    from collections import defaultdict
    groups = defaultdict(list)
    for t in m.index:
        th = tmap.get(t)
        if not th:
            continue
        rs = m.at[t, "rs189"]
        if rs is None or (isinstance(rs, float) and np.isnan(rs)):
            continue
        mom = m.at[t, "rs189_d"] if "rs189_d" in m.columns else 0.0
        r21 = m.at[t, "ret21"] if "ret21" in m.columns else np.nan
        groups[th].append(dict(t=t, rs=float(rs), mom=float(mom) if mom == mom else 0.0,
                               ret21=float(r21) if r21 == r21 else 0.0))
    out = []
    for th, mem in groups.items():
        if len(mem) < min_members:
            continue
        mem.sort(key=lambda x: -x["rs"])
        rs_med = float(np.median([x["rs"] for x in mem]))
        mom_med = float(np.median([x["mom"] for x in mem]))
        q = ("主導" if rs_med >= 50 and mom_med >= 0 else "弱化" if rs_med >= 50
             else "改善" if mom_med >= 0 else "停滞")
        out.append(dict(name=th, n=len(mem), rs=rs_med, mom=mom_med, q=q, members=mem))
    out.sort(key=lambda d: -d["rs"])
    return out

def _theme_drill_card(themes):
    if not themes:
        return ""
    def tile(i, th):
        rs = th["rs"]; g = rs >= 50
        inten = min(1.0, abs(rs - 50) / 42)
        bg = (f"rgba(34,197,94,{0.14+inten*0.34:.2f})" if g else f"rgba(239,68,68,{0.14+inten*0.34:.2f})")
        arr = "▲" if th["mom"] > 1.5 else "▼" if th["mom"] < -1.5 else "▬"
        acol = "#4ade80" if th["mom"] > 1.5 else "#f87171" if th["mom"] < -1.5 else "#8fa0b5"
        return (f'<button class="thtile" style="background:{bg}" onclick="thDrill({i})" id="tht-{i}">'
                f'<span class="tht-n">{th["name"]}</span>'
                f'<span class="tht-m"><b>RS{rs:.0f}</b> <span style="color:{acol}">{arr}</span>'
                f'<span class="tht-c">{th["n"]}銘柄</span></span></button>')
    tiles = "".join(tile(i, th) for i, th in enumerate(themes))
    panels = ""
    for i, th in enumerate(themes):
        chips = "".join(
            f'<span class="thstk" data-tk="{x["t"]}" onclick="thStk(this)">'
            f'<b>{x["t"]}</b><span class="thstk-rs">RS{x["rs"]:.0f}</span>'
            f'<span class="thstk-m" style="color:{"#4ade80" if x["mom"]>1.5 else "#f87171" if x["mom"]<-1.5 else "#7d8da1"}">'
            f'{"▲" if x["mom"]>1.5 else "▼" if x["mom"]<-1.5 else "▬"}</span></span>'
            for x in th["members"][:24])
        more = f'<span class="thmore">+{len(th["members"])-24}銘柄</span>' if len(th["members"]) > 24 else ""
        panels += (f'<div class="thpanel" id="thp-{i}" style="display:none">'
                   f'<div class="thpanel-h">{th["name"]}・{th["n"]}銘柄 <span class="mut">（RS強い順・タップで詳細）</span></div>'
                   f'<div class="thstks">{chips}{more}</div></div>')
    return (f'<div class="card"><h2>テーマ・ドリルダウン</h2>'
            f'<div class="sub">中テーマの強さ順（緑=強い/濃さ=強度・▲=RSランク上昇中）。'
            f'<b>タップでその中の銘柄ローテ</b>（RS強い順）を表示。</div>'
            f'<div class="thgrid">{tiles}</div>{panels}</div>')

# equal-weight sector ETF RS — market-representative, unbiased, complete (11 GICS sectors)
SECTOR_ETFS = [("RSPT","情報技術"),("RSPF","金融"),("RSPN","資本財"),("RSPD","一般消費財"),
               ("RSPM","素材"),("RSPC","通信"),("RSPU","公益"),("RSPS","生活必需品"),
               ("RSPH","ヘルスケア"),("RSPR","不動産"),("RSPG","エネルギー")]

def build_sector_etf_rs(macro):
    recs = []
    rets63 = {}
    for tk, ja in SECTOR_ETFS:
        if tk not in macro:
            continue
        c = macro[tk]["Close"].dropna()
        if len(c) < 70:
            continue
        last = float(c.iloc[-1])
        def r(d):
            return (last/float(c.iloc[-d-1])-1) if len(c) > d else np.nan
        rets63[tk] = r(63)
        recs.append(dict(tk=tk, ja=ja, d1=r(1), w1=r(5), m1=r(21), r63=r(63)))
    if not recs:
        return []
    sr = pd.Series({x["tk"]: x["r63"] for x in recs}).rank(pct=True) * 100
    for x in recs:
        x["rs"] = float(sr[x["tk"]])
    recs.sort(key=lambda x: (-(x["r63"] if x["r63"] == x["r63"] else -9)))
    return recs

# 小分類（業種テーマETF）— sector_etf.csv から代表を厳選（重複テーマは1本に集約）
MICRO_ETFS = [("SMH","半導体"),("XSD","半導体EW"),("DRAM","メモリ"),("SOXX","半導体装置"),
              ("DTCR","データセンター"),("IGV","ソフトウェア"),("WCLD","クラウドSaaS"),("SKYY","クラウド基盤"),
              ("CIBR","サイバー"),("AIQ","AI"),("QTUM","量子・次世代"),("BOTZ","ロボティクス"),("ARKW","次世代ネット"),
              ("XBI","バイオテック"),("IHI","医療機器"),("PPH","製薬"),("GNOM","ゲノム"),
              ("KBE","銀行"),("KRE","地銀"),("IAI","証券・取引所"),("KIE","保険"),
              ("XOP","石油探査"),("OIH","油田サービス"),("XES","油田装置"),
              ("TAN","ソーラー"),("ICLN","クリーンEN"),("GRID","スマートグリッド"),("FAN","風力"),
              ("URA","ウラン"),("NLR","原子力"),("LIT","リチウム電池"),("HYDR","水素"),
              ("GDX","金鉱"),("SIL","銀鉱"),("COPX","銅鉱"),("XME","金属・鉱業"),("SLX","鉄鋼"),("REMX","レアアース"),
              ("ITA","航空宇宙・防衛"),("SHLD","防衛テック"),("XAR","宇宙・防衛"),
              ("JETS","航空"),("IYT","運輸"),("BOAT","海運"),
              ("XHB","住宅建設"),("PAVE","インフラ"),("PKB","建設"),
              ("XRT","小売"),("IBUY","EC"),("PEJ","レジャー"),
              ("BLOK","ブロックチェーン"),("WGMI","BTCマイニング"),("DRIV","EV・自動運転"),
              ("MOO","農業"),("PHO","水関連"),("WOOD","林業")]

# RRG用の厳選テーマ（読みやすさ優先で16本・半導体は特別マーカー）
RRG_THEMES = [("SMH","半導体"),("SOXX","半導体装置"),("DTCR","データセンター"),
              ("IGV","ソフトウェア"),("CIBR","サイバー"),("AIQ","AI"),
              ("XBI","バイオテック"),("IHI","医療機器"),
              ("KBE","銀行"),("IAI","証券"),
              ("XOP","石油探査"),("OIH","油田"),
              ("GDX","金鉱"),("XME","金属"),("URA","ウラン"),
              ("ITA","防衛"),("PAVE","インフラ"),("IYT","運輸")]

def load_market_extras(period="9mo"):
    """小分類テーマETF + QQQE + ^VIX6M をライブ取得（macroキャッシュとは独立・失敗時は空dict）。
       返り値: {ticker: Close系列}。本番/サンドボックス両方で常にライブ取得。"""
    tks = [t for t, _ in MICRO_ETFS] + ["QQQE", "^VIX6M"]
    out = {}
    try:
        import yfinance as yf, warnings as _w
        _w.filterwarnings("ignore")
        df = yf.download(tks, period=period, interval="1d", progress=False, threads=True)
        if df is None or getattr(df, "empty", True):
            return out
        cl = df["Close"] if isinstance(df.columns, pd.MultiIndex) and "Close" in df.columns.get_level_values(0) else df
        for t in tks:
            try:
                s = cl[t].dropna() if hasattr(cl, "columns") and t in cl.columns else None
                if s is not None and len(s) >= 22:
                    out[t] = s
            except Exception:
                pass
    except Exception as e:
        sys.stderr.write(f"[extras] fetch failed: {e}\n")
    return out

def _rank_etfs(close_dict, etf_list, minbars=22):
    """{tk: Close系列} と [(tk,ja)] から d1/w1/m1 を計算した recs を返す。"""
    recs = []
    for tk, ja in etf_list:
        c = close_dict.get(tk)
        if c is None:
            continue
        c = c.dropna()
        if len(c) < minbars:
            continue
        last = float(c.iloc[-1])
        def r(d):
            return (last/float(c.iloc[-d-1]) - 1) if len(c) > d else np.nan
        recs.append(dict(tk=tk, ja=ja, d1=r(1), w1=r(5), m1=r(21)))
    return recs

def build_sector_ranks(macro, extras):
    """大分類(11セクター・等ウェイトRSP*=キャッシュ) と 小分類(テーマ=ライブextras) の d1/w1/m1。"""
    macro_close = {tk: macro[tk]["Close"] for tk, _ in SECTOR_ETFS if tk in macro}
    return {"macro": _rank_etfs(macro_close, SECTOR_ETFS),
            "micro": _rank_etfs(extras, MICRO_ETFS)}

# ----------------------------------------------------------------------------- breadth + yields
def build_breadth(m):
    n = len(m)
    a200 = (m["close"] > m["sma200"]).sum()
    a50  = (m["close"] > m["sma50"]).sum()
    adv  = (m["pchg"] > 0).sum()
    dec  = (m["pchg"] < 0).sum()
    nh   = (m["dist52"] >= -0.005).sum()
    return dict(n=int(n),
                pa200=100*a200/n, pa50=100*a50/n,
                adv=int(adv), dec=int(dec),
                adpct=100*adv/max(adv+dec,1),
                nh=int(nh), pnh=100*nh/n)

def build_yields(macro):
    out = {}
    for tk, lab in [("^TNX","米10年"), ("^FVX","米5年"), ("^TYX","米30年")]:
        if tk in macro:
            c = macro[tk]["Close"].dropna()
            if len(c) >= 2:
                out[lab] = dict(y=float(c.iloc[-1]), chg=float(c.iloc[-1]-c.iloc[-2]))
    return out

def build_breadth_ts(W, lookback=CHART_LB):
    """% of universe above its 200-day MA, as a daily time series (S5TH analog)."""
    C = W["Close"]
    sma200 = C.rolling(200, min_periods=150).mean()
    # 十分な銘柄数(母数の6割以上)が200MAを持つ日からのみ集計→頭のスカスカ区間を除去
    valid_cnt = sma200.notna().sum(axis=1)
    uni_cnt = C.notna().sum(axis=1)
    ok = valid_cnt >= (uni_cnt * 0.6).clip(lower=30)
    pct = ((C > sma200).sum(axis=1) / uni_cnt.replace(0, np.nan) * 100)
    pct = pct[ok].dropna()
    s = pct.iloc[-lookback:]
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]

def build_dollarvol_ts(W, macro=None, lookback=CHART_LB, smooth=21):
    """売買代金推移: ユニバース合算(終値×出来高の総和)＋QQQ/SPYの売買代金を、
       <b>21日平滑</b>してから期間開始=100にリベース（日次スパイクで潰れないよう平滑）。約2年。
       あわせてユニバース売買代金のトレンド（拡大/縮小）を判定してコメント用に返す。表示専用。"""
    C = W.get("Close"); V = W.get("Volume")
    if C is None or V is None or getattr(C, "shape", (0,))[0] < 30:
        return None
    dv_raw = (C * V).sum(axis=1, min_count=1)
    cnt = C.notna().sum(axis=1)
    uni = int(cnt.max()) if len(cnt) else 0
    if uni:
        dv_raw = dv_raw[cnt >= 0.6 * uni]
    dv_raw = dv_raw.dropna()
    if len(dv_raw) < max(60, smooth + 5):
        return None
    mp = max(5, smooth // 2)
    dvs = dv_raw.rolling(smooth, min_periods=mp).mean().dropna()
    # ユニバース売買代金のトレンド（平滑後・3ヶ月前比＋直近1ヶ月の向き）
    uni_trend = None
    if len(dvs) >= 80:
        cur = float(dvs.iloc[-1]); ref = float(dvs.iloc[-min(len(dvs), 63)])
        s21 = float(dvs.iloc[-min(len(dvs), 21)])
        pct = (cur / ref - 1) if ref else 0.0
        if pct >= 0.08 and cur >= s21:
            d = "拡大"
        elif pct <= -0.08 and cur <= s21:
            d = "縮小"
        else:
            d = "横ばい"
        uni_trend = dict(dir=d, pct=pct * 100, sig=abs(pct) >= 0.08, cur=cur)
    idx = dvs.iloc[-lookback:].index
    raw_series = [("ユニバース合算", dv_raw, "#38bdf8")]
    if macro:
        for key, color in (("QQQ", "#a78bfa"), ("SPY", "#7ff0a8")):
            d = macro.get(key)
            if d is None:
                continue
            raw_series.append((key, (d["Close"] * d["Volume"]).dropna(), color))
    out = {"dates": [dd.strftime("%Y-%m-%d") for dd in idx], "series": [],
           "span": _span_label([(dd.strftime("%Y-%m-%d"), 0.0) for dd in idx]),
           "uni_trend": uni_trend, "smooth": smooth}
    for name, s, color in raw_series:
        sm_full = s.rolling(smooth, min_periods=mp).mean()          # 21日平滑（全期間）
        ma200 = sm_full.rolling(200, min_periods=60).mean()         # 自分の200日平均
        ratio = (sm_full / ma200).reindex(idx).ffill().bfill()      # 参加度＝平滑売買代金÷200日平均
        rv = ratio.dropna()
        if rv.empty:
            continue
        smv = sm_full.reindex(idx).ffill().bfill().dropna()
        last_abs = float(smv.iloc[-1]) if len(smv) else float("nan")
        chg20 = (last_abs / float(smv.iloc[-min(len(smv), 21)]) - 1) * 100 if len(smv) else 0.0
        out["series"].append(dict(
            name=name, color=color, last_abs=last_abs, chg20=chg20, last_ratio=float(rv.iloc[-1]),
            ys=[(float(v) if v == v else None) for v in ratio.values]))
    return out if out["series"] else None

def _updown_state(v):
    """上げ日/下げ日 売買代金比の状態（O'Neil式 集積/分散）。"""
    if v >= 1.25: return ("集積（買い集め優勢）", "#7ff0a8", "accum")
    if v >= 1.00: return ("集積寄り", "#9ae6b4", "accum")
    if v >= 0.80: return ("分散寄り（注意）", "#fcd34d", "distrib")
    return ("分散（売り抜け優勢）", "#fca5a5", "distrib")

def build_updown_vol_ts(W, macro=None, lookback=CHART_LB, win=20):
    """上げ日出来高÷下げ日出来高（20日・ユニバース合算$売買代金）。O'Neil式の集積/分散。
       市場の方向はQQQ日次で判定（取れなければ等加重ユニバース平均リターン）。>1=買い集め優勢。表示専用。"""
    C = W.get("Close"); V = W.get("Volume")
    if C is None or V is None or getattr(C, "shape", (0,))[0] < win + 10:
        return None
    dv = (C * V).sum(axis=1, min_count=1)
    cnt = C.notna().sum(axis=1)
    uni = int(cnt.max()) if len(cnt) else 0
    if uni:
        dv = dv[cnt >= 0.6 * uni]
    dv = dv.dropna()
    ret = None
    if macro and macro.get("QQQ") is not None:
        ret = macro["QQQ"]["Close"].pct_change().reindex(dv.index)
    if ret is None or ret.notna().sum() < win + 10:
        ret = C.pct_change().reindex(dv.index).mean(axis=1)
    up = dv.where(ret > 0, 0.0); dn = dv.where(ret < 0, 0.0)
    ups = up.rolling(win).sum(); dns = dn.rolling(win).sum()
    ratio = (ups / dns.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(ratio) < 20:
        return None
    s = ratio.iloc[-lookback:]
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]

def _updown_vol_card(ts):
    """集積/分散: 上げ日/下げ日 売買代金比の推移・1.0基準線つき。"""
    if not ts or len(ts) < 5:
        return ""
    raw_last = ts[-1][1]
    ys = [min(3.0, max(0.2, v)) for _, v in ts]      # 表示クランプ（スパイク抑制）
    n = len(ys)
    Wd, Ht, pad = 680, 180, 6
    lo, hi = min(ys), max(ys); lo = min(lo, 0.85); hi = max(hi, 1.20)
    rng = (hi - lo) or 1
    lo2, hi2 = lo - rng * 0.08, hi + rng * 0.08; rng2 = (hi2 - lo2) or 1
    def X(i): return pad + i * (Wd - 2 * pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo2) / rng2) * (Ht - 2 * pad)
    # ゾーン塗り（>1.25集積 / <0.8分散）
    zr = ""
    if hi2 > 1.25:
        zr += f'<rect x="{pad}" y="{Y(hi2):.1f}" width="{Wd-2*pad}" height="{max(0.0,Y(1.25)-Y(hi2)):.1f}" fill="#22c55e" opacity="0.06"/>'
    if lo2 < 0.80:
        zr += f'<rect x="{pad}" y="{Y(0.80):.1f}" width="{Wd-2*pad}" height="{max(0.0,Y(lo2)-Y(0.80)):.1f}" fill="#ef4444" opacity="0.06"/>'
    gl = ""
    for g in (0.8, 1.0, 1.25):
        if not (lo2 <= g <= hi2):
            continue
        is1 = abs(g - 1.0) < 1e-9
        stroke = "#3b4b63" if is1 else "#1c2533"
        dash = ' stroke-dasharray="4 3"' if is1 else ""
        gl += (f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="{stroke}" stroke-width="1"{dash}/>'
               f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g:.2f}</text>')
    area = (f"M{X(0):.1f},{Y(ys[0]):.1f} " + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
            + f" L{X(n-1):.1f},{Ht-pad:.1f} L{X(0):.1f},{Ht-pad:.1f} Z")
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    state, col, _reg = _updown_state(raw_last)
    svg = (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
           f'<defs><linearGradient id="uvg" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="{col}" stop-opacity="0.28"/>'
           f'<stop offset="1" stop-color="{col}" stop-opacity="0"/></linearGradient></defs>'
           f'{zr}{gl}<path d="{area}" fill="url(#uvg)"/>'
           f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>'
           f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="{col}"/></svg>')
    return (f'<div class="card"><h2>集積／分散（上げ日÷下げ日 売買代金）</h2>'
            f'<div class="sub">上げ日の売買代金 ÷ 下げ日の売買代金（20日・ユニバース合算）。O\'Neil式。'
            f'<b>1.0超＝買い集め優勢</b>（上げ日に金が集まる）／<b>1.0割れ＝売り抜け優勢</b>。'
            f'ブレッドスやディストリビューション・デイとは独立した「本物か」の裏取り。表示専用。</div>'
            f'<div class="chart">{svg}'
            f'<div class="cap cap-c"><span style="color:{col};font-weight:700">現在 {raw_last:.2f}（{state}）</span></div>'
            f'{_date_axis(ts)}</div></div>')

def build_ratio_ts(macro, num, den_keys, lookback=CHART_LB):
    """num / basket(den_keys) の比率を期間先頭=100にリベースした系列（B-2/B-3用）。
    分母バスケットは各系列を初期値=1に正規化してから平均（生値平均だと高株価ETFに過重になるのを修正）。"""
    cl = lambda k: macro[k]["Close"] if k in macro else None
    n = cl(num)
    dens = [cl(k) for k in den_keys if cl(k) is not None]
    if n is None or not dens:
        return []
    df = pd.concat([n] + dens, axis=1).sort_index().ffill().dropna()
    if len(df) < 30:
        return []
    den_norm = df.iloc[:, 1:].apply(lambda col: col / col.iloc[0], axis=0).mean(axis=1)
    ratio = (df.iloc[:, 0] / df.iloc[:, 0].iloc[0]) / den_norm
    s = ratio.iloc[-lookback:]
    if len(s) < 20:
        return []
    mu = float(s.mean()); sd = float(s.std())
    if not sd or sd != sd:
        return []
    z = (s - mu) / sd                                  # 平均からの偏差(σ)＝狭い比率でも足元の強弱が読める
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in z.items()]

import math as _math_em

def build_expected_move(macro, m=None, picks=None, horizon=21):
    """オプション想定変動幅（下値予測）。
       市場=VIX/VXN（=S&P/Nasdaqのオプション・インプライド・ボラ）／個別=ADR（実現ボラ）。
       1σ move ≈ price × σ_daily × √(horizon)。個別のyfinance IVは歯抜けで信頼不可のためADRで代替。"""
    out = {"market": [], "holdings": [], "horizon": horizon}
    def last(k):
        try:
            return float(macro[k]["Close"].dropna().iloc[-1])
        except Exception:
            return None
    def _mkt(sym, volkey, mult=1.0, label=None):
        px = last(sym)
        iv = last(volkey)
        if iv is None:
            v = last("^VIX")
            iv = (v * mult) if v is not None else None
        if px is None or not iv:
            return
        ivf = iv / 100.0
        em = ivf * _math_em.sqrt(horizon / 252.0)          # horizon日 1σ（年率IV→期間換算）
        out["market"].append(dict(sym=sym, label=label or sym, px=px, iv=iv, em=em,
                                  dn1=px * (1 - em), dn2=px * (1 - 2 * em), up1=px * (1 + em)))
    _mkt("SPY", "^VIX", label="SPY（VIX）")
    _mkt("QQQ", "^VXN", mult=1.15, label="QQQ（VXN）")
    if m is not None and picks:
        for t, _, r in picks:
            adr = r.get("adr"); px = r.get("close")
            if adr is None or adr != adr or px is None or px != px:
                continue
            em = float(adr) * 0.55 * _math_em.sqrt(horizon)  # ADR≈日中レンジ→日次σ≈ADR×0.55, N日1σ
            out["holdings"].append(dict(t=t, px=float(px), adr=float(adr), em=em, dn1=float(px) * (1 - em)))
    return out

def _expected_move_card(em):
    """オプション/ボラ想定変動幅カード（市場VIX/VXN・~1ヶ月の下値バンド）。"""
    if not em or not em.get("market"):
        return ""
    hd = em.get("horizon", 21)
    rows = ""
    for mk in em["market"]:
        rows += (f'<div class="le-row"><span class="le-k">{mk["label"]}</span>'
                 f'<span class="le-sub">IV {mk["iv"]:.1f}% ・ 1σ <b>±{mk["em"]*100:.1f}%</b> '
                 f'→ 下値 <b class="neg">{mk["dn1"]:.0f}</b>（−{mk["em"]*100:.1f}%）／2σ {mk["dn2"]:.0f}'
                 f'<span class="mut">・現在 {mk["px"]:.0f}</span></span></div>')
    return (f'<div class="card"><h2>オプション想定変動幅（VIX/VXN・約1ヶ月）</h2>'
            f'<div class="sub">株価指数のオプションが織り込む{hd}営業日先の<b>1σ変動</b>と下値目安。'
            f'VIX/VXN＝S&P/Nasdaqのインプライド・ボラ。<b>下値1σ＝約68%はこの中に収まる想定</b>（2σ≒95%）。'
            f'保有個別の想定下値は<b>ADR（実現ボラ）</b>ベースでポート表に反映（出口線がノイズ内なら印）。表示専用。</div>'
            f'{rows}</div>')

def build_vix_term_ts(macro, lookback=CHART_LB):
    """B-4a: VIX/VIX3M の生比率系列（リベースしない・1.0が構造的原点）。"""
    cl = lambda k: macro[k]["Close"] if k in macro else None
    v1, v3 = cl("^VIX"), cl("^VIX3M")
    if v1 is None or v3 is None:
        return []
    df = pd.concat([v1, v3], axis=1).sort_index().ffill().dropna()
    if len(df) < 30:
        return []
    r = (df.iloc[:, 0] / df.iloc[:, 1]).iloc[-lookback:]
    return [(d.strftime("%Y-%m-%d"), float(x)) for d, x in r.items()]

def build_adline_ts(W, lookback=CHART_LB):
    """騰落ライン→マクレラン・オシレーター（足元の広がりの勢い）。
       RANA=(adv−dec)/(adv+dec)×1000 の EMA19−EMA39。0中心・プラス=買い広がり/マイナス=売り広がり。
       2年累積ラインは"遅い確認"で200日線上%と重複するため、足元感応のオシレーターに変更。"""
    C = W["Close"]
    ret = C.pct_change()
    adv = (ret > 0).sum(axis=1); dec = (ret < 0).sum(axis=1)
    denom = (adv + dec).replace(0, np.nan)
    rana = ((adv - dec) / denom * 1000.0).dropna()     # 銘柄数に依存しない正規化ネット
    if len(rana) < 45:
        return []
    osc = (rana.ewm(span=19, adjust=False).mean() - rana.ewm(span=39, adjust=False).mean())
    s = osc.iloc[-lookback:]
    if len(s) < 5:
        return []
    return [(d.strftime("%Y-%m-%d"), float(x)) for d, x in s.items()]

def build_distribution(macro):
    """IBD-style distribution days: down >=0.2% on higher volume than prior day,
    counted over the trailing 25 sessions, for SPY & QQQ. A distribution day is
    washed out once the index later closes >=5% above that day's close (IBD rally reset)."""
    out = {}
    for tk in ["SPY", "QQQ"]:
        if tk not in macro:
            continue
        df = macro[tk].dropna()
        if len(df) < 30:
            continue
        c = df["Close"]; v = df["Volume"]
        dist = (c / c.shift(1) - 1 <= -0.002) & (v > v.shift(1))
        win = dist.iloc[-25:]
        days = []
        for d, hit in win.items():
            if not bool(hit):
                continue
            cd = float(c.loc[d])
            future = c.loc[c.index > d]          # その日より後の終値
            if len(future) and float(future.max()) >= cd * 1.05:
                continue                         # +5%上昇でリセット → カウントしない
            days.append(d.strftime("%-m/%-d"))
        n = len(days)
        if n >= 6:   st, cls = "調整警戒", "bad"
        elif n >= 4: st, cls = "観察",    "warn"
        else:        st, cls = "良好",    "good"
        out[tk] = dict(n=n, st=st, cls=cls, days=days)
    return out

def build_ftd(macro, idxs=(("QQQ", "NASDAQ100"), ("SPY", "S&P500"))):
    """フォロースルー・デイ（一般定義準拠）:
    Day1 = 調整安値の当日（プラス引けの場合）または安値後で最初に前日比プラス引けした日。
    Day4以降に 前日比+1.25%以上 × 出来高が前日超 の確認日が出れば点灯。
    ラリー中に日中安値を割れたら試行リセット（Day1から数え直し）。"""
    out = []
    for tk, lab in idxs:
        d = macro.get(tk)
        if d is None:
            continue
        df = d.dropna(subset=["Close"])
        if len(df) < 30:
            continue
        c = df["Close"]
        l = df["Low"] if "Low" in df.columns else df["Close"]
        v = df["Volume"] if "Volume" in df.columns else None
        N = min(60, len(c))
        cc = c.iloc[-N:]; ll = l.iloc[-N:]
        vv = v.iloc[-N:] if v is not None else None
        low_v, low_i = float(ll.iloc[0]), 0
        day1, ftd_ago, ftd_pct = None, None, None
        for j in range(1, N):
            if float(ll.iloc[j]) < low_v:                 # 日中安値の更新＝試行リセット
                low_v, low_i = float(ll.iloc[j]), j
                day1 = j if float(cc.iloc[j]) > float(cc.iloc[j - 1]) else None
                ftd_ago = None
                continue
            if day1 is None:
                if float(cc.iloc[j]) > float(cc.iloc[j - 1]):
                    day1 = j                              # 安値後で最初のプラス引け＝Day1
                else:
                    continue
            att = j - day1 + 1                            # ラリー試行の日数（Day1=1）
            if att >= 4:
                chg = float(cc.iloc[j]) / float(cc.iloc[j - 1]) - 1
                volup = (vv is not None and float(vv.iloc[j]) > float(vv.iloc[j - 1]))
                if chg >= 0.0125 and volup:
                    ftd_ago, ftd_pct = (N - 1) - j, chg
        days_low = (N - 1) - low_i
        att_day = ((N - 1) - day1 + 1) if day1 is not None else 0
        sma50 = c.rolling(50).mean().iloc[-1] if len(c) >= 50 else None
        above50 = bool(sma50 is not None and sma50 == sma50 and float(c.iloc[-1]) >= float(sma50))
        if ftd_ago is not None and ftd_ago <= 15:
            st, cls = f"点灯 {ftd_ago}日前 +{ftd_pct * 100:.1f}%", "pos"
        elif above50 and days_low >= 12:
            st, cls = "上昇継続中", "mut"
        elif not above50 and att_day >= 1:
            st, cls = f"試行 {att_day}日目・確認待ち", "warnt"
        elif not above50:
            st, cls = "安値模索（試行未開始）", "mut"
        else:
            st, cls = "—", "mut"
        out.append(dict(tk=tk, lab=lab, st=st, cls=cls))
    return out

def _perf_one(c):
    last = float(c.iloc[-1])
    def ret(d):
        return (last / float(c.iloc[-d-1]) - 1) if len(c) > d else None
    jan = c[c.index.year == c.index[-1].year]
    ytd = (last / float(jan.iloc[0]) - 1) if len(jan) else None
    hi52 = float(c.iloc[-252:].max()); lo52 = float(c.iloc[-252:].min())
    pos = (last - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None
    sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else None
    ext200 = (last / float(sma200) - 1) if sma200 and not np.isnan(sma200) else None
    return dict(ytd=ytd, w1=ret(5), m1=ret(21), y1=ret(252), pos52=pos, ext200=ext200)

def build_perf(macro, extras=None):
    """Performance: cap-weight (SPY/QQQ) + equal-weight/breadth (RSP/QQQE) + VIX curve."""
    extras = extras or {}
    def _close(tk):
        if tk in macro:
            return macro[tk]["Close"].dropna()
        if tk in extras:
            return extras[tk].dropna()
        return None
    out = {"indices": [], "breadth_etf": [], "vix": None, "vixcurve": None}
    for tk, lab in [("SPY", "S&P500"), ("QQQ", "NASDAQ100")]:
        c = _close(tk)
        if c is not None and len(c) >= 30:
            d = _perf_one(c); d["label"] = lab
            out["indices"].append(d)
    # 等ウェイト/ブレッドスETF（地合いの本音）— 21EMA・50SMA に対する位置も
    for tk, lab in [("RSP", "S&P均等 RSP"), ("QQQE", "NDX均等 QQQE")]:
        c = _close(tk)
        if c is not None and len(c) >= 30:
            d = _perf_one(c); d["label"] = lab
            d["px"] = float(c.iloc[-1])
            d["e21"] = float(c.ewm(span=21, adjust=False).mean().iloc[-1])
            d["s50"] = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
            out["breadth_etf"].append(d)
    v1, v3, v6 = _close("^VIX"), _close("^VIX3M"), _close("^VIX6M")
    if v1 is not None and len(v1):
        out["vix"] = float(v1.iloc[-1])
    if v1 is not None and v3 is not None and len(v1) and len(v3):
        a, b = float(v1.iloc[-1]), float(v3.iloc[-1])
        c6 = float(v6.iloc[-1]) if (v6 is not None and len(v6)) else None
        out["vixcurve"] = {"v1": a, "v3": b, "v6": c6, "ratio": (a / b if b else None)}
    # ブレッドス乖離：大型株(SPY)先行 vs 等ウェイト(RSP)追随
    out["divergence"] = None
    spy = next((x for x in out["indices"] if x["label"].startswith("S&P")), None)
    rsp = next((x for x in out["breadth_etf"] if x["label"].startswith("S&P")), None)
    if spy and rsp and spy.get("m1") is not None and rsp.get("m1") is not None:
        gap = spy["m1"] - rsp["m1"]
        pos_gap = (spy.get("pos52") or 0) - (rsp.get("pos52") or 0)
        if spy["m1"] > 0 and (gap >= 0.03 or pos_gap >= 12):
            out["divergence"] = {"st": f"乖離・警戒（大型株が1カ月 {gap * 100:+.1f}pt 先行）", "cls": "neg"}
        elif rsp["m1"] >= spy["m1"]:
            out["divergence"] = {"st": "良好（等ウェイトが追随）", "cls": "pos"}
        else:
            out["divergence"] = {"st": "中立", "cls": "mut"}
    return out

# ----------------------------------------------------------------------------- HTML
def fmt_pct(x, d=1):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x*100:+.{d}f}%"
def fmt_pct0(x, d=1):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x*100:.{d}f}%"
def fmt_num(x, d=2):
    if x is None or (isinstance(x,float) and (np.isnan(x))): return "—"
    return f"{x:,.{d}f}"

def _pcls(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return "mut"
    return "pos" if x >= 0 else "neg"

def _perf_card(p):
    if not p or not p.get("indices"):
        return ""
    def _strip(ix, cells):
        inner = "".join(f'<div class="c"><div class="k">{k}</div>'
                        f'<div class="v {cl}">{v}</div></div>' for k, v, cl in cells)
        return f'<div class="ixn">{ix["label"]}</div><div class="perf">{inner}</div>'
    blocks = []
    for ix in p["indices"]:
        blocks.append(_strip(ix, [
            ("YTD", fmt_pct(ix["ytd"]), _pcls(ix["ytd"])),
            ("1週", fmt_pct(ix["w1"]), _pcls(ix["w1"])),
            ("1カ月", fmt_pct(ix["m1"]), _pcls(ix["m1"])),
            ("1年", fmt_pct(ix["y1"]), _pcls(ix["y1"])),
            ("52週位置", (f'{ix["pos52"]:.0f}%' if ix.get("pos52") is not None else "—"), "mut")]))
    # 等ウェイト（RSP / QQQE）— 時価加重(QQQ/SPY)と同じ書き振りで並べる
    be = p.get("breadth_etf") or []
    if be:
        blocks.append('<div class="perf-div">等ウェイト（ブレッドス）</div>')
        for ix in be:
            blocks.append(_strip(ix, [
                ("YTD", fmt_pct(ix["ytd"]), _pcls(ix["ytd"])),
                ("1週", fmt_pct(ix["w1"]), _pcls(ix["w1"])),
                ("1カ月", fmt_pct(ix["m1"]), _pcls(ix["m1"])),
                ("1年", fmt_pct(ix["y1"]), _pcls(ix["y1"])),
                ("52週位置", (f'{ix["pos52"]:.0f}%' if ix.get("pos52") is not None else "—"), "mut")]))
    # VIXカーブ
    # VIX水準のみ（カーブ＝期間構造の物語は④の「VIX期間構造」チャートが担当）
    vixhtml = ""
    if p.get("vix") is not None:
        vixhtml = (f'<div class="vixc"><span class="vixc-l">VIX</span> <b>{p["vix"]:.1f}</b>'
                   f'<span class="mut" style="font-size:11px"> ・カーブはVIX期間構造を参照</span></div>')
    dv = p.get("divergence")
    dvhtml = (f'<div class="vixc"><span class="vixc-l">ブレッドス</span> '
              f'<span class="{dv["cls"]}">{dv["st"]}</span></div>') if dv else ""
    return (f'<div class="card"><h2>マーケット・パフォーマンス</h2>'
            + "".join(blocks) + dvhtml + vixhtml + '</div>')

def _dd_card(dd):
    if not dd:
        return ""
    def _box(tk, d):
        days = d.get("days") or []
        dline = (f'<div class="dddays">{"・".join(days)}</div>') if days else ""
        return (f'<div class="box"><div class="t">{tk}</div>'
                f'<div class="num">{d["n"]}</div>'
                f'<span class="st st-{d["cls"]}">{d["st"]}</span>{dline}</div>')
    boxes = "".join(_box(tk, d) for tk, d in dd.items())
    return (f'<div class="card"><h2>ディストリビューション・デイ（直近25営業日）</h2>'
            f'<div class="sub">前日比−0.2%以下かつ出来高増の「売り抜け日」。指数が+5%上昇で解消</div>'
            f'<div class="dd">{boxes}</div></div>')

def _ftd_card(ftd):
    if not ftd:
        return ""
    rows = "".join(
        f'<div class="ftd-row"><span class="ftd-x">{x["lab"]}</span>'
        f'<span class="{x["cls"]}">{x["st"]}</span></div>' for x in ftd)
    return (f'<div class="card"><h2>フォロースルー・デイ</h2>'
            f'<div class="sub">下落後のラリーが本物かの確認日。安値後の最初のプラス引け＝Day1、<b>Day4以降に前日比+1.25%以上×出来高増</b>で点灯。日中安値割れで数え直し</div>'
            f'{rows}</div>')

def _ext_card(perf):
    """指数の200日線乖離（参考表示）。+12〜15%超で青モードでも新規勝率↓、+5〜10%が妙味。"""
    if not perf or not perf.get("indices"):
        return ""
    rows = []
    for ix in perf["indices"]:
        e = ix.get("ext200")
        if e is None or (isinstance(e, float) and np.isnan(e)):
            ev, ek, ecls = "—", "通常", "ex-warn"
        else:
            ep = e * 100
            if   ep >= 15:  ek, ecls = "過熱（押し目待ち）", "ex-bad"
            elif ep >= 12:  ek, ecls = "やや過熱",         "ex-bad"
            elif ep >= 5:   ek, ecls = "妙味",            "ex-good"
            elif ep >= -2:  ek, ecls = "通常",            "ex-warn"
            else:           ek, ecls = "200日割れ近辺",    "ex-bad"
            ev = f"{ep:+.1f}%"
        rows.append(f'<div class="exrow"><div class="exk">{ix["label"]}</div>'
                    f'<div class="exv">{ev}</div>'
                    f'<div class="exn {ecls}">{ek}</div></div>')
    return (f'<div class="card"><h2>指数の200日線乖離（参考）</h2>'
            f'<div class="sub">+12〜15%超は過熱（青でも新規は押し目待ち）／+5〜10%が妙味。'
            f'フィルタではなく地合いの過熱度メーター</div>'
            f'<div class="extbl">{"".join(rows)}</div></div>')

_COLOR_RANK = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}
_COLOR_JP = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}

def load_trend_history(cur_color, asof_date):
    """Append today's trend color to trend_history.json (committed), return (history, prev_color).
    prev_color = last recorded color on a different date (for transition-aware comments)."""
    import json
    paths = [os.environ.get("V38_TREND_JSON"),
             os.path.join(os.path.dirname(CACHE), "trend_history.json"),
             "/mnt/project/trend_history.json", "trend_history.json"]
    path = next((p for p in paths if p and os.path.exists(p)), None)
    hist = []
    if path:
        try: hist = json.load(open(path))
        except Exception: hist = []
    today = str(asof_date)
    prev = None
    for d, c in reversed(hist):
        if d != today and c:
            prev = c; break
    hist = [hc for hc in hist if hc and hc[0] != today]   # upsert today
    if cur_color:
        hist.append([today, cur_color])
    hist = hist[-120:]
    outp = path or os.environ.get("V38_TREND_JSON") or os.path.join(os.path.dirname(CACHE), "trend_history.json")
    try: json.dump(hist, open(outp, "w"))
    except Exception: pass
    return hist, prev

def trend_phrase(prev, cur):
    """Transition-aware phrase for the trend pill (色変化でコメントを変える)."""
    if not cur:
        return "判定不可"
    if not prev or prev == cur:
        return {"Blue": "強い上昇が継続", "Green": "上昇(中位)が継続",
                "Yellow": "弱含みが継続", "Red": "下落が継続"}.get(cur, cur)
    arrow = f"{_COLOR_JP.get(prev, prev)}→{_COLOR_JP.get(cur, cur)}"
    improving = _COLOR_RANK.get(cur, -1) > _COLOR_RANK.get(prev, -1)
    if improving:
        msg = {"Blue": "上昇が加速", "Green": "弱含みから持ち直し(中位)",
               "Yellow": "下げ止まり・様子見"}.get(cur, "改善")
    else:
        msg = {"Green": "上昇一服(中位へ減速)", "Yellow": "弱含みへ転換",
               "Red": "下落へ転換・回避"}.get(cur, "悪化")
    return f"{arrow} {msg}"

def broad_vs_cap_note(vals):
    """時価加重トレンド vs 等加重(broad)トレンドの乖離＝地合いの本音。(文, 色クラス)を返す。"""
    try:
        last = vals.iloc[-1]
    except Exception:
        return None
    def avg(*ks):
        xs = [last.get(k) for k in ks if last.get(k) == last.get(k)]
        return (sum(xs) / len(xs)) if xs else None
    cap   = avg("qqq_50", "spy_200")     # 時価加重トレンド
    broad = avg("rsp_50", "qqqe_50")     # 等加重トレンド
    if cap is None or broad is None:
        return None
    cu, bu = cap > 0, broad > 0
    if cu and bu:
        return ("広く強い：時価加重も等加重も上向きで、上昇に幅がある", "pos")
    if cu and not bu:
        return ("⚠ 細い相場：指数(時価加重)は上だが平均的銘柄(等加重)は弱含み＝メガキャップ主導。天井圏で出やすく要警戒", "neg")
    if (not cu) and bu:
        return ("循環：メガキャップは調整だが等加重(broad)は底堅く、物色が広がる健全な調整", "pos")
    return ("全面安：時価加重も等加重も下向き", "neg")

def _market_comment(aux, mkt, sar):
    """その日の地合いを動き(推移・高値からの調整)を主役に編んだ読み物。スコア/NQは末尾の補助。"""
    slope = {"↑": "上向き", "→": "横ばい", "↓": "鈍化"}.get(aux["slope"], aux["slope"])
    band  = mri_band(aux["hl"])[0].replace("（過熱・反落注意⚠）", "（過熱気味）")
    trend = trend_phrase(mkt.get("trend_prev"), sar[0]) if sar[0] else "判定不可"

    def dirof(ts, up, dn):
        if not ts or len(ts) < 60:
            return None
        st, _ = _trend_state([v for _, v in ts], up, dn)
        return "横ばい" if st == "中立" else st

    # 動き：地合いの高値からの調整 + 指数の52週位置
    drop = aux.get("drop", 0.0); peak = aux.get("peak", "通常")
    perf_ix = (mkt.get("perf") or {}).get("indices", [])
    qqq = next((x for x in perf_ix if str(x.get("label", "")).startswith("NASDAQ")), None)
    pos = qqq.get("pos52") if qqq else None

    bts = mkt.get("breadth_ts", [])
    pa200 = bts[-1][1] if bts else None
    breadth_dir = dirof(bts, "拡大", "縮小")
    ad_dir = dirof(mkt.get("adline_ts", []), "改善", "悪化")
    micro = [x for x in (mkt.get("sector_ranks") or {}).get("micro", []) if x.get("m1") == x.get("m1")]
    lead = max(micro, key=lambda x: x["m1"])["ja"] if micro else None      # 主導は1カ月で安定化
    defv = dirof(mkt.get("defensive_ts", []), "攻め優勢", "守りへの逃避")
    credit = dirof(mkt.get("credit_ts", []), "良好", "悪化")
    vt = mkt.get("vixterm_ts", []); vlast = vt[-1][1] if vt else None
    vix_state = (None if vlast is None else
                 "平穏" if vlast < 0.95 else "やや警戒" if vlast <= 1.0 else "逆転")
    dd = mkt.get("distrib", {}); warn = [k for k, v in dd.items() if v["n"] >= 6]
    ftd_on = [x["lab"] for x in mkt.get("ftd", []) if "点灯" in x.get("st", "")]

    parts = []
    # 1) 動きを主役に（傾き＋高値からの調整＋指数の位置）
    move = f"地合いの傾きは<b>{slope}</b>"
    if peak != "通常":
        move += f"、直近高値から{drop:.0f}ポイント調整し<b>{peak}</b>"
    else:
        move += "、直近高値圏で大きな崩れはなし"
    if pos is not None:
        zone = "高値圏" if pos >= 80 else "レンジ中位" if pos >= 40 else "安値圏"
        move += f"（指数は52週レンジの{pos:.0f}%＝{zone}）"
    parts.append(move + "。")
    # 2) 中身（推移）
    inner = []
    if pa200 is not None: inner.append(f"200日線上は{pa200:.0f}%で{breadth_dir or '横ばい'}")
    if ad_dir: inner.append(f"騰落ラインは{ad_dir}")
    if lead: inner.append(f"主導は{lead}")
    # 売買代金（参加度）のトレンド：有意なときだけ本文に差す（日次ノイズは21日平滑で除去済み）
    _dvts = mkt.get("dollarvol_ts")
    ut = _dvts.get("uni_trend") if isinstance(_dvts, dict) else None
    turnover_dir = ut["dir"] if (ut and ut.get("sig")) else None
    if turnover_dir == "拡大":
        inner.append(f"売買代金は拡大（3ヶ月{ut['pct']:+.0f}%＝参加が厚い）")
    elif turnover_dir == "縮小":
        inner.append(f"売買代金は細り（3ヶ月{ut['pct']:+.0f}%＝参加が薄い）")
    if inner: parts.append("中身は、" + "、".join(inner) + "。")
    # 2.5) 守り/攻めローテの検出のみ(総括連動用)。詳細な業種ローテは別カード(_rotation_comment・定点比較)へ分離。
    secs = mkt.get("sectors_rs") or []
    rotation_signal = None
    if secs:
        _def_kw = ("生活必需品", "公益", "REIT", "ヘルスケア", "化粧品", "パーソナルケア",
                   "食品", "飲料", "医薬", "たばこ", "タバコ")
        _off_kw = ("半導体", "AI", "ソフトウェア", "サイバー", "フィンテック", "暗号資産", "バイオテック")
        # 定点: 先週・2週前・1ヶ月前で一貫して同方向に動いた業種のみ(短期ノイズ除外)
        def _consistent(x, sign):
            vals = [x.get("d_w1", 0), x.get("d_w2", 0), x.get("d_m1", 0)]
            return all((v >= 5) for v in vals) if sign > 0 else all((v <= -5) for v in vals)
        _def_in = sum(1 for x in secs if any(k in x["ja"] for k in _def_kw) and _consistent(x, 1))
        _off_in = sum(1 for x in secs if any(k in x["ja"] for k in _off_kw) and _consistent(x, 1))
        if _def_in >= 2 and _def_in > _off_in:
            rotation_signal = "defensive"
        elif _off_in >= 2 and _off_in > _def_in:
            rotation_signal = "offensive"
    # 3) 先行指標（株より先に動くもの）
    flow = []
    if defv: flow.append(f"資金は{defv}")
    if credit: flow.append(f"クレジットは{credit}")
    if vix_state: flow.append(f"VIX期間構造は{vix_state}")
    if flow: parts.append("先行指標は、" + "、".join(flow) + "。")
    # 4) 短期の警戒/転換
    if warn: parts.append(f"{'・'.join(warn)}で売り抜け日が嵩み短期は調整に警戒。")
    if ftd_on: parts.append(f"一方{'・'.join(ftd_on)}にフォロースルー・デイ点灯で底打ち試行を確認。")
    # 5) 総括：内部と資金フローの票数で判定（スコア/NQは末尾の括弧へ降格・数字はバナーに任せる）
    det = sum([breadth_dir == "縮小", ad_dir == "悪化", defv == "守りへの逃避", credit == "悪化",
               rotation_signal == "defensive", turnover_dir == "縮小"])
    imp = sum([breadth_dir == "拡大", ad_dir == "改善", defv == "攻め優勢", credit == "良好", bool(ftd_on),
               rotation_signal == "offensive", turnover_dir == "拡大"])
    off_high = peak in ("減速", "深押し")
    # 強気材料・弱気材料を名指し（チグハグ解説用）
    bull_side, bear_side = [], []
    if breadth_dir == "拡大": bull_side.append("幅の拡大")
    if ad_dir == "改善": bull_side.append("騰落改善")
    if defv == "攻め優勢": bull_side.append("資金は攻め")
    if credit == "良好": bull_side.append("信用良好")
    if ftd_on: bull_side.append("FTD点灯")
    if turnover_dir == "拡大": bull_side.append("売買代金拡大")
    if breadth_dir == "縮小": bear_side.append("幅の細り")
    if ad_dir == "悪化": bear_side.append("騰落悪化")
    if defv == "守りへの逃避": bear_side.append("守りへ逃避")
    if credit == "悪化": bear_side.append("信用悪化")
    if warn: bear_side.append("売り抜け日")
    if rotation_signal == "defensive": bear_side.append("守りローテ")
    if turnover_dir == "縮小": bear_side.append("売買代金の細り")
    if rotation_signal == "offensive": bull_side.append("攻めローテ")
    band_bull = aux["hl"] >= 60
    band_bear = aux["hl"] < 45
    genuine_conflict = (imp >= 2 and det >= 2) or (band_bull and det >= 2) or (band_bear and imp >= 2)
    if genuine_conflict:
        bl = "・".join(bull_side) or "表面の強さ"
        br = "・".join(bear_side) or "内部の弱さ"
        verdict = (f"強気材料（{bl}）と弱気材料（{br}）が混在＝シグナルは割れている。"
                   f"こういう時は<b>弱い方の内部・資金フローを重視</b>し、確認できるまで新規は選別的に。")
    elif det >= 1 and aux["hl"] >= 60 and imp <= 1:
        verdict = "表面の強さに対し内部・資金フローが先行して弱含み。過熱と幅の細りに警戒。"
    elif off_high and imp >= 1 and det <= 1:
        verdict = "高値から調整したが内部に底打ちの芽。転換の初動を見極めたい。"
    elif imp >= 2 and det == 0:
        verdict = "中身を伴って改善方向。押し目は買い向かいやすい。"
    elif det >= 2:
        verdict = "内部から崩れが進行。新規は急がず確認を待ちたい。"
    elif det == 1 and imp >= 2:
        verdict = "改善が優勢だが一部に綻び。買いは選別的に。"
    else:
        verdict = "方向感は限定的。確認を待ちたい局面。"
    # ヘッドライン（地合いスコア）とトレンド（NQ色）・中身の食い違いを1文で埋め合わせ
    reconcile = ""
    net_bear = det - imp
    if band_bull and (trend in ("赤", "黄")):
        reconcile = f"なお地合いスコアは強気寄りだがNQトレンドは{trend}＝スコア（幅広い平均）が高値の余韻を残す一方、値動きは既に慎重方向。<b>トレンド（NQ色）を優先</b>。"
    elif band_bear and imp >= 2:
        reconcile = "なお地合いスコアは弱いが内部に改善の芽＝底打ちの初動の可能性。確認を待って動きたい。"
    elif band_bull and net_bear >= 2:
        reconcile = "なおスコアは高いが中身が追いついていない＝数字だけ見て強気に傾かないこと。"
    parts.append(f"<b>{verdict}</b>" + (f" {reconcile}" if reconcile else "") + f"（地合い「{band}」・NQ{trend}）")

    note = mkt.get("broad_note")
    note_html = ""
    if note:
        ntext, ncls = note
        note_html = f'<div class="cmt-note cmt-{ncls}">{ntext}</div>'
    return (f'<div class="card cmt"><h2>今日のマーケット</h2>'
            f'{note_html}'
            f'<div class="cmt-b">{"".join(parts)}</div></div>')


def _rotation_comment(mkt):
    """業種ローテの定点コメント(別カード)。先週・2週前・1ヶ月前と比較し、一貫した動きのみ言及。
       短期のブレでコメントが変わらないよう、複数時点で同方向のものだけ拾う。動きが無ければ空(触れない)。"""
    secs = mkt.get("sectors_rs") or []
    rrg = mkt.get("rrg") or []
    if not secs:
        return ""
    parts = []
    # ① 大分類(大テーマ): 強さ×勢い。ただし勢いは1点でなく、ここでは強さ順の中心のみ(安定)
    if rrg and len(rrg) >= 3:
        srt = sorted(rrg, key=lambda z: -z["x"])
        center = [p["ja"] for p in srt[:2] if p["x"] >= 50]
        if center:
            parts.append(f"資金の中心にあるのは<b>{'・'.join(center)}</b>")

    # ② 小分類(ニッチ業種): 先週(d_w1)・2週前(d_w2)・1ヶ月前(d_m1)で一貫して同方向のものだけ
    def trend_of(x):
        vals = [x.get("d_w1", 0.0), x.get("d_w2", 0.0), x.get("d_m1", 0.0)]
        if all(v >= 5 for v in vals):
            return "up", min(vals)          # 3時点すべて上昇＝底堅い資金流入
        if all(v <= -5 for v in vals):
            return "down", max(vals)        # 3時点すべて下落＝継続的な流出
        return None, 0.0

    ups, downs = [], []
    for x in secs:
        d, mag = trend_of(x)
        if d == "up":
            ups.append((x, mag))
        elif d == "down":
            downs.append((x, mag))
    ups.sort(key=lambda z: -z[1]); downs.sort(key=lambda z: z[1])

    def _fmt(x):
        p = x.get("parent", "")
        return f'{x["ja"]}（{p}内）' if p and p != "—" else x["ja"]

    if ups:
        names = "・".join(_fmt(x) for x, _ in ups[:3])
        parts.append(f"この1ヶ月、継続して資金が入っているのは<b>{names}</b>")
    if downs:
        names = "・".join(_fmt(x) for x, _ in downs[:3])
        parts.append(f"逆に資金が抜け続けているのは<b>{names}</b>")

    # 何も一貫した動きが無ければ、このカード自体を出さない
    if not ups and not downs:
        if not (rrg and len(rrg) >= 3):
            return ""
        parts.append("ニッチ業種の資金の向きに、先週から続く明確な偏りは見られない")

    body = "。".join(parts) + "。"
    return (f'<div class="card cmt cmt-rot"><h2>業種ローテ（定点観測）</h2>'
            f'<div class="cmt-sub">先週・2週間前・1ヶ月前と比べ、複数時点で一貫した資金の動きだけを拾っています（短期のブレは除外）。</div>'
            f'<div class="cmt-b">{body}</div></div>')


def build_leader_temp(W, win=CHART_LB):
    """先導株の強さ温度計: 先導株(RS189上位10%)の63日リターン平均の、過去分布に対する%タイル系列。
       予測でなく現状描写。非対称=左端(枯渇)のみNQ底に中央値18日先行(的中6割)/右端(過熱)は先取りせず。表示専用。"""
    closes = W.get("Close")
    if closes is None or closes.shape[0] < 200:
        return None
    r63 = closes / closes.shift(63) - 1
    rs189 = closes / closes.shift(189) - 1
    lead = []
    idx = closes.index
    for i in range(189, len(idx)):
        rr = r63.iloc[i]; rk = rs189.iloc[i]
        valid = rk.dropna()
        if len(valid) < 30:
            lead.append(np.nan); continue
        thr = valid.quantile(0.90)
        top = rr[rk >= thr].dropna()
        lead.append(float(top.mean()) if len(top) else np.nan)
    lead_s = pd.Series(lead, index=idx[189:]).dropna()
    if len(lead_s) < 60:
        return None
    pctile = lead_s.rank(pct=True) * 100          # 各点の全期間内%タイル
    cur = float(pctile.iloc[-1])
    # 推移: 直近 win 営業日・%タイル（他グラフと同じ表示期間・密度）
    tail = pctile.iloc[-win:]
    ts = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in tail.items()]
    # 実際の期間ラベルを動的生成（表記と実データのズレを防ぐ）
    if len(tail) >= 2:
        _mo = round((tail.index[-1] - tail.index[0]).days / 30.44)
        _y, _m = _mo // 12, _mo % 12
        span_label = (f"{_y}年{_m}ヶ月" if _y and _m else f"{_y}年" if _y else f"{_m}ヶ月")
    else:
        span_label = "—"
    return dict(cur=cur, ts=ts, span=span_label)

def _leader_temp_card(lt):
    """先導株の強さ: %タイル推移（マーケットステータスと同形式のゾーン塗り折れ線）。表示専用。"""
    if not lt or not lt.get("ts"):
        return ""
    cur = lt["cur"]; ts = lt["ts"]; span = lt.get("span", "")
    zone = ("枯渇（反発予兆）" if cur < 10 else "過熱（現状の強さ）" if cur >= 82 else
            "強（過熱手前）" if cur >= 65 else "並" if cur >= 30 else "やや枯渇")
    # 推移SVG: _svg_mri と同じ幾何・帯域塗り（%タイル0-100固定）
    ys = [v for _, v in ts]; n = len(ys)
    if n < 3:
        chart = ""
    else:
        Wd, Ht, pad = 680, 180, 6
        def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
        def Y(v): return pad + (1 - v/100) * (Ht - 2*pad)
        zones = [(0,10,"#1f6feb"),(10,30,"#22c55e"),(30,65,"#64748b"),(65,82,"#d29922"),(82,100,"#ef4444")]
        zr = "".join(f'<rect x="{pad}" y="{Y(z1):.1f}" width="{Wd-2*pad}" '
                     f'height="{max(0.0,Y(z0)-Y(z1)):.1f}" fill="{zc}" opacity="0.07"/>' for z0,z1,zc in zones)
        gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="#1c2533" stroke-width="1"/>'
                     f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g}</text>'
                     for g in (10,30,65,82))
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i,v in enumerate(ys))
        svg = (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">{zr}{gl}'
               f'<polyline points="{pts}" fill="none" stroke="#e6edf3" stroke-width="2"/>'
               f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="#e6edf3"/></svg>')
        chart = (f'<div class="chart">{svg}'
                 f'<div class="cap cap-c"><span style="color:#e6edf3;font-weight:700">現在 {cur:.0f}%（{zone}）・{span}</span></div>'
                 f'{_date_axis(ts)}</div>')
    return (
        f'<div class="card"><h2>リーダーの強さ</h2>'
        f'<div class="sub">リーダー群(RS189上位10%)の勢いが過去分布の何%タイルか＝獲物の温度。露出には非接続・表示専用。</div>'
        f'{chart}'
        f'<div style="font-size:11px;color:#8b949e;margin-top:10px;padding:10px;background:#0d1420;border-radius:8px;line-height:1.6">'
        f'<b style="color:#58a6ff">左端(枯渇0-10%)</b>＝反発の予兆。先行60日で平均+8.6%、NQ底打ちに中央値18日先行(的中約6割)。NQ色の青転換に備える補助。<br>'
        f'<b style="color:#f0883e">右端(過熱)</b>＝現状の強さのみ。<b>先行きは予測しない</b>(先行20日相関ゼロ)。下落対応はNQ4色ゲート。</div></div>')

def _buy_today_card(buys):
    """本日のピックアップ＝セットアップ・スクリーナー（裁量参考）。セットアップ別のコンパクト表・タップで詳細。"""
    if not buys:
        return ('<div class="card hot-card"><h2>本日のピックアップ</h2>'
                '<div class="empty">本日の該当なし（RS90以上のセットアップ）</div></div>')
    GMETA = {
        "ブレイク": ("st-break", "ghb-break", "新高値・出来高増"),
        "保ち合い": ("st-base",  "ghb-base",  "高値圏で収縮・出来高枯れ"),
        "押し目":   ("st-pull",  "ghb-pull",  "上昇トレンドの押し目"),
        "新高値":   ("st-high",  "ghb-high",  "高値圏・様子見"),
    }
    from collections import Counter
    cnt = Counter(b["tag"] for b in buys)
    body = []; cur = None
    for b in buys:
        if b["tag"] != cur:
            cur = b["tag"]
            gcls, gbg, gdesc = GMETA.get(cur, ("st-high", "ghb-high", ""))
            body.append(
                f'<tr class="scr-gh {gbg}"><td colspan="5">'
                f'<span class="bt-tag {gcls}">{cur}</span>'
                f'<span class="scr-gn">{cnt[cur]}件</span>'
                f'<span class="scr-gd">{gdesc}</span></td></tr>'
                f'<tr class="scr-ch {gbg}"><td class="l">銘柄</td><td>RS</td><td>ピボット</td>'
                f'<td>出来高</td><td class="l">押し目</td></tr>')
        held = '<span class="scr-star">★</span>' if b.get("held") else ''
        if b["tag"] == "ブレイク":                       # ブレイクは当日の出来高増(RVOL)
            rv = b.get("rvol"); vval = (f'{rv:.1f}×' if rv == rv else '—')
            vcls = "pos" if (rv == rv and rv >= 1.4) else "mut"
        else:                                            # それ以外は枯れ(vdry)
            vd = b.get("vdry"); vval = (f'{vd:.2f}×' if vd == vd else '—')
            vcls = "pos" if b.get("dry") else "mut"
        pb = b.get("pb")
        if pb == pb:
            drop = max(0.0, -pb * 100)                 # 高値からの下げ幅(%)
            w = max(2, min(100, drop / 20 * 100))      # 20%下げで満タン
            num = '0%' if drop < 0.5 else f'-{drop:.0f}%'
            poscell = (f'<span class="posbar"><span class="posfill" style="width:{w:.0f}%"></span></span>'
                       f'<span class="posn">{num}</span>')
        else:
            poscell = '—'
        body.append(
            f'<tr class="scr-row" data-liq="{(b.get("dvol") or 0)/1e6:.1f}" data-tkone="{b["t"]}">'
            f'<td class="scr-tk">{b["t"]}{held}</td>'
            f'<td class="scr-c">{b["rs"]:.0f}</td>'
            f'<td class="scr-c">${b["pivot"]:.2f}</td>'
            f'<td class="scr-c {vcls}">{vval}</td>'
            f'<td class="scr-c scr-pos">{poscell}</td></tr>')
    return (f'<div class="card hot-card"><div class="hdr"><h2>本日のピックアップ</h2>'
            f'{_cp([b["t"] for b in buys])}</div>'
            f'<div class="sub">RS90以上(かつ持続)・MA整列・$10M以上の強い銘柄を実用セットアップで抽出（最大{len(buys)}・<b>タップで詳細</b>）。'
            f'出来高=<b>枯れ</b>(10日平均/50日平均、ブレイクは当日RVOL)／ピボット=直近40日高値／'
            f'<b>押し目</b>=直近高値からの下げ幅（バーが短いほど高値に近い）／<b>★</b>=保有トップ{N_PORT}。</div>'
            f'<table class="scrtab"><tbody>' + "".join(body) + '</tbody></table></div>')


def _vcp_card(rows):
    """圧縮コイル（VCP）ウォッチ・カード。締まり順に、収縮/枯れ/ADR/高値差を表示。"""
    head = ('<div class="card"><div class="hdr"><h2>圧縮コイル（VCP）ウォッチ</h2>'
            + (_cp([r["t"] for r in rows]) if rows else "") + '</div>'
            '<div class="sub">ステージ2上昇 × 高値圏（52週−20%以内）× <b>ボラ収縮</b>（BB幅が126日で下位15%）× '
            '<b>出来高の枯れ</b>（10日/50日≤0.85）× 21EMA上（higher-lows）× RS≥80 × ADR≥3%（動ける）。'
            '<b>締まりが強いほどコイルにエネルギーが溜まる</b>——ブレイクで放出。'
            '<b>眼を鍛える／ウォッチ専用</b>（VCPの機械ゲートは検証で無効＝仕掛けはブレイク実現を確認して裁量で）。</div>')
    if not rows:
        return head + '<div class="empty">今日は該当なし（十分に締まったコイルが不在）</div></div>'
    trs = ""
    for r in rows:
        bbw = r["bbw"] if r["bbw"] == r["bbw"] else 100.0
        comp = max(0.0, min(100.0, 100.0 - bbw))                 # 圧縮スコア（高いほど締まり）
        vd = f'{r["vdry"]:.2f}×' if (r.get("vdry") is not None and r["vdry"] == r["vdry"]) else "—"
        trs += (f'<tr data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{r["t"]}">'
                f'<td class="l tk">{r["t"]}'
                f'<div class="rowsec">{r["theme"]} ・ {r["ind"]}</div>'
                f'<div class="rowbadges"><span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span></div></td>'
                f'<td>{r["rs"]:.0f}</td>'
                f'<td><div class="coil"><i style="width:{comp:.0f}%"></i></div>'
                f'<span class="mut" style="font-size:10px">{comp:.0f}</span></td>'
                f'<td class="pos">{vd}</td>'
                f'<td>{r["adr"]*100:.1f}%</td>'
                f'<td class="{color_pct(r["d52"])}">{fmt_pct(r["d52"])}</td></tr>')
    return (head + '<table><tr><th class="l">銘柄</th><th>RS</th><th>締まり</th>'
            '<th>枯れ</th><th>ADR</th><th>52週<br>高値差</th></tr>' + trs + '</table></div>')


def _buy_card(buys, pick_set=None):
    if not buys:
        return ('<div class="card"><h2>本日の押し目シグナル</h2>'
                '<div class="empty">本日の③該当なし</div></div>')
    rows = []
    for b in buys:
        held = f'<span class="bt-held">★トップ{N_PORT}</span>' if (pick_set and b["t"] in pick_set) else ''
        rows.append(
            f'<div class="buy" data-liq="{(b.get("dvol") or 0)/1e6:.1f}" data-tkone="{b["t"]}">'
            f'<div class="buy-h"><span class="tk">{b["t"]}</span>{held}'
            f'<span class="rs">RS {b["rs"]:.0f}</span></div>'
            f'<div class="buy-m">{b["theme"]} ・ {b["ind"]}</div>'
            f'<div class="rowbadges">'
            f'<span class="capb cap-{b["tier_key"]}">{b["tier_lab"]}</span>'
            f'{_state_badge(b.get("state",""), b.get("nut",""), b.get("nucls","mut"))}</div>'
            f'<div class="buy-g">'
            f'<div><span class="k">エントリー</span><span class="v">${b["lo"]:.2f}〜${b["hi"]:.2f}</span></div>'
            f'<div><span class="k">−25%ストップ</span><span class="v neg">${b["lo"]*0.75:.2f}</span></div>'
            f'<div><span class="k">利確</span><span class="v mut">ピーク×0.70</span></div>'
            f'<div><span class="k">押し目</span><span class="v">{fmt_pct(b["pb"])}</span></div>'
            f'<div><span class="k">ADR</span><span class="v">{fmt_pct0(b["adr"])}</span></div>'
            f'<div><span class="k">RVOL</span><span class="v">{b["rvol"]:.1f}</span></div>'
            f'</div></div>')
    return (f'<div class="card"><div class="hdr"><h2>本日の押し目シグナル <span class="role-tag rt-act">仕掛ける</span></h2>'
            f'{_cp([b["t"] for b in buys])}</div>'
            f'<div class="sub">RS90以上の主力（リーダー）で押し目が成立した銘柄。<b>押し目</b>＝直近高値からの下げ幅、<b>ADR</b>＝1日の平均値幅（値動きの荒さ）、<b>RVOL</b>＝平常比の出来高（注目度）。エントリー幅と初期ストップ付き（利確はトレール・固定目標なし）。<b>★トップ{N_PORT}</b>＝機械システムの保有候補と一致。</div>'
            + "".join(rows) + '</div>')

def _leaders_card(by_state):
    total = sum(len(v) for v in by_state.values())
    all_tk = [x["t"] for code, _, _ in STATE_DEF for x in by_state.get(code, [])]
    secs = []
    for code, label, cls in STATE_DEF:
        lst = by_state.get(code, [])
        ticks = [x["t"] for x in lst]
        shown = lst[:CHIP_CAP]
        extra = len(lst) - len(shown)
        chips = "".join(f'<span class="chip {cls}" data-liq="{(x.get("dvol") or 0)/1e6:.1f}" data-tkone="{x["t"]}">{x["t"]}</span>' for x in shown)
        more = f'<span class="more">+{extra}件</span>' if extra > 0 else ""
        secs.append(
            f'<div class="setup-h"><span class="nm">{code} {label}</span>'
            f'<span style="display:flex;gap:6px;align-items:center">{_cp(ticks)}'
            f'<span class="ct">{len(lst)}銘柄</span></span></div>'
            f'<div class="chips">{chips or "<span class=empty>なし</span>"}{more}</div>')
    return (f'<div class="card"><div class="hdr"><h2>リーダー監視（RS≥85・200MA上）</h2>{_cp(all_tk)}</div>'
            f'<div class="sub">高RSリーダーを状態①〜⑤で色分け（計{total}銘柄）。'
            f'③押し目／②継続／①伸び過ぎ待ち／④深押し／⑤様子見。'
            f'<b>状態は形状の参考であって買いシグナルではない</b>（仕掛けは隔週月曜のRS上位選定のみ）。</div>'
            + "".join(secs) + '</div>')

CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;background:#0b0f17;color:#e6edf3;font-size:14px;-webkit-text-size-adjust:100%}
.wrap{max-width:680px;margin:0 auto;padding:0 12px calc(60px + env(safe-area-inset-bottom))}
header{padding:14px 4px 8px}
h1{font-size:18px;font-weight:800;letter-spacing:.01em}
.asof{color:#7d8da1;font-size:11px;margin-top:2px}
.banner{border-radius:14px;padding:14px 16px;margin:10px 0 4px;border:1px solid #1c2533;background:linear-gradient(135deg,#121a28,#172033)}
.banner .lab{font-size:12px;color:#cbd5e1;opacity:.85}
.banner .val{font-size:31px;font-weight:800;line-height:1.1;margin:2px 0;font-variant-numeric:tabular-nums}
.banner .st{font-size:13px;font-weight:800}
/* 地合いバンドは背景でなくラベル文字色で表現（トレンド判定ピルとの色被りを回避） */
.b-ovh .st{color:#86efac}.b-bull .st{color:#4ade80}
.b-neu .st{color:#fbbf24}.b-weak .st{color:#fb923c}.b-bear .st{color:#f87171}
.gauge{height:10px;border-radius:6px;margin:10px 0 4px;background:linear-gradient(90deg,#991b1b 0%,#9a3412 30%,#a16207 45%,#15803d 60%,#166534 100%);position:relative}
.gauge .mk{position:absolute;top:-4px;width:3px;height:18px;background:#fff;border-radius:2px;box-shadow:0 0 4px rgba(0,0,0,.6)}
.aux{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.aux .a{background:rgba(0,0,0,.22);border-radius:8px;padding:5px 9px;font-size:11px}
.aux .a b{font-size:13px}
/* NQ-SAR signal pill (leverage sleeve; logic hidden) */
.sar{border-radius:14px;padding:12px 16px;margin:10px 0 4px;border:1px solid rgba(255,255,255,.10);
     display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.sar .lhs{display:flex;align-items:center;gap:11px}
.sar .dot{width:16px;height:16px;border-radius:50%;box-shadow:0 0 0 3px rgba(255,255,255,.15),0 0 10px rgba(0,0,0,.4);flex:0 0 auto}
.sar .lab{font-size:11px;color:#dbe4ef;opacity:.9;letter-spacing:.04em}
.sar .col{font-size:22px;font-weight:800;line-height:1.05}
.sar .rhs{text-align:right}
.sar .jud{font-size:20px;font-weight:800;line-height:1.05}
.sar .lot{font-size:11px;opacity:.92;margin-top:2px}
.sar-blue{background:linear-gradient(135deg,#0b2a6b,#1d4ed8)}   .sar-blue .dot{background:#60a5fa}
.sar-green{background:linear-gradient(135deg,#14532d,#16a34a)}  .sar-green .dot{background:#4ade80}
.sar-yellow{background:linear-gradient(135deg,#713f12,#ca8a04)} .sar-yellow .dot{background:#facc15}
.sar-red{background:linear-gradient(135deg,#7f1d1d,#dc2626)}    .sar-red .dot{background:#f87171}
.sar-gray{background:linear-gradient(135deg,#374151,#4b5563)}   .sar-gray .dot{background:#9ca3af}
.sar-badge{display:inline-block;font-size:10px;font-weight:800;border-radius:6px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.sar-badge.ok{background:rgba(255,255,255,.18);color:#dffbe8}
.sar-badge.est{background:#a16207;color:#fde68a}
.sar-badge.none{background:#1f2937;color:#cbd5e1}
/* distribution-day + performance widgets */
.dd{display:flex;gap:10px;flex-wrap:wrap}
.dd .box{flex:1 1 120px;background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:10px 12px}
.dd .box .t{font-size:12px;color:#9fb0c5;font-weight:700}
.dd .box .num{font-size:26px;font-weight:800;line-height:1.1;margin:2px 0;font-variant-numeric:tabular-nums}
.dd .st{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:7px}
.st-good{background:#14532d;color:#86efac}.st-warn{background:#713f12;color:#fde68a}.st-bad{background:#7f1d1d;color:#fca5a5}
.perf{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.ixn{font-size:13px;font-weight:800;color:#9ecbff;margin:10px 0 6px}
.ixn:first-child{margin-top:0}
.perf-vix{margin-top:10px;font-size:13px;color:#9fb0c5}
.perf-vix b{font-size:16px;color:#e6edf3}
.perf-div{font-size:11px;font-weight:800;color:#8fa0b5;margin:10px 0 4px;padding-top:8px;border-top:1px dashed #1c2533}
.vixc{margin-top:10px;font-size:12.5px;color:#9fb0c5}
.vixc-l{font-weight:800;color:#cbd5e1;margin-right:4px}
.vixc b{font-size:15px;color:#e6edf3}
.warnt{color:#fbbf24;font-weight:700}
.ftd-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-top:1px solid #161e2b;font-size:13px}
.ftd-row:first-of-type{border-top:0}
.ftd-x{font-weight:800;color:#cbd5e1}
.perf .c{background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:8px 10px;text-align:center}
.perf .c .k{font-size:11px;color:#7d8da1}.perf .c .v{font-size:16px;font-weight:800;margin-top:2px;font-variant-numeric:tabular-nums}
nav{position:sticky;top:0;z-index:9;background:rgba(11,15,23,.88);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);display:flex;gap:6px;overflow-x:auto;padding:9px 0;border-bottom:1px solid #1c2533;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{flex:0 0 auto;background:#141b29;color:#9fb0c5;border:1px solid #1f2a3a;border-radius:18px;padding:8px 15px;font-size:13px;font-weight:700;transition:background .15s,color .15s}
nav button.on{background:#1f6feb;color:#fff;border-color:#1f6feb}
button:focus-visible,a:focus-visible{outline:2px solid #3b82f6;outline-offset:2px}
section{display:none;padding-top:12px}
section.on{display:block}
.card{background:#0f1623;border:1px solid #1c2533;border-radius:13px;padding:12px 14px;margin-bottom:12px}
.card h2{font-size:14.5px;font-weight:800;margin-bottom:7px;color:#eef3fa}
.card .sub{font-size:11px;color:#8494ab;line-height:1.55;margin:-3px 0 9px}
.setup-h{display:flex;justify-content:space-between;align-items:baseline;margin:10px 0 6px}
.setup-h .nm{font-size:13px;font-weight:700}
.setup-h .ct{font-size:11px;color:#7d8da1}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:#162132;border:1px solid #243349;border-radius:9px;padding:8px 12px;font-size:12.5px;font-weight:600;color:#cfe0f5;cursor:pointer}
.chip:active{background:#22324a}
.chip.hot{border-color:#2f81f7;color:#9ecbff}
.chip.ov{border-color:#a16207;color:#fde68a;background:#2a210a}
.chip.ov .b{display:inline-block;margin-left:5px;background:#a16207;color:#0b0f17;font-size:10px;font-weight:800;border-radius:5px;padding:0 5px}
/* ①〜⑤ state chips */
.chip.s-buy{background:#0f3d1f;border-color:#1f9d4d;color:#7ff0a8}
.chip.s-shape{background:#1a2130;border-color:#2b3648;color:#aab6c8}
.chip.s-go{background:#10331f;border-color:#1f7a45;color:#86efac}
.chip.s-wait{background:#33290a;border-color:#a16207;color:#fde68a}
.chip.s-deep{background:#3a210f;border-color:#c2660b;color:#fdba74}
.chip.s-break{background:#33161a;border-color:#a13030;color:#fca5a5}
.qb{font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;white-space:nowrap;border:1px solid}
.qb-go{background:#0f3d1f;color:#7ff0a8;border-color:#1d7840}
.qb-wait{background:#11161f;color:#8fa0b5;border-color:#2a3340}
.blkrow td{background:rgba(255,255,255,.018)}
.blkrow .tk{color:#aeb9c7}
/* 本日◎押し目 buy cards */
.buy{background:#0c1a12;border:1px solid #1f6d3c;border-radius:11px;padding:8px 11px;margin-bottom:6px}
.buy-h{display:flex;justify-content:space-between;align-items:baseline}
.buy-h .tk{font-size:16px;font-weight:800;color:#9ff0bb}
.buy-h .rs{font-size:12px;font-weight:700;color:#7d8da1}
.buy-m{font-size:11px;color:#9fb0c5;margin:2px 0 5px}
.buy-g{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}
.buy-g>div{background:rgba(0,0,0,.25);border-radius:7px;padding:4px 6px}
.buy-g .k{display:block;font-size:9px;color:#7d8da1}
.buy-g .v{font-size:12px;font-weight:700}
.cmt{background:linear-gradient(135deg,#0f1b2e,#10233b);border-color:#26415f}
.cmt-b{font-size:14px;line-height:1.65;color:#e6edf3}
.cmt-b b{color:#9ecbff}
.chart{margin-top:4px}
.chart svg{width:100%;height:auto;display:block}
.chart .cap{display:flex;justify-content:space-between;font-size:11px;color:#7d8da1;margin-top:4px}
.empty{color:#5b6b80;font-size:12px;font-style:italic}
.more{display:inline-block;color:#7d8da1;font-size:11px;font-weight:700;padding:4px 2px;vertical-align:middle}
/* copy buttons */
.cp{background:#16263a;border:1px solid #2f4a6a;border-radius:7px;color:#9ecbff;font-size:11px;
    font-weight:700;padding:3px 9px;cursor:pointer}
.cp .n{opacity:.6;font-weight:600}
.pendb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:3px;vertical-align:middle}
.pend-wait{background:rgba(239,68,68,.16);color:#f87171;border:1px solid rgba(239,68,68,.4)}
.pend-ok{background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.4)}
.waitb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;background:rgba(239,68,68,.16);color:#f87171;border:1px solid rgba(239,68,68,.4);vertical-align:middle}
.okb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.4);vertical-align:middle}
.row-wait{background:rgba(239,68,68,.05)}
.row-carry{background:rgba(96,165,250,.06)}
.coil{display:inline-block;width:52px;height:7px;border-radius:4px;background:#1c2533;overflow:hidden;vertical-align:middle;margin-right:4px}
.coil i{display:block;height:7px;border-radius:4px;background:linear-gradient(90deg,#22c55e,#84cc16)}
.adrb{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle}
.adr-lo{background:rgba(148,163,184,.18);color:#94a3b8;border:1px solid rgba(148,163,184,.4)}
.adr-hi{background:rgba(234,88,12,.16);color:#fb923c;border:1px solid rgba(234,88,12,.42)}
.r3b{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;background:rgba(34,197,94,.18);color:#4ade80;border:1px solid rgba(34,197,94,.45);vertical-align:middle}
.shallow{display:inline-block;font-size:9px;font-weight:800;border-radius:4px;padding:0 4px;margin-left:4px;background:rgba(234,88,12,.18);color:#fb923c;border:1px solid rgba(234,88,12,.5);vertical-align:middle}
.entb{display:inline-block;font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle;border:1px solid}
.ent-good{background:rgba(34,197,94,.16);color:#4ade80;border-color:rgba(34,197,94,.45)}
.ent-ok{background:rgba(56,189,248,.14);color:#7dd3fc;border-color:rgba(56,189,248,.4)}
.ent-lo{background:rgba(148,163,184,.16);color:#9fb0c5;border-color:rgba(148,163,184,.4)}
.ent-warn{background:rgba(234,179,8,.16);color:#eab308;border-color:rgba(234,179,8,.42)}
.ent-bad{background:rgba(239,68,68,.16);color:#f87171;border-color:rgba(239,68,68,.45)}
.carryb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:5px;background:rgba(96,165,250,.16);color:#60a5fa;border:1px solid rgba(96,165,250,.4);vertical-align:middle}
.chip-tap{cursor:pointer}
.chip-arr{margin-left:3px;color:#8b949e;font-weight:800}
.hier-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:100;align-items:center;justify-content:center;padding:16px}
.hier-modal.on{display:flex}
.hier-box{background:#111722;border:1px solid #2f4a6a;border-radius:14px;padding:18px;max-width:460px;width:100%;max-height:82vh;overflow:auto}
.hier-box h3{font-size:15px;margin-bottom:2px}
.hier-box .hb-sub{font-size:11px;color:#8b949e;margin-bottom:12px}
.hsub-row{border-bottom:1px solid #1c2533;padding:9px 0}
.hsub-row:last-child{border:0}
.hsub-hd{display:flex;align-items:center;justify-content:space-between;cursor:pointer}
.hsub-name{font-size:12.5px;font-weight:700}
.hsub-q{font-size:9px;font-weight:800;padding:1px 6px;border-radius:5px;margin-left:6px}
.hsub-meta{font-size:11px;color:#8b949e}
.hsub-mem{display:none;flex-wrap:wrap;gap:6px;margin-top:8px}
.hsub-mem.on{display:flex}
.hmem{background:#0e1622;border:1px solid #263850;border-radius:7px;padding:3px 8px;font-size:11px;cursor:pointer}
.hmem .rsb{margin-left:4px;color:#9ecbff;font-weight:700}
.hback{background:#16263a;border:1px solid #2f4a6a;border-radius:7px;color:#9ecbff;font-size:11px;padding:3px 10px;cursor:pointer;margin-bottom:10px}
.copybtn{background:#16263a;border:1px solid #2f4a6a;border-radius:7px;color:#9ecbff;font-size:11px;font-weight:700;padding:3px 9px;cursor:pointer;vertical-align:middle;margin-left:8px}
.copybtn.done{background:#0d3320;border-color:#238636;color:#3fb950}
.exq{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:4px;background:rgba(139,148,158,.16);color:#8b949e;border:1px solid rgba(139,148,158,.4)}
.skip-note{font-size:11px;color:#eab308;background:rgba(234,179,8,.08);border-radius:8px;padding:8px 10px;margin:8px 0}
.lagb{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:4px;background:rgba(234,179,8,.16);color:#eab308;border:1px solid rgba(234,179,8,.4)}
tr.row-excluded{opacity:.5}
tr.row-excluded td{text-decoration:line-through;text-decoration-color:rgba(139,148,158,.5)}
.cp.done{background:#0f3d1f;border-color:#1f9d4d;color:#7ff0a8}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px}
.hdr h2{margin:0}
table{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:4px 5px;border-bottom:1px solid #18212f}
th{color:#8595aa;font-weight:700;font-size:10.5px;letter-spacing:.05em}
td.l,th.l{text-align:left}
.tk{font-weight:700;color:#e6edf3}
.pos{color:#4ade80}.neg{color:#f87171}.mut{color:#8595aa}
.bar{height:6px;border-radius:4px;background:#16202e;overflow:hidden;min-width:54px;display:inline-block;vertical-align:middle}
.bar i{display:block;height:100%;background:#2f81f7}
.alloc{display:flex;height:30px;border-radius:8px;overflow:hidden;margin:6px 0}
.alloc div{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff}
.a-ind{background:#1f6feb}.a-lev{background:#8957e5}.a-cash{background:#3d4858}
.note{font-size:11px;color:#7d8da1;line-height:1.5;margin-top:6px}
.kv{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #18212f;font-size:12.5px}
.kv .k{color:#9fb0c5}.kv .v{font-weight:700}
ul.rules{font-size:12.5px;line-height:1.7;padding-left:18px;color:#cbd5e1}
ul.rules li{margin-bottom:4px}
.rh{font-size:13px;font-weight:800;color:#9ecbff;margin:14px 0 4px}
.nqt{margin:6px 0 2px}
.nqt th,.nqt td{text-align:center}
.nqt td.l,.nqt th.l{text-align:left}
.nqt tr.hl{background:rgba(56,161,105,.14)}
.nqt tr.hl td{font-weight:800;color:#e6edf3}
.nqd{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
.nqd.c-bl{background:#3b82f6}.nqd.c-gr{background:#22c55e}
.nqd.c-yl{background:#eab308}.nqd.c-rd{background:#ef4444}
.warn{background:#1a1206;border:1px solid #5c4410;border-radius:8px;padding:8px 10px;font-size:11.5px;color:#d6b56a;margin-top:8px}
/* ② distribution-day dates */
.dddays{font-size:10px;color:#7d8da1;margin-top:4px;line-height:1.5}
/* ⑤ index 200MA extension card */
.extbl{display:flex;flex-direction:column;gap:6px}
.exrow{display:flex;align-items:center;gap:10px;background:#0b1220;border:1px solid #1c2533;border-radius:9px;padding:8px 10px}
.exk{flex:0 0 84px;font-size:13px;font-weight:700;color:#e6edf3}
.exv{flex:0 0 64px;font-size:14px;font-weight:800;text-align:right}
.exn{flex:1;text-align:right;font-size:12px;font-weight:700}
.ex-good{color:#4ade80}.ex-warn{color:#9fb0c5}.ex-bad{color:#f87171}
/* ⑥ status breakdown panel */
.banner{cursor:pointer}
.cmt-sub{font-size:11px;color:#8b949e;margin:2px 0 10px;line-height:1.5}
.cmt-rot h2{font-size:15px}
.tap{font-size:10px;font-weight:700;color:#9ecbff;opacity:.85;margin-left:6px}
.mri-bd{display:none;cursor:default;margin-top:10px;background:rgba(0,0,0,.28);border-radius:10px;padding:10px 12px}
.mri-bd.open{display:block}
.mbd-h{font-size:12px;font-weight:800;color:#cbd5e1;margin-bottom:6px}
.mgrp{font-size:10px;font-weight:700;color:#9ecbff;letter-spacing:.04em;margin:8px 0 2px}
.mgrp:first-of-type{margin-top:0}
.mrow{display:flex;align-items:center;gap:8px;padding:3px 0}
.mk2{flex:0 0 116px;font-size:11px;color:#cbd5e1}
.mraw{flex:0 0 58px;font-size:11px;font-weight:700;text-align:right;color:#e6edf3}
.mbar{flex:1;height:6px;border-radius:4px;background:#16202e;overflow:hidden}
.mbar i{display:block;height:100%;background:#2f81f7}
.mpts{flex:0 0 50px;font-size:10px;color:#9fb0c5;text-align:right}
.mnote{font-size:10px;color:#7d8da1;text-align:center;margin-top:6px}
.bflags{display:flex;flex-wrap:wrap;gap:5px;margin-top:2px}
.bfl{font-size:10px;font-weight:700;border-radius:6px;padding:2px 7px}
.bfl.on{background:#3a1414;color:#fca5a5;border:1px solid #7f1d1d}
.bfl.off{background:#0f1622;color:#5b6b80;border:1px solid #1c2533}
/* ⑧ 本日のピックアップ */
.hot-card{border-color:#2f81f7}
.bt{background:#0c1422;border:1px solid #233149;border-radius:10px;padding:7px 10px;margin-bottom:6px}
.bt-h{display:flex;align-items:baseline;gap:8px}
.bt-h .tk{font-size:15px;font-weight:800;color:#9ecbff}
.bt-h .rs{margin-left:auto;font-size:12px;font-weight:700;color:#7d8da1}
.bt-tag{font-size:10px;font-weight:800;border-radius:6px;padding:1px 7px}
.st-break{color:#06210f;background:#7ff0a8}
.st-base{color:#241c00;background:#fcd34d}
.st-pull{color:#0a1830;background:#9cc2ff}
.st-high{color:#c7d2fe;background:#2a2f45}
.scrtab{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
.scrtab th{font-size:10px;color:#7f8ea3;font-weight:700;text-align:right;padding:3px 6px;border-bottom:1px solid #1c2433}
.scrtab th.l{text-align:left}
.scr-row td{padding:5px 6px;border-bottom:1px solid #141b27;text-align:right}
.scr-tk{font-weight:800;color:#cfe0f5;text-align:left!important}
.scr-c{font-variant-numeric:tabular-nums}
.scr-star{color:#ffd34d;margin-left:3px;font-size:11px}
.scr-gh td{padding:8px 6px 2px;text-align:left}
.scr-gn{font-size:11px;color:#9fb0c5;margin-left:6px;font-weight:700}
.scr-gd{font-size:10px;color:#7f8ea3;margin-left:6px}
.scr-ch td{font-size:10px;color:#7f8ea3;font-weight:700;text-align:right;padding:1px 6px 5px;border-bottom:1px solid #1c2433}
.scr-ch td.l{text-align:left}
.ghb-break td{background:rgba(55,210,127,.06)}
.ghb-base td{background:rgba(252,211,77,.07)}
.ghb-pull td{background:rgba(156,194,255,.07)}
.ghb-high td{background:rgba(130,142,170,.07)}
.ghb-break td:first-child{border-left:3px solid #37d27f}
.ghb-base td:first-child{border-left:3px solid #fcd34d}
.ghb-pull td:first-child{border-left:3px solid #9cc2ff}
.ghb-high td:first-child{border-left:3px solid #6b7689}
.scr-pos{white-space:nowrap;text-align:left}
.posbar{display:inline-block;width:46px;height:7px;border-radius:4px;background:#26334a;vertical-align:middle;overflow:hidden;margin-right:6px}
.posfill{display:block;height:100%;background:linear-gradient(90deg,#5b7fb0,#9cc2ff);border-radius:4px}
.posn{font-size:11px;color:#9fb0c5;vertical-align:middle;font-variant-numeric:tabular-nums}
.bt-held{font-size:9px;font-weight:700;color:#0b0e14;background:#7ff0a8;border-radius:4px;padding:1px 5px;margin-left:5px}
.role-tag{font-size:10px;font-weight:700;border-radius:5px;padding:1px 7px;vertical-align:middle;margin-left:6px}
.rt-view{color:#9cc2ff;background:#16243e}
.rt-act{color:#7ff0a8;background:#0c2a1c}
.bt-good{background:#0f3d1f;color:#7ff0a8}
.bt-warn{background:#33290a;color:#fde68a}
.bt-bad{background:#3a210f;color:#fdba74}
.bt-g{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:6px}
.bt-g>div{background:rgba(0,0,0,.25);border-radius:7px;padding:4px 6px}
.bt-g .k{display:block;font-size:9px;color:#7d8da1}
.bt-g .v{font-size:12px;font-weight:700}
.bt-g .v.bt-good{background:none;color:#4ade80}
.bt-g .v.bt-warn{background:none;color:#9fb0c5}
.bt-g .v.bt-bad{background:none;color:#f87171}
/* §4 tap-to-ticker detail bottom-sheet */
.chip,.bt-h .tk,.buy-h .tk{cursor:pointer}
.dov-bg{display:none;position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.55);align-items:flex-end;justify-content:center}
.dov-bg.open{display:flex}
.dov{width:100%;max-width:680px;max-height:88vh;overflow-y:auto;background:#0f1623;border:1px solid #1c2533;border-bottom:none;border-radius:16px 16px 0 0;padding:16px 16px 28px;box-shadow:0 -8px 30px rgba(0,0,0,.5)}
.dov-h{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}
.dov-tk{font-size:20px;font-weight:800;color:#9ecbff}
.dov-x{font-size:18px;color:#7d8da1;cursor:pointer;padding:4px 10px}
.dov-nm{font-size:12px;color:#7d8da1;margin-bottom:10px}
.dov-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.dov-status{margin:2px 0 12px}
.msec{margin:22px 0 8px;padding-top:14px;border-top:2px solid #1c2738}
.msec-l{font-size:16px;font-weight:800;color:#e6edf3;letter-spacing:.02em}
.msec-q{font-size:11.5px;color:#8b9bb0;margin-top:2px;line-height:1.4}
.disc{color:#5b6b80;font-size:11px;text-align:center;margin:26px 0 10px}
.gatebox{display:flex;align-items:center;gap:12px;margin:10px 0 14px}
.gate-c{font-size:18px;font-weight:800;color:#fff;border-radius:10px;padding:8px 16px;white-space:nowrap}
.gate-meta{font-size:13px;color:#cdd9ea;line-height:1.5}
.calc-in{display:flex;flex-direction:column;gap:8px;margin:8px 0 6px}
.ci-row{display:flex;align-items:center;gap:8px}
.ci-pre{font-size:18px;color:#8b9bb0;font-weight:700}
.ci-row input,.ci-row2 input{flex:1;min-width:0;background:#0b1220;border:1px solid #243044;border-radius:9px;color:#e6edf3;font-size:17px;padding:10px 12px;-webkit-appearance:none}
.ci-row2{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.ci-row2 input{flex:0 0 92px;font-size:14px;padding:7px 10px}
.ci-fxl{font-size:12px;color:#8b9bb0;font-weight:700}
.calc-sum{margin:8px 0}
.cs-row{display:flex;justify-content:space-between;align-items:center;padding:6px 2px;border-bottom:1px solid #161e2b;font-size:13px;color:#aab6c6}
.cs-row b{color:#e6edf3;font-size:14px}
.cs-cash b{color:#7ff0a8}
.lev-box{background:#0b1220;border:1px solid #1c2533;border-radius:10px;padding:10px 12px;margin:8px 0}
.lev-h{font-size:12px;color:#9fb0c5;margin-bottom:6px;font-weight:700}
.lev-r{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:14px}
.lev-r span:first-child{flex:0 0 56px;font-weight:700;color:#cdd9ea}
.lev-r b{flex:0 0 auto;color:#e6edf3}
.lev-r .mut{flex:1;text-align:right}
.soxl-tr{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 0 2px;font-size:12px;border-top:1px dashed #1c2533;margin-top:4px}
.soxl-tr .mut{flex:1;min-width:140px}
.soxl-btns{display:flex;gap:6px;flex:0 0 auto}
.soxl-btns .nqb{font-size:11px;padding:3px 8px}
.calc-tab{width:100%;border-collapse:collapse;margin-top:6px}
.calc-tab th{font-size:10px;color:#7f8da3;font-weight:700;text-align:right;padding:4px 6px;border-bottom:1px solid #243044}
/* --- v3 additions: sentiment / equity / ribbon / heatmap / changelog / trail --- */
.sn-hero{display:flex;align-items:baseline;gap:12px;margin:6px 0 2px}
.sn-num{font-size:38px;font-weight:900;line-height:1}
.sn-band{font-size:15px;font-weight:800}
.sn-cur{font-size:13px;font-weight:700;margin:8px 0 4px;line-height:1.2}
.sn-gauge{position:relative;height:10px;border-radius:6px;margin:6px 0 2px;
  background:linear-gradient(90deg,#22c55e 0 15%,#38bdf8 15% 35%,#64748b 35% 65%,#f97316 65% 85%,#ef4444 85% 100%);opacity:.9}
.sn-gauge i{position:absolute;top:-3px;width:4px;height:16px;background:#fff;border-radius:2px;box-shadow:0 0 6px #000}
.sn-gl{display:flex;justify-content:space-between;font-size:10px;color:#7d8da1;margin-bottom:8px}
.sn-ref{font-size:9px;font-weight:800;color:#7d8da1;background:#141c2b;border-radius:5px;padding:1px 5px;margin-left:5px}
.sn-note{font-size:10px;color:#5b6b80;margin:0 0 4px 0;padding-left:2px}
/* 要因分解 */
.attrib{margin-top:9px;background:#0b1220;border:1px solid #22304a;border-radius:10px;padding:9px 11px}
.attrib-h{font-size:11.5px;font-weight:800;color:#cfe0f5;margin-bottom:6px}
.attrib-g{display:flex;flex-wrap:wrap;align-items:baseline;gap:5px 7px;font-size:12px;margin-top:2px;font-variant-numeric:tabular-nums}
.attrib-g b{font-size:14px}
.atk{color:#8fa0b5;font-size:11px}
.atsub{font-size:9.5px;color:#5b6b82;margin-left:2px}
.eqrow{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:6px 0}
.eqkv{font-size:12px;color:#9fb0c5}.eqkv b{font-size:14px}
.ribwrap{margin:10px 0 12px}
.riblab{font-size:10px;color:#7d8da1;margin-bottom:4px;font-weight:700;letter-spacing:.03em}
.ribbon{display:flex;gap:1.5px}
.ribbon .rb{flex:1;height:16px;border-radius:2.5px;min-width:2px}
.rb.c-bl{background:#3b82f6}.rb.c-gr{background:#22c55e}.rb.c-yl{background:#eab308}.rb.c-rd{background:#ef4444}
.led{display:inline-flex;gap:2px;margin-left:8px;vertical-align:middle}
.led i{width:9px;height:12px;border-radius:2px;background:#1c2533;display:inline-block}
.led i.on{background:linear-gradient(180deg,#fca5a5,#ef4444);box-shadow:0 0 5px #ef444488}
.ch-card{border-color:#2f4a6a}
ul.chlog{font-size:13px;line-height:1.8;padding-left:18px;color:#dbe4ef;margin:4px 0}
ul.chlog li{margin-bottom:2px}
.hmgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:6px;margin-top:6px}
.hm{border-radius:9px;padding:8px 8px;display:flex;flex-direction:column;gap:2px;min-height:44px}
.hm-n{font-size:11px;font-weight:800;color:#0b0f17;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.55);line-height:1.25}
.hm-tk{display:block;font-size:9px;font-weight:700;opacity:.55;letter-spacing:.03em;margin-top:1px}
.hm-v{font-size:12px;font-weight:900;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.55)}
.erb{font-size:9px;font-weight:800;color:#0b0e14;background:#fbbf24;border-radius:4px;padding:1px 6px;margin-left:5px;vertical-align:middle}
.rsd{font-size:10px;font-weight:800;margin-left:3px}
.rsd.up{color:#4ade80}.rsd.dn{color:#f87171}.rsd.fl{color:#4b5866}
.tday{font-size:9px;color:#7d8da1;font-weight:400}
.risknote{border-top:1px dashed #1c2533;padding-top:6px}
.dov-stage{display:flex;align-items:center;gap:8px;border-radius:9px;padding:7px 10px;margin-bottom:6px;color:#fff}
.dov-stage b{font-size:14px;font-weight:900}
.dov-stg-w{font-size:11.5px;opacity:.95}
.dov-stage.stg1{background:linear-gradient(135deg,#1f2937,#4b5563)}
.dov-stage.stg2{background:linear-gradient(135deg,#0b2a6b,#1d4ed8)}
.dov-stage.stg3{background:linear-gradient(135deg,#713f12,#ca8a04)}
.dov-stage.stg4{background:linear-gradient(135deg,#7f1d1d,#dc2626)}

/* 要因分解 */
.thgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}
.thtile{text-align:left;border:1px solid #22304a;border-radius:11px;padding:9px 11px;cursor:pointer;
        display:flex;flex-direction:column;gap:3px;color:#e6edf3;transition:border-color .15s}
.thtile.on{border-color:#e6edf3;box-shadow:0 0 0 1px #e6edf3 inset}
.tht-n{font-size:13.5px;font-weight:800}
.tht-m{font-size:11px;color:#cbd5e1;font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:6px}
.tht-m b{font-size:13px;color:#fff}
.tht-c{margin-left:auto;color:#8fa0b5;font-weight:600}
.thpanel{margin-top:9px;background:#0b1220;border:1px solid #22304a;border-radius:11px;padding:10px 11px}
.thpanel-h{font-size:12.5px;font-weight:800;color:#eef3fa;margin-bottom:8px}
.thpanel-h .mut{font-weight:500}
.thstks{display:flex;flex-wrap:wrap;gap:6px}
.thstk{display:inline-flex;align-items:center;gap:5px;background:#152134;border:1px solid #26374f;
       border-radius:8px;padding:5px 9px;font-size:12px;cursor:pointer;font-variant-numeric:tabular-nums}
.thstk:active{background:#1e2f49}
.thstk b{color:#cfe0f5;font-weight:800}
.thstk-rs{color:#8fa0b5;font-size:10.5px;font-weight:700}
.thstk-m{font-size:10px}
.thmore{align-self:center;color:#7d8da1;font-size:11px;font-weight:700;padding:0 4px}
.rrgtog{display:flex;gap:4px}
.rtg{background:#141b29;color:#9fb0c5;border:1px solid #1f2a3a;border-radius:14px;padding:4px 11px;font-size:11px;font-weight:700;cursor:pointer}
.rtg.on{background:#1f6feb;color:#fff;border-color:#1f6feb}
.rrgseed{font-size:12.5px;color:#bfe3ff;background:#0e2036;border:1px solid #1d3a55;border-radius:9px;padding:7px 10px;margin:8px 0 4px}
.rrgq{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:7px}
.rrgq-l{font-size:11px;font-weight:900;min-width:34px}
.shiftrow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:2px 0 10px}
.secparent{font-size:9.5px;color:#5a6b82;margin-top:2px;font-weight:500}
.shl{font-size:10px;font-weight:900;color:#4ade80}
.shl-n{color:#f87171;margin-left:6px}
.chip.shp{border-color:#14532d;color:#a7f3d0}
.chip.shn{border-color:#7f1d1d;color:#fecaca}
.le-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:6px 0 2px}
.le-k{font-size:11px;font-weight:900;color:#9fb0c5;min-width:76px;letter-spacing:.03em}
.le-v{font-size:15px;font-weight:800;color:#e6edf3}
.le-pct{font-size:11px;color:#9fb0c5;font-weight:600;margin-left:3px}
.le-rot{font-size:14px;font-weight:900}
.le-sub{font-size:11px;color:#7d8da1}
.le-size{font-size:12px;font-weight:800;margin-left:auto;padding:2px 9px;border-radius:7px;background:#141c2b}
.le-size.pos{color:#7ff0a8}.le-size.neg{color:#fca5a5}.le-size.mut{color:#cbd5e1}
.le-vg{margin:6px 0 2px}


.calc-tab th.l{text-align:left}
.calc-tab td{text-align:right;padding:7px 6px;border-bottom:1px solid #131a26;font-size:13px;vertical-align:top}
.calc-tab td.l{text-align:left}
.entIn{width:74px;background:#0b1220;border:1px solid #243044;border-radius:7px;color:#e6edf3;font-size:13px;padding:5px 7px;text-align:right;-webkit-appearance:none}
.calc-empty{color:#6b7a8d;font-size:13px;text-align:center;padding:18px 0}
.calc-mem{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}
.memx{background:#0b1220;border:1px solid #2a3850;color:#cdd9ea;border-radius:8px;font-size:12px;padding:6px 10px}
.memx:active{background:#0f1a2c}
.tkbtn{display:block;margin-top:5px;width:74px;background:#0b1220;border:1px solid #3a2a12;color:#d9b06a;border-radius:7px;font-size:10px;padding:4px 0;text-align:center}
.tkbtn.on{background:#3a2a12;border-color:#ca8a04;color:#fcd34d;font-weight:700}
.tkbtn:active{opacity:.7}
.redep{background:#0b1220;border:1px solid #20304a;border-radius:10px;padding:10px 12px;margin:8px 0}
.todayact{border:1px solid #243044;border-left:4px solid #6b7280;border-radius:11px;background:#121a26;padding:9px 12px;margin:0 0 10px}
.todayact.ta-blue{border-left-color:#4d9fff}.todayact.ta-green{border-left-color:#34d39c}
.todayact.ta-yellow{border-left-color:#fbbf24}.todayact.ta-red{border-left-color:#f87171}.todayact.ta-gray{border-left-color:#6b7280}
.ta-h{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:#7f8da3;font-weight:700}
.ta-top{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:5px}
.ta-col{font-weight:800;font-size:14px}
.todayact.ta-blue .ta-col{color:#4d9fff}.todayact.ta-green .ta-col{color:#34d39c}
.todayact.ta-yellow .ta-col{color:#fbbf24}.todayact.ta-red .ta-col{color:#f87171}.todayact.ta-gray .ta-col{color:#9aa4b2}
.ta-expo{font-size:12.5px;color:#cbd5e1}
.ta-est{font-size:10px;color:#fbbf24;border:1px solid #5b4a1f;border-radius:5px;padding:1px 6px}
.ta-act{font-size:12.5px;font-weight:600;line-height:1.4;padding:6px 9px;border-radius:7px;background:#0d1420}
.ta-act.ta-alert{color:#fecaca;background:#2a1416;border:1px solid #7f1d1d}
.ta-act.ta-change-up{color:#bfdbfe;background:#0f1d2e}
.ta-act.ta-change-dn{color:#fde68a;background:#241c0a}
.ta-act.ta-normal{color:#9aa4b2;background:transparent;padding-left:0}
.ta-rebal{margin-top:6px;font-size:12px;color:#c7d2fe;background:#161a2e;border-radius:7px;padding:6px 9px}
.ta-go{font-size:11.5px;font-weight:700;color:#a5c8ff;cursor:pointer;margin-left:auto;white-space:nowrap}
.ta-rec{margin-top:7px;display:flex;flex-wrap:wrap;gap:5px;align-items:center;font-size:11.5px;color:#9fb0c5}
.ta-reclab{color:#7f8ea3}
.nqb{font-size:11.5px;font-weight:800;border:1px solid #2a3950;background:#161d2b;color:#cfe0f5;border-radius:6px;padding:2px 9px;cursor:pointer}
.nqb.b-blue{border-color:#4f7fff}
.nqb.b-green{border-color:#37d27f}
.nqb.b-yellow{border-color:#e8b84a}
.nqb.b-red{border-color:#ef5d6c}
.nqb.b-clear{color:#7f8ea3;font-weight:700}
.ta-manual{font-size:10px;font-weight:800;background:#dbe7ff;color:#0e2138;border-radius:5px;padding:1px 7px;margin-left:6px}
.ta-recst{color:#7f8ea3;font-size:11px}
.ta-tog{margin-left:auto;font-size:14px;line-height:1;color:#8a99ad;cursor:pointer;user-select:none;padding:2px 5px}
.ta-tog:active{opacity:.55}
.ta-more{margin-top:5px}
.ta-go:active{opacity:.6}
.cmt-note{font-size:13.5px;font-weight:700;line-height:1.5;padding:9px 12px;border-radius:9px;margin-bottom:10px}
.cmt-pos{color:#9be8b8;background:#0c1f16;border:1px solid #1c4631}
.cmt-neg{color:#fecaca;background:#2a1416;border:1px solid #7f1d1d}
.secrs th.sortable{cursor:pointer}
.secrs th.sortable:active{opacity:.55}
.secrs th.sortable.act{color:#e6edf3;text-decoration:underline}
.secrs th .so{font-size:9px;color:#7f8da3}
.rc-h{font-size:12px;color:#aab6c6;margin-bottom:8px;font-weight:700}
.rc-sec{margin:8px 0}
.rc-l{font-size:11px;font-weight:700;margin-bottom:4px}
.rc-sl{color:#fca5a5}.rc-ad{color:#7ff0a8}
.rc-row{display:flex;justify-content:space-between;align-items:center;padding:6px 9px;border-radius:7px;background:#0b1220;border:1px solid #161e2b;margin-bottom:4px;font-size:13px}
.rc-row b{color:#e6edf3}
.rc-okall{font-size:12.5px;color:#7ff0a8;background:#0c1f16;border-radius:8px;padding:9px 11px}
.dov-meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 8px}
.dov-sec{font-size:12.5px;font-weight:700;color:#9ecbff}
.dov-cap{font-size:11px;font-weight:800;color:#cbd5e1;background:#1b2433;border:1px solid #2a3547;border-radius:6px;padding:1px 7px}
.dov-loc{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin:0 0 12px}
.dov-loc-l{font-size:10px;font-weight:800;color:#7d8da1;margin-right:2px}
.dov-loc-b{font-size:11px;font-weight:700;border-radius:6px;padding:2px 8px}
.loc-p{background:#0f3d1f;border:1px solid #1f9d4d;color:#86efac}
.loc-d{background:#10271f;border:1px solid #1f7a55;color:#7fe0c0}
.loc-k{background:#3a210f;border:1px solid #c2660b;color:#fdba74}
.loc-h{background:#0d2740;border:1px solid #2f81f7;color:#9ecbff}
.loc-w{background:#1b2433;border:1px solid #2a3547;color:#cbd5e1}
.dov-st{display:flex;align-items:center;gap:8px;flex-wrap:wrap;border-radius:10px;padding:9px 12px;border:1px solid #1c2533;background:#0b1220}
.dov-st.lead{border-left:4px solid #1f6feb}
.dov-st.nolead{border-left:4px solid #3a4452;opacity:.85}
.dov-st-pos{font-size:14px;font-weight:800;color:#e6edf3}
.dov-st-nu{font-size:11px;font-weight:800;border-radius:6px;padding:2px 8px;margin-left:auto}
.dov-st-nu.pos{background:#14331f;color:#86efac;border:1px solid #1d7840}
.dov-st-nu.neg{background:#3a1414;color:#fca5a5;border:1px solid #7f1d1d}
.dov-st-nu.mut{background:#0f1622;color:#9fb0c5;border:1px solid #1c2533}
.dov-st-note{font-size:11px;color:#9fb0c5;margin-top:6px;line-height:1.45}
.dov-st.st-③{border-left-color:#16a34a}.dov-st.st-②{border-left-color:#1f6feb}
.dov-st.st-①{border-left-color:#d97706}.dov-st.st-④{border-left-color:#ea580c}
.dov-st.st-⑤{border-left-color:#dc2626}
.dov-c{background:#0b1220;border:1px solid #1c2533;border-radius:9px;padding:8px 10px}
.dov-k{font-size:11px;color:#7d8da1}
.dov-v{font-size:16px;font-weight:800;margin-top:2px}
.dov-note{font-size:10px;color:#7d8da1;text-align:center;margin-top:12px}
/* 銘柄検索 */
.tksearch{width:100%;background:#0b1220;border:1px solid #243349;border-radius:9px;color:#e6edf3;font-size:15px;padding:10px 12px;margin-top:4px}
.tksearch:focus{outline:none;border-color:#2f81f7}
.tkresults{margin-top:8px;display:flex;flex-direction:column;gap:5px}
.tkr{display:flex;align-items:center;gap:8px;background:#0b1220;border:1px solid #1c2533;border-radius:8px;padding:8px 10px;cursor:pointer}
.tkr-s{font-size:14px;font-weight:800;color:#9ecbff;flex:0 0 62px}
.tkr-n{font-size:11px;color:#9fb0c5;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tkr-rs{font-size:11px;color:#7d8da1;flex:0 0 auto}
.tkno{color:#7d8da1;font-size:12px;padding:4px}
.secrow{cursor:pointer}
.secx{font-size:9px;color:#7d8da1}
.secsub{display:none}
.secsub.open{display:table-row}
.secchips{display:flex;flex-wrap:wrap;gap:5px;padding:8px 2px}
.rsb{margin-left:5px;opacity:.6;font-size:10px;font-weight:700}
.rowsec{font-size:9px;font-weight:400;color:#7d8da1;margin-top:1px;line-height:1.15}
tr[data-tkone]{cursor:pointer}
tr[data-tkone]:active{background:#0f1a2c}
.bt:active,.buy:active,.tkr:active{background:#13233a}
.capb{font-size:9px;font-weight:800;border-radius:5px;padding:1px 4px;white-space:nowrap}
.cap-micro{background:#3a1414;color:#fca5a5;border:1px solid #7f1d1d}
.cap-small{background:#3a2a14;color:#fcd34d;border:1px solid #78531d}
.cap-mid{background:#14233a;color:#93c5fd;border:1px solid #1d4e78}
.cap-large{background:#14331f;color:#86efac;border:1px solid #1d7840}
.cap-mega{background:#0f2e2e;color:#5eead4;border:1px solid #156464}
.cap-none{background:#0f1622;color:#5b6b80;border:1px solid #1c2533}
.stb{font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;white-space:nowrap;border:1px solid #1c2533;background:#0b1220}
.stb b{font-weight:800}
.stb-③{color:#86efac;border-color:#1d7840}.stb-②{color:#93c5fd;border-color:#1d4e78}
.stb-①{color:#fcd34d;border-color:#78531d}.stb-④{color:#fdba74;border-color:#9a4a1d}
.stb-⑤{color:#fca5a5;border-color:#7f1d1d}.stb-none{color:#7d8da1}
.rowbadges{display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-top:2px}
.bt[data-tkone],.buy[data-tkone]{cursor:pointer}
.rk-note{background:#0b1626;border:1px solid #16324f;border-radius:9px;padding:8px 10px;color:#9fb0c5}
.capfil{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.liqstick{position:sticky;top:46px;z-index:8;padding:8px 12px;margin-bottom:10px;box-shadow:0 4px 12px rgba(0,0,0,.35)}
.liqrow{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.liqlab{font-size:11px;font-weight:800;color:#9fb0c5;display:flex;flex-direction:column;line-height:1.1;margin-right:3px}
.liqsub{font-size:8px;font-weight:600;color:#5b6b80}
.lqf-b{font-size:12px;font-weight:700;padding:6px 10px;border-radius:8px;background:#0f1622;color:#9fb0c5;border:1px solid #1c2533;cursor:pointer}
.lqf-b.active{background:#1d4ed8;color:#fff;border-color:#1d4ed8}
.lqf-rec{border-color:#1d7840}
.lqf-tag{font-size:8px;font-weight:800;margin-left:3px;color:#86efac;vertical-align:top}
.lqf-rec.active .lqf-tag{color:#bbf7d0}
.sectog{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:2px 0 8px}
.stg-g,.stg-t{font-size:12px;font-weight:700;padding:4px 10px;border-radius:7px;background:#0f1622;color:#9fb0c5;border:1px solid #1c2533;cursor:pointer}
.stg-g.active{background:#1d4ed8;color:#fff;border-color:#1d4ed8}
.stg-t.active{background:#334155;color:#fff;border-color:#475569}
.stg-sep{color:#3a4453;font-weight:400;margin:0 2px}
.secsub td{background:#0c1320;color:#8fa0b5;font-size:10px;font-weight:800;padding:3px 4px}
td.hl{background:rgba(56,80,140,.20);font-weight:800}
.subgrp{margin:6px 0 2px}
.subgrp-h{font-size:10px;font-weight:700;color:#8fa3bd;letter-spacing:.02em;margin:0 0 3px;display:flex;align-items:center;gap:5px}
.subgrp-n{font-size:9px;font-weight:700;color:#5b6b80;background:#0f1622;border:1px solid #1c2533;border-radius:4px;padding:0 4px}

/* ランク番号＋急落局面フラグ（配分calc） */
.rkb{display:inline-block;min-width:22px;text-align:center;font-size:10.5px;font-weight:800;color:#0b0f17;background:#93b7df;border-radius:5px;padding:1px 4px;margin-right:2px;font-variant-numeric:tabular-nums}
.kflag{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 5px;margin-left:4px;vertical-align:middle}
.kf-half{background:rgba(234,179,8,.18);color:#eab308;border:1px solid rgba(234,179,8,.4)}
.kf-skip{background:rgba(239,68,68,.16);color:#f87171;border:1px solid rgba(239,68,68,.4)}
.kf-skiptxt{color:#f87171;font-weight:800;font-size:12px}
.kf-ok{background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.4)}
.kf-oktxt{color:#4ade80;font-weight:800;font-size:12px}
.hf{color:#eab308;font-weight:800;font-size:11px;margin-left:3px}
.row-skip{opacity:.72}
.th-w{white-space:nowrap;line-height:1.15}
.dax{display:flex;justify-content:space-between;font-size:9px;color:#5b6b82;padding:3px 3px 0;font-variant-numeric:tabular-nums}
.cap-c{justify-content:center}
/* 先導株の強さ温度計 */
.lt-hero{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:7px}
.lt-big{font-size:32px;font-weight:800;color:#f59e0b;font-variant-numeric:tabular-nums;line-height:1}
.lt-big span{font-size:13px;font-weight:700;color:#8494ab;margin-left:3px}
.lt-lv{font-size:13px;font-weight:700;color:#cfe0f5}
.lt-hist{display:flex;justify-content:space-between;gap:4px;margin-top:9px}
.lt-h{flex:1;text-align:center;background:#0b1220;border:1px solid #1c2533;border-radius:8px;padding:5px 2px}
.lt-hk{display:block;font-size:9.5px;color:#8494ab;margin-bottom:1px}
.lt-h b{font-size:15px;font-variant-numeric:tabular-nums}
.lt-hu{display:block;font-size:8.5px;color:#5b6b82}
/* マーケット感応度 β */
.beta-hero{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.beta-big{font-size:34px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums}
.beta-lb{font-size:11px;color:#8494ab;margin-top:2px}
.beta-read{font-size:13px;font-weight:700;color:#cfe0f5}
.beta-read .mut{font-weight:500;display:block;font-size:11px}
.beta-det{margin-top:9px}
.beta-det summary{font-size:12px;color:#93b7df;cursor:pointer;font-weight:700}
.bt-grid{margin-top:7px;display:flex;flex-direction:column;gap:5px}
.bt-row{display:flex;align-items:baseline;gap:8px;font-size:12.5px}
.bt-k{color:#8fa0b5;min-width:120px}
.bt-row b{font-size:15px;font-variant-numeric:tabular-nums}
.bt-s{color:#5b6b82;font-size:10.5px}
/* ===== レスポンシブ: タブレット/デスクトップ（末尾＝最優先） ===== */
@media (min-width:760px){
  .wrap{max-width:920px;padding-left:20px;padding-right:20px}
  body{font-size:15px}
  h1{font-size:21px}
  .card{padding:14px 18px;border-radius:15px;margin-bottom:14px}
  .card h2{font-size:16px}
  .card .sub{font-size:12px}
  nav{padding:11px 0}
  nav button{font-size:14px;padding:9px 18px}
  .banner{padding:16px 20px}
  .banner .val{font-size:36px}
  .perf{grid-template-columns:repeat(6,1fr)}
  .hmgrid{grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:8px}
  .dov-grid{grid-template-columns:repeat(4,1fr)}
  .buy-g,.bt-g{grid-template-columns:repeat(4,1fr)}
  table{font-size:13.5px}
  th,td{padding:6px 8px}
}
@media (min-width:1080px){
  .wrap{max-width:1060px}
  .buy-g,.bt-g{grid-template-columns:repeat(5,1fr)}
}
"""

JS = r"""
function tab(id,btn){
  document.querySelectorAll('section').forEach(s=>s.classList.remove('on'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  btn.classList.add('on');
  window.scrollTo(0,0);
  if(id==='t-alloc'){ try{eqInit();}catch(e){} }
}
function goTab(id){
  var t=null;
  document.querySelectorAll('nav button').forEach(function(b){
    var oc=b.getAttribute('onclick')||''; if(oc.indexOf("'"+id+"'")>-1) t=b;
  });
  if(t) tab(id,t);
}
function rrgGran(mode,btn){
  var a=document.getElementById('rrg-16'), z=document.getElementById('rrg-all');
  if(!a||!z) return;
  if(mode===16){ a.style.display=''; z.style.display='none'; }
  else { a.style.display='none'; z.style.display=''; }
  var b16=document.getElementById('rtg-16'), ball=document.getElementById('rtg-all');
  if(b16&&ball){ b16.classList.toggle('on',mode===16); ball.classList.toggle('on',mode!==16); }
}
function showThemeHier(el){
  if(event){event.stopPropagation();}
  var d; try{ d=JSON.parse(el.getAttribute('data-hier').replace(/&quot;/g,'"')); }catch(e){ return; }
  var QC={'主導':'#4ade80','改善':'#60a5fa','弱化':'#fbbf24','停滞':'#f87171'};
  var disp=d.theme.indexOf('. ')>=0? d.theme.split('. ').slice(1).join('. '):d.theme;
  var rows=d.subs.map(function(su,ix){
    var qc=QC[su.q]||'#8b949e';
    var mem=(su.members||[]).map(function(mm){
      return '<span class="hmem" data-tkone="'+mm.t+'" onclick="hierPick(this)">'+mm.t+
        (mm.rs!=null?'<span class="rsb">'+mm.rs+'</span>':'')+'</span>';
    }).join('');
    var arrow=su.drs>0?'▲':su.drs<0?'▼':'＝';
    return '<div class="hsub-row"><div class="hsub-hd" onclick="hierSub('+ix+')">'+
      '<div class="hsub-name">'+su.sub+'<span class="hsub-q" style="background:'+qc+'22;color:'+qc+'">'+su.q+'</span></div>'+
      '<div class="hsub-meta">RS '+su.rs+' ・ '+arrow+Math.abs(su.drs)+' ・ '+su.n+'銘柄</div></div>'+
      '<div class="hsub-mem" id="hsub'+ix+'">'+mem+'</div></div>';
  }).join('');
  var m=document.getElementById('hierModal');
  m.querySelector('.hier-box').innerHTML='<h3>'+disp+'</h3>'+
    '<div class="hb-sub">ニッチ業種をRS強い順に表示。行タップで構成銘柄、銘柄タップで詳細。</div>'+rows;
  m.classList.add('on');
}
function hierSub(ix){ var e=document.getElementById('hsub'+ix); if(e) e.classList.toggle('on'); }
function hierPick(el){
  if(event){event.stopPropagation();}
  var tk=el.getAttribute('data-tkone');
  document.getElementById('hierModal').classList.remove('on');
  if(tk && typeof showDet==='function'){ showDet(tk); }
}
function copyTk(b){
  if(event){event.stopPropagation();}
  var t=b.getAttribute('data-tk')||'';
  navigator.clipboard.writeText(t).then(function(){
    var o=b.textContent; b.textContent='✓ コピー済'; b.classList.add('done');
    setTimeout(function(){b.textContent=o; b.classList.remove('done');},1200);
  });
}
function copyList(b){
  if(event){event.stopPropagation();}
  var t=b.getAttribute('data-list')||'';
  navigator.clipboard.writeText(t).then(function(){
    var o=b.textContent; b.textContent='✓ コピー済'; b.classList.add('done');
    setTimeout(function(){b.textContent=o; b.classList.remove('done');},1200);
  });
}
function eqInit(){
  try{
    var el=document.getElementById('eqIn'); if(!el) return;
    var jp=document.getElementById('jpyIn'); var jv=jp?parseFloat(jp.value):NaN;
    if(jv&&jv>0){ el.value=Math.round(jv); }
    else { var last=null; try{last=localStorage.getItem('eqLast');}catch(e){} if(last&&!el.value){ el.value=last; } }
    var ds=document.getElementById('eqDate');
    if(ds){ var d=new Date(),p=function(n){return(n<10?'0':'')+n;};
      ds.textContent=d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate()); }
  }catch(e){}
}
function copyEquityRow(){
  var el=document.getElementById('eqIn');
  var v=el?parseFloat(el.value):NaN;
  var btn=document.getElementById('eqCopyBtn');
  if(!v || v<=0){
    if(btn){var o=btn.textContent; btn.textContent='⚠ 金額を入力してから'; setTimeout(function(){btn.textContent=o;},1500);}
    return;
  }
  try{ localStorage.setItem('eqLast', String(Math.round(v))); }catch(e){}
  var d=new Date(), pad=function(n){return (n<10?'0':'')+n;};
  var ds=d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  var ue=document.getElementById('eqUsIn');
  var uv=ue?parseFloat(ue.value):NaN;
  var dl=((window.CALC&&window.CALC.eq_delim)||',');   // 既存ファイルの区切りに合わせる（写真の体裁ズレ対策）
  var row=ds+dl+Math.round(v)+((uv||uv===0)&&uv>=0&&uv<=100?dl+uv:'');
  navigator.clipboard.writeText(row).then(function(){
    if(btn){var o=btn.textContent; btn.textContent='✓ コピー済（'+(dl===','?'カンマ':'スペース')+'区切り）→ equity.csvに貼り付け'; btn.classList.add('done');
      setTimeout(function(){btn.textContent=o; btn.classList.remove('done');},2200);}
  });
}
function toggleMri(){
  var p=document.getElementById('mri-bd');
  if(p){p.classList.toggle('open');}
}
function _f(v,s){ return (v===null||v===undefined)?'—':(v+(s||'')); }
function _sg(v){ if(v===null||v===undefined) return 'mut'; return v>=0?'pos':(v<0?'neg':'mut'); }
function thStk(el){ var t=el.getAttribute('data-tk'); if(t) showDet(t); }
function thDrill(i){
  var pan=document.getElementById('thp-'+i), til=document.getElementById('tht-'+i);
  if(!pan) return;
  var open = pan.style.display!=='none';
  // 全パネル閉じ＆全タイル非アクティブ
  document.querySelectorAll('.thpanel').forEach(function(x){x.style.display='none';});
  document.querySelectorAll('.thtile').forEach(function(x){x.classList.remove('on');});
  if(!open){ pan.style.display='block'; if(til) til.classList.add('on'); pan.scrollIntoView({block:'nearest',behavior:'smooth'}); }
}
function showDet(tk){
  var d=(window.DET||{})[tk]; if(!d) return;
  document.getElementById('dov-tk').textContent=tk;
  var NUNOTE={'急落中':'下げが速い（急落局面）。投げ（セリングクライマックス）を確認できるまで新規は一服待ち・保有は防御を',
              '反発中':'下げ止まって切り返し。押し目なら入りやすい局面',
              '堅調':'値持ちが良く落ち着いた値動き・押しが浅い',
              '軟調':'じり安で方向感に乏しい・様子見'};
  var nunote=NUNOTE[d.nut]||'';
  var sb='';
  if(d.ld){
    sb='<div class="dov-st lead st-'+d.stc+'"><span class="dov-st-pos">RSリーダー '+d.stc+d.stl+'</span>'
      +(d.nut?'<span class="dov-st-nu '+d.nucls+'">'+d.nut+'</span>':'')+'</div>'
      +(nunote?'<div class="dov-st-note">'+nunote+'</div>':'');
  } else {
    sb='<div class="dov-st nolead"><span class="dov-st-pos">'+(d.rsn||'リーダー対象外')+'</span>'
      +(d.nut?'<span class="dov-st-nu '+d.nucls+'">'+d.nut+'</span>':'')+'</div>'
      +(nunote?'<div class="dov-st-note">'+nunote+'</div>':'');
  }
  var STG={1:['ステージ1','stg1','底固め・移行期（30週線の上に出たが線はまだ下向き）。ステージ2入り＝線が上向くのを確認してから'],
           2:['ステージ2','stg2','上昇トレンド（30週線の上×線が上向き）。押し目・ブレイクの対象'],
           3:['ステージ3','stg3','天井圏の兆候（30週線割れ・線はまだ上向き）。新規は避け、利確・トレール管理を優先'],
           4:['ステージ4','stg4','下降トレンド（30週線の下×線が下向き）。買い禁止・戻りは売り場']};
  if(d.wst&&STG[d.wst]){
    var sg=STG[d.wst],ex='';
    if(d.wst==2){
      var done=d.wsb||0, late=done+(d.wsbf?1:0);
      if(d.wsbf){ex=' ・ 第'+(done+1)+'ベース形成中';}
      else if(done>0){ex=' ・ ベース'+done+'本消化';}
      if(late>=3){ex+='（後期・失敗率上昇）';}
    }
    sb='<div class="dov-stage stg'+d.wst+'"><b>'+sg[0]+'</b><span class="dov-stg-w">'
       +(d.wstw?d.wstw+'週目':'')+ex+'</span></div>'
       +'<div class="dov-st-note">'+sg[2]+'</div>'+sb;
  }
  document.getElementById('dov-status').innerHTML=sb;
  // セクター/サブテーマ/時価総額
  var meta='';
  if(d.sec||d.sth){
    meta='<span class="dov-sec">'+(d.sec||'')+(d.sth&&d.sth!==d.sec?' ・ '+d.sth:'')+'</span>';
  }
  if(d.cap){ meta+='<span class="dov-cap">'+d.cap+'</span>'; }
  document.getElementById('dov-meta').innerHTML=meta;
  // 登場箇所（保有/控え/ピックアップ/新高値/ウォッチ）
  var lc=d.loc||[];
  document.getElementById('dov-loc').innerHTML = lc.length
    ? '<span class="dov-loc-l">登場</span>'+lc.map(function(x){
        var c='loc-w'; if(x.indexOf('保有')===0)c='loc-p'; else if(x.indexOf('控え')===0)c='loc-d';
        else if(x.indexOf('ピックアップ')===0)c='loc-k'; else if(x.indexOf('新高値')===0)c='loc-h';
        return '<span class="dov-loc-b '+c+'">'+x+'</span>'; }).join('')
    : '';
  var rows=[['RS(63日)',_f(d.rs),'mut'],
            ['RS(189日・選定)',_f(d.rs189),'mut'],
            ['価格',(d.px===null||d.px===undefined)?'—':('$'+d.px),'mut'],
            ['前日比',_f(d.ch,'%'),_sg(d.ch)],
            ['vs50MA',_f(d.v50,'%'),_sg(d.v50)],
            ['vs200MA',_f(d.v200,'%'),_sg(d.v200)],
            ['21EMA乖離',_f(d.d21,'%'),'mut'],
            ['押し目',_f(d.pb,'%'),_sg(d.pb)],
            ['ADR',_f(d.adr,'%'),'mut'],
            ['RVOL',_f(d.rv),'mut'],
            ['β(市場感応度)',(d.beta===null||d.beta===undefined)?'—':_f(d.beta),(d.beta>=1.3?'neg':d.beta<=0.9?'pos':'mut')],
            ['出来高$',(d.dvol===null||d.dvol===undefined)?'—':(d.dvol+'M'),'mut']];
  document.getElementById('dov-body').innerHTML=rows.map(function(r){
    return '<div class="dov-c"><div class="dov-k">'+r[0]+'</div><div class="dov-v '+r[2]+'">'+r[1]+'</div></div>';
  }).join('');
  document.getElementById('dov-bg').classList.add('open');
}
function hideDet(){ var b=document.getElementById('dov-bg'); if(b){b.classList.remove('open');} }
function secToggle(id){ var r=document.getElementById(id); if(r){ r.classList.toggle('open'); } }
function secSort(key, th){
  var tbl=th.closest('table'); if(!tbl) return;
  var gs=Array.prototype.slice.call(tbl.querySelectorAll('tbody.secgrp'));
  var val=function(g){var v=parseFloat(g.getAttribute('data-'+key));return isNaN(v)?-Infinity:v;};
  gs.sort(function(a,b){return val(b)-val(a);});
  gs.forEach(function(g,i){tbl.appendChild(g);var n=g.querySelector('.secnum');if(n)n.textContent=(i+1);});
  tbl.querySelectorAll('th.sortable').forEach(function(h){h.classList.remove('act');});
  th.classList.add('act');
}
function liqFilter(min, btn){
  var sec=btn.closest('section'); if(!sec) return;
  sec.querySelectorAll('.lqf-b').forEach(function(b){ b.classList.remove('active'); });
  btn.classList.add('active');
  sec.querySelectorAll('[data-liq]').forEach(function(el){
    el.style.display=(parseFloat(el.getAttribute('data-liq'))>=min)?'':'none';
  });
}
document.addEventListener('click',function(e){
  var el=e.target.closest?e.target.closest('[data-tkone]'):null;
  if(el){ showDet(el.getAttribute('data-tkone')); return; }
  if(e.target.id==='dov-bg'){ hideDet(); }
});
function _liqDefault(){
  try{ document.querySelectorAll('section .lqf-rec').forEach(function(b){ liqFilter(10, b); }); }catch(e){}
}
if(document.readyState!=='loading'){ _liqDefault(); }
else { document.addEventListener('DOMContentLoaded', _liqDefault); }
/* --- NQ手動記録（localStorage上書き：推定より優先・端末ローカル） --- */
var NQG={Blue:[1,1],Green:[1,0.5],Yellow:[1,0],Red:[0,0]};
var NQL={Blue:'青',Green:'緑',Yellow:'黄',Red:'赤'};
var NQR={Red:0,Yellow:1,Green:2,Blue:3};
var NQJUD={Blue:['Blue','強い上昇','継続'],Green:['Green','上昇(中位)','中立'],Yellow:['Yellow','弱含み','警戒'],Red:['Red','下落','回避']};
function _nqPct(x){return Math.round(x*100);}
function _nqExpo(c){
  if(c==='Red') return '個別 0% ／ レバ 0% ・ 全現金';
  var g=NQG[c]; var cash=(g[0]<1||g[1]<1)?'残りは現金（ゲート由来）':'フル投資';
  return '個別 '+_nqPct(g[0])+'% ／ レバ '+_nqPct(g[1])+'% ・ '+cash;
}
function _nqMult(p,n){
  if(n<=0) return p<=0?'なし':'全部売り';
  if(p<=0) return '配分タブの株数で新規';
  var r=n/p;
  if(Math.abs(r-1)<1e-9) return '変更なし';
  if(Math.abs(r-0.5)<1e-9) return '半分売り（×0.5）';
  if(Math.abs(r-2)<1e-9) return '倍に買い増し（×2）';
  return '×'+(Math.round(r*100)/100);
}
function _nqAct(prev,c){
  if(prev && prev!==c && NQG[prev]){
    var up=NQR[c]>NQR[prev]; var gp=NQG[prev], gn=NQG[c];
    return 'NQ '+NQL[prev]+'→'+NQL[c]+'（'+(up?'攻め強化':'守りへ')+'）→ 翌寄りで 個別：'+_nqMult(gp[0],gn[0])+'／レバ：'+_nqMult(gp[1],gn[1]);
  }
  if(c==='Red') return '退避：個別0%・レバ0%・全現金。保有は寄りで手仕舞い';
  if(c==='Blue') return 'フル投資：個別100%・レバ100%。保有維持・トレール対応';
  return NQL[c]+'：個別'+_nqPct(NQG[c][0])+'%／レバ'+_nqPct(NQG[c][1])+'%。色が変わったら配分タブで株数調整';
}
function _nqApply(c,prev,ts){
  var card=document.getElementById('taCard'); if(!card||!NQG[c]) return;
  card.className=card.className.replace(/ta-(blue|green|yellow|red|gray)/g,'ta-'+c.toLowerCase());
  var col=document.getElementById('taCol'); if(col) col.textContent='NQ '+NQL[c];
  var ex=document.getElementById('taExpo'); if(ex) ex.textContent=_nqExpo(c);
  var k=(prev&&prev!==c&&NQG[prev])?(NQR[c]>NQR[prev]?'change-up':'change-dn'):(c==='Red'?'alert':'normal');
  var ac=document.getElementById('taAct'); if(ac){ ac.textContent=_nqAct(prev,c); ac.className='ta-act ta-'+k; }
  var es=document.getElementById('taEst'); if(es) es.style.display='none';
  var mb=document.getElementById('taManual'); if(mb) mb.innerHTML='<span class="ta-manual">手動確定 '+NQL[c]+(ts?'（記録 '+ts+'）':'')+'</span>';
  if(k!=='normal'){ var mm=document.getElementById('taMore'),tt=document.getElementById('taTog'); if(mm) mm.style.display=''; if(tt) tt.textContent='▴'; }
  var pill=document.getElementById('sarPill');
  if(pill){
    pill.className=pill.className.replace(/sar-(blue|green|yellow|red|gray)/g,'sar-'+c.toLowerCase());
    var J=NQJUD[c]||['','',''];
    var sc=document.getElementById('sarCol'); if(sc) sc.textContent=J[0];
    var sj=document.getElementById('sarJud'); if(sj) sj.textContent=J[1];
    var sl=document.getElementById('sarLot'); if(sl) sl.textContent=J[2];
    var sb=document.getElementById('sarBadge'); if(sb) sb.innerHTML='<span class="sar-badge ok">手動</span>';
  }
  var gc=document.getElementById('calcGateC');
  if(gc){ gc.className=gc.className.replace(/sar-(blue|green|yellow|red|gray)/g,'sar-'+c.toLowerCase()); gc.textContent='NQ '+NQL[c]; }
  var ce=document.getElementById('calcExpo');
  if(ce){ var g2=NQG[c]; ce.innerHTML='個別 露出 <b>'+_nqPct(g2[0])+'%</b> ／ レバ 露出 <b>'+_nqPct(g2[1])+'%</b>'; }
  if(window.CALC){ window.CALC.e_ind=NQG[c][0]; window.CALC.e_lev=NQG[c][1]; window.CALC.color=c; }
  if(typeof calcRun==='function'){ try{calcRun();}catch(e){} }
}
function taToggle(){
  var m=document.getElementById('taMore'), t=document.getElementById('taTog'); if(!m) return;
  var open=m.style.display!=='none';
  m.style.display=open?'none':''; if(t) t.textContent=open?'▾':'▴';
}
function _nqNow(){var d=new Date();function z(x){return(x<10?'0':'')+x;}return z(d.getMonth()+1)+'/'+z(d.getDate())+' '+z(d.getHours())+':'+z(d.getMinutes());}
function setNQ(c){
  var cur=null; try{cur=JSON.parse(localStorage.getItem('nqManual'));}catch(e){}
  var card=document.getElementById('taCard');
  var prev=(cur&&cur.color)||(card?card.getAttribute('data-srv'):'')||'';
  var rec={color:c,prev:prev,ts:_nqNow()};
  try{localStorage.setItem('nqManual',JSON.stringify(rec));}catch(e){}
  _nqApply(c,prev,rec.ts);
}
function clearNQ(){ try{localStorage.removeItem('nqManual');}catch(e){} location.reload(); }
(function(){ try{var s=JSON.parse(localStorage.getItem('nqManual')); if(s&&s.color&&NQG[s.color]) _nqApply(s.color,'',s.ts||''); }catch(e){} })();
/* ---- 隔週・月曜リバランス判定（今日が月曜 かつ 前回から≥13日／localStorage・祝日でもズレない） ---- */
function _rebalCheck2(){
  var el=document.getElementById('taRebal'); if(!el) return;
  var today=new Date(), isMon=today.getDay()===1, last=null;
  try{last=localStorage.getItem('lastRebal');}catch(e){}
  var days=last?Math.floor((today-new Date(last+'T00:00:00'))/864e5):999;
  var n=(window.CALC&&window.CALC.n)||12;
  if(isMon&&days>=13){
    el.style.display='';
    var _col=(window.CALC&&window.CALC.color)||'';
    var _msg;
    if(_col==='Yellow'||_col==='Red'){
      _msg='📅 隔週リバランス日（月曜・NQ'+(_col==='Yellow'?'黄':'赤')+'＝新規停止） → 継続条件（50&gt;200日線・RS上位'+(2*n)+'）を外れた保有を<b>売るのみ</b>。空き枠は現金・新規は組まない（青/緑復帰まで）';
    } else {
      _msg='📅 今日は隔週リバランス日（月曜） → 継続条件（50&gt;200日線・RS上位'+(2*n)+'）を外れた銘柄を売って最新トップ'+n+'へ組み直し＋<b onclick="goTab(\'t-alloc\')" style="cursor:pointer;text-decoration:underline">配分タブ</b>で株数確認';
    }
    el.innerHTML=_msg+' <button class="nqb b-clear" onclick="rebalDone()" style="margin-left:6px">完了にする</button>';
    var mm=document.getElementById('taMore'), tt=document.getElementById('taTog');
    if(mm) mm.style.display=''; if(tt) tt.textContent='▴';
  } else { el.style.display='none'; }
}
function rebalDone(){ try{localStorage.setItem('lastRebal',new Date().toISOString().slice(0,10));}catch(e){} _rebalCheck2(); }
if(document.readyState!=='loading'){ _rebalCheck2(); }
else { document.addEventListener('DOMContentLoaded', _rebalCheck2); }
function tkSearch(q){
  var box=document.getElementById('tkresults'); if(!box) return;
  q=(q||'').trim().toUpperCase();
  if(q.length<1){ box.innerHTML=''; return; }
  var D=window.DET||{}, out=[];
  for(var k in D){
    if(k.indexOf(q)>-1){ out.push(k); }
    if(out.length>200) break;
  }
  out.sort(function(a,b){
    var pa=a.indexOf(q)===0?0:1, pb=b.indexOf(q)===0?0:1;
    if(pa!==pb) return pa-pb; return a<b?-1:1;
  });
  if(out.length===0){ box.innerHTML='<div class="tkno">該当なし</div>'; return; }
  box.innerHTML=out.slice(0,20).map(function(k){
    var d=D[k];
    return '<div class="tkr" data-tkone="'+k+'"><span class="tkr-s">'+k+'</span>'
      +'<span class="tkr-rs">RS '+(d.rs==null?'—':d.rs)+'</span></div>';
  }).join('');
}
/* ---- 資金配分・株数計算＋建値/売却メモリ（localStorage） ---- */
function ccKey(){return 'cc_entries_v1';}
function ccPeakKey(){return 'cc_peak_v1';}
function ccTakenKey(){return 'cc_taken_v1';}
function ccLoad(k){try{return JSON.parse(localStorage.getItem(k)||'{}')||{};}catch(e){return {};}}
function ccSet(k,o){try{localStorage.setItem(k,JSON.stringify(o));}catch(e){}}
function ccPeak(t,px,entry){
  if(!entry) return null;
  var o=ccLoad(ccPeakKey()); var cur=o[t]||entry; if(px>cur)cur=px; o[t]=cur; ccSet(ccPeakKey(),o); return cur;
}
function takenLoad(){return ccLoad(ccTakenKey());}
function toggleTaken(t){ var o=takenLoad(); if(o[t])delete o[t]; else o[t]=1; ccSet(ccTakenKey(),o); calcRun(); }
function plHtml(n,e,tk){
  if(!e) return '<span class="mut">建値未入力</span>';
  var trM=(window.CALC&&window.CALC.color==='Yellow')?0.85:0.70;
  var pl=(n.px/e-1)*100, stop=e*0.75, pk=ccPeak(n.t,n.px,e), tr=pk?pk*trM:null;
  var sh=n.px<=stop?' <span class="neg">割れ</span>':'';
  var trHit=(tr&&n.px<=tr)?' <span class="neg">割れ→売り</span>':'';
  return '<span class="'+(pl>=0?'pos':'neg')+'" style="font-weight:700">'+(pl>=0?'+':'')+pl.toFixed(1)+'%</span>'
       + '<div class="mut" style="font-size:10px">−25% $'+stop.toFixed(2)+sh+' ・ trail('+(trM===0.85?'15%':'30%')+') $'+(tr?tr.toFixed(2):'—')+trHit+'</div>';
}
function entSave(el){
  var o=ccLoad(ccKey()), t=el.getAttribute('data-t'), v=parseFloat(el.value);
  if(v>0)o[t]=v; else delete o[t]; ccSet(ccKey(),o);
  var C=window.CALC||{}, n=(C.names||[]).find(function(x){return x.t===t;}); if(!n)return;
  var tr=el.closest('tr'), c=tr&&tr.querySelector('.pl-cell'); if(c)c.innerHTML=plHtml(n,v>0?v:null,!!takenLoad()[t]);
  rebalCheck();
}
function soxlTrGet(){ try{var v=parseInt(localStorage.getItem('v38_soxl_tr')||'0',10); return (v>=0&&v<=3)?v:0;}catch(e){return 0;} }
function soxlTrSet(v){ try{localStorage.setItem('v38_soxl_tr',String(Math.max(0,Math.min(3,v))));}catch(e){} try{calcRun();}catch(e){} }
function calcRun(){
  var C=window.CALC||{}, out=document.getElementById('calcOut'), sum=document.getElementById('calcSum');
  if(!out) return;
  var jpy=parseFloat((document.getElementById('jpyIn')||{}).value)||0;
  var fx=parseFloat((document.getElementById('fxIn')||{}).value)||C.fx||0;
  var ent=ccLoad(ccKey()), sold=takenLoad(), has=jpy>0&&fx>0;
  var usd=has?jpy/fx:0, indPool=usd*(C.alloc_ind/100)*C.e_ind, levPool=usd*(C.alloc_lev/100)*C.e_lev, per=indPool/(C.n||12);
  var soldCt=0, rows='';
  (C.names||[]).forEach(function(n){
    var tk=!!sold[n.t]; if(tk)soldCt++;
    var drop=(n.drop&&!tk), clx=(n.clx&&!tk);
    var wait=(drop&&!clx), okentry=(drop&&clx);
    var base=(has&&!tk)?Math.floor(per/n.px):null;
    var sh=(base!=null&&half)?Math.floor(base*0.5):base, doll=(sh!=null)?sh*n.px:0;
    var shCell;
    if(!has){ shCell='<span class="mut">—</span>'; }
    else if(tk){ shCell='<span class="mut">売却済</span>'; }
    else if(wait){ shCell='<span class="kf-skiptxt">一服待ち</span><div class="mut" style="font-size:10px">急落局面・投げ未確認</div>'; }
    else if(okentry){ shCell='<span class="kf-oktxt">解禁</span><div class="mut" style="font-size:10px">セリクラ確認→満額</div>'; }
    else { shCell='<b>'+sh+'</b>'+(half?'<span class="hf">½</span>':'')+'<div class="mut" style="font-size:10px">$'+doll.toFixed(0)+'</div>'; }
    var tkBtn='<button class="tkbtn'+(tk?' on':'')+'" onclick="toggleTaken(\''+n.t+'\')">'+(tk?'売却済':'売却')+'</button>';
    var rkb='<span class="rkb">#'+n.rk+'</span>';
    var flg='';
    if(wait) flg+='<span class="kflag kf-skip">一服待ち</span>';
    if(okentry) flg+='<span class="kflag kf-ok">解禁</span>';
    var sub='RS'+n.rs+' ・ $'+n.px.toFixed(2)+((n.r5!=null)?' ・ 5日'+(n.r5>=0?'+':'')+n.r5+'%':'');
    rows+='<tr'+(wait?' class="row-skip"':'')+'><td class="l tk">'+rkb+' '+n.t+' '+flg+'<div class="mut" style="font-size:10px">'+sub+'</div></td>'
       +'<td>'+shCell+'</td>'
       +'<td><input class="entIn" type="number" inputmode="decimal" value="'+(ent[n.t]||'')+'" placeholder="建値" data-t="'+n.t+'" oninput="entSave(this)">'+tkBtn+'</td>'
       +'<td class="pl-cell">'+plHtml(n,ent[n.t],tk)+'</td></tr>';
  });
  var tab='<table class="ptab calc-tab"><thead><tr><th class="l">銘柄</th><th>株数</th><th>建値 / 売却</th><th>損益</th></tr></thead><tbody>'+rows+'</tbody></table>';
  var lev='';
  if(has&&levPool>0){
    var sw=(C.soxl_w!=null)?C.soxl_w:0.5, tw=1-sw;                 // SOXL投入帯→0.5 / 帯外→0（全額TQQQ）
    var tq=C.tqqq, sx=C.soxl;
    var tr=soxlTrGet();                                            // 段階投入 0〜3（端末保存）
    if(C.color==='Red'){ try{localStorage.setItem('v38_soxl_tr','0');}catch(e){} tr=0; }  // 赤=全撤退→赤明けは投入帯(50MA)から段階1/3で入り直し
    var tPool=levPool*tw, sFull=levPool*sw, sNow=sFull*(tr/3), sWait=sFull-sNow;
    var th=tq?Math.floor(tPool/tq):null, sxh=(sx&&sNow>0)?Math.floor(sNow/sx):null;
    var hdr=(sw>0)?('TQQQ '+Math.round(tw*100)+'% / SOXL '+Math.round(sw*100)+'%（段階 '+tr+'/3）・寄り執行')
                  :('TQQQ 100%・SOXL見送り（'+((C.soxl_reason)||'投入帯外')+'）');
    lev='<div class="lev-box"><div class="lev-h">レバ枠（'+hdr+'）</div>'
      +'<div class="lev-r"><span>TQQQ</span><b>'+(th!=null?th+' 株':'価格不明')+'</b><span class="mut">$'+tPool.toFixed(0)+(tq?' / @$'+tq.toFixed(2):'')+'</span></div>';
    if(sw>0){
      // 投入帯：段階投入トラッカー
      lev+='<div class="lev-r"><span>SOXL <span class="mut">'+tr+'/3</span></span><b>'+(sxh!=null?sxh+' 株':(tr>0?'価格不明':'0 株'))+'</b><span class="mut">$'+sNow.toFixed(0)+'（満額$'+sFull.toFixed(0)+'）'+(sx?' / @$'+sx.toFixed(2):'')+'</span></div>';
      lev+='<div class="soxl-tr"><span class="mut">段階投入 '+tr+'/3';
      if(tr<3){ lev+='・投入帯なので今日 <b>+1/3（$'+(sFull/3).toFixed(0)+'）</b> 追加可'; }
      else { lev+='・満額（3/3）到達'; }
      lev+='</span><span class="soxl-btns">';
      if(tr<3){ lev+='<button class="nqb b-green" onclick="soxlTrSet('+(tr+1)+')">＋1/3 投入</button>'; }
      lev+='<button class="nqb b-clear" onclick="soxlTrSet(0)">リセット</button></span></div>';
      if(sWait>0.5){ lev+='<div class="lev-r" style="opacity:.7"><span>未投入(待機)</span><b class="mut">現金</b><span class="mut">$'+sWait.toFixed(0)+'／次の投入帯日に +1/3</span></div>'; }
    } else {
      lev+='<div class="lev-r" style="opacity:.75"><span>SOXL</span><b class="neg">見送り</b><span class="mut">'+((C.soxl_reason)||'50MA帯外')+'／新規停止（段階投入は50MA +0〜3%で解禁）</span></div>';
      if(tr>0){ lev+='<div class="soxl-tr"><span class="mut">既存 '+tr+'/3 は継続（帯外では買い増さない・保有はNQ色/建値ルールで管理）</span><span class="soxl-btns"><button class="nqb b-clear" onclick="soxlTrSet(0)">リセット</button></span></div>'; }
    }
    lev+='</div>';
  }
  if(has){
    var freed=per*soldCt;                            // 売却(トレール/ストップ全量退出)で空いた個別枠
    var cash=usd-indPool-levPool;                    // 構造的な現金（ゲート由来）
    var s='<div class="cs-row"><span>USD換算</span><b>$'+usd.toFixed(0)+'</b></div>'
      +'<div class="cs-row"><span>個別枠 40%×'+(C.e_ind*100).toFixed(0)+'%</span><b>$'+indPool.toFixed(0)+'</b></div>'
      +'<div class="cs-row"><span>レバ枠 60%×'+(C.e_lev*100).toFixed(0)+'%</span><b>$'+levPool.toFixed(0)+'</b></div>'
      +'<div class="cs-row cs-cash"><span>残り現金（ゲート由来）</span><b>$'+cash.toFixed(0)+' ・ ¥'+Math.round(cash*fx).toLocaleString()+'</b></div>';
    if(freed>0){
      s+='<div class="cs-row"><span>売却で空いた枠（'+soldCt+'銘柄）</span><b>$'+freed.toFixed(0)+'</b></div>';
    }
    sum.innerHTML=s;
    if(C.color==='Yellow'){
      sum.innerHTML+='<div class="cs-row cs-cash" style="color:#eab308"><span>⚠ NQ黄＝新規停止</span><b>下の株数は既存保有の管理用。新規に買い増さない</b></div>';
    } else if(C.color==='Red'){
      sum.innerHTML+='<div class="cs-row cs-cash" style="color:#f87171"><span>⚠ NQ赤＝撤退</span><b>個別0%・全て現金</b></div>';
    }
    // 月中の売却枠は再投下せず現金で保持し、次の隔週(月曜)トゥルーアップで吸収。
    if(freed>0){
      lev+='<div class="redep mut" style="padding:8px 10px">売却で空いた $'+freed.toFixed(0)+' は<b>現金のまま保持</b>し、次の隔週トゥルーアップ（月曜）で新トップ12へ均等配分。期中の再投下はしない。</div>';
    }
  } else { sum.innerHTML=''; }
  out.innerHTML = lev + tab;
  rebalCheck();
}
function rebalCheck(){
  var box=document.getElementById('rebalBox'); if(!box) return;
  var C=window.CALC||{}, D=window.DET||{};
  var held=Object.keys(ccLoad(ccKey()));
  if(!held.length){ box.innerHTML='<div class="mut" style="font-size:12px">建値を入れた保有銘柄が、ここに点検対象として表示されます。</div>'; return; }
  var floor=C.floor_rs189||0, picks=(C.names||[]).map(function(n){return n.t;});
  var sell=[], hold=0;
  held.forEach(function(t){
    var d=D[t];
    if(!d){ sell.push({t:t,why:'データ無（ユニバース外）'}); return; }
    var okMA=!!d.ma5020, okRs=(d.rs189!=null&&d.rs189>=floor);
    if(okMA&&okRs){ hold++; return; }
    var why=[]; if(!okMA)why.push('50日線<200日線'); if(!okRs)why.push('RS<'+floor.toFixed(0));
    sell.push({t:t,why:why.join('・')});
  });
  var add=picks.filter(function(t){return held.indexOf(t)<0;});
  var _nqcol=(window.CALC&&window.CALC.color)||'';
  var _noEntry=(_nqcol==='Yellow'||_nqcol==='Red');
  var h='<div class="rc-h">継続OK '+hold+' ／ 売り候補 '+sell.length+' ／ 組み入れ候補 '+(_noEntry?'停止中':add.length)+'（継続床 RS≥'+floor.toFixed(0)+'）</div>';
  if(sell.length){
    h+='<div class="rc-sec"><div class="rc-l rc-sl">売り候補（継続条件を外れた保有）</div>'
      + sell.map(function(x){return '<div class="rc-row"><b>'+x.t+'</b><span class="mut">'+x.why+'</span></div>';}).join('')+'</div>';
  }
  if(_noEntry){
    h+='<div class="rc-sec"><div class="rc-l rc-ad">組み入れ（新規）</div>'
      + '<div class="rc-row"><span class="mut">NQ'+(_nqcol==='Yellow'?'黄':'赤')+'＝新規エントリー停止中。空き枠は現金で保持し、保有はトレール'+(_nqcol==='Yellow'?'15%':'')+'で継続。青/緑に戻ってから組み入れる。</span></div></div>';
  } else if(add.length){
    h+='<div class="rc-sec"><div class="rc-l rc-ad">組み入れ候補（新トップ'+picks.length+'で未保有）</div>'
      + add.map(function(t){var d=D[t]||{};return '<div class="rc-row"><b>'+t+'</b><span class="mut">RS'+(d.rs189!=null?d.rs189:'—')+' / $'+(d.px!=null?d.px:'—')+'</span></div>';}).join('')+'</div>';
  }
  if(!sell.length&&!add.length&&!_noEntry){ h+='<div class="rc-okall">保有はすべて継続条件を満たし、新トップ'+picks.length+'と一致。入替なし。</div>'; }
  box.innerHTML=h;
}
function memExport(){var s=JSON.stringify({entries:ccLoad(ccKey()),taken:takenLoad(),peak:ccLoad(ccPeakKey())}); try{window.prompt('保存用JSON（コピーして保管）',s);}catch(e){}}
function memImport(){var s=null; try{s=window.prompt('JSONを貼り付け');}catch(e){} if(s){try{var o=JSON.parse(s); if(o.entries)ccSet(ccKey(),o.entries); if(o.taken)ccSet(ccTakenKey(),o.taken); if(o.peak)ccSet(ccPeakKey(),o.peak); calcRun();}catch(e){alert('JSONが不正です');}}}
if(document.readyState!=='loading'){ try{calcRun();}catch(e){} }
else { document.addEventListener('DOMContentLoaded',function(){ try{calcRun();}catch(e){} }); }


"""

def _cp(tickers):
    """Copy button for a list of tickers (comma-separated to clipboard)."""
    if not tickers:
        return ""
    data = ",".join(tickers)
    return (f'<button class="cp" data-tk="{data}" onclick="copyTk(this)">'
            f'コピー <span class="n">{len(tickers)}</span></button>')

def _build_det_extra(m, s2t, s2i, e2j, picks, deck, buys, nh_list, where):
    """タップ詳細用の集約：セクター/サブテーマ/時価総額/登場箇所（保有・控え・ピックアップ・新高値・ウォッチ）。"""
    loc = {}
    def add(t, lab):
        if t:
            loc.setdefault(t, []).append(lab)
    for i, (t, _, _) in enumerate(picks, 1):
        add(t, f"保有 #{i}")
    try:
        for rk, t in enumerate(list(deck.index), N_PORT + 1):
            add(t, f"控え #{rk}")
    except Exception:
        pass
    for b in buys:
        add(b.get("t"), "ピックアップ")
    for t in nh_list:
        add(t, "新高値圏")
    for t, nm in (where or {}).items():
        add(t, "ウォッチ:" + "・".join(nm))
    caps = m["tier_lab"].to_dict() if "tier_lab" in m.columns else {}
    extra = {}
    for t in m.index:
        extra[t] = {"sec": theme_of(t, s2t),
                    "sth": subtheme_of(t, s2t, e2j.get(s2i.get(t), "—")),
                    "cap": caps.get(t),
                    "loc": loc.get(t, [])}
    return extra

def _det_json(m, names, tapset, extra=None):
    """§4: compact per-ticker data for the tap-to-detail panel (displayed tickers only)."""
    import json as _json
    extra = extra or {}
    def _r(x, n=2):
        try:
            if x is None or (isinstance(x, float) and np.isnan(x)):
                return None
            return round(float(x), n)
        except Exception:
            return None
    def _p(r, k, n=1):  # percent field
        v = r.get(k)
        return _r(v * 100, n) if v is not None and pd.notna(v) else None
    out = {}
    for t in tapset:
        if t not in m.index:
            continue
        r = m.loc[t]
        is_l, code, lab, reason = leader_state(r)
        nu_tag, nu_note, nu_cls = momentum_nuance(r)
        ex = extra.get(t, {})
        out[t] = {"rs": _r(r.get("rs"), 0), "rs189": _r(r.get("rs189"), 0),
                  "px": _r(r.get("close"), 2), "ch": _p(r, "pchg", 2),
                  "v50": _p(r, "vs50"), "v200": _p(r, "vs200"), "d21": _p(r, "dma21"),
                  "adr": _p(r, "adr"), "rv": _r(r.get("rvol"), 1), "pb": _p(r, "pb"),
                  "p52": _r(r.get("pos52"), 0), "d52": _p(r, "dist52"),
                  "dvol": _r((r.get("dvol") or 0) / 1e6, 1),
                  "sec": ex.get("sec"), "sth": ex.get("sth"),
                  "cap": ex.get("cap"), "loc": ex.get("loc") or [],
                  "ld": 1 if is_l else 0, "stc": code, "stl": lab, "rsn": reason,
                  "beta": _r(r.get("beta"), 2),
                  "ma5020": 1 if (r.get("sma50") is not None and r.get("sma200") is not None
                                  and r["sma50"] == r["sma50"] and r["sma200"] == r["sma200"]
                                  and r["sma50"] > r["sma200"]) else 0,
                  "sarb": 1 if r.get("sar_bull") else 0,
                  "wst": (int(r["wst"]) if pd.notna(r.get("wst")) else None),
                  "wstw": (int(r["wstw"]) if pd.notna(r.get("wstw")) else None),
                  "wsb": (int(r["wsb"]) if pd.notna(r.get("wsb")) else None),
                  "wsbf": (int(r["wsbf"]) if pd.notna(r.get("wsbf")) else 0),
                  "nut": nu_tag, "nucls": nu_cls}
    return _json.dumps(out, ensure_ascii=False, separators=(",", ":"))

def color_pct(x):
    if x is None or (isinstance(x,float) and np.isnan(x)): return "mut"
    return "pos" if x > 0 else ("neg" if x < 0 else "mut")

def _svg_inner(ys, accent, gid, gridvals, suffix, lo_pad=4, hi_pad=4, ymin=0, ymax=100, zero_ref=False):
    """Return inner SVG (area+line) for a value series. zero_ref=Trueで y=0 に破線基準。"""
    n = len(ys)
    Wd, Ht, pad = 680, 180, 6
    lo, hi = min(ys), max(ys)
    lo = max(ymin, lo - lo_pad); hi = min(ymax, hi + hi_pad)
    rng = (hi - lo) or 1
    def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo)/rng) * (Ht - 2*pad)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    area = (f"M{X(0):.1f},{Y(ys[0]):.1f} "
            + " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
            + f" L{X(n-1):.1f},{Ht-pad:.1f} L{X(0):.1f},{Ht-pad:.1f} Z")
    gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" '
                 f'stroke="#1c2533" stroke-width="1"/>'
                 f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" '
                 f'text-anchor="end">{g}{suffix}</text>'
                 for g in gridvals if lo <= g <= hi)
    zr = ""
    if zero_ref and lo <= 0 <= hi:
        zr = (f'<line x1="{pad}" y1="{Y(0):.1f}" x2="{Wd-pad}" y2="{Y(0):.1f}" '
              f'stroke="#3b4b63" stroke-width="1" stroke-dasharray="4 3"/>')
    return (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{accent}" stop-opacity="0.35"/>'
            f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/></linearGradient></defs>'
            f'{gl}{zr}<path d="{area}" fill="url(#{gid})"/>'
            f'<polyline points="{pts}" fill="none" stroke="{accent}" stroke-width="2"/>'
            f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="{accent}"/></svg>')

def _date_axis(ts):
    """チャート下端に半年ごとの日付ラベル（yy/m）を等間隔で並べる。"""
    if not ts or len(ts) < 2:
        return ""
    seen, labs = set(), []
    for d, _ in ts:
        dt = pd.Timestamp(d)
        h = 1 if dt.month <= 6 else 7
        key = (dt.year, h)
        if key not in seen:
            seen.add(key)
            labs.append(f'<span>{dt.year % 100}/{h}</span>')
    if len(labs) < 2:
        labs = [f'<span>{pd.Timestamp(ts[0][0]).strftime("%y/%-m")}</span>',
                f'<span>{pd.Timestamp(ts[-1][0]).strftime("%y/%-m")}</span>']
    return '<div class="dax">' + "".join(labs) + '</div>'

def _span_label(ts):
    """推移データの実期間を'○年○ヶ月'で返す（表記と実データのズレ防止）。"""
    if not ts or len(ts) < 2:
        return "—"
    try:
        d0 = pd.Timestamp(ts[0][0]); d1 = pd.Timestamp(ts[-1][0])
        months = round((d1 - d0).days / 30.44)
        yy = months // 12; mm = months % 12
        if yy and mm: return f"{yy}年{mm}ヶ月"
        if yy: return f"{yy}年"
        return f"{mm}ヶ月"
    except Exception:
        return "—"

def _svg_breadth(ts, n_uni=None):
    """Breadth time series (S5TH analog)."""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    svg = _svg_inner(ys, "#58a6ff", "bg", [20,40,50,60,80], "%")
    uni_txt = f"約{round(n_uni,-1):,.0f}銘柄" if n_uni else "ユニバース"
    return (f'<div class="card"><h2>ブレッドス推移（200日線上の割合）</h2>'
            f'<div class="sub">200日線を上回る銘柄の割合（{uni_txt}・{_span_label(ts)}）</div>'
            f'<div class="chart">{svg}'
            f'<div class="cap cap-c"><span style="color:#9ecbff;font-weight:700">現在 {last:.0f}%</span></div>'
            f'{_date_axis(ts)}</div></div>')

def _fmt_usd_big(v):
    v = float(v)
    if v >= 1e12: return f"${v/1e12:.2f}T"
    if v >= 1e9:  return f"${v/1e9:.0f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"

def _dollarvol_card(dv):
    """売買代金 参加度: ユニバース合算/QQQ/SPY を各自の200日平均比（1.0=平常）で重ねた足元感応チャート。"""
    if not dv or not dv.get("series"):
        return ""
    dates = dv["dates"]; n = len(dates)
    if n < 5:
        return ""
    allv = [y for s in dv["series"] for y in s["ys"] if y is not None]
    if len(allv) < 5:
        return ""
    lo, hi = min(allv), max(allv); lo = min(lo, 0.9); hi = max(hi, 1.1); rng = (hi - lo) or 1
    lo2, hi2 = lo - rng * 0.08, hi + rng * 0.08; rng2 = (hi2 - lo2) or 1
    Wd, Ht, pad = 680, 180, 6
    def X(i): return pad + i * (Wd - 2 * pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo2) / rng2) * (Ht - 2 * pad)
    gl = ""
    for g in (0.8, 1.0, 1.2, 1.4):
        if not (lo2 <= g <= hi2):
            continue
        is1 = abs(g - 1.0) < 1e-9
        stroke = "#33415a" if is1 else "#1c2533"
        dash = ' stroke-dasharray="3 3"' if is1 else ""
        gl += (f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" '
               f'stroke="{stroke}" stroke-width="1"{dash}/>'
               f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" '
               f'font-weight="600" text-anchor="end">{g:.1f}</text>')
    lines = ""
    for s in dv["series"]:
        ys = s["ys"]
        seg = [(i, v) for i, v in enumerate(ys) if v is not None]
        if len(seg) < 2:
            continue
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in seg)
        wdt = 2.4 if s["name"] == "ユニバース合算" else 1.6
        lines += f'<polyline points="{pts}" fill="none" stroke="{s["color"]}" stroke-width="{wdt}"/>'
        li, lv = seg[-1]
        lines += f'<circle cx="{X(li):.1f}" cy="{Y(lv):.1f}" r="3" fill="{s["color"]}"/>'
    svg = f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">{gl}{lines}</svg>'
    legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
        f'<span style="width:10px;height:3px;background:{s["color"]};display:inline-block;border-radius:2px"></span>'
        f'<span style="color:#c7d2fe;font-size:11px">{s["name"]}</span></span>' for s in dv["series"])
    uni = next((s for s in dv["series"] if s["name"] == "ユニバース合算"), dv["series"][0])
    ut = dv.get("uni_trend") or {}
    tcol = "#7ff0a8" if ut.get("dir") == "拡大" else "#fca5a5" if ut.get("dir") == "縮小" else "#9fb0c5"
    tclause = (f'・<b style="color:{tcol}">{ut["dir"]}</b>（3ヶ月{ut["pct"]:+.0f}%）' if ut else "")
    ur = uni.get("last_ratio")
    urtxt = f'参加度 {ur:.2f}倍' if (ur is not None and ur == ur) else "—"
    return (f'<div class="card"><h2>売買代金 参加度（200日平均比）</h2>'
            f'<div class="sub">1日あたり売買代金（終値×出来高・21日平滑）を<b>各自の200日平均で割った比</b>・{dv["span"]}。'
            f'<b>1.0=平常</b>／1.0超=平常より資金が厚い／1.0割れ=細り。累積でなく比なので<b>足元の強弱</b>が読める。'
            f'<span style="margin-left:6px">{legend}</span></div>'
            f'<div class="chart">{svg}'
            f'<div class="cap cap-c"><span style="color:#7dd3fc;font-weight:700">'
            f'ユニバース {urtxt}・現在 {_fmt_usd_big(uni["last_abs"])}（20日前比 {uni["chg20"]:+.0f}%）{tclause}</span></div>'
            f'{_date_axis([(d, 0.0) for d in dates])}</div></div>')

def _trend_state(ys, up_label, dn_label, win=50, slope_lb=10):
    """系列自身のトレンドでラベル：50日平均より上か下か＋平均の向き。
       リベース/累積系列のように『自然な原点』が無い系列は基準日を借りず必ずこれで判定。"""
    s = pd.Series(ys)
    if len(s) < win + slope_lb:
        return ("中立", "#9aa4b2")
    ma = s.rolling(win).mean()
    above = s.iloc[-1] > ma.iloc[-1]
    slope = ma.iloc[-1] - ma.iloc[-1 - slope_lb]
    if above and slope >= 0:
        return (up_label, "#7ff0a8")
    if (not above) and slope < 0:
        return (dn_label, "#fca5a5")
    return ("中立", "#9aa4b2")

def _svg_ratio_card(ts, title, sub, up_label, dn_label, accent, gid, show_value=True,
                    zero_ref=False, unit=""):
    """推移カード。zero_ref=Trueで0基準線＋σ表示（z-score系列用）。ラベルは系列自身のトレンドで判定。"""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    lo, hi = min(ys), max(ys)
    pad = max(0.4, (hi - lo) * 0.12)
    grid = sorted(set(round(x, 1) for x in ([lo, 0.0, hi] if zero_ref else [lo, (lo + hi) / 2, hi])))
    svg = _svg_inner(ys, accent, gid, grid, "", lo_pad=pad, hi_pad=pad, ymin=-1e9, ymax=1e9,
                     zero_ref=zero_ref)
    state, col = _trend_state(ys, up_label, dn_label)
    _v = (f'{last:+.1f}{unit}' if zero_ref else f'{last:.1f}')
    cap = (f'現在 {_v}（{state}）' if show_value else f'現在 {state}')
    return (f'<div class="card"><h2>{title}</h2>'
            f'<div class="sub">{sub}</div>'
            f'<div class="chart">{svg}'
            f'<div class="cap cap-c"><span style="color:{col};font-weight:700">{cap}</span></div>'
            f'{_date_axis(ts)}</div></div>')

def _svg_vixterm_card(ts):
    """B-4a: VIX期間構造(1M÷3M)の推移・生比率。1.0=バックワーデーション線（構造的原点ありで水準ラベル可）。"""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    dlo, dhi = min(ys), max(ys)
    # 1.0基準線が常に見えるよう上端を≥1.02に（_svg_innerのpadで調整）
    svg = _svg_inner(ys, "#c4b5fd", "vt", [0.90, 0.95, 1.00, 1.05], "",
                     lo_pad=0.03, hi_pad=max(0.03, 1.02 - dhi), ymin=0, ymax=100)
    if last < 0.95:
        state, col = "コンタンゴ（平穏）", "#7ff0a8"
    elif last <= 1.00:
        state, col = "フラット（要観察）", "#fcd34d"
    else:
        state, col = "バックワーデーション（ストレス）", "#fca5a5"
    return (f'<div class="card"><h2>VIX期間構造（1M÷3M）</h2>'
            f'<div class="sub">VIX 1カ月物 ÷ 3カ月物（1.0超でカーブ逆転）</div>'
            f'<div class="chart">{svg}'
            f'<div class="cap cap-c"><span style="color:{col};font-weight:700">現在 {last:.2f}（{state}）</span></div>'
            f'{_date_axis(ts)}</div></div>')

def _mkt_section(label, q):
    """マーケットタブのストーリー章ヘッダ（章タイトル＋この章が答える問い）。"""
    return (f'<div class="msec"><div class="msec-l">{label}</div>'
            f'<div class="msec-q">{q}</div></div>')

def _svg_mri(ts):
    """Market-status time series, ~6 months, with regime-zone shading (帯域塗り)."""
    if not ts or len(ts) < 5:
        return ""
    ys = [v for _, v in ts]; last = ys[-1]
    hl = sum(ys[-3:]) / 3 if len(ys) >= 3 else last
    band_lab = mri_band(hl)[0].replace("（過熱・反落注意⚠）", "")
    # zone-shaded custom svg (same geometry as _svg_inner)
    n = len(ys); Wd, Ht, pad = 680, 180, 6
    lo, hi = min(ys), max(ys)
    lo = max(0, lo - 4); hi = min(100, hi + 4)
    rng = (hi - lo) or 1
    def X(i): return pad + i * (Wd - 2*pad) / (n - 1)
    def Y(v): return pad + (1 - (v - lo)/rng) * (Ht - 2*pad)
    zones = [(0, 30, "#ef4444"), (30, 45, "#f97316"), (45, 60, "#64748b"),
             (60, 75, "#22c55e"), (75, 100, "#a855f7")]
    zr = ""
    for z0, z1, zc in zones:
        a, b = max(z0, lo), min(z1, hi)
        if b <= a:
            continue
        zr += (f'<rect x="{pad}" y="{Y(b):.1f}" width="{Wd-2*pad}" '
               f'height="{max(0.0, Y(a)-Y(b)):.1f}" fill="{zc}" opacity="0.07"/>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    gl = "".join(f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{Wd-pad}" y2="{Y(g):.1f}" stroke="#1c2533" stroke-width="1"/>' 
                 f'<text x="{Wd-pad}" y="{Y(g)-2:.1f}" fill="#8b9bb0" font-size="20" font-weight="600" text-anchor="end">{g}</text>'
                 for g in (30, 45, 60, 75) if lo <= g <= hi)
    svg = (f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none">'
           f'<defs><linearGradient id="mg" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="#34d399" stop-opacity="0.30"/>'
           f'<stop offset="1" stop-color="#34d399" stop-opacity="0"/></linearGradient></defs>'
           f'{zr}{gl}'
           f'<polyline points="{pts}" fill="none" stroke="#34d399" stroke-width="2"/>'
           f'<circle cx="{X(n-1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="#34d399"/></svg>')
    return (f'<div class="card"><h2>マーケットステータス推移</h2>'
            f'<div class="sub">地合いスコアの推移・{_span_label(ts)}（75強気/60中立/45弱含み/30弱気）</div>'
            f'<div class="chart">{svg}'
            f'<div class="cap cap-c"><span style="color:#7ff0a8;font-weight:700">現在 {last:.0f}（{band_lab}）</span></div>'
            f'{_date_axis(ts)}</div></div>')

def _sec_rows(recs, tf, topbottom=False):
    rs = [x for x in recs if x.get(tf) is not None and not (isinstance(x[tf], float) and np.isnan(x[tf]))]
    rs.sort(key=lambda x: x[tf], reverse=True)
    def row(i, s):
        cells = ""
        for k in ("d1", "w1", "m1"):
            hl = " hl" if k == tf else ""
            cells += f'<td class="{color_pct(s[k])}{hl}">{fmt_pct(s[k])}</td>'
        return (f'<tr><td class="l mut">{i}</td>'
                f'<td class="l tk" style="font-size:12px">{s["ja"]}'
                f'<span class="mut" style="font-size:10px"> {s["tk"]}</span></td>{cells}</tr>')
    if topbottom and len(rs) > 10:
        top, bot = rs[:5], rs[-5:]
        h = lambda lab: f'<tr class="secsub"><td colspan="5" class="l">{lab}</td></tr>'
        return (h("強い") + "".join(row(i + 1, s) for i, s in enumerate(top))
                + h("弱い") + "".join(row(len(rs) - 4 + i, s) for i, s in enumerate(bot)))
    return "".join(row(i + 1, s) for i, s in enumerate(rs))

def _sector_rank_card(ranks):
    if not ranks or not (ranks.get("macro") or ranks.get("micro")):
        return ""
    tbls = ""
    for grp in ("macro", "micro"):
        recs = ranks.get(grp, [])
        tb = (grp == "micro")
        for tf in ("d1", "w1", "m1"):
            disp = "" if (grp == "macro" and tf == "d1") else "display:none"
            head = ('<table><tr><th class="l">#</th><th class="l">セクター</th>'
                    '<th>日</th><th>週</th><th>月</th></tr>')
            tbls += (f'<div class="sectbl" id="sec-{grp}-{tf}" style="{disp}">'
                     f'{head}{_sec_rows(recs, tf, tb)}</table></div>')
    return (f'<div class="card"><h2>セクターETF強弱</h2>'
            f'<div class="sub">S&amp;P500の11セクターETFと業種テーマETFの騰落率（下のサブテーマ別RSは個別株のRS中央値・別物）</div>'
            f'<div class="sectog">'
            f'<button class="stg-g active" onclick="secG(\'macro\',this)">大分類</button>'
            f'<button class="stg-g" onclick="secG(\'micro\',this)">小分類</button>'
            f'<span class="stg-sep">|</span>'
            f'<button class="stg-t active" onclick="secT(\'d1\',this)">日</button>'
            f'<button class="stg-t" onclick="secT(\'w1\',this)">週</button>'
            f'<button class="stg-t" onclick="secT(\'m1\',this)">月</button>'
            f'</div>{tbls}</div>'
            f'<script>var _sg="macro",_st="d1";'
            f'function _secShow(){{document.querySelectorAll(".sectbl").forEach(function(e){{e.style.display="none"}});'
            f'var el=document.getElementById("sec-"+_sg+"-"+_st);if(el)el.style.display="";}}'
            f'function secG(g,b){{_sg=g;document.querySelectorAll(".stg-g").forEach(function(e){{e.classList.remove("active")}});b.classList.add("active");_secShow();}}'
            f'function secT(t,b){{_st=t;document.querySelectorAll(".stg-t").forEach(function(e){{e.classList.remove("active")}});b.classList.add("active");_secShow();}}</script>')

def _liq_bar():
    """Slim sticky liquidity (avg daily $ volume) filter toolbar — works in any tab via liqFilter()."""
    return (
        '<div class="card liqstick"><div class="liqrow">'
        '<span class="liqlab">流動性<span class="liqsub">日次$出来高</span></span>'
        '<button class="lqf-b" onclick="liqFilter(-1,this)">全て</button>'
        '<button class="lqf-b lqf-rec active" onclick="liqFilter(10,this)">≥$10M<span class="lqf-tag">推奨</span></button>'
        '<button class="lqf-b" onclick="liqFilter(20,this)">≥$20M</button>'
        '<button class="lqf-b" onclick="liqFilter(50,this)">≥$50M</button>'
        '</div></div>')

def gate_coeffs(color):
    """NQ4色 → (E_ind, E_lev)。個別 青100/緑100/黄=保有100%継続だが新規停止(トレール15%)/赤0、レバ 青100/緑50/黄0/赤0。
       不明/無判定は安全側で(0,0)＝赤扱い。"""
    return {"Blue": (1.0, 1.0), "Green": (1.0, 0.5),
            "Yellow": (1.0, 0.0), "Red": (0.0, 0.0)}.get(color, (0.0, 0.0))

def _sleeve_mult(p, n):
    """前回露出p→今回露出n の月中アクションを倍率で表現。建値は価格でlocalStorage保持なので
       株数を増減してもストップ/トレール表示は崩れない。0から増やす時だけ絶対株数が必要。"""
    if n <= 0:
        return "全部売り" if p > 0 else "なし"
    if p <= 0:
        return "配分タブの株数で新規"
    r = n / p
    if abs(r - 1) < 1e-6:
        return "変更なし"
    if abs(r - 0.5) < 1e-6:
        return "半分売り（×0.5）"
    if abs(r - 2) < 1e-6:
        return "倍に買い増し（×2）"
    return f"×{r:.2g}"

def build_today_action(sar, mkt, asof):
    """最上部の『今日の運用』。色→露出→今日の引き金（赤明け>色変化>通常）＋隔週月曜リバランス旗。"""
    color, src = sar
    prev = mkt.get("trend_prev")
    e_ind, e_lev = gate_coeffs(color)
    cj = _COLOR_JP.get(color, "—")
    ccls = (color or "gray").lower()

    # 露出文言
    if color is None:
        expo = "NQ未取得 → 安全側で露出0%。TradingViewで確認を"
    elif color == "Red":
        expo = "個別 0% ／ レバ 0% ・ 全現金"
    elif color == "Yellow":
        expo = "個別 保有継続（トレール15%に締める）・新規エントリーは停止 ／ レバ 0% ・ 空き枠は現金"
    else:
        cash = "残りは現金（ゲート由来）" if (e_ind < 1 or e_lev < 1) else "フル投資"
        expo = f"個別 {e_ind*100:.0f}% ／ レバ {e_lev*100:.0f}% ・ {cash}"

    # リバランス日判定はクライアント側（隔週・月曜／localStorage・_rebalCheck2）に移管

    # 引き金（優先順）
    if color and prev == "Red" and color != "Red":
        acls = "alert"
        act = f"⚠ 赤明け！翌寄りで最新トップ{N_PORT}を新規選定して即入り（次回リバランスを待たない）"
    elif color and prev and prev != color:
        up = _COLOR_RANK.get(color, -1) > _COLOR_RANK.get(prev, -1)
        tag = "攻め強化" if up else "守りへ"
        acls = "change-up" if up else "change-dn"
        ei_p, el_p = gate_coeffs(prev)
        ei_n, el_n = gate_coeffs(color)
        act = (f"NQ {_COLOR_JP.get(prev, prev)}→{cj}（{tag}）→ 翌寄りで "
               f"個別：{_sleeve_mult(ei_p, ei_n)}／レバ：{_sleeve_mult(el_p, el_n)}")
    elif color is None:
        acls = "alert"
        act = "NQ色が未取得。TradingViewでOniMineの色を確認してから動く"
    else:
        acls = "normal"
        act = "色変化なし → 新規アクションなし（保有維持。トレール・ストップのみ対応）"

    est = ('<span class="ta-est">推定・要TradingView確認</span>'
           if (src == "estimate" and color in ("Yellow", "Red")) else "")

    open_more = acls in ("alert", "change-up", "change-dn")
    more_sty = "" if open_more else ' style="display:none"'
    tog = "▴" if open_more else "▾"
    return (f'<div class="todayact ta-{ccls}" id="taCard" data-srv="{color or ""}">'
            f'<div class="ta-top"><span class="ta-h">今日の運用</span>'
            f'<span class="ta-col" id="taCol">NQ {cj}</span>'
            f'<span class="ta-expo" id="taExpo">{expo}</span>'
            f'<span id="taEst">{est}</span><span id="taManual"></span>'
            f'<span class="ta-tog" id="taTog" onclick="taToggle()">{tog}</span></div>'
            f'<div class="ta-more" id="taMore"{more_sty}>'
            f'<div class="ta-act ta-{acls}" id="taAct">{act}</div>'
            f'<div class="ta-rebal" id="taRebal" style="display:none"></div>'
            f'<div class="ta-rec"><span class="ta-reclab">記録</span>'
            f'<button class="nqb b-blue" onclick="setNQ(\'Blue\')">青</button>'
            f'<button class="nqb b-green" onclick="setNQ(\'Green\')">緑</button>'
            f'<button class="nqb b-yellow" onclick="setNQ(\'Yellow\')">黄</button>'
            f'<button class="nqb b-red" onclick="setNQ(\'Red\')">赤</button>'
            f'<button class="nqb b-clear" onclick="clearNQ()">推定に戻す</button>'
            f'<span class="ta-go" onclick="goTab(\'t-alloc\')">配分タブで点検 ›</span>'
            f'<span class="ta-recst" id="nqRecSt"></span></div></div></div>')


def build_calc_extras(picks, color, cand=None):
    """円→株数計算機＋配分表示に渡すデータ。FX(JPY=X)とレバ価格(TQQQ/SOXL)はライブ取得・失敗時None。
    各銘柄にRSランク順位＋急落局面フラグ（投げ確認で解禁／未確認は一服待ち）を付与。

    ── 急落局面エントリー規則の検証台帳（研究側confirmed・公開タブには出さない）──
      最終仕様: 急落局面(20日安値割れ or 5日−15%)は、直近5日にセリングクライマックス
                (RVOL≥2.5 & 日足−5%超=売り手枯渇)があれば満額解禁、無ければ一服待ち=見送り
                (枠は現金・繰上げなし・次回再判定)。投げ確認は8勝1敗・閾値2.0-3.0頑健。
      棄却: 構造ピボット底値割れ→sl20より悪い(割れたまま組の先行10日+3.00% vs 非割れ+1.89%)。
            「割れは避けてよい／割れたままは避けるな」。位置・速度・構造25構成の最終形。
            ½サイズ単独は投げ確認(満額)に吸収(半分版58.1<満額59.4)。
    """
    e_ind, e_lev = gate_coeffs(color)
    names = []
    for i, (t, _, r) in enumerate(picks, 1):
        r5 = r.get("ret5")
        r5 = float(r5) if (r5 is not None and r5 == r5) else None
        names.append({"t": t,
                      "rk": i,                                    # RS189ランク（1=最強）
                      "rs": int(round(float(r.get("rs189", 0) or 0))),
                      "px": round(float(r.get("close", 0) or 0), 2),
                      "r5": round(r5 * 100, 1) if r5 is not None else None,
                      "drop": 1 if (bool(r.get("lo20_break")) or (r5 is not None and r5 <= -0.15)) else 0,  # 急落局面
                      "clx": 1 if bool(r.get("capit5")) else 0})  # セリングクライマックス(投げ)確認済み→解禁
    floor_rs189 = 0.0
    try:
        if cand is not None and len(cand) >= 2 * N_PORT:
            floor_rs189 = float(cand.iloc[2 * N_PORT - 1]["rs189"])
    except Exception:
        floor_rs189 = 0.0
    fx = tqqq = soxl = None
    try:
        import yfinance as yf
        d = yf.download(["JPY=X", "TQQQ", "SOXL"], period="5d",
                        progress=False, auto_adjust=True)
        cl = d["Close"] if "Close" in getattr(d, "columns", []) else d
        def last(k):
            try:
                return round(float(cl[k].dropna().iloc[-1]), 2)
            except Exception:
                return None
        fx, tqqq, soxl = last("JPY=X"), last("TQQQ"), last("SOXL")
    except Exception as e:
        sys.stderr.write("[calc_extras] %s\n" % e)
    return {"color": color or None, "e_ind": e_ind, "e_lev": e_lev, "n": N_PORT,
            "alloc_ind": ALLOC[0], "alloc_lev": ALLOC[1],
            "fx": fx, "tqqq": tqqq, "soxl": soxl, "names": names,
            "floor_rs189": round(floor_rs189, 1)}

def _alloc_tab(calc, eq=None):
    """配分・株数計算タブ（静的スケルトン。明細はJSがwindow.CALCから生成）。"""
    c = calc or {}
    color = c.get("color")
    cj = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}.get(color, "—")
    ccls = (color or "gray").lower()
    e_ind = c.get("e_ind", 0.0); e_lev = c.get("e_lev", 0.0)
    fx = c.get("fx")
    fx_disp = ("%.2f" % fx) if fx else ""
    fx_note = "" if fx else "自動取得できず・手入力を"
    nq_warn = "" if color else '<div class="mut" style="font-size:11px;margin-top:4px">⚠ NQ色が未取得。安全側で露出0%。TradingViewで確認を</div>'
    # 末尾行アンカー: 既知の記録数(=eq['n'])＋ヘッダ1行 → 編集画面をその行に飛ばす（末尾＝入力位置）
    _eq_n = int((eq or {}).get("n") or 0)
    _last_line = _eq_n + 1 if _eq_n else 0                         # header + records
    _edit_href = "https://github.com/thanzo12wizu-stack/v38-watchlist/edit/main/equity.csv"
    if _last_line:
        _edit_href += f"#L{_last_line}"
    return (
        _mkt_section("① 記録", "今日の総資産を残す（週1でOK）")
        + '<div class="card">'
        '<div class="hdr"><h2>エクイティ記録</h2></div>'
        '<div class="sub">今日の総資産（＋任意で米株比率%）を入れて<b>コピー</b> → GitHubの equity.csv <b>末尾（一番下の空行）</b>に貼り付け（週1でOK）。<b>コピーは既存ファイルの区切り（カンマ/スペース）に自動で合わせる</b>ので体裁が揃う。リンクは<b>最終行に飛ぶ</b>ので下までスクロール不要。カーブと露出バンドはマーケットタブ⑥に表示。</div>'
        '<div class="calc-in">'
        '<div class="ci-row"><span class="ci-pre">¥</span>'
        '<input id="eqIn" type="number" inputmode="numeric" placeholder="今日の総資産（例 6742525）"></div>'
        '<div class="ci-row" style="margin-top:6px"><span class="ci-pre" style="font-size:12px">米株%</span>'
        '<input id="eqUsIn" type="number" inputmode="decimal" placeholder="任意（例 76.5）・空欄OK"></div>'
        '<div class="ci-row2" style="margin-top:6px">'
        '<button class="memx" id="eqCopyBtn" onclick="copyEquityRow()">📋 <span id="eqDate">今日</span> の1行をコピー</button>'
        f'<a class="memx" style="text-decoration:none" href="{_edit_href}" target="_blank" rel="noopener">✏️ 末尾を開いて追記</a>'
        '</div>'
        '<div class="mut" style="font-size:11px;margin-top:4px">流れ: 📋コピー → ✏️（最終行付近で開く）→ 一番下に貼り付け → Commit（3タップ）。日付は自動で付く。※GitHubの編集画面はアンカーが効かない場合あり——その時は末尾へ一度スクロール。</div>'
        '</div></div>'
        + _mkt_section("② 配分計算", "NQ色 → 今日の株数に落とす")
        + '<div class="card">'
        '<div class="hdr"><h2>資金配分・株数計算</h2></div>'
        '<div class="sub">円の総資産から、現在のNQ色に応じた各銘柄の買付株数を出す。'
        '<b>隔週リバランス時点の計画値</b>（金曜クローズ判定→月曜寄りで執行）（実約定はギャップ・手数料でズレる）。<b>#</b>=RSランク・<b class="kf-skip" style="padding:0 4px">一服待ち</b>=急落局面で投げ未確認・<b class="kf-ok" style="padding:0 4px">解禁</b>=セリングクライマックス確認済み（満額）。<b>レバ枠のTQQQ/SOXL比はSOXL投入帯（SOXX 50MA +0〜3%）に自動連動</b>——帯外は全額TQQQ。</div>'
        # 現在の色＋係数
        '<div class="gatebox">'
        f'<div class="gate-c sar-{ccls}" id="calcGateC">NQ {cj}</div>'
        '<div class="gate-meta">'
        f'<span id="calcExpo">個別 露出 <b>{e_ind*100:.0f}%</b> ／ レバ 露出 <b>{e_lev*100:.0f}%</b></span>'
        '<div class="mut" style="font-size:11px">青100·100／緑100·50／黄100·0／赤0·0（個別·レバ・黄は個別ト15%）</div>'
        f'{nq_warn}</div></div>'
        # 入力
        '<div class="calc-in">'
        '<div class="ci-row"><span class="ci-pre">¥</span>'
        '<input id="jpyIn" type="number" inputmode="numeric" placeholder="円の総資産（例 10000000）" oninput="calcRun()"></div>'
        '<div class="ci-row2"><span class="ci-fxl">USD/JPY</span>'
        f'<input id="fxIn" type="number" inputmode="decimal" value="{fx_disp}" placeholder="150" oninput="calcRun()">'
        f'<span class="mut ci-fxn" style="font-size:11px">{fx_note}</span></div>'
        '</div>'
        # サマリ＋明細（JSが描画）
        '<div id="calcSum" class="calc-sum"></div>'
        '<div id="calcOut"><div class="calc-empty">金額を入れると株数を計算します</div></div>'
        '<div class="calc-mem">'
        '<button class="memx" onclick="memExport()">建値を書き出し</button>'
        '<button class="memx" onclick="memImport()">読み込み</button>'
        '<span class="mut" style="font-size:11px">建値はこの端末（ブラウザ）に保存。機種変・データ消去前に書き出しを</span>'
        '</div></div>'
        # 隔週リバランス点検（月曜）（P3）
        + _mkt_section("③ リバランス点検", "隔週月曜のチェックリスト")
        + '<div class="card"><div class="hdr"><h2>隔週リバランス点検（月曜）</h2></div>'
        '<div class="sub">建値を入れた保有を継続条件（<b>50日線&gt;200日線・189日RS上位24</b>）と突合。'
        '外れた銘柄＝売り候補、新トップ12で未保有＝組み入れ候補。該当の月曜に確認する。</div>'
        '<div id="rebalBox"></div></div>'
        # 補足
        '<div class="card"><div class="sub">'
        'この計算機は各銘柄を<b>個別枠÷12</b>で均等配分（端数は切り捨て）。建値を入れると保有ごとに'
        '<b>現在損益・出口線（10日安値×0.998 と 21EMA×0.99 の高い方）＋+3R⅓利確の合図</b>を表示する。'
        'トレールまたはストップに当たった銘柄は<b>「売却済」</b>を押すと、その枠を空けて集計する。'
        '空いた枠は<b>次回リバランスまで再投下せず現金で保持</b>し、次の隔週トゥルーアップ（月曜）で新トップ12へ均等配分する。'
        '建値・利確の記録はこの端末に残り、次回も覚えている。</div></div>')


def render(names, m, mri, breakdown, dropped, aux, setups, picks, cand,
           sectors, breadth, yields, asof, sar, mkt, leaders, s2i, e2j, s2t):
    band_lab, band_cls = mri_band(aux["hl"])
    mk = max(0, min(100, aux["cur"]))
    # ---- トレンド判定 pill (file=確定 / live=推定 / none=無判定グレー). logic hidden
    sar_color, sar_src = sar
    if sar_color is None:                       # everything failed -> gray no-judgment
        s_lab, s_jud, s_lot, s_cls = "—", "判定不可", "データ取得不可", "sar-gray"
    else:
        s_lab, s_jud, s_lot, s_cls = SAR_JUDGMENT.get(sar_color, SAR_JUDGMENT["Blue"])
    if sar_src == "file":
        badge = '<span class="sar-badge ok">確定</span>'
    elif sar_src == "estimate":
        badge = '<span class="sar-badge est">推定</span>'
        if sar_color in ("Yellow", "Red"):      # weak-side estimate is unreliable
            s_lot = "推定・要TradingView確認"
    else:
        badge = '<span class="sar-badge none">無判定</span>'
    sar_pill = f"""
    <div class="sar {s_cls}" id="sarPill">
      <div class="lhs">
        <span class="dot"></span>
        <div>
          <div class="lab">トレンド判定 <span id="sarBadge">{badge}</span></div>
          <div class="col" id="sarCol">{s_lab}</div>
        </div>
      </div>
      <div class="rhs">
        <div class="jud" id="sarJud">{s_jud}</div>
        <div class="lot" id="sarLot">{s_lot}</div>
      </div>
    </div>"""
    # ---- status banner + ⑥ tappable breakdown panel
    drop_note = ""
    if dropped:
        drop_note = f'<div class="note">注記：データ未取得のため除外し残り指標で100点満点に再正規化 → {", ".join(dropped)}</div>'
    _kj = {"qqq_50":"QQQ vs50MA","qqq_200":"QQQ vs200MA","spy_50":"SPY vs50MA","spy_200":"SPY vs200MA",
           "rsp_50":"等加重S&P vs50MA","rsp_200":"等加重S&P vs200MA","qqqe_50":"等加重NDX vs50MA",
           "vix":"VIX","vix_ratio":"VIX/VIX3M","vvix":"VVIX","hyglqd_20":"クレジット HYG/LQD",
           "hyglqd_5d":"クレジット 5日","rsp_spy_20":"ブレッス RSP/SPY","qqqe_qqq_20":"ブレッス QQQE/QQQ","iwm_spy_20":"小型株 IWM/SPY"}
    _gj = {"trend":"トレンド","vol":"ボラティリティ","credit":"信用","breadth":"ブレッドス"}
    def _mraw(k, v):
        if v is None or (isinstance(v, float) and np.isnan(v)): return "—"
        if k in ("vix", "vvix"): return f"{v:.1f}"
        if k in ("vix_ratio", "hyglqd_20", "rsp_spy_20", "qqqe_qqq_20", "iwm_spy_20"): return f"{v:.3f}"
        if k == "hyglqd_5d": return f"{v*100:+.2f}%"
        return f"{v*100:+.1f}%"
    _bd_rows = []; _seen_grp = None
    for b in breakdown:
        if b["group"] != _seen_grp:
            _seen_grp = b["group"]
            _bd_rows.append(f'<div class="mgrp">{_gj.get(_seen_grp, _seen_grp)}</div>')
        _bd_rows.append(
            f'<div class="mrow"><span class="mk2">{_kj.get(b["key"], b["key"])}</span>'
            f'<span class="mraw">{_mraw(b["key"], b["raw"])}</span>'
            f'<span class="mbar"><i style="width:{100*b["frac"]:.0f}%"></i></span>'
            f'<span class="mpts">{b["pts"]:.1f}/{b["ptsmax"]}</span></div>')
    # ベア警戒：点灯中の要因を明示（点灯=赤、非点灯=グレー）
    _bf = aux.get("bear_flags", [])
    _blit = [lab for lab, on in _bf if on]
    _boff = [lab for lab, on in _bf if not on]
    _bchips = ("".join(f'<span class="bfl on">{lab}</span>' for lab in _blit)
               + "".join(f'<span class="bfl off">{lab}</span>' for lab in _boff))
    bear_sec = (f'<div class="mgrp">ベア警戒 点灯 {aux["bear_n"]}/11</div>'
                f'<div class="bflags">{_bchips or "<span class=bfl off>—</span>"}</div>')
    mri_bd = (f'<div id="mri-bd" class="mri-bd" onclick="event.stopPropagation()">'
              f'<div class="mbd-h">地合いスコアの内訳（11指標・加重合計）</div>'
              + "".join(_bd_rows) + bear_sec
              + '<div class="mnote">赤=点灯中のベア要因。もう一度タップで閉じる ▴</div></div>')
    banner = sar_pill + _ribbon(mkt.get("trend_hist")) + f"""
    <div class="banner b-{band_cls}" onclick="toggleMri()">
      <div class="lab">マーケットステータス（地合いスコア）<span class="tap">タップで内訳 ▾</span></div>
      <div class="val">{aux['cur']:.0f}<span style="font-size:15px;font-weight:600">/100</span></div>
      <div class="st">{band_lab}</div>
      <div class="gauge"><div class="mk" style="left:{mk}%"></div></div>
      <div class="aux">
        <div class="a">傾き <b>{aux['slope']}</b></div>
        <div class="a">ベア警戒 <b>{aux['bear_n']}</b>/11 {_led(aux['bear_n'])}</div>
      </div>
      {mri_bd}
      {drop_note}
    </div>"""

    # ---- TAB 今日 — procedure-aligned (本日◎押し目 ③ + リーダー監視 ①〜⑤)
    comment = _market_comment(aux, mkt, sar)
    rotation = _rotation_comment(mkt)
    pick_set = {t for t, _, _ in picks}
    buytoday = build_buy_today(m, s2i, e2j, s2t, pick_set=pick_set)
    vcp_rows = build_vcp(m, s2i, e2j, s2t)
    by_state, buys = leaders
    leaders_card = _leaders_card(by_state)
    # new 52w-high breakouts — 強い銘柄のみに厳選（RS90以上・$10M以上）
    nh = m[(m["dist52"] >= -0.005) & (m["rs"] >= 90) & (m["dvol"] >= DVOL_FLOOR)].sort_values("rs", ascending=False)
    nh_list = list(nh.index)
    nh_chips = "".join(
        f'<span class="chip hot" data-liq="{(m.at[t,"dvol"] or 0)/1e6:.1f}" data-tkone="{t}">{t}</span>' for t in nh_list)
    newhigh_card = (
        f'<div class="card"><div class="hdr"><h2>本日の新高値圏</h2>{_cp(nh_list)}</div>'
        f'<div class="sub">52週高値まで0.5%以内・<b>RS90以上かつ$10M以上の強い銘柄のみ</b>・RS順（{len(nh_list)}銘柄）</div>'
        f'<div class="chips">{nh_chips or "<span class=empty>該当なし</span>"}</div></div>')
    # ピックアップtab（旧ウォッチと統合）は、検索/セットアップ等のカード生成後に下でまとめて組み立てる。

    # ---- TAB ポートフォリオ
    per = ALLOC[0] / N_PORT
    _raw_rank = {t: i + 1 for i, t in enumerate(cand.index)}   # 全候補内の189RS順位（控えと共通の通し番号）
    _hv = mkt.get("hold") or {}
    _er = mkt.get("er") or {}
    def _trail_cell(t):
        h = _hv.get(t)
        if not h or h.get("dist") is None or h["dist"] != h["dist"]:
            return '<td class="mut">—</td>'
        d = h["dist"]
        w = h.get("which", "")
        # 想定変動幅(ADR実現ボラ・約1ヶ月1σ)と出口距離を並記＝タイトさが一目
        adr = (m.at[t, "adr"] if (t in m.index and pd.notna(m.at[t, "adr"])) else None)
        em = (float(adr) * 0.55 * float(np.sqrt(21))) if adr is not None else None
        shallow = (em is not None and d < em)                 # 出口が1σより内＝ノイズで振られやすい
        cls = "neg" if (d < 0.05 or shallow) else ("mut" if d < 0.10 else "pos")
        r3 = '<span class="r3b">+3R⅓利確</span>' if h.get("hit3") else ""
        flag = '<span class="shallow">浅</span>' if shallow else ""
        emtxt = f'・想定±{em*100:.0f}%' if em is not None else ""
        return (f'<td class="{cls}">{d*100:.0f}%{flag}{r3}'
                f'<div class="tday">保有{h.get("days",1)}日{("・"+w) if w else ""}{emtxt}</div></td>')
    # 保有テーブル = RS上位から連番で、選定12(=リーダーのみ)が埋まるまでの全銘柄
    #   (選外=出遅れ/小型創薬/リーダー外 もバッジ付きで同じ表にRS順表示・買わない)。
    _pick_set = set(t for t, _, _ in picks)
    # 選定銘柄の最下位RS順位まで表示（12銘柄未満なら最後の選定まで・0なら文脈として上位12行）
    _pick_pos = [pos for pos, t in enumerate(cand.index, 1) if t in _pick_set]
    _disp_cap = max((_pick_pos[-1] if _pick_pos else 0), min(len(cand), N_PORT))
    rows = []
    for i, (t, r) in enumerate(cand.iterrows(), 1):
        if i > _disp_cap:
            break                                   # 選定が埋まった位置まで＝以降は控えへ
        sth = subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))
        is_l, code, _lab, _rsn = leader_state(r)
        nu_tag, _nun, nu_cls = momentum_nuance(r)
        _selected = t in _pick_set
        _exq = bool(r.get("excluded_theme")); _lag = bool(r.get("laggard")); _nl = bool(r.get("nonleader"))
        _lag_tag = '<span class="lagb">出遅れ</span>' if _lag else ''   # 買う対象・タグのみ
        # 選外バッジ / 組み込み待ち判定
        if _exq:
            _badge = '<span class="exq">除外（小型創薬）</span>'; _trcls = ' class="row-excluded"'
        elif _nl and not _selected:
            _badge = '<span class="lagb">リーダー外（選外）</span>'; _trcls = ' class="row-excluded"'
        else:
            _r5 = r.get("ret5"); _r5 = float(_r5) if (_r5 is not None and _r5 == _r5) else None
            _drop = bool(r.get("lo20_break")) or (_r5 is not None and _r5 <= -0.15)
            _clx = bool(r.get("capit5"))
            _wait = ('<span class="waitb">組み込み待ち</span>' if (_drop and not _clx) else
                     '<span class="okb">投げ確認・解禁</span>' if (_drop and _clx) else "")
            _badge = _lag_tag + _wait                                  # 出遅れタグ＋（あれば）急落状態
            _trcls = ' class="row-wait"' if (_drop and not _clx) else ""
        _th = theme_of(t, s2t)
        rows.append(
            f'<tr{_trcls} data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}"><td class="l mut">{i}</td>'
            f'<td class="l tk">{t}{_badge}'
            f'<div class="rowsec">{_th} ・ {sth}</div>'
            f'<div class="rowbadges">'
            f'<span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span>'
            f'{_state_badge(code, nu_tag, nu_cls, _rsn)}{_er_badge(t, _er, mkt.get("asof_bar"))}{_adr_badge(r.get("adr"))}{_entry_badge(r.get("rs"), r.get("close"), r.get("ema21"))}</div></td>'
            f'<td>{r["rs189"]:.0f}{_rs_arrow(r.get("rs189_d"))}</td>'
            f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
            f'<td class="{color_pct(r["vs200"])}">{fmt_pct(r["vs200"])}</td>'
            f'{_trail_cell(t)}'
            f'<td class="{color_pct(r["dist52"])}">{fmt_pct(r["dist52"])}</td></tr>')
    alloc_bar = (f'<div class="alloc">'
                 f'<div class="a-ind" style="width:{ALLOC[0]}%">個別 {ALLOC[0]}</div>'
                 f'<div class="a-lev" style="width:{ALLOC[1]}%">レバ {ALLOC[1]}</div>'
                 + (f'<div class="a-cash" style="width:{ALLOC[2]}%">現金 {ALLOC[2]}</div>' if ALLOC[2] > 0 else "")
                 + '</div>')
    port = (f'<div class="card"><div class="hdr"><h2>ポートフォリオ（個別株スリーブ）</h2>'
            f'{_cp([t for t, _, _ in picks])}</div>'
            + alloc_bar +
            f'<div class="note rk-note"><b>RS</b>＝189営業日（≒9ヶ月）リターンの全市場パーセンタイル。<b>#</b>＝RS順位（保有＝上位・控え＝以降）。銘柄名の下にリーダー状態と値動きを表示。<b>リーダー</b>＝63日RS≥85 かつ 200MA上（欠けると「リーダー外」）。<b>買うのはリーダーの中で上位{N_PORT}銘柄だけ</b>。<b>出口まで</b>＝トレール（<b>10日安値×0.998</b> と <b>21EMA×0.99</b> の高い方）までの距離＋<b>想定±Y%</b>（ADR実現ボラの約1ヶ月1σ）。<b class="shallow" style="margin:0 2px">浅</b>＝出口が想定変動より内側＝ノイズで振られやすい。<b class="r3b" style="margin:0 2px">+3R⅓利確</b>＝+3R到達で1/3利確（残りは10日安値割れ・建値移動なし）。<b class="entb ent-good" style="margin:0 2px">◎ゾーン内</b>＝21EMAの−1〜+4%＝理想の拾い場（<b>RS97+は伸びを追わず厳守</b>／RS75-90は位置ほぼ不問）。<b>出遅れ</b>（業種内−20%劣後）は<b>タグのみで買う対象</b>。<b class="adrb adr-lo" style="margin:0 2px">ADR↓</b>/<b class="adrb adr-hi" style="margin:0 2px">ADR↑</b>＝日中値幅が3.5〜8%の外。<b>選外（小型創薬／リーダー外）はグレーアウト</b>。</div>'
            f'<table><tr><th class="l">#</th><th class="l">銘柄</th><th>RS</th>'
            f'<th>前日比</th><th class="th-w">200MA<br>乖離</th><th class="th-w">出口<br>まで</th><th class="th-w">52週<br>高値差</th></tr>'
            + "".join(rows) + '</table>'
            + _risk_note(mkt) +
            f'<div class="note">1銘柄あたり{per:.2f}%（各1/{N_PORT}等分）。トレンド悪化時は{N_PORT}銘柄が揃わず現金が増えるのが正常。<b>組み込み待ち</b>＝急落局面で投げ未確認・枠は現金（13位以降を繰り上げず次回リバランスで再判定）。詳しいルールはルールタブへ。</div></div>')
    # RSリーダー控え（15社）は下でdeck_card構築後に port へ追加



    # ---- TAB ウォッチ — watchlist: 複数ヒット overlap + セットアップ別 + RSリーダー控え
    from collections import Counter
    memb = Counter(); where = {}
    for nm, lst in setups.items():
        for t in lst:
            memb[t] += 1; where.setdefault(t, []).append(nm)
    multi = sorted([(t, c) for t, c in memb.items() if c >= 3],
                   key=lambda x: (-x[1], -(float(m.at[x[0], "rs"]) if x[0] in m.index else 0)))
    multi_tk = [t for t, _ in multi]
    ov_chips = "".join(
        f'<span class="chip ov" data-liq="{(m.at[t,"dvol"] or 0)/1e6:.1f}" data-tkone="{t}" title="{"・".join(where[t])}">{t}'
        f'<span class="b">×{c}</span></span>' for t, c in multi)
    overlap_card = (
        f'<div class="card"><div class="hdr"><h2>複数ヒット（3つ以上のステータス）</h2>{_cp(multi_tk)}</div>'
        f'<div class="sub">3つ以上のセットアップに同時該当した高確度銘柄・ヒット数順（{len(multi)}銘柄）</div>'
        f'<div class="chips">{ov_chips or "<span class=empty>該当なし</span>"}</div></div>')
    setup_html = []
    for nm, lst in setups.items():
        shown = lst[:CHIP_CAP]                   # top N by RS (already RS-sorted)
        extra = len(lst) - len(shown)
        chips = "".join(
            f'<span class="chip{" hot" if (m.at[t,"rs"]>=90) else ""}" data-liq="{(m.at[t,"dvol"] or 0)/1e6:.1f}" data-tkone="{t}">{t}</span>' for t in shown)
        more = f'<span class="more">+{extra}件</span>' if extra > 0 else ""
        setup_html.append(
            f'<div class="setup-h"><span class="nm">{nm}</span>'
            f'<span style="display:flex;gap:6px;align-items:center">{_cp(lst)}'
            f'<span class="ct">{len(lst)}</span></span></div>'
            f'<div class="chips">{chips or "<span class=empty>なし</span>"}{more}</div>')
    setup_card = (f'<div class="card"><h2>セットアップ別</h2>'
                  f'<div class="sub">押し目/ブレイク近/出来高急増/モメンタム/ボラ収縮/深押し ・各RS上位{CHIP_CAP}件</div>'
                  + "".join(setup_html) + '</div>')
    # 控え = 保有テーブル(選定が埋まるまでのRS順)に出た範囲より下＝真に次の繰上げ候補。
    _pick_set = set(t for t, _, _ in picks)
    # 保有テーブルの最終行の位置(最下位選定銘柄のcand内index位置)を求める（12未満でも正しく動く）
    _last_pos = 0
    for _pos, _tk in enumerate(cand.index):
        if _tk in _pick_set:
            _last_pos = _pos
    deck = cand.iloc[_last_pos+1:_last_pos+1+15]   # 保有表の下から15(次の繰上げ候補)
    wrows = []
    for rank, (t, r) in enumerate(deck.iterrows(), start=_last_pos+2):
        _sth = subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))
        _il, _code, _l, _rsn = leader_state(r)
        _nt, _nn, _nc = momentum_nuance(r)
        _exq = bool(r.get("excluded_theme"))
        _lag = bool(r.get("laggard"))
        _nl = bool(r.get("nonleader"))
        _lag_tag = '<span class="lagb">出遅れ</span>' if _lag else ''
        _exbadge = ('<span class="exq">除外（小型創薬）</span>' if _exq else
                    '<span class="lagb">リーダー外（選外）</span>' if _nl else _lag_tag)
        _trcls = ' class="row-excluded"' if (_exq or _nl) else ""      # 出遅れはグレーアウトしない（買う）
        wrows.append(
            f'<tr{_trcls} data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}"><td class="l mut">{rank}</td>'
            f'<td class="l tk">{t}{_exbadge}'
            f'<div class="rowsec">{_sth}</div>'
            f'<div class="rowbadges">'
            f'<span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span>'
            f'{_state_badge(_code, _nt, _nc, _rsn)}{_entry_badge(r.get("rs"), r.get("close"), r.get("ema21"))}</div></td>'
            f'<td>{r["rs189"]:.0f}{_rs_arrow(r.get("rs189_d"))}</td>'
            f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
            f'<td class="{color_pct(r["ret63"])}">{fmt_pct(r["ret63"])}</td>'
            f'<td class="{color_pct(r["dist52"])}">{fmt_pct(r["dist52"])}</td></tr>')
    deck_card = (f'<div class="card"><div class="hdr"><h2>RSリーダー控え</h2>{_cp(list(deck.index))}</div>'
             f'<div class="sub">保有（上位{N_PORT}リーダー）に次ぐRS順の繰上げ候補。次の隔週入替（月曜）で<b>リーダー化した順に</b>繰り上がる。'
             f'並びでどの業種が強いかも分かる。<b class="lagb" style="padding:0 4px">出遅れ</b>＝業種内−20%劣後だが<b>買う対象（タグのみ）</b>。<b class="lagb" style="padding:0 4px">リーダー外（選外）</b>＝63日RS&lt;85 or 200MA下・<b>除外（小型創薬）</b>＝臨床段階バイオ、この2つはグレーアウト＝選定/繰上げ対象外（大手バイオ/製薬/GLP-1/手術ロボは対象）。</div>'
             f'<table><tr><th class="l">#</th><th class="l">銘柄</th><th>RS</th>'
             f'<th>前日比</th><th>63日</th><th>52週高値差</th></tr>'
             + "".join(wrows) + '</table></div>')
    # 順位落ち保有カード（トップ12外だが継続条件OK＝月曜まで出口監視）
    _carry = mkt.get("carry") or []
    carry_card = ""
    if _carry:
        crows = []
        for t in _carry:
            if t not in m.index:
                continue
            r = m.loc[t]
            _rk = {tk: i + 1 for i, tk in enumerate(cand.index)}.get(t, "—")
            _sth = subtheme_of(t, s2t, e2j.get(s2i.get(t), "—"))
            _il, _code, _l, _rsn = leader_state(r)
            _nt, _nn, _nc = momentum_nuance(r)
            _th = theme_of(t, s2t)
            crows.append(
                f'<tr class="row-carry" data-liq="{(r.get("dvol") or 0)/1e6:.1f}" data-tkone="{t}">'
                f'<td class="l mut">{_rk}</td>'
                f'<td class="l tk">{t}<span class="carryb">順位落ち・保有中</span>'
                f'<div class="rowsec">{_th} ・ {_sth}</div>'
                f'<div class="rowbadges"><span class="capb cap-{r.get("tier_key","none")}">{r.get("tier_lab","—")}</span>'
                f'{_state_badge(_code, _nt, _nc, _rsn)}{_adr_badge(r.get("adr"))}</div></td>'
                f'<td>{r["rs189"]:.0f}{_rs_arrow(r.get("rs189_d"))}</td>'
                f'<td class="{color_pct(r["pchg"])}">{fmt_pct(r["pchg"])}</td>'
                f'<td class="{color_pct(r["vs200"])}">{fmt_pct(r["vs200"])}</td>'
                f'{_trail_cell(t)}'
                f'<td class="{color_pct(r["dist52"])}">{fmt_pct(r["dist52"])}</td></tr>')
        if crows:
            carry_card = (
                f'<div class="card"><div class="hdr"><h2>順位落ち保有（出口監視）</h2>{_cp(_carry)}</div>'
                f'<div class="note">今日のトップ{N_PORT}からRSが落ちたが<b>継続条件（50&gt;200MA かつ 189日RS上位{2*N_PORT}）を満たす保有</b>。'
                f'ルール通り<b>月曜の隔週判定まで売らずに出口監視を継続</b>（トレール/初期ストップは有効）。継続を割った銘柄はここから消え＝月曜売却の対象。</div>'
                f'<table><tr><th class="l">#</th><th class="l">銘柄</th><th>RS</th>'
                f'<th>前日比</th><th class="th-w">200MA<br>乖離</th><th class="th-w">出口<br>まで</th><th class="th-w">52週<br>高値差</th></tr>'
                + "".join(crows) + '</table></div>')
    _carry_sec = (_mkt_section("② 順位落ち保有", "トップ12外だが継続OK＝月曜まで監視") + carry_card) if carry_card else ""
    _deck_num = "③" if carry_card else "②"
    port = (_beta_card(build_beta_view(m, picks)) + _liq_bar()
            + _mkt_section("① 現在の構成", "個別株スリーブ（N=12・等ウェイト）") + port
            + _carry_sec
            + _mkt_section(f"{_deck_num} 控え", "次の入替で上がってくる候補") + deck_card)
    search_card = (
        '<div class="card"><h2>銘柄検索</h2>'
        '<div class="sub">ティッカーで全ユニバースを検索（タップで詳細）</div>'
        '<input id="tksearch" class="tksearch" type="text" inputmode="search" autocomplete="off" '
        'placeholder="例: NVDA" oninput="tkSearch(this.value)">'
        '<div id="tkresults" class="tkresults"></div></div>')
    # ---- TAB ピックアップ（旧「ウォッチ」を統合：役割が重複していた2タブを1つに集約）
    #   構成: 本日の注目 → リーダー監視(状態別) → 新高値圏 → 複数ヒット/セットアップ → 銘柄検索。
    #   旧ウォッチの「リーダー(フラット羅列)」は「リーダー監視(①〜⑤状態別)」と重複するため削除。
    today = (_liq_bar()
             + _mkt_section("① 本日の注目", "セットアップ合致・裁量の参考（ルール外）") + _buy_today_card(buytoday)
             + _mkt_section("② 圧縮コイル（VCP）", "締まり＝エネルギー蓄積・ブレイクで放出（眼を鍛える用）") + _vcp_card(vcp_rows)
             + _mkt_section("③ リーダー監視", "サイクルを引っ張るRS上位群（RS≥85・200MA上）を状態別に") + leaders_card
             + _mkt_section("④ 今日の値動き", "新高値圏＝需給が強い") + newhigh_card
             + _mkt_section("⑤ セットアップで絞る", "複数条件ヒット＝注目度が高い") + overlap_card + setup_card
             + _mkt_section("⑥ 銘柄を調べる", "ティッカー検索 → タップで詳細") + search_card)

    # ---- §4: collect every displayed ticker + build compact detail data (DET)
    tapset = set()
    for _t, _, _ in picks: tapset.add(_t)
    for _lst in setups.values(): tapset.update(_lst)
    for _st in by_state.values():
        for _x in _st: tapset.add(_x["t"])
    for _x in buys: tapset.add(_x["t"])
    for _x in buytoday: tapset.add(_x["t"])
    for _x in vcp_rows: tapset.add(_x["t"])
    tapset.update(nh_list); tapset.update(multi_tk); tapset.update(list(deck.index))
    det_json = _det_json(m, names, set(m.index), _build_det_extra(m, s2t, s2i, e2j, picks, deck, buytoday, nh_list, where))   # 全ユニバース（検索＆タップ詳細）
    dov = ('<div id="dov-bg" class="dov-bg"><div class="dov" onclick="event.stopPropagation()">'
           '<div class="dov-h"><span id="dov-tk" class="dov-tk"></span>'
           '<span class="dov-x" onclick="hideDet()">✕</span></div>'
           '<div id="dov-status" class="dov-status"></div>'
           '<div id="dov-meta" class="dov-meta"></div>'
           '<div id="dov-loc" class="dov-loc"></div>'
           '<div id="dov-body" class="dov-grid"></div>'
           '<div class="dov-note">タップした銘柄のデータ（全リスト共通・裁量参考）</div>'
           '</div></div>')

    # ---- TAB 業種RS（サブテーマ単位）
    def _chip(t, rs):
        _ok = (rs == rs)
        _rs = f'{rs:.0f}' if _ok else '—'
        _hot = ' hot' if (_ok and rs >= 90) else ''
        return (f'<span class="chip{_hot}" data-tkone="{t}">{t}'
                f'<span class="rsb">{_rs}</span></span>')
    def _dz(x): return f'{x:.5f}' if (x is not None and x == x) else 'nan'
    srows = []
    for i, s in enumerate(sectors, 1):
        chips = "".join(_chip(t, rs) for t, rs in s.get("members", []))
        srows.append(
            f'<tbody class="secgrp" data-score="{s["score"]:.3f}" data-d1="{_dz(s.get("d1"))}" '
            f'data-w1="{_dz(s.get("w1"))}" data-m1="{_dz(s.get("m1"))}">'
            f'<tr class="secrow" onclick="secToggle(\'sec{i}\')">'
            f'<td class="l mut secnum">{i}</td>'
            f'<td class="l tk" style="font-size:12px">{s["ja"]} <span class="secx">▾</span>'
            f'<span class="mut" style="font-size:10px;font-weight:400"> {s["n"]}社・RS{s["score"]:.0f}</span>{_rs_arrow(s.get("drs"), th=3)}'
            f'<div class="secparent">{s.get("parent","—")}</div></td>'
            f'<td class="{color_pct(s.get("d1"))}">{fmt_pct(s.get("d1"))}</td>'
            f'<td class="{color_pct(s.get("w1"))}">{fmt_pct(s.get("w1"))}</td>'
            f'<td class="{color_pct(s.get("m1"))}">{fmt_pct(s.get("m1"))}</td></tr>'
            f'<tr id="sec{i}" class="secsub"><td></td>'
            f'<td colspan="4"><div class="secchips">{chips}</div></td></tr>'
            f'</tbody>')
    _imp = sorted([x for x in sectors if x.get("drs", 0) >= 5], key=lambda x: -x["drs"])[:5]
    _wor = sorted([x for x in sectors if x.get("drs", 0) <= -5], key=lambda x: x["drs"])[:5]
    _shift = ""
    if _imp or _wor:
        _shift = ('<div class="shiftrow">'
                  + (('<span class="shl">改善</span>' + "".join(f'<span class="chip shp">{x["ja"]} <b>+{x["drs"]:.0f}</b></span>' for x in _imp)) if _imp else "")
                  + (('<span class="shl shl-n">悪化</span>' + "".join(f'<span class="chip shn">{x["ja"]} <b>{x["drs"]:.0f}</b></span>' for x in _wor)) if _wor else "")
                  + '</div>')
    sector = (f'<div class="card"><h2>サブテーマ別RS（ユニバース内）</h2>'
              f'<div class="sub">構成銘柄の<b>63日RS×189日RS</b>（中央値・均等ブレンド）をサブテーマ単位で0-100ランク（≥2社）。'
              f'▲▼＝<b>約1ヶ月前の63日RS中央値との差</b>＝資金ローテの向き。'
              f'<b>見出しタップで並べ替え</b>・行タップで構成銘柄を展開。各行の下に<b>親テーマ</b>を表示。大枠はマーケットタブのRRG、ここは詳細ランキング。※銘柄選定には不使用の参考指標</div>'
              + _shift +
              f'<table class="secrs"><thead><tr><th class="l">#</th>'
              f'<th class="l sortable act" onclick="secSort(\'score\',this)">サブテーマ <span class="so">⇅RS</span></th>'
              f'<th class="sortable" onclick="secSort(\'d1\',this)">日</th>'
              f'<th class="sortable" onclick="secSort(\'w1\',this)">週</th>'
              f'<th class="sortable" onclick="secSort(\'m1\',this)">月</th></tr></thead>'
              + "".join(srows) + '</table></div>')

    # ---- TAB マーケット
    grp_ja = {"trend":"トレンド","vol":"ボラティリティ","credit":"信用","breadth":"ブレッドス"}
    grp_rows = {}
    for b in breakdown:
        grp_rows.setdefault(b["group"], []).append(b)
    keyja = {"qqq_50":"QQQ vs50MA","qqq_200":"QQQ vs200MA","spy_50":"SPY vs50MA",
             "spy_200":"SPY vs200MA","vix":"VIX水準","vix_ratio":"VIX/VIX3M","vvix":"VVIX",
             "hyglqd_20":"HYG/LQD vs20MA","hyglqd_5d":"HYG/LQD 5日","rsp_50":"等加重S&P vs50MA","rsp_200":"等加重S&P vs200MA","qqqe_50":"等加重NDX vs50MA","rsp_spy_20":"RSP/SPY vs20MA",
             "qqqe_qqq_20":"QQQE/QQQ vs20MA","iwm_spy_20":"IWM/SPY vs20MA"}
    mri_rows = []
    for g in ["trend","vol","credit","breadth"]:
        if g not in grp_rows: continue
        gp = sum(x["pts"] for x in grp_rows[g]); gm = sum(x["ptsmax"] for x in grp_rows[g])
        mri_rows.append(f'<tr><td class="l" style="color:#9ecbff;font-weight:700">{grp_ja[g]}</td>'
                        f'<td colspan="2"></td><td style="color:#9ecbff;font-weight:700">{gp:.0f}/{gm}</td></tr>')
        for x in grp_rows[g]:
            w = 100*x["frac"]
            mri_rows.append(
                f'<tr><td class="l mut" style="padding-left:12px">{keyja.get(x["key"],x["key"])}</td>'
                f'<td class="mut">{fmt_num(x["raw"],3)}</td>'
                f'<td class="l"><span class="bar"><i style="width:{w:.0f}%"></i></span></td>'
                f'<td>{x["pts"]:.1f}/{x["ptsmax"]}</td></tr>')
    ycards = "".join(
        f'<div class="kv"><span class="k">{lab}</span>'
        f'<span class="v">{d["y"]:.2f}% '
        f'<span class="{ "pos" if d["chg"]>=0 else "neg"}" style="font-size:11px">'
        f'{d["chg"]:+.2f}</span></span></div>'
        for lab, d in yields.items())
    market = (
        # ① 全体感 — まず結論
        _mkt_section("① 全体感", "結論と露出方針")
        + banner
        + comment
        + rotation
        + _changelog_card(mkt.get("chlog"), mkt.get("chref"))
        # ② トレンド — 上げか下げか
        + _mkt_section("② トレンド", "指数の方向と勢い")
        + _svg_mri(mkt.get("mri_ts", []))
        + _perf_card(mkt.get("perf", {}))
        # ③ 中身（本物か） — 広がり・主導・資金の向き
        + _mkt_section("③ 中身", "広がり・主導・資金の流れ")
        + _svg_breadth(mkt.get("breadth_ts", []), breadth["n"])
        + _dollarvol_card(mkt.get("dollarvol_ts"))
        + _updown_vol_card(mkt.get("updown_ts"))
        + _leader_temp_card(mkt.get("leader_temp"))
        + _svg_ratio_card(mkt.get("adline_ts", []),
                          "広がりの勢い（マクレラン・オシレーター）",
                          "騰落数の正規化ネット（RANA）の EMA19−EMA39・0中心（2年）。0超=買いの広がり／0割れ=売りの広がり。株価との逆行で崩れの初動を検知",
                          "広がり加速（内部良好）", "広がり失速（内部悪化・要警戒）",
                          "#58a6ff", "ad", show_value=True, zero_ref=True)
        + _svg_ratio_card(mkt.get("defensive_ts", []),
                          "攻守ローテーション（一般消費財 / ディフェンシブ）",
                          "一般消費財 ÷ ディフェンシブ〔生活必需品・公益〕・<b>平均からの偏差σ</b>（2年）。0=平常・プラス=攻め",
                          "攻め優勢", "守り優勢", "#a78bfa", "dg", zero_ref=True, unit="σ")
        # ④ リスク・警戒 — 崩れの兆候
        + _mkt_section("④ リスク・警戒", "株価に先行する変調")
        + _svg_ratio_card(mkt.get("credit_ts", []),
                          "クレジット推移（HYG / LQD）",
                          "ハイイールド債 ÷ 投資適格債・<b>平均からの偏差σ</b>（2年）。狭い比率を偏差化して足元の強弱を可視化。0=平常・プラス=リスクオン",
                          "リスクオン", "信用悪化・警戒", "#fbbf24", "cg", zero_ref=True, unit="σ")
        + _svg_vixterm_card(mkt.get("vixterm_ts", []))
        + _expected_move_card(mkt.get("expmove"))
        + _dd_card(mkt.get("distrib", {}))
        + _sentiment_card(mkt.get("senti"))
        # ⑤ 転換シグナル — いつ動くか
        + _mkt_section("⑤ 転換シグナル", "底打ちと再上昇の確認")
        + _ftd_card(mkt.get("ftd", []))
        # ⑥ 口座リスク管理（自分のカーブをトレードする）
        + _mkt_section("⑥ 口座リスク管理", "自分のエクイティカーブと相場の相性")
        + _equity_card(mkt.get("equity"), mkt.get("eq_attrib"))
        # ⑦ 参考データ
        + _mkt_section("⑦ 参考データ", "金利と内部指標・データ品質")
        + f'<div class="card"><h2>金利</h2>{ycards}</div>'
        + f'<div class="card"><h2>広域ブレッドス</h2>'
        f'<div class="sub">50日線上の比率・当日の騰落・52週高値圏（200日線上の比率はブレッドス推移を参照）</div>'
        f'<div class="kv"><span class="k">50MA上</span><span class="v">{breadth["pa50"]:.0f}%</span></div>'
        f'<div class="kv"><span class="k">上昇/下落</span><span class="v">{breadth["adv"]} / {breadth["dec"]} '
        f'<span class="mut" style="font-size:11px">({breadth["adpct"]:.0f}% up)</span></span></div>'
        f'<div class="kv"><span class="k">52週高値圏</span><span class="v">{breadth["nh"]} '
        f'<span class="mut" style="font-size:11px">({breadth["pnh"]:.1f}%)</span></span></div></div>'
        + _quality_card(mkt.get("quality"))
        # ⑧ レバレッジ環境（旧・配分タブ最下段の「レバ玉の環境」を移設）
        + _mkt_section("⑧ レバレッジ環境", "半導体3xを入れる時のサイズ目安（表示専用）")
        + _lev_env_card(mkt.get("lev_env"), mkt.get("rrg")))

    # ---- TAB ルール (確定版 2026-06-26)
    cur_jp = {"Blue": "青", "Green": "緑", "Yellow": "黄", "Red": "赤"}.get(sar[0])
    exp_rows = [("青", "c-bl", "100%", "100%"), ("緑", "c-gr", "100%", "50%"),
                ("黄", "c-yl", "100%（ト15%）", "0%（撤退）"), ("赤", "c-rd", "0%（全現金）", "0%（全撤退）")]
    nq_rows = ""
    for cj, cls, indv, lev in exp_rows:
        hl = ' class="hl"' if cj == cur_jp else ""
        nq_rows += (f'<tr{hl}><td class="l"><span class="nqd {cls}"></span>{cj}'
                    f'{"（現在）" if cj == cur_jp else ""}</td><td>{indv}</td><td>{lev}</td></tr>')
    cur_line = ""
    if cur_jp:
        em = {"青": ("100%", "100%"), "緑": ("100%", "50%"),
              "黄": ("100%（ト15%）", "0%"), "赤": ("0%", "0%")}[cur_jp]
        cur_line = (f'<div class="sub" style="margin-top:8px">現在の地合い：<b style="color:#e6edf3">{cur_jp}</b>'
                    f' → 個別 {em[0]} ／ レバ {em[1]}</div>')
    rules = (
        f'<div class="card"><h2>システムルール（v2・確定）</h2>'
        f'<div class="sub" style="color:#c7d2fe">相場の方向でリスク量を4段階に調整し、その中で最も強い{N_PORT}銘柄を等分で持つ。負けは早く小さく、勝ちは伸ばす。ルールは事前に固定し、その日の気分で動かさない。</div>'
        f'<div class="rh">配分</div>'
        f'<div class="sub">個別株 <b>{ALLOC[0]}%</b> ／ レバレッジ <b>{ALLOC[1]}%</b>'
        + (f' ／ 現金 <b>{ALLOC[2]}%</b>' if ALLOC[2] > 0 else '')
        + f'。総資産の<b>76%以上</b>をこのシステムに置く。想定ドローダウンは中央値<b>−37〜44%</b>（黄トレール採用で<b>−48%級</b>・週足SAR撤廃で従来より深化）。これに耐えるサイズにし、恐怖で減らさず強気でも増やさない。</div>'
        f'<div class="rh">土台：NQ 4色ゲートで露出を調整</div>'
        f'<div class="sub">毎日トレンドの色を確認し、変わったら翌日の寄りで露出を下表に合わせる（前日終値で確定）。色は手動（TradingView）で読むのが正。</div>'
        f'<table class="nqt"><tr><th class="l">色</th><th>個別株</th><th>レバ(TQQQ/SOXL)</th></tr>{nq_rows}</table>'
        + cur_line +
        f'<div class="sub mut" style="margin-top:6px">黄：個別は持ち続けトレールを15%に締める（下段）。レバは黄で撤退。</div>'
        f'<div class="rh">個別株スリーブ（{ALLOC[0]}%）</div>'
        f'<ul class="rules">'
        f'<li><b>選定</b>（隔週・月曜）：<b>189日RS</b>（≒9ヶ月の相対的な強さの順位）の上位{N_PORT}銘柄。条件は 50日線&gt;200日線・売買代金$10M/日以上・株価$5以上。<b>買うのはリーダー（63日RS≥85 かつ 200MA上）の中だけ</b>——リーダー外は買わない。<b>出遅れ（業種内−20%劣後）は買う</b>（タグのみ）。小型創薬（臨床段階バイオ）は対象外。<b>各1/{N_PORT}を等分</b>、テーマ上限なし。</li>'
        f'<li><b>継続</b>（隔週トゥルーアップ・月曜）：50日線&gt;200日線・<b>189日RS上位24</b>を満たす限り保有。崩れた枠だけ売り、新しいトップRSで{N_PORT}に補充。ランクが下がっただけでは即売りしない。</li>'
        f'<li><b>出口</b>（確定 2026-07-07・同一イベント比較で期待値も勝率も優越）：<b>初期ストップ = max(10日安値×0.998, 21EMA×0.99)</b> → <b>+3R到達で1/3利確</b>（建値移動なし） → <b>残り2/3は10日安値割れで全売り</b>。固定利確ラインは置かない。'
        f'<span class="mut">※+3R利確＝触れた玉を数学的に不敗化、裾を担ぐ2/3は最も裾を殺さない10日安値に任せる役割分担。21EMA×0.93は出口に使わない（判定定規の警戒帯＝深さ−5%超×ADR≥6.5% のみ）。NQ黄=新規停止・保有はトレール継続、赤=全撤退。</span></li>'
        f'<li><b>初期ストップ</b>：建値<b>×0.75（−25%）</b>で全売り。<b>クールダウンなし</b>——切られてもRS上位12・適格なら次の隔週で即復帰（バックテストで撤廃が優位・DD悪化なし）。</li>'
        f'</ul>'
        f'<div class="rh">レバレッジスリーブ（{ALLOC[1]}%）</div>'
        f'<ul class="rules">'
        f'<li><b>構成</b>：TQQQ 50 ： SOXL 50。ただし<b>SOXXの50日線&lt;100日線</b>の間はSOXLを外し全額TQQQ（半導体の下落トレンドで3xを回避）。</li>'
        f'<li><b>SOXL投入帯</b>（MAE実測ベース）：SOXLは<b>SOXXが50MAの+0〜3%上</b>にある日だけ新規投入する（NQ青/緑の日）。この帯は建て直後の初期逆行（MAE）が最も浅く、<b>−25%級の大事故が半分</b>（50MA割れ直下25%→12%）。理由＝支持線がすぐ下＝invalidationが近く、割れたら即撤退できるので深傷になる前に逃げられる。'
        f'<b>投入は1/3ずつ×3トランシェ</b>（各サイズはボラターゲットでスケール）。<b>invalidation＝SOXXが50MAを終値で割ったら新規投入停止</b>（保有はNQ色ルールに従う）。'
        f'<b>50MA割れ・+3%超乖離の日はSOXLを入れずTQQQのみ</b>。※距離で削れるのは大事故確率まで——最良帯でもMAE平均−11%・3割で−15%を食らう前提でサイズを決める（痛くない入り方は無い）。0〜+3%帯は全青緑日の約17%＝月3〜4回来るので待機は長くない。</li>'
        f'<li><b>ゲート</b>：両ETFともNQで露出を＝<b>青100 ／ 緑50 ／ 黄0 ／ 赤0</b>。執行は翌寄り・確認日数ゼロ（3xは執行の遅れがドローダウンを増幅するため即応）。</li>'
        f'</ul>'
        f'<div class="rh">リバランスと例外</div>'
        f'<ul class="rules">'
        f'<li>能動的に動くのは基本<b>NQの色</b>だけ。変われば翌寄りで%を合わせる（同じ銘柄のまま増減）。</li>'
        f'<li><b>スリーブ配分（{ALLOC[0]}/{ALLOC[1]}・TQQQ:SOXL比）のリセットは隔週月曜</b>（銘柄入替と同日）。ゲート露出とSOXL除外の切替は<b>即日</b>（別サイクル）。</li>'
        f'<li><b>赤入り</b>＝両スリーブ全現金。<b>赤明けは翌寄りで即、最新トップ{N_PORT}を選び直す</b>（次回リバランスを待たない）。<b>SOXLは投入帯（SOXX 50MAの+0〜3%）から段階1/3×3で入り直し</b>（赤で段階カウンタは0にリセット・帯外ならTQQQのみ）。</li>'
        f'<li>ストップ／トレールで出た現金は<b>次回リバランスまで現金で保持</b>（期中に再投下しない）。</li>'
        f'<li>保有株が弱っても<b>トレール・ストップ以外では動かさない</b>（SAR弱気・200日割れ・RS低下だけでは売らず、隔週月曜で処理）。</li>'
        f'</ul>'
        f'<div class="rh">非常口（ジリ下げ相場の安全弁）</div>'
        f'<ul class="rules">'
        f'<li>ブレンドNAVが過去ピークから<b>−28%</b>割れ、<b>かつ</b>対QQQ12ヶ月相対が<b>−12%</b>割れ、が同時成立で<b>レバを半減</b>。両方が回復（DD&gt;−20% かつ 相対&gt;−8%）するまで維持。機械的に、判断を挟まない。</li>'
        f'</ul>'
        f'<div class="rh">やらないこと</div>'
        f'<ul class="rules">'
        f'<li>その日の裁量で仕掛けない（エントリーは事前ルールのみ・押し目／ブレイク待ちの裁量はしない）。</li>'
        f'<li>途中の値動きで利確しない（利確はトレールに任せる）。</li>'
        f'<li>業績（EPS・売上）や業種で銘柄を絞らない（選定は価格の強さ＝RSのみ）。</li>'
        f'<li>NQの色を自動推定で代用しない（手動が正）。赤明け・色変化で確認日数を置かない。</li>'
        f'</ul>'
        f'<div class="warn">⚠ 数字の読み方：個別のCAGRは<b>生存バイアス</b>で上振れ（最大の割引要因）、レバは強気相場で上振れ。全数字は「どの構成が優れているか」の相対比較であり、絶対リターンの予測ではない（主指標はSharpeと最大DD）。'
        f'公称成績は「どの月曜から数えるか」で<b>+5pt CAGR相当の運</b>を含む（位相平均でCAGR2〜3pt・Sharpe0.05〜0.07を割り引いて読む）。'
        f'NQの色は手動が正で、自動推定はOniMine復元FSM＝<b>方向は99.04%一致（±2日以内97%）</b>。'
        f'真のドローダウンは生存バイアス込み<b>−37〜44%級（黄トレール採用で−48%級・週足SAR撤廃で深化）・テールp5 −73%〜</b>を想定してサイズを決める。</div></div>')

    body = (build_today_action(sar, mkt, asof)
            + '<nav>'
            '<button class="on" onclick="tab(\'t-market\',this)">マーケット</button>'
            '<button onclick="tab(\'t-today\',this)">ピックアップ</button>'
            '<button onclick="tab(\'t-port\',this)">ポートフォリオ</button>'
            '<button onclick="tab(\'t-alloc\',this)">配分</button>'
            '<button onclick="tab(\'t-sector\',this)">業種RS</button>'
            '<button onclick="tab(\'t-rules\',this)">ルール</button></nav>'
            f'<section id="t-market" class="on">{market}</section>'
            f'<section id="t-today">{today}</section>'
            f'<section id="t-port">{port}</section>'
            f'<section id="t-alloc">{_alloc_tab(mkt.get("calc"), mkt.get("equity"))}</section>'
            f'<section id="t-sector">'
            + _mkt_section("① 今週の温度", "どのテーマが買われたか（1週騰落）")
            + f'{_heatmap_card(mkt.get("sector_ranks"))}'
            + _mkt_section("② ローテーションの向き", "資金は次にどこへ回っているか")
            + f'{_rrg_card(mkt.get("rrg_etf"), None, None, 100, "テーマ・ローテーション（ETF・市場全体の大枠）", "業種テーマETFのSPY相対力(横=SPY基準63日・100が市場平均)×勢い(縦=10日変化)。市場全体のセクター資金フロー。<b>改善→主導→弱化→停滞</b>の時計回り。■＝半導体。")}'
            + f'{_rrg_card(mkt.get("rrg"), None, mkt.get("theme_hier"), 50, "テーマ・ローテーション（自ユニバースのRS）", None)}'
            + _mkt_section("③ 期間別の数字", "日・週・月のリターンで確認")
            + f'{_sector_rank_card(mkt.get("sector_ranks"))}'
            + _mkt_section("④ ユニバース内の実勢", "テーマの強さを個別株RSで裏取り")
            + f'{sector}</section>'
            f'<section id="t-rules">{rules}</section>')

    if asof:
        _ts = pd.Timestamp(asof)
        if _ts.tzinfo is None:
            _ts = _ts.tz_localize("UTC")
        asof_disp = _ts.tz_convert("Asia/Tokyo").strftime("%Y-%m-%d %H:%M JST")
    else:
        asof_disp = ""
    _thex = {"Blue": "#1d4ed8", "Green": "#16a34a", "Yellow": "#ca8a04", "Red": "#dc2626"}.get(sar[0], "#0b0f17")
    html = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='theme-color' content='" + _thex + "'>"
            "<meta name='apple-mobile-web-app-capable' content='yes'>"
            "<meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'>"
            "<title>Command Center</title><style>" + CSS + "</style></head><body>"
            "<div class='wrap'><header><h1>Command Center</h1>"
            f"<div class='asof'>更新 {asof_disp}</div></header>"
            + body + dov
            + "<div id='hierModal' class='hier-modal' onclick=\"this.classList.remove('on')\"><div class='hier-box' onclick='event.stopPropagation()'></div></div>"
            + "<footer class='disc'>※個人の研究用ダッシュボードであり、投資助言ではありません</footer>"
            + "</div>"
            + "<script>window.DET=" + det_json + ";</script>"
            + "<script>window.CALC=" + json.dumps(mkt.get("calc") or {}, ensure_ascii=False, separators=(",", ":")) + ";</script>"
            + "<script>" + JS + "</script></body></html>")
    return html

# ----------------------------------------------------------------------------- selftest
def selftest(html, picks, setups, sectors):
    errs = []
    for sid in ["t-today","t-market","t-port","t-alloc","t-sector","t-rules"]:
        if f'id="{sid}"' not in html:
            errs.append(f"missing tab {sid}")
    if "マーケットステータス（地合いスコア）" not in html: errs.append("status banner missing")
    if "トレンド判定" not in html: errs.append("trend pill missing")
    if not any(c in html for c in ["sar-blue","sar-green","sar-yellow","sar-red"]):
        errs.append("NQ-SAR color class missing")
    if f">{len(picks)}銘柄<" is None: pass
    if len(picks) > N_PORT: errs.append(f"portfolio exceeds N={N_PORT} (got {len(picks)})")
    if "None" in html: errs.append("literal 'None' in html")
    # --- 仕様ガード(回帰防止・最終確定2026-07-05) ---
    if gate_coeffs("Yellow") != (1.0, 0.0): errs.append("gate: 黄=保有露出100(新規停止・トレール15%)が正")
    if gate_coeffs("Red")    != (0.0, 0.0): errs.append("gate: 赤=撤退0が正")
    if gate_coeffs("Green")  != (1.0, 0.5): errs.append("gate: 緑")
    if "建値×0.70（−30" in html or "−30%初期" in html: errs.append("旧stop30が残存")
    if "落ちるナイフ" in html or "刃物" in html: errs.append("旧・ナイフ用語が残存")
    if "セリングクライマックス" not in html and "投げ" not in html: print("[warn] 投げ確認ルールの説明が見当たらない")
    if "出遅れ" not in html and "業種内" not in html: print("[warn] 出遅れ株除外の説明が見当たらない")
    if "新規停止" not in html and "新規エントリーは停止" not in html: print("[warn] 黄=新規停止の表示が見当たらない(黄以外の日は正常)")
    if "小型創薬" not in html: print("[warn] 小型創薬除外の説明が見当たらない")
    if EXCLUDE_SUBTHEMES != ("臨床段階・中小型バイオ",): errs.append("バイオ除外サブテーマが変更されている")
    if ">nan<" in html or " nan%" in html or "nan/100" in html: errs.append("literal nan in html")
    if "リーダー監視" not in html: errs.append("leaders card missing")
    if "本日のピックアップ" not in html: errs.append("pickup card missing")
    if not sectors: errs.append("sector RS empty")
    if "VIX期間構造" not in html: errs.append("VIX term chart missing")
    if "todayact" not in html: errs.append("today action header missing")
    if "騰落ライン" not in html: errs.append("A/D line chart missing")
    if f"上位{N_PORT}" not in html: errs.append("N reflected text missing")
    # --- v3 additions
    if "センチメント（群衆温度計）" not in html: errs.append("sentiment card missing")
    if ("エクイティカーブ×21EMA" not in html): errs.append("equity card missing")
    if "前回からの変化" not in html: errs.append("changelog card missing")
    if "データ品質" not in html: errs.append("quality card missing")
    if "セクター温度マップ" not in html and "hmgrid" not in html: errs.append("sector heatmap missing")
    if "トレール" not in html: errs.append("trail column missing")
    if "先導株の強さ" not in html: print("[warn] leader temp gauge missing (データ不足の可能性)")
    if "theme-color" not in html: errs.append("theme meta missing")
    if "テーマ・ローテーション" not in html: errs.append("RRG card missing")
    if "ステージ2" not in html: errs.append("stage analysis (DET) missing")
    if "Day4以降" not in html: errs.append("FTD canonical text missing")
    if "レバレッジ・コンディション" not in html: errs.append("lev-env panel missing")
    return errs

# ----------------------------------------------------------------------------- main
def main():
    diag = "--diag" in sys.argv
    do_self = "--selftest" in sys.argv or not diag
    names, order, s2i, s2t, e2j, W, macro, asof = load_inputs()
    W = guard_last_bar(W)                        # A5: 部分/不完全な最終バーを落としてから計算
    m, asof_bar = compute_metrics(W, order, s2i)
    m["beta"] = build_betas(W, macro)
    mcaps = load_market_caps(list(m.index), live=not os.path.exists(CACHE))
    m["mcap"] = m.index.map(lambda t: mcaps.get(t))
    _tier = m["mcap"].map(cap_tier)
    m["tier_key"]  = _tier.map(lambda x: x[0])
    m["tier_lab"]  = _tier.map(lambda x: x[1])
    m["tier_rank"] = _tier.map(lambda x: x[2])
    mri, breakdown, dropped, active, vals = mri_frame(macro)
    aux = mri_auxiliary(mri, vals, m)
    setups = build_setups(m)
    picks, cand = build_portfolio(m, s2t)
    leaders = build_leaders(m, s2i, e2j, s2t)
    sectors = build_sector_rs(m, s2i, e2j, s2t)
    breadth = build_breadth(m)
    yields = build_yields(macro)
    sar = read_sar_state()
    _thist, _tprev = load_trend_history(sar[0], asof_bar.date())
    _extras = load_market_extras()
    mkt = {"distrib": build_distribution(macro), "ftd": build_ftd(macro), "perf": build_perf(macro, _extras),
           "sector_ranks": build_sector_ranks(macro, _extras),
           "breadth_ts": build_breadth_ts(W),
           "dollarvol_ts": build_dollarvol_ts(W, macro, lookback=CHART_LB),
           "updown_ts": build_updown_vol_ts(W, macro),
           "credit_ts": build_ratio_ts(macro, "HYG", ["LQD"]),
           "defensive_ts": build_ratio_ts(macro, "RSPD", ["RSPS", "RSPU"]),
           "vixterm_ts": build_vix_term_ts(macro),
           "expmove": build_expected_move(macro, m, picks),
           "adline_ts": build_adline_ts(W),
           "trend_prev": _tprev,
           "trend_hist": _thist,
           "asof_bar": asof_bar,
           "mri_ts": [(d.strftime("%Y-%m-%d"), float(v)) for d, v in mri.iloc[-CHART_LB:].items()],
           "leader_temp": build_leader_temp(W)}
    mkt["rrg"] = build_rrg(m, s2t)
    mkt["rrg_etf"] = build_rrg_etf(macro, _extras)
    mkt["sectors_rs"] = sectors
    mkt["theme_hier"] = build_theme_hierarchy(m, s2t)
    mkt["lev_env"] = build_lev_env(macro)
    mkt["calc"] = build_calc_extras(picks, sar[0], cand)
    # SOXL投入帯 → 配分計算のTQQQ:SOXL比に自動反映（投入帯なら50/50、帯外は全額TQQQ）
    _le = mkt["lev_env"] or {}
    if mkt["calc"] is not None:
        _ok = bool(_le.get("entry_ok"))
        mkt["calc"]["soxl_w"] = 0.5 if _ok else 0.0
        mkt["calc"]["soxl_reason"] = (_le.get("entry_txt") or ("投入帯" if _ok else "帯外"))
    mkt["broad_note"] = broad_vs_cap_note(vals)

    # --- v3: sentiment / equity / state+changelog / trail / corr / earnings / quality
    _live = not os.path.exists(CACHE) or os.environ.get("V38_FORCE_LIVE") == "1"
    try:
        mkt["senti"] = build_sentiment(macro, W, live=_live or os.environ.get("V38_SENTI_LIVE") == "1")
    except Exception as _e:
        sys.stderr.write("[senti] build failed: %r\n" % repr(_e)[:120]); mkt["senti"] = None
    try:
        _eq_s = load_equity()
        mkt["equity"] = build_equity_view(_eq_s)
        mkt["eq_attrib"] = build_equity_attrib(_eq_s, macro)
    except Exception as _e:
        sys.stderr.write("[equity] build failed: %r\n" % repr(_e)[:120]); mkt["equity"] = None
    # コピー行の区切りを既存 equity.csv に合わせる（写真の体裁ズレ対策・多数決）
    if mkt.get("calc") is not None:
        mkt["calc"]["eq_delim"] = (mkt.get("equity") or {}).get("delim") or ","
    _prev_state = load_state()
    _hold, _hv, _heat, _tf, _carry = track_holdings(_prev_state, picks, sar[0], asof_bar.date(), m)
    mkt["hold"], mkt["heat"] = _hv, _heat
    mkt["carry"] = _carry                         # 順位落ちだが継続条件を満たす保有（出口監視継続）
    mkt["corr"] = portfolio_corr(W, [t for t, _, _ in picks])
    # レジーム値（changelog＋状態保存用）: SOXL投入帯 / 売買代金トレンド / 集積分散
    _soxl_ok = bool((mkt.get("lev_env") or {}).get("entry_ok"))
    _dvts = mkt.get("dollarvol_ts") if isinstance(mkt.get("dollarvol_ts"), dict) else None
    _turn_dir = ((_dvts or {}).get("uni_trend") or {}).get("dir")
    _udts = mkt.get("updown_ts")
    _ud_reg = _updown_state(_udts[-1][1])[2] if _udts else None
    _chlog, _chref, _major = build_changelog(_prev_state, sar[0], aux, mkt["senti"], picks, asof_bar.date(),
                                             soxl_ok=_soxl_ok, turnover_dir=_turn_dir, updown_reg=_ud_reg)
    mkt["chlog"], mkt["chref"] = _chlog, _chref
    _er_tickers = [t for t, _, _ in picks] + list(cand.index[N_PORT:N_PORT + 15])
    mkt["er"] = load_earnings(_er_tickers, live=_live)
    mkt["quality"] = dict(
        uni_total=len(order), uni_ok=len(m),
        split_suspect=int(m["split_suspect"].sum()) if "split_suspect" in m else 0,
        rs_pool=int(m["rs_pool"].sum()) if "rs_pool" in m else len(m),
        nq_src=sar[1],
        next_rebal=(lambda _d: f'{_d.strftime("%Y-%m-%d")}（隔週・月曜）')(
            asof_bar + pd.Timedelta(days=(7 - asof_bar.weekday()) % 7 or 7)),
        macro_missing=[k for k in MACRO_TICKERS if k not in macro],
        mri_dropped=list(dropped),
        senti_src=(mkt["senti"] or {}).get("avail") or [],
        er_n=len(mkt["er"] or {}), eq=bool(mkt["equity"]),
        state=_chref)
    # persist state (prevdayは直近の別日サマリを保持) + 日次ログ + 通知
    _today = str(asof_bar.date())
    _prevday = (_summ(_prev_state) if (_prev_state.get("date") and _prev_state["date"] != _today)
                else _prev_state.get("prevday"))
    save_state(dict(date=_today, gate=sar[0], mri=round(aux["cur"], 1),
                    bear_lit=[lab for lab, on in aux["bear_flags"] if on],
                    senti=(round(mkt["senti"]["cur"], 1) if mkt["senti"] else None),
                    senti_flags=[l for l, on in (mkt["senti"] or {}).get("flags", []) if on],
                    soxl_band=("投入帯" if _soxl_ok else "帯外"), turnover=_turn_dir, updown=_ud_reg,
                    picks=[t for t, _, _ in picks], hold=_hold, prevday=_prevday))
    append_log_csv(asof_bar.date(), sar[0], aux, mkt["senti"], picks)
    if _major:
        post_webhook(_chlog, sar[0])

    if diag:
        print("=== DIAG ===")
        print(f"metrics tickers: {len(m)} | asof bar: {asof_bar.date()}")
        _sj = SAR_JUDGMENT.get(sar[0], ("", "判定不可"))[1] if sar[0] else "判定不可(無判定)"
        print(f"Trend(SAR): {sar[0]}  判定={_sj}  source={sar[1]}")
        print(f"地合いスコア now: {aux['cur']:.1f}  band: {mri_band(aux['cur'])[0]}")
        print(f"  slope {aux['slope']} | bear {aux['bear_n']}/11 | peak {aux['peak']} (drop {aux['drop']:.1f} from {aux['hi20']:.1f})")
        print(f"  dropped indicators: {dropped or 'none'} | active weights sum: {sum(w for _,w,_,_,_ in active)}")
        print("  breakdown (key: pts/max  raw):")
        for b in breakdown:
            print(f"    {b['key']:12s} {b['pts']:5.1f}/{b['ptsmax']:<3d} raw={b['raw']:.4f}")
        print(f"\nPortfolio N={len(picks)} (no theme cap):")
        for t,th,r in picks:
            print(f"  {t:6s} RS{r['rs']:3.0f}  d%{r['pchg']*100:+5.1f}  v200{r['vs200']*100:+6.1f}  [{th}]")
        print(f"\nSetup counts:")
        for k,v in setups.items():
            print(f"  {k:8s} {len(v):4d}   {', '.join(v[:8])}{' ...' if len(v)>8 else ''}")
        bs, bys = leaders
        ltot = sum(len(v) for v in bs.values())
        print(f"\nLeaders (RS>=85 & >200MA): {ltot} total")
        for code, lab, _ in STATE_DEF:
            print(f"  {code} {lab:14s} {len(bs.get(code,[])):4d}")
        print(f"本日◎押し目 (③ buys): {len(bys)}  " +
              ", ".join(b['t'] for b in bys[:12]) + (' ...' if len(bys) > 12 else ''))
        print(f"\nSector RS top8:")
        for s in sectors[:8]:
            print(f"  {s['score']:5.1f}  {s['ja'][:24]:24s} (n={s['n']})")
        print(f"Sector RS bottom5:")
        for s in sectors[-5:]:
            print(f"  {s['score']:5.1f}  {s['ja'][:24]:24s} (n={s['n']})")
        print(f"\nBreadth: >200MA {breadth['pa200']:.0f}% | >50MA {breadth['pa50']:.0f}% | adv/dec {breadth['adv']}/{breadth['dec']} | 52wH {breadth['nh']}")
        print(f"Yields: " + " | ".join(f"{k} {d['y']:.2f}%({d['chg']:+.2f})" for k,d in yields.items()))
        dd = mkt["distrib"]; pf = mkt["perf"]
        print("Distribution days: " + (", ".join(f"{k} {v['n']}({v['st']})" for k,v in dd.items()) or "n/a"))
        if pf and pf.get("indices"):
            for ix in pf["indices"]:
                print(f"{ix['label']} perf: YTD {fmt_pct(ix['ytd'])} 1W {fmt_pct(ix['w1'])} "
                      f"1M {fmt_pct(ix['m1'])} 1Y {fmt_pct(ix['y1'])} | 52w-pos "
                      f"{(ix['pos52'] if ix.get('pos52') is not None else float('nan')):.0f}%")
            if pf.get("vix") is not None:
                print(f"VIX {pf['vix']:.1f} | curve {pf.get('vixcurve')}")
            print(f"divergence: {pf.get('divergence')}")
        sr = mkt["sector_ranks"]
        for grp, lab in [("macro", "大分類"), ("micro", "小分類")]:
            rr = sorted(sr.get(grp, []), key=lambda x: (-(x["d1"] if x["d1"] == x["d1"] else -9)))
            print(f"\nSector {lab} ({len(rr)}) by 1d:")
            for s in rr:
                print(f"  {s['ja']:10s} {s['tk']:5s}  d{fmt_pct(s['d1'])} w{fmt_pct(s['w1'])} m{fmt_pct(s['m1'])}")
        bts = mkt["breadth_ts"]
        if bts:
            print(f"Breadth TS (>200MA): {len(bts)} pts, {bts[0][1]:.0f}% -> {bts[-1][1]:.0f}%")
        print(f"SAR-bullish count: {(m['sar_bull']==True).sum()} / {m['sar_bull'].notna().sum()} valid")
        return

    html = render(names, m, mri, breakdown, dropped, aux, setups, picks, cand,
                  sectors, breadth, yields, asof, sar, mkt, leaders, s2i, e2j, s2t)
    if do_self:
        errs = selftest(html, picks, setups, sectors)
        if errs:
            print("SELFTEST FAILED:")
            for e in errs: print("  -", e)
            sys.exit(1)
        bs_, bys_ = leaders
        print("SELFTEST OK (7 tabs, status banner, N=%d, leaders=%d, buys=%d, sectors=%d, no None/nan)" %
              (len(picks), sum(len(v) for v in bs_.values()), len(bys_), len(sectors)))
    _outdir = os.path.dirname(OUT_HTML)
    if _outdir:
        os.makedirs(_outdir, exist_ok=True)
    open(OUT_HTML, "w").write(html)
    print("WROTE", OUT_HTML, f"({len(html)//1024} KB)")
    try:
        _ts2 = pd.Timestamp(asof)
        if _ts2.tzinfo is None:
            _ts2 = _ts2.tz_localize("UTC")
        _ad = _ts2.tz_convert("Asia/Tokyo").strftime("%Y-%m-%d")
    except Exception:
        _ad = str(asof_bar.date())
    share = build_share_html(aux, sar, mkt, picks, mkt.get("senti"), _ad)
    share_path = OUT_HTML.replace(".html", "_share.html")
    open(share_path, "w").write(share)
    print("WROTE", share_path, "(X投稿用シェアカード 1200x675・スクショして使う)")

if __name__ == "__main__":
    main()
