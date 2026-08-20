from pathlib import Path
import re

p = Path('build_dashboard.py')
s = p.read_text(encoding='utf-8')


def replace_once(old, new, label):
    global s
    if new in s:
        return
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f'{label}: expected 1 anchor, got {n}')
    s = s.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Split / reverse split confirmation
# -----------------------------------------------------------------------------
if 'SPLIT_EVENT_CONFIRM_V1' not in s:
    anchor = 'def compute_metrics(W, order, s2i=None, macro=None, incept=None):\n'
    helper = '''# SPLIT_EVENT_CONFIRM_V1
SPLIT_CONFIRM_WINDOW_DAYS = 5
SPLIT_HARD_ANOMALY = 10.0  # unmatched one-day move >1000%; broken-history guard, not split suspicion


def _confirmed_split_events(candidates):
    """Confirm >150% jump candidates with an actual Yahoo split/reverse-split action.

    A price jump alone is never classified as a split. Lookup failure is fail-open for
    split classification; the separate >1000% hard anomaly guard still catches obviously
    broken histories such as legacy adjustment ghosts.
    """
    if not candidates or not _net_ok():
        return set()
    try:
        import yfinance as yf
    except Exception as e:
        sys.stderr.write(f"[split] yfinance unavailable: {type(e).__name__}\\n")
        return set()
    confirmed = set()
    for ticker, jump_date in candidates.items():
        try:
            jd = pd.Timestamp(jump_date)
            if getattr(jd, "tzinfo", None) is not None:
                jd = jd.tz_localize(None)
            jd = jd.normalize()
            start = (jd - pd.Timedelta(days=SPLIT_CONFIRM_WINDOW_DAYS + 2)).strftime("%Y-%m-%d")
            end = (jd + pd.Timedelta(days=SPLIT_CONFIRM_WINDOW_DAYS + 3)).strftime("%Y-%m-%d")
            hist = yf.Ticker(str(ticker)).history(
                start=start, end=end, auto_adjust=False, actions=True
            )
            if hist is None or hist.empty or "Stock Splits" not in hist.columns:
                continue
            splits = pd.to_numeric(hist["Stock Splits"], errors="coerce").fillna(0.0)
            for event_idx, ratio in splits[splits != 0].items():
                ed = pd.Timestamp(event_idx)
                if getattr(ed, "tzinfo", None) is not None:
                    ed = ed.tz_localize(None)
                if abs((ed.normalize() - jd).days) <= SPLIT_CONFIRM_WINDOW_DAYS:
                    confirmed.add(str(ticker))
                    break
        except Exception as e:
            sys.stderr.write(f"[split] action lookup failed {ticker}: {type(e).__name__}\\n")
    return confirmed


'''
    if s.count(anchor) != 1:
        raise RuntimeError('compute_metrics anchor missing')
    s = s.replace(anchor, helper + anchor, 1)

replace_once(
    '        maxabs1d = float(c.pct_change(fill_method=None).iloc[-200:].abs().max()) if len(c) >= 2 else np.nan\n',
    '''        _chg200 = c.pct_change(fill_method=None).iloc[-200:].replace([np.inf, -np.inf], np.nan).dropna() if len(c) >= 2 else pd.Series(dtype=float)
        if len(_chg200):
            _abschg200 = _chg200.abs()
            maxabs1d = float(_abschg200.max())
            try:
                maxabs1d_date = pd.Timestamp(_abschg200.idxmax()).strftime("%Y-%m-%d")
            except Exception:
                maxabs1d_date = None
        else:
            maxabs1d = np.nan
            maxabs1d_date = None
''',
    'maxabs jump date',
)

replace_once(
    '            maxabs1d=maxabs1d, lo10=lo10, lo10_prev=lo10_prev, ema21_10ago=ema21_10ago,\n',
    '            maxabs1d=maxabs1d, maxabs1d_date=maxabs1d_date, lo10=lo10, lo10_prev=lo10_prev, ema21_10ago=ema21_10ago,\n',
    'record jump date',
)

old_split = '''    # A1 分割アーティファクト・ガード: 直近200日の単日変化率>150%はスプリット/データ異常のゴースト
    #   （CHRD +80,376% 等）。RSランキングから除外＝RS=NaNで選定・リーダー判定から自然脱落。
    df["split_suspect"] = (df["maxabs1d"] > 1.50).fillna(False)
'''
new_split = '''    # A1 price-event guard: >150% is only a candidate. Exclude as split/reverse-split
    # only when Yahoo corporate actions confirms the event near the jump date.
    _raw_split_jump = (pd.to_numeric(df["maxabs1d"], errors="coerce") > 1.50).fillna(False)
    _split_candidates = {str(t): df.at[t, "maxabs1d_date"] for t in df.index[_raw_split_jump]
                         if df.at[t, "maxabs1d_date"]}
    _confirmed_splits = _confirmed_split_events(_split_candidates)
    df["split_suspect"] = pd.Series(df.index.astype(str).isin(_confirmed_splits), index=df.index, dtype=bool)
    # Keep clear data corruption separate from corporate actions. Genuine 150-1000% moves survive.
    df["data_anomaly"] = ((pd.to_numeric(df["maxabs1d"], errors="coerce") > SPLIT_HARD_ANOMALY)
                          & ~df["split_suspect"]).fillna(False)
    df["price_event_excluded"] = (df["split_suspect"] | df["data_anomaly"]).fillna(False)
'''
replace_once(old_split, new_split, 'split classification')

replace_once(
    '    _pool = ((~df["split_suspect"]) & (df["close"] >= 5) & (df["dvol"] >= DVOL_FLOOR)\n',
    '    _pool = ((~df["price_event_excluded"]) & (df["close"] >= 5) & (df["dvol"] >= DVOL_FLOOR)\n',
    'RS pool event guard',
)
replace_once(
    '        if bool(r.get("split_suspect")) or bool(r.get("excluded_theme")):\n',
    '        if bool(r.get("price_event_excluded", r.get("split_suspect"))) or bool(r.get("excluded_theme")):\n',
    'W30 event guard',
)
replace_once(
    '        mask &= ~m.get("split_suspect", pd.Series(True, index=m.index)).fillna(True)\n',
    '        _event_bad = m.get("price_event_excluded", m.get("split_suspect", pd.Series(True, index=m.index)))\n        mask &= ~_event_bad.fillna(True).astype(bool)\n',
    'setup event guard',
)

old_hist = '''        if "split_suspect" in m.columns:
            bad = [t for t in cols if bool(m.at[t, "split_suspect"])]
            if bad:
                pool.loc[:, bad] = False
'''
new_hist = '''        _bad_col = "price_event_excluded" if "price_event_excluded" in m.columns else "split_suspect"
        if _bad_col in m.columns:
            bad = [t for t in cols if bool(m.at[t, _bad_col])]
            if bad:
                pool.loc[:, bad] = False
'''
replace_once(old_hist, new_hist, 'historical RS event guard')

replace_once(
    '    "liq": "流動性外", "price": "低位株", "split": "分割疑い",\n',
    '    "liq": "流動性外", "price": "低位株", "split": "分割/併合確認", "data": "価格データ異常",\n',
    'RS off labels',
)
replace_once(
    '    "split": "直近200日に単日±150%超の変化。分割/データ異常としてRSから除外",\n',
    '    "split": "単日±150%超の変化日にYahoo corporate actionの分割/併合イベントを確認。RSから除外",\n    "data": "分割/併合イベント未確認だが単日+1000%超。価格履歴破損として別枠で除外",\n',
    'RS off help',
)
replace_once(
    '    if bool(r.get("split_suspect")):\n        return "split"\n',
    '    if bool(r.get("split_suspect")):\n        return "split"\n    if bool(r.get("data_anomaly")):\n        return "data"\n',
    'RS off reason',
)

s = s.replace('("分割サスペクト", (f\'{q.get("split_suspect")}銘柄 除外\' if q.get("split_suspect") else "0（クリーン）")),',
              '("分割/併合確認", (f\'{q.get("split_suspect")}銘柄 除外\' if q.get("split_suspect") else "0（クリーン）")),', 1)
s = s.replace('("RSプール幅", f\'{q.get("rs_pool", 0)}銘柄（非サスペクト×$5×$10M内で順位付け）\'),',
              '("RSプール幅", f\'{q.get("rs_pool", 0)}銘柄（価格イベント正常×$5×$10M内で順位付け）\'),', 1)
s = s.replace('分割疑い除外・除外テーマ除外', '確認済み分割/併合・価格データ異常・除外テーマ除外')
s = s.replace('株価・流動性・時価総額・分割疑い・除外テーマを共通適用',
              '株価・流動性・時価総額・確認済み分割/併合・価格データ異常・除外テーマを共通適用')


# -----------------------------------------------------------------------------
# True price-level confluence
# -----------------------------------------------------------------------------
if 'TRUE_PRICE_LEVEL_CONFLUENCE_V1' not in s:
    anchor = '# コンフルエンスは採点しない。\n'
    helper = '''# TRUE_PRICE_LEVEL_CONFLUENCE_V1
def _confluence_overlap(r):
    """Return the densest actual cluster of independent price levels near spot.

    Levels: 21EMA, 50MA, 200MA, pivot, 63/252 VWAP and valid inception VWAP.
    Total cluster span must fit a volatility-aware 1-2% band:
    min(2%, max(1%, 0.25 * ADR20)). Remote levels >10% from spot are ignored.
    """
    def fin(v):
        try:
            return v is not None and np.isfinite(float(v)) and float(v) > 0
        except Exception:
            return False

    close = r.get("close")
    if not fin(close):
        return dict(count=0, labels=[], center=np.nan, dist=np.nan, span=np.nan, tol=np.nan)
    close = float(close)
    try:
        adr = float(r.get("adr"))
        adr = adr if np.isfinite(adr) else np.nan
    except Exception:
        adr = np.nan
    tol = min(0.02, max(0.01, 0.25 * adr)) if np.isfinite(adr) else 0.0125

    levels = [
        ("21EMA", r.get("ema21")),
        ("50MA", r.get("sma50")),
        ("200MA", r.get("sma200")),
        ("ピボット", r.get("pivot40")),
        ("63VWAP", r.get("vwap63")),
        ("252VWAP", r.get("vwap252")),
    ]
    try:
        all_valid = bool(r.get("vwap_all_valid")) and not pd.isna(r.get("vwap_all_valid"))
    except Exception:
        all_valid = False
    if all_valid:
        levels.append(("上場来VWAP", r.get("vwap_all")))

    levels = [(lab, float(px)) for lab, px in levels
              if fin(px) and abs(float(px) / close - 1.0) <= 0.10]
    levels.sort(key=lambda x: x[1])
    best = None
    for i in range(len(levels)):
        for j in range(i, len(levels)):
            group = levels[i:j + 1]
            center = sum(px for _lab, px in group) / len(group)
            span = (group[-1][1] - group[0][1]) / center if center > 0 else np.inf
            if span > tol:
                break
            dist = center / close - 1.0
            key = (len(group), -abs(dist), -span)
            if best is None or key > best[0]:
                best = (key, group, center, dist, span)
    if best is None:
        return dict(count=0, labels=[], center=np.nan, dist=np.nan, span=np.nan, tol=tol)
    _key, group, center, dist, span = best
    return dict(count=len(group), labels=[lab for lab, _px in group],
                center=center, dist=dist, span=span, tol=tol)


'''
    if s.count(anchor) != 1:
        raise RuntimeError('confluence anchor missing')
    s = s.replace(anchor, helper + '# コンフルエンスは「価格レベルの重なり」を主語にする。\n', 1)
    s = s.replace('# 既存指標が示す「セットアップ/発火/確認/位置・警戒」を分類して、\n# 観測値とブール値をそのまま表示する。発注候補の合否には使わない。\n',
                  '# VCP/PP/RS等は文脈情報。重なりの有無そのものを代用しない。発注候補の合否には使わない。\n', 1)

old_ret = '''    return dict(setup=setups, trigger=triggers, confirm=confirms,
                location=locations, warning=warnings,
                has_setup=bool(setups), has_trigger=bool(triggers))
'''
new_ret = '''    overlap = _confluence_overlap(r)
    return dict(setup=setups, trigger=triggers, confirm=confirms,
                location=locations, warning=warnings, overlap=overlap,
                has_setup=bool(setups), has_trigger=bool(triggers))
'''
replace_once(old_ret, new_ret, 'confluence facts return')

pat = re.compile(r'def _cf_tier\(a, r\):\n.*?\n\n\ndef _cf_row\(', re.S)
new_tier = '''def _cf_tier(a, r):
    """Tier by literal overlap density and the cluster's distance from spot."""
    ov = a.get("overlap") or {}
    count = int(ov.get("count") or 0)
    dist = abs(float(ov.get("dist")) * 100) if _cf_fin(ov.get("dist")) else 999.0
    fresh = _cf_fresh_days(a, r)
    if count >= 3 and dist <= 3:
        return 0, (fresh if fresh is not None else 99), dist
    if (count >= 2 and dist <= 3) or (count >= 3 and dist <= 6):
        return 1, (fresh if fresh is not None else 99), dist
    if count >= 2 and dist <= 6:
        return 2, (fresh if fresh is not None else 99), dist
    return 3, (fresh if fresh is not None else 99), dist


def _cf_row('''
s, n = pat.subn(new_tier, s, count=1)
if n != 1:
    raise RuntimeError(f'cf tier replace count={n}')

old_flow = '''    flow = ""
    if a["setup"]:
        flow += '<span>' + _h(" / ".join(a["setup"])) + '</span>'
    if a["setup"] and a["trigger"]:
        flow += '<i>→</i>'
    if a["trigger"]:
        flow += '<b class="pos">' + _h(" / ".join(a["trigger"])) + '</b>'
    if not flow:
        flow = '<span class="mut">—</span>'
'''
new_flow = '''    flow = ""
    _ov = a.get("overlap") or {}
    _ov_n = int(_ov.get("count") or 0)
    if _ov_n >= 2:
        _ov_dist = float(_ov.get("dist")) * 100 if _cf_fin(_ov.get("dist")) else 999.0
        _ov_span = float(_ov.get("span")) * 100 if _cf_fin(_ov.get("span")) else 999.0
        _ov_txt = f"{_ov_n}重: " + " + ".join(_ov.get("labels") or []) + f" ({_ov_dist:+.1f}%, 幅{_ov_span:.1f}%)"
        flow += '<b class="cfnear">' + _h(_ov_txt) + '</b>'
    if a["setup"]:
        if flow:
            flow += '<i>＋</i>'
        flow += '<span>' + _h(" / ".join(a["setup"])) + '</span>'
    if a["trigger"]:
        if flow:
            flow += '<i>→</i>'
        flow += '<b class="pos">' + _h(" / ".join(a["trigger"])) + '</b>'
    if not flow:
        flow = '<span class="mut">—</span>'
'''
replace_once(old_flow, new_flow, 'confluence row flow')

old_build = '''        a = _confluence_facts(r, ne.get(t))
        if not (a["setup"] or a["trigger"] or a["location"]):
            continue
        order, fresh, pdist = _cf_tier(a, r)
        # 並びは「執行の近さ」。第1キー=発火の鮮度、第2キー=ピボットまでの距離。
        # どちらも事実の量で、重み付けや総合点は使っていない。
        buckets[order].append(((fresh, round(pdist, 2), -float(r.get("rs189") or 0)), t, r, a))
'''
new_build = '''        a = _confluence_facts(r, ne.get(t))
        ov = a.get("overlap") or {}
        ov_n = int(ov.get("count") or 0)
        ov_dist = abs(float(ov.get("dist"))) if _cf_fin(ov.get("dist")) else 999.0
        if ov_n < 2 or ov_dist > 0.08:
            continue
        order, fresh, cdist = _cf_tier(a, r)
        ov_span = float(ov.get("span")) if _cf_fin(ov.get("span")) else 999.0
        # Literal confluence first. Trigger freshness and RS are tie-break/context only.
        buckets[order].append(((-ov_n, round(cdist, 2), round(ov_span, 5), fresh,
                                -float(r.get("rs189") or 0)), t, r, a))
'''
replace_once(old_build, new_build, 'confluence build filter')
replace_once(
    '        items = sorted(buckets[order], key=lambda x: (x[0], x[1]))\n',
    '        items = sorted(buckets[order], key=lambda x: x[0])\n',
    'confluence sort',
)

labels = {
    0: ('A 3重以上・現値±3%', 'True'),
    1: ('B 2重近接 / 3重やや遠い', 'True'),
    2: ('C 2重・現値±6%', 'False'),
    3: ('D 2重・現値±8%（監視）', 'False'),
}
for tier, (label, opened) in labels.items():
    lp = re.compile(rf'\({tier},\s*"[ABCD][^"]*",\s*(True|False)\),')
    s, n = lp.subn(f'({tier}, "{label}", {opened}),', s, count=1)
    if n != 1:
        raise RuntimeError(f'confluence section {tier} replace count={n}')

# Replace the explanatory block without depending on its middle text.
start_marker = '    det = (\'<details class="cfdet"><summary>並べ方と列の意味</summary>\'\n'
end_marker = "           '</div></details>')\n"
start = s.find(start_marker)
if start < 0:
    raise RuntimeError('confluence detail start missing')
end = s.find(end_marker, start)
if end < 0:
    raise RuntimeError('confluence detail end missing')
end += len(end_marker)
new_det = '''    det = ('<details class="cfdet"><summary>重なり判定と列の意味</summary>'
           '<div class="cflg">'
           'コンフルエンス＝価格レベルの実際の重なり。21EMA・50MA・200MA・ピボット・63/252VWAP・上場来VWAPから、'
           '現値±10%内の独立レベルを集め、ADR連動の幅 min(2%, max(1%, 0.25×ADR)) 内で2本以上重なる場合だけ表示。<br>'
           '並びは①重なり本数（多い順）→②重なり中心の現値からの距離→③帯の狭さ。発火鮮度とRSは文脈のみ。<br>'
           'piv=ピボットまでの距離／50MAσ=50日線からのATR距離／U/D=20日の上昇下降出来高比／'
           'ADR=1日の平均値幅／損切まで=下にある損切候補のうち最も近いものまでの距離。'
           '</div></details>')
'''
s = s[:start] + new_det + s[end:]

s = s.replace(
    'f\'<div class="sub">RS189≥{min_rs}の該当なし。{det}</div>\'',
    'f\'<div class="sub">RS189≥{min_rs}の中に、2本以上の価格レベルが実際に重なる銘柄なし。{det}</div>\'',
    1,
)
old_sub = '''            f'<div class="sub">RS189≥{min_rs}。発火の新しい順・ピボットに近い順。pivは±3%以内を強調、'
            f'-15%より下を淡色表示（距離表示のみ・合否ではない）。{det}</div>'
'''
new_sub = '''            f'<div class="sub">RS189≥{min_rs}は候補母集団の条件のみ。表示条件は2本以上の価格レベル重なり。'
            f'重なり本数→中心距離→帯の狭さの順。VCP/PP/RS/ブレイクは文脈で、重なりの代用にはしない。{det}</div>'
'''
replace_once(old_sub, new_sub, 'confluence description')

p.write_text(s, encoding='utf-8')
print('PATCH_OK')
