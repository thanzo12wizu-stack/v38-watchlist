from pathlib import Path

SRC = Path("build_dashboard.py")
s = SRC.read_text(encoding="utf-8")


def replace_exact(old: str, new: str, count: int = 1, label: str = "patch") -> None:
    global s
    found = s.count(old)
    if found != count:
        raise SystemExit(f"{label}: expected {count} occurrence(s), found {found}")
    s = s.replace(old, new)


# ---------------------------------------------------------------------------
# Constants only. The confirmed 57-ETF universe and 12 Raw metrics stay intact.
replace_exact(
    '''MC_MARKET_TICKERS = list(dict.fromkeys(MC_BROAD_ETFS + MC_SECTOR_ETFS + MC_INDUSTRY_ETFS))
assert len(MC_MARKET_TICKERS) == 57
MACRO_TICKERS = list(dict.fromkeys(MACRO_TICKERS + MC_MARKET_TICKERS))''',
    '''MC_MARKET_TICKERS = list(dict.fromkeys(MC_BROAD_ETFS + MC_SECTOR_ETFS + MC_INDUSTRY_ETFS))
assert len(MC_MARKET_TICKERS) == 57
MC_BASELINE_BARS = 252 * 15
MC_LONG_LOOKBACK_YEARS = 21
# Historical occupancy is display-only context from the audited MC15 series.
# It is NEVER an input to the score.
MC_OCCUPANCY_LONG = ("2008–2026", 52.4, 11.9, 35.6)
MC_OCCUPANCY_50ETF = ("2013–2026・50ETF以上", 57.1, 12.4, 30.5)
MACRO_TICKERS = list(dict.fromkeys(MACRO_TICKERS + MC_MARKET_TICKERS))''',
    label="constants",
)


# ---------------------------------------------------------------------------
# Dedicated long-history fetch. It is called only by Market Conditions and does
# not lengthen the shared macro series used by any other dashboard logic.
helper = r'''
def _fetch_mc_long_history(asof=None):
    """Dedicated adjusted daily history for the fixed 57-ETF MC universe.

    MC needs the previous 3780 sessions plus warm-up for its 1Y/200SMA/52W legs.
    Missing or not-yet-listed ETFs stay missing; they are never zero-filled.
    """
    if not _net_ok():
        return {}
    try:
        import yfinance as yf
    except Exception as exc:
        sys.stderr.write("[mc15] yfinance import failed: %s\n" % type(exc).__name__)
        return {}

    try:
        _end_ts = pd.Timestamp(asof) if asof is not None else pd.Timestamp.utcnow()
        try:
            _end_ts = _end_ts.tz_localize(None)
        except TypeError:
            _end_ts = _end_ts.tz_convert(None)
        _end_ts = _end_ts.normalize()
        _start = (_end_ts - pd.DateOffset(years=MC_LONG_LOOKBACK_YEARS)).strftime("%Y-%m-%d")
        _end = (_end_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d") if asof is not None else None
    except Exception:
        _start, _end, _end_ts = "2005-01-01", None, None

    out = {}
    try:
        raw = yf.download(
            MC_MARKET_TICKERS, start=_start, end=_end, progress=False,
            auto_adjust=True, group_by="ticker", threads=True,
        )
        out.update(_extract(raw, MC_MARKET_TICKERS, minbars=30))
    except Exception as exc:
        sys.stderr.write("[mc15] batch history failed: %s\n" % type(exc).__name__)

    missing = [t for t in MC_MARKET_TICKERS if t not in out]
    for t in missing:
        try:
            hist = yf.Ticker(t).history(start=_start, end=_end, auto_adjust=True)
            got = _extract(hist, [t], minbars=30).get(t)
            if got is not None and len(got):
                out[t] = got
        except Exception as exc:
            sys.stderr.write("[mc15] %s history fallback failed: %s\n" % (t, type(exc).__name__))

    # Defensive as-of cut even when Yahoo returns an unexpected latest row.
    if _end_ts is not None:
        clean = {}
        for t, frame in out.items():
            try:
                f = frame.copy()
                idx = pd.to_datetime(f.index)
                try:
                    idx = idx.tz_localize(None)
                except TypeError:
                    idx = idx.tz_convert(None)
                f.index = idx
                f = f[f.index <= _end_ts]
                if len(f):
                    clean[t] = f
            except Exception:
                continue
        out = clean

    if out:
        try:
            first = min(pd.Timestamp(v.index.min()) for v in out.values() if len(v))
            last = max(pd.Timestamp(v.index.max()) for v in out.values() if len(v))
            sys.stderr.write(
                "[mc15] long history: %d/%d ETFs, %s..%s\n"
                % (len(out), len(MC_MARKET_TICKERS), first.date(), last.date())
            )
        except Exception:
            sys.stderr.write(
                "[mc15] long history: %d/%d ETFs\n"
                % (len(out), len(MC_MARKET_TICKERS))
            )
    return out


'''
replace_exact(
    "def _mc_frame_from_macro(macro):\n",
    helper + "def _mc_frame_from_macro(macro):\n",
    label="long_history_helper",
)


# ---------------------------------------------------------------------------
# Final-score calibration helpers.
replace_exact(
    '''def _mc_linear(series, lo, hi):
    return ((pd.to_numeric(series, errors="coerce") - lo) / (hi - lo)).clip(0.0, 1.0) * 100.0


def mri_frame(macro, W=None):''',
    '''def _mc_linear(series, lo, hi):
    return ((pd.to_numeric(series, errors="coerce") - lo) / (hi - lo)).clip(0.0, 1.0) * 100.0


def _mc_z_to_temperature(z):
    """Symmetric map: z=0→50, ±1σ→75/25, ±2σ→90/10."""
    z = pd.to_numeric(z, errors="coerce")
    return 100.0 / (1.0 + np.exp(-np.log(3.0) * z))


def _mc_temperature_from_raw(raw_score):
    """Normalize Raw MC against the PREVIOUS 3780 trading observations only."""
    rs = pd.to_numeric(raw_score, errors="coerce")
    base = rs.shift(1)  # current session never enters its own reference distribution
    mean15 = base.rolling(MC_BASELINE_BARS, min_periods=MC_BASELINE_BARS).mean()
    sd15 = base.rolling(MC_BASELINE_BARS, min_periods=MC_BASELINE_BARS).std(ddof=0)
    z15 = (rs - mean15) / sd15.replace(0.0, np.nan)
    return _mc_z_to_temperature(z15), mean15, sd15, z15


def mri_frame(macro, W=None):''',
    label="normalization_helpers",
)

replace_exact(
    '''    """Market Conditions v4: 57 ETFs × 12 metrics, fully equal weighted.

    No historical percentile recentering and no one-sided deterioration penalty,
    floor or guard. Each 0-100 component has a literal neutral midpoint and the
    final arithmetic mean preserves directional symmetry. EMA2 is smoothing only.
    """''',
    '''    """Market Conditions v5: 57 ETFs × 12 equal metrics → EMA2 Raw → MC15.

    The confirmed v4 Raw construction stays unchanged. The displayed 0–100 value
    is Raw's deviation from the PREVIOUS 3780 trading-day mean/std, mapped by a
    symmetric logistic curve (50=15Y mean, 75/25=±1σ, 90/10=±2σ). VIX, percentile
    ranking, deterioration penalties and ETF-family reweighting remain excluded.
    """''',
    label="docstring",
)

# Only MC gets long history. Shared macro remains unchanged.
replace_exact(
    '''    c = _mc_frame_from_macro(macro)
    if c.empty:''',
    '''    c = _mc_frame_from_macro(macro)
    _need_long = len(c.index) < (MC_BASELINE_BARS + 260)
    if _need_long and _net_ok():
        _mc_asof = None
        try:
            if isinstance(W, dict) and hasattr(W.get("Close"), "index") and len(W["Close"].index):
                _mc_asof = pd.Timestamp(W["Close"].index[-1])
        except Exception:
            _mc_asof = None
        _mc_long = _fetch_mc_long_history(asof=_mc_asof)
        if len(_mc_long) < 50:
            raise RuntimeError(
                "Market Conditions: long-history coverage too low (%d/%d ETFs)"
                % (len(_mc_long), len(MC_MARKET_TICKERS))
            )
        c = _mc_frame_from_macro(_mc_long)
    if c.empty:''',
    label="isolated_long_history_use",
)

replace_exact(
    '''    if c.empty:
        idx = next((d.index for d in macro.values() if hasattr(d, "index") and len(d.index)), pd.DatetimeIndex([pd.Timestamp.today().normalize()]))
        z = pd.Series(50.0, index=idx, dtype=float)''',
    '''    if c.empty:
        if "--selftest" not in sys.argv:
            raise RuntimeError("Market Conditions: 57ETF price frame is empty")
        idx = next((d.index for d in macro.values() if hasattr(d, "index") and len(d.index)), pd.DatetimeIndex([pd.Timestamp.today().normalize()]))
        z = pd.Series(50.0, index=idx, dtype=float)''',
    label="empty_fail_closed",
)

replace_exact(
    '''    raw = pd.concat([p[k] for k in score_keys], axis=1).mean(axis=1, skipna=True)
    score = raw.ewm(span=2,adjust=False).mean()

    # Four display-only summaries; their weights match the number of equal metrics.''',
    '''    raw = pd.concat([p[k] for k in score_keys], axis=1).mean(axis=1, skipna=True)
    raw_score = raw.ewm(span=2,adjust=False).mean()
    temp, mean15, sd15, z15 = _mc_temperature_from_raw(raw_score)
    _raw_clean = raw_score.dropna()
    _latest_idx = _raw_clean.index[-1] if len(_raw_clean) else None
    _latest_temp = temp.get(_latest_idx, np.nan) if _latest_idx is not None else np.nan
    if _latest_idx is not None and np.isfinite(float(_latest_temp)):
        score = temp
    elif "--selftest" in sys.argv:
        # Offline fixtures are deliberately short. Keep rendering testable there;
        # dedicated regression tests below fingerprint the production MC15 transform.
        score = raw_score
    else:
        raise RuntimeError(
            "Market Conditions: 15Y baseline unavailable at latest session "
            "(need 3780 prior trading observations)"
        )

    # Four display-only summaries; their weights match the number of equal metrics.''',
    label="raw_to_temperature",
)

replace_exact(
    '''    vals["breadth_level"] = breadth_level; vals["breadth_delta10"] = breadth_delta10
    vals["mc_coverage"] = coverage
    for k,v in p.items(): vals[k] = v''',
    '''    vals["breadth_level"] = breadth_level; vals["breadth_delta10"] = breadth_delta10
    vals["mc_coverage"] = coverage
    vals["mc_raw"] = raw_score
    vals["mc_mean15"] = mean15
    vals["mc_sd15"] = sd15
    vals["mc_z15"] = z15
    for k,v in p.items(): vals[k] = v''',
    label="telemetry",
)

replace_exact(
    '''    return dict(cur=cur, hl=hl, slope=slope_dir, bear_n=bear_n, bear_flags=bear_flags,
                peak=peak, drop=drop, hi20=hi20,
                breadth_delta10=breadth_delta10, breadth_arrow=breadth_arrow,
                components=components, mc_coverage=mc_coverage)''',
    '''    def _last_num(key):
        try:
            _v = float(last.get(key, np.nan))
            return _v if np.isfinite(_v) else None
        except Exception:
            return None
    recent_mri = {
        d.strftime("%Y-%m-%d"): float(v)
        for d, v in clean.tail(260).items() if np.isfinite(float(v))
    }
    return dict(cur=cur, hl=hl, slope=slope_dir, bear_n=bear_n, bear_flags=bear_flags,
                peak=peak, drop=drop, hi20=hi20,
                breadth_delta10=breadth_delta10, breadth_arrow=breadth_arrow,
                components=components, mc_coverage=mc_coverage,
                mc_raw=_last_num("mc_raw"), mc_mean15=_last_num("mc_mean15"),
                mc_sd15=_last_num("mc_sd15"), mc_z15=_last_num("mc_z15"),
                recent_mri=recent_mri)''',
    label="auxiliary_telemetry",
)


# ---------------------------------------------------------------------------
# Band text uses the current already-smoothed MC value; slope/peak logic stays as-is.
band_old = 'mri_band(aux["hl"])'
if s.count(band_old) != 3:
    raise SystemExit(f"band_current: expected 3 occurrences, found {s.count(band_old)}")
s = s.replace(band_old, 'mri_band(aux["cur"])')
replace_exact(
    'band_lab = mri_band(hl)[0].replace("（過熱・反落注意⚠）", "")',
    'band_lab = mri_band(last)[0].replace("（過熱・反落注意⚠）", "")',
    label="chart_band_current",
)

# Preserve the existing colors/layout; only align zone/grid boundaries with mri_band().
replace_exact(
    '''    zones = [(0, 25, "#ef4444"), (25, 40, "#f97316"), (40, 55, "#64748b"),
             (55, 70, "#22c55e"), (70, 100, "#16a34a")]''',
    '''    zones = [(0, 20, "#ef4444"), (20, 45, "#f97316"), (45, 55, "#64748b"),
             (55, 80, "#22c55e"), (80, 100, "#16a34a")]''',
    label="chart_zones",
)
replace_exact(
    'for g in (25, 40, 55, 70) if lo <= g <= hi)',
    'for g in (20, 35, 45, 55, 65, 80) if lo <= g <= hi)',
    label="chart_grid",
)


# ---------------------------------------------------------------------------
# Existing tap/fold detail only: calibration line + audited occupancy ratios.
replace_exact(
    '''    _bd_rows.append('<div class="mgrp">コンテキスト（MC点数には不算入）</div>')''',
    '''    _bd_rows.append('<div class="mgrp">15年基準（最終MCへの変換）</div>')
    _raw_now, _mu_now, _sd_now, _z_now = (
        aux.get("mc_raw"), aux.get("mc_mean15"), aux.get("mc_sd15"), aux.get("mc_z15")
    )
    try:
        _cal_ok = all(v is not None and np.isfinite(float(v)) for v in (_raw_now, _mu_now, _sd_now, _z_now))
    except Exception:
        _cal_ok = False
    if _cal_ok:
        _bd_rows.append(
            f'<div class="mnote">Raw {float(_raw_now):.1f} → 15年平均 {float(_mu_now):.1f} / σ {float(_sd_now):.1f} '
            f'→ Z {float(_z_now):+.2f}σ → MC {aux["cur"]:.1f}</div>'
        )
    else:
        _bd_rows.append('<div class="mnote">15年基準は長期履歴不足のテスト環境では表示しません。</div>')
    _op, _ob, _on, _or = MC_OCCUPANCY_LONG
    _op2, _ob2, _on2, _or2 = MC_OCCUPANCY_50ETF
    _bd_rows.append(
        f'<div class="mnote">長期滞在比率（検証値・scoreには不算入）: {_op} Bull(55+) {_ob:.1f}% / '
        f'Neutral(45–55) {_on:.1f}% / Bear(&lt;45) {_or:.1f}%。'
        f'{_op2}: Bull {_ob2:.1f}% / Neutral {_on2:.1f}% / Bear {_or2:.1f}%。</div>'
    )
    _bd_rows.append('<div class="mgrp">コンテキスト（MC点数には不算入）</div>')''',
    label="folded_context",
)

replace_exact(
    '''              + '<div class="mnote">各指標は0–100、12指標を完全等加重。右端は各指標の総合点への寄与。Breadth 10日変化はscore外。もう一度タップで閉じる ▴</div></div>')''',
    '''              + '<div class="mnote">Rawは57ETF×12指標を完全等加重→EMA2。右端は各指標のRawへの寄与。最終MCはRawを直前3780営業日（当日除外）の平均・母標準偏差でZ化し、50=15年平均 / 75=+1σ / 25=−1σ / 90=+2σ / 10=−2σとなるよう0–100へ変換。Breadth 10日変化はscore外。もう一度タップで閉じる ▴</div></div>')''',
    label="folded_note",
)


# ---------------------------------------------------------------------------
# Migration: old daily-log/state MC values must never be compared with the new scale.
replace_exact(
    'def _build_log_csv_content(path, asof_date, color, aux, senti, picks):',
    'def _build_log_csv_content(path, asof_date, color, aux, senti, picks, mri_history=None):',
    label="log_signature",
)
replace_exact(
    '''    if os.path.exists(path):
        rows = [ln for ln in open(path).read().splitlines()
                if ln and not ln.startswith(today + ",") and not ln.startswith("date,")]
    line = ",".join([today, color or "",  f"{aux['cur']:.1f}", str(aux["bear_n"]),''',
    '''    if os.path.exists(path):
        rows = [ln for ln in open(path).read().splitlines()
                if ln and not ln.startswith(today + ",") and not ln.startswith("date,")]
    if mri_history is not None and rows:
        try:
            _hist = pd.to_numeric(mri_history, errors="coerce").dropna()
            _hmap = {d.strftime("%Y-%m-%d"): float(v) for d, v in _hist.items() if np.isfinite(float(v))}
            _migrated = []
            for _ln in rows:
                _parts = _ln.split(",", 5)
                if len(_parts) >= 3 and _parts[0] in _hmap:
                    _parts[2] = f"{_hmap[_parts[0]]:.1f}"
                _migrated.append(",".join(_parts))
            rows = _migrated
        except Exception as _e:
            sys.stderr.write("[mc15] daily_log MRI migration skipped: %r\n" % (repr(_e)[:100],))
    line = ",".join([today, color or "",  f"{aux['cur']:.1f}", str(aux["bear_n"]),''',
    label="log_migration",
)
replace_exact(
    '''                asof_bar.date(), sar[0], aux, mkt["senti"], picks)''',
    '''                asof_bar.date(), sar[0], aux, mkt["senti"], picks, mri_history=mri)''',
    label="production_log_call",
)

replace_exact(
    '''    try:
        dm = float(aux["cur"]) - float(base.get("mri", aux["cur"]))
        if abs(dm) >= 3:
            ch.append(f'Market Conditions <b>{base.get("mri"):.0f}→{aux["cur"]:.0f}</b>（{dm:+.0f}）')
    except Exception:
        pass''',
    '''    try:
        _base_mri = base.get("mri", aux["cur"])
        _recalc_prev = (aux.get("recent_mri") or {}).get(str(base.get("date") or ""))
        if _recalc_prev is not None and np.isfinite(float(_recalc_prev)):
            _base_mri = float(_recalc_prev)
        dm = float(aux["cur"]) - float(_base_mri)
        if abs(dm) >= 3:
            ch.append(f'Market Conditions <b>{float(_base_mri):.0f}→{aux["cur"]:.0f}</b>（{dm:+.0f}）')
    except Exception:
        pass''',
    label="changelog_migration",
)

replace_exact(
    '''    _prevday = _older_summary(_prev_state)
    # state/log/Webhookはここでは実行しない。selftest成功→両HTML出力成功の後に production_run のときだけcommitする。''',
    '''    _prevday = _older_summary(_prev_state)
    if isinstance(_prevday, dict) and _prevday.get("date"):
        try:
            _recalc_pd = (aux.get("recent_mri") or {}).get(str(_prevday.get("date")))
            if _recalc_pd is not None and np.isfinite(float(_recalc_pd)):
                _prevday = dict(_prevday)
                _prevday["mri"] = round(float(_recalc_pd), 1)
        except Exception:
            pass
    # state/log/Webhookはここでは実行しない。selftest成功→両HTML出力成功の後に production_run のときだけcommitする。''',
    label="prevday_migration",
)

SRC.write_text(s, encoding="utf-8")


# ---------------------------------------------------------------------------
# Regression fingerprints.
test_path = Path("tests/test_dashboard_build_regressions.py")
ts = test_path.read_text(encoding="utf-8")
if "def test_market_condition_15y_temperature_contract():" not in ts:
    ts += '''


def test_market_condition_15y_temperature_contract():
    z = pd.Series([-2.0, -1.0, 0.0, 1.0, 2.0])
    got = dashboard._mc_z_to_temperature(z).to_numpy()
    assert np.allclose(got, [10.0, 25.0, 50.0, 75.0, 90.0])
    assert dashboard.MC_BASELINE_BARS == 252 * 15

    raw = pd.Series(np.arange(dashboard.MC_BASELINE_BARS + 2, dtype=float))
    temp, mean15, sd15, z15 = dashboard._mc_temperature_from_raw(raw)
    i = dashboard.MC_BASELINE_BARS
    expected = raw.iloc[:i]
    assert np.isclose(mean15.iloc[i], expected.mean())
    assert np.isclose(sd15.iloc[i], expected.std(ddof=0))
    assert np.isclose(z15.iloc[i], (raw.iloc[i] - expected.mean()) / expected.std(ddof=0))
    assert np.isfinite(temp.iloc[i])


def test_market_condition_fold_contains_occupancy_context():
    source = Path(dashboard.__file__).read_text(encoding="utf-8")
    assert "長期滞在比率（検証値・scoreには不算入）" in source
    assert "右端は各指標のRawへの寄与" in source
    assert 'mri_band(aux["cur"])' in source
'''
    test_path.write_text(ts, encoding="utf-8")

print("MC15 patch prepared")
