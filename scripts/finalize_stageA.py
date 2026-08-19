from pathlib import Path
import re

p = Path('build_dashboard.py')
s = p.read_text(encoding='utf-8')

# -----------------------------------------------------------------------------
# 1) Master Universe: common stocks + DR/ADR/registry shares, with structured
#    exclusion of preferred/warrant/unit/right/pre-IPO securities.
#    This intentionally removes the old type=stock-only blind spot (ASML/ARM/SKHY).
# -----------------------------------------------------------------------------
pat = re.compile(r'def fetch_universe_rows\(\):\n.*?\n\n\ndef refresh_universe_csv', re.S)
new = r'''def fetch_universe_rows():
    """TradingView stock screenerからMaster Universeを取得。

    普通株に加えてDR/ADR/Registry Shareを含める。Preferred/Warrant/Unit/Right等は
    typespecsを主判定、ticker suffixを補助判定としてここで除外する。自由文名称は
    除外判定に使わない。total_revenueは選定適格性用のTTM売上スナップショット。
    """
    if not _net_ok():
        return []

    import urllib.request as _ur
    import re as _re

    base_cols = ["name", "description", "close", "change", "volume", "market_cap_basic",
                 "sector", "industry", "exchange", "type", "typespecs"]
    revenue_col = "total_revenue"

    def _scan_type(payload_type, with_revenue=True):
        cols = list(base_cols) + ([revenue_col] if with_revenue else [])
        flt = [{"left": "type", "operation": "equal", "right": payload_type},
               {"left": "exchange", "operation": "in_range", "right": UNIVERSE_EXCHANGES},
               {"left": "market_cap_basic", "operation": "egreater", "right": UNIVERSE_MIN_MCAP},
               {"left": "close", "operation": "egreater", "right": UNIVERSE_MIN_PRICE}]
        out = []
        for start in range(0, 20000, 1000):
            body = {"filter": flt, "columns": cols,
                    "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
                    "range": [start, start + 1000]}
            req = _ur.Request(_TV_SCAN, data=json.dumps(body).encode("utf-8"),
                              headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(req, timeout=40) as fh:
                obj = json.loads(fh.read().decode("utf-8"))
            data = obj.get("data") or []
            for item in data:
                d = item.get("d") or []
                if len(d) < len(cols):
                    continue
                rec = dict(zip(cols, d))
                if revenue_col not in rec:
                    rec[revenue_col] = None
                out.append(rec)
            if len(data) < 1000:
                break
        return out

    raw = []
    for _typ in ("stock", "dr"):
        try:
            raw.extend(_scan_type(_typ, with_revenue=True))
        except Exception as _e:
            # Fundamental column outage must not break the universe. Retry without it.
            sys.stderr.write("[universe] total_revenue付き%s scan失敗(%s) -> revenue無しで再試行\n"
                             % (_typ, type(_e).__name__))
            try:
                raw.extend(_scan_type(_typ, with_revenue=False))
            except Exception as _e2:
                sys.stderr.write("[universe] %s scan失敗: %s\n" % (_typ, type(_e2).__name__))

    def _tokens(v):
        vals = v if isinstance(v, (list, tuple)) else ([] if v is None else [v])
        z = []
        for part in vals:
            z.extend(x for x in _re.split(r"[^a-z0-9]+", str(part).lower()) if x)
        return set(z)

    def _ticker_bad(t):
        t = str(t or "").strip().upper()
        rules = (
            (r"/P[A-Z0-9]*$", "preferred_slash"),
            (r"\.PR[A-Z0-9]*$", "preferred_dot_pr"),
            (r"-P[A-Z0-9]*$", "preferred_dash"),
            (r"[./-]U$", "unit_suffix"),
            (r"[./-](WT|WTS|WS)$", "warrant_suffix"),
            (r"[./-](RT|RTS)$", "rights_suffix"),
        )
        for rx, reason in rules:
            if _re.search(rx, t):
                return reason
        return None

    bad_specs = {"preferred", "preference", "warrant", "warrants", "unit", "units",
                 "right", "rights", "pre", "ipo"}
    kept = []
    removed = []
    seen = set()
    for rec in raw:
        t = str(rec.get("name") or "").strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        typ = str(rec.get("type") or "").lower()
        toks = _tokens(rec.get("typespecs"))
        subtype_bad = sorted(toks & bad_specs)
        # 'pre-ipo' is tokenized as pre + ipo; require both together.
        if "pre" in subtype_bad and "ipo" not in subtype_bad:
            subtype_bad.remove("pre")
        if "ipo" in subtype_bad and "pre" not in toks:
            subtype_bad.remove("ipo")
        reason = subtype_bad[0] if subtype_bad else _ticker_bad(t)
        if typ not in ("stock", "dr"):
            reason = reason or ("type_" + typ if typ else "unknown_type")
        if reason:
            removed.append((t, reason))
            continue
        dvol = 0.0
        try:
            dvol = float(rec.get("close") or 0) * float(rec.get("volume") or 0)
        except Exception:
            pass
        kept.append({
            "シンボル": t,
            "名称": rec.get("description") or "",
            "価格": rec.get("close"),
            "価格変動 %, 1日": rec.get("change"),
            "出来高, 1日": rec.get("volume"),
            "時価総額": rec.get("market_cap_basic"),
            "セクター": rec.get("sector") or "",
            "業種": rec.get("industry") or "",
            "取引所": rec.get("exchange") or "",
            "証券種別": typ,
            "証券サブタイプ": ",".join(sorted(_tokens(rec.get("typespecs")))),
            "売上高TTM": rec.get(revenue_col),
            "_dvol": dvol,
        })

    # Ordinary share-class duplicates are a separate issue from security type.
    # Only explicit Class A/B/etc groups are collapsed; free-text fuzzy matching alone
    # is never enough. Keep the most liquid class so one issuer cannot distort RS twice.
    def _issuer_key(name):
        x = str(name or "").upper()
        x = _re.sub(r"\bCLASS\s+[A-Z0-9]+\b", "", x)
        x = _re.sub(r"\bCOMMON\s+STOCK\b", "", x)
        x = _re.sub(r"\bORDINARY\s+SHARES?\b", "", x)
        x = _re.sub(r"[^A-Z0-9]+", " ", x)
        return " ".join(x.split())

    groups = {}
    for rec in kept:
        if rec.get("証券種別") != "stock":
            continue
        nm = str(rec.get("名称") or "")
        tk = rec["シンボル"]
        explicit = bool(_re.search(r"\bClass\s+[A-Z0-9]+\b", nm, _re.I) or _re.search(r"\.[A-Z]$", tk))
        if not explicit:
            continue
        key = _issuer_key(nm)
        if key:
            groups.setdefault(key, []).append(rec)

    dup_drop = set()
    for key, members in groups.items():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=lambda r: (float(r.get("_dvol") or 0), r["シンボル"]), reverse=True)
        keep = ranked[0]["シンボル"]
        for rec in ranked[1:]:
            dup_drop.add(rec["シンボル"])
            removed.append((rec["シンボル"], "duplicate_share_class_keep_" + keep))

    out = []
    for rec in kept:
        if rec["シンボル"] in dup_drop:
            continue
        rec.pop("_dvol", None)
        out.append(rec)

    for t, reason in sorted(removed):
        sys.stderr.write("[universe] security-excluded %s (%s)\n" % (t, reason))
    sys.stderr.write("[universe] common/DR kept=%d removed=%d\n" % (len(out), len(removed)))
    return out


def refresh_universe_csv'''
s, n = pat.subn(new, s, count=1)
if n != 1:
    raise SystemExit(f'fetch_universe_rows replacement count={n}')

old_cols = '''    cols = ["シンボル", "名称", "価格", "価格変動 %, 1日", "出来高, 1日",
            "時価総額", "セクター", "業種", "取引所"]'''
new_cols = '''    cols = ["シンボル", "名称", "価格", "価格変動 %, 1日", "出来高, 1日",
            "時価総額", "セクター", "業種", "取引所", "証券種別", "証券サブタイプ", "売上高TTM"]'''
if s.count(old_cols) != 1:
    raise SystemExit(f'universe writer cols anchor count={s.count(old_cols)}')
s = s.replace(old_cols, new_cols, 1)

# Correct stale design note: biotech remains in Master Universe.
s = s.replace('※ユニバース段階でも時価総額<$100億のヘルスケアは除外済み(二重の網)。除外株はRS順に表示だけ残す(強さ確認用・買わない)。',
              '※臨床段階バイオもMaster Universeには残す。RS母集団/具体候補からのみ除外し、参考RSと除外理由は表示する。売上不明は通過+警告。')

# -----------------------------------------------------------------------------
# 2) Revenue-based clinical/small-mid biotech selection eligibility.
#    TV TTM revenue is broad/cheap; SEC audit is an automatic fallback when present.
#    Missing revenue is PASS + visible flag. No ticker override list.
# -----------------------------------------------------------------------------
anchor = 'BIO_KEEP_MCAP = 1e10          # $10B以上は治験一発で消えない規模とみなして残す\n'
if s.count(anchor) != 1:
    raise SystemExit(f'BIO_KEEP_MCAP anchor count={s.count(anchor)}')
insert = anchor + r'''
BIO_REVENUE_MAX = float(os.environ.get("V38_BIO_REVENUE_MAX", "50000000"))
BIO_REVENUE_AUDIT_JSON = os.environ.get("V38_BIO_REVENUE_JSON", "bio_revenue_audit.json")
_BIO_SELECTION_META = None
_BIO_UNKNOWN_WARNED = set()


def _bio_selection_meta():
    """Master Universe metadata + SEC audit fallback. No manual ticker maintenance."""
    global _BIO_SELECTION_META
    if _BIO_SELECTION_META is not None:
        return _BIO_SELECTION_META
    meta = {}
    try:
        for r in csv.DictReader(open(UNIVERSE_CSV, encoding="utf-8-sig")):
            t = str(r.get("シンボル") or r.get("Symbol") or r.get("Ticker") or "").strip().upper()
            if t:
                meta[t] = {
                    "mcap": r.get("時価総額"),
                    "sector": r.get("セクター") or "",
                    "industry": r.get("業種") or "",
                    "tv_revenue_ttm": r.get("売上高TTM"),
                }
    except Exception:
        pass
    sec_records = {}
    try:
        obj = json.load(open(BIO_REVENUE_AUDIT_JSON, encoding="utf-8"))
        if isinstance(obj, dict) and isinstance(obj.get("records"), dict):
            sec_records = obj["records"]
    except Exception:
        pass
    for t, rec in sec_records.items():
        if isinstance(rec, dict):
            meta.setdefault(str(t).upper(), {})["sec"] = rec
    _BIO_SELECTION_META = meta
    return meta


def _finite_float(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except Exception:
        return None


def _bio_selection_status(t, mcap=None, ind_map=None):
    """Return structural selection eligibility without deleting the symbol.

    Rule: healthcare-like x market cap < $10B x revenue < $50M.
    Revenue precedence: TradingView TTM -> SEC TTM -> explicit SEC latest-FY fallback.
    Missing revenue never excludes: PASS + unknown flag.
    """
    t = str(t or "").strip().upper()
    meta = _bio_selection_meta().get(t, {})
    tv_ind = (ind_map or _bio_industry_map()).get(t)
    sector = str(meta.get("sector") or (tv_ind[0] if isinstance(tv_ind, list) and len(tv_ind) >= 1 else ""))
    industry = str(meta.get("industry") or (tv_ind[1] if isinstance(tv_ind, list) and len(tv_ind) >= 2 else ""))
    txt = (sector + " | " + industry).upper()
    healthcare = any(k in txt for k in ("HEALTH", "BIOTECH", "PHARM", "MEDICAL", "DRUG"))

    mc = _finite_float(mcap)
    if mc is None:
        mc = _finite_float(meta.get("mcap"))
    if not healthcare or mc is None or mc >= BIO_KEEP_MCAP:
        return {"exclude": False, "unknown": False, "revenue": None, "source": "not_applicable"}

    rev = _finite_float(meta.get("tv_revenue_ttm"))
    source = "tradingview_ttm"
    sec = meta.get("sec") if isinstance(meta.get("sec"), dict) else {}
    if rev is None:
        rev = _finite_float(sec.get("revenue_ttm"))
        source = "sec_ttm"
    if rev is None and str(sec.get("status") or "") == "annual_fallback":
        rev = _finite_float(sec.get("revenue_latest_fy"))
        source = "sec_latest_fy"
    if rev is None:
        return {"exclude": False, "unknown": True, "revenue": None, "source": "missing_pass"}
    return {"exclude": bool(rev < BIO_REVENUE_MAX), "unknown": False, "revenue": rev, "source": source}


def _bio_selection_masks(index):
    ex = pd.Series(False, index=index, dtype=bool)
    unk = pd.Series(False, index=index, dtype=bool)
    for t in index:
        st = _bio_selection_status(t)
        ex.at[t] = bool(st.get("exclude"))
        unk.at[t] = bool(st.get("unknown"))
    return ex, unk
'''
s = s.replace(anchor, insert, 1)

pat = re.compile(r'def is_excluded_theme\(t, s2t, mcap=None, ind_map=None\):\n.*?\n    return False\n\nLEADER_RS = 85', re.S)
new = r'''def is_excluded_theme(t, s2t, mcap=None, ind_map=None):
    """Canonical selection exclusion. Master Universe is never changed here."""
    return bool(_bio_selection_status(t, mcap=mcap, ind_map=ind_map).get("exclude"))

LEADER_RS = 85'''
s, n = pat.subn(new, s, count=1)
if n != 1:
    raise SystemExit(f'is_excluded_theme replacement count={n}')

# -----------------------------------------------------------------------------
# 3) RS: exclude structural biotech from the percentile denominator, but retain a
#    reference percentile for the excluded stock itself so it can still be shown.
# -----------------------------------------------------------------------------
old = '''    _pool = (~df["split_suspect"]) & (df["close"] >= 5) & (df["dvol"] >= DVOL_FLOOR)
    df["rs_pool"] = _pool
    def _rk(col):                                         # トレーダブル母集団内でのみ百分位付け
        return df[col].where(_pool).rank(pct=True) * 100'''
new = '''    _bio_excluded, _bio_unknown = _bio_selection_masks(df.index)
    df["selection_excluded"] = _bio_excluded
    df["excluded_theme"] = _bio_excluded                 # existing UI/filters use this canonical flag
    df["bio_revenue_unknown"] = _bio_unknown
    _pool = ((~df["split_suspect"]) & (df["close"] >= 5) & (df["dvol"] >= DVOL_FLOOR)
             & (~_bio_excluded))
    df["rs_pool"] = _pool
    def _rank_with_excluded_reference(col, pool):
        out = df[col].where(pool).rank(pct=True) * 100
        # Structural exclusions do not enter the denominator, but get an empirical-CDF
        # reference RS for display/candidate audit. Other non-tradable names remain NaN.
        try:
            refmask = _bio_excluded & df[col].notna()
            vals = np.sort(pd.to_numeric(df.loc[pool & df[col].notna(), col], errors="coerce").dropna().to_numpy())
            if len(vals) and bool(refmask.any()):
                x = pd.to_numeric(df.loc[refmask, col], errors="coerce")
                out.loc[refmask] = np.searchsorted(vals, x.to_numpy(), side="right") / len(vals) * 100.0
        except Exception:
            pass
        return out
    def _rk(col):                                         # selection-eligible母集団内の百分位 + 除外株の参考RS
        return _rank_with_excluded_reference(col, _pool)'''
if s.count(old) != 1:
    raise SystemExit(f'RS pool anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''    def _pool_lag(clc, dvc, mxc):
        if clc in df and dvc in df and mxc in df:
            return (df[mxc].fillna(0) <= 1.50) & (df[clc] >= 5) & (df[dvc] >= DVOL_FLOOR)
        return _pool'''
new = '''    def _pool_lag(clc, dvc, mxc):
        if clc in df and dvc in df and mxc in df:
            return ((df[mxc].fillna(0) <= 1.50) & (df[clc] >= 5) & (df[dvc] >= DVOL_FLOOR)
                    & (~_bio_excluded))
        return _pool'''
if s.count(old) != 1:
    raise SystemExit(f'RS lag pool anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''    def _rk_at(col, pool):
        return (df[col].where(pool).rank(pct=True) * 100) if col in df else np.nan'''
new = '''    def _rk_at(col, pool):
        return _rank_with_excluded_reference(col, pool) if col in df else np.nan'''
if s.count(old) != 1:
    raise SystemExit(f'_rk_at anchor count={s.count(old)}')
s = s.replace(old, new, 1)

s = s.replace('    r0 = df["ret63"].where(_pool).rank(pct=True)\n    df["rs63"] = r0 * 100',
              '    r0 = _rk("ret63") / 100.0\n    df["rs63"] = r0 * 100', 1)

# Setups are concrete ticker suggestions: never surface structural exclusions there.
old = '''    def names(mask, sort="rs"):
        sub = m[mask.fillna(False)].sort_values(sort, ascending=False)
        return list(sub.index)'''
new = '''    def names(mask, sort="rs"):
        ok = mask.fillna(False)
        if "selection_excluded" in m.columns:
            ok = ok & (~m["selection_excluded"].fillna(False))
        sub = m[ok].sort_values(sort, ascending=False)
        return list(sub.index)'''
if s.count(old) != 1:
    raise SystemExit(f'build_setups names anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Existing Core continuation must not keep a structurally excluded name.
old = '''        elig = m["rs189"].notna() & (m["rs189"] >= 85)   # 189日RS≥85（cand と一致）'''
new = '''        elig = m["rs189"].notna() & (m["rs189"] >= 85)   # 189日RS≥85（cand と一致）
        if "selection_excluded" in m.columns:
            elig = elig & (~m["selection_excluded"].fillna(False))'''
if s.count(old) != 1:
    raise SystemExit(f'core continuation anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Leadership pulse also uses actual eligible RS pool, not reference RS of exclusions.
old = '''        top=m.dropna(subset=["rs189"]).sort_values("rs189",ascending=False).head(RS_CONTINUITY_TOP_N)'''
new = '''        _lm = m[m["rs_pool"].fillna(False)] if "rs_pool" in m.columns else m
        top=_lm.dropna(subset=["rs189"]).sort_values("rs189",ascending=False).head(RS_CONTINUITY_TOP_N)'''
if s.count(old) != 1:
    raise SystemExit(f'leadership pulse anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Candidate warning only: missing fundamentals pass, never remove.
old = '''    cand["excluded_theme"] = [is_excluded_theme(t, s2t,
                                                (_mc.get(t) if _mc is not None else None))
                              for t in cand.index]'''
new = '''    cand["excluded_theme"] = [is_excluded_theme(t, s2t,
                                                (_mc.get(t) if _mc is not None else None))
                              for t in cand.index]
    cand["bio_revenue_unknown"] = [bool(_bio_selection_status(
        t, (_mc.get(t) if _mc is not None else None)).get("unknown")) for t in cand.index]
    _bio_missing = [t for t in cand.index if bool(cand.at[t, "bio_revenue_unknown"])]
    if _bio_missing:
        sys.stderr.write("::warning::bio revenue unknown -> PASS (selection unchanged by missing data): %s\\n"
                         % ",".join(_bio_missing[:50]))'''
if s.count(old) != 1:
    raise SystemExit(f'candidate exclusion anchor count={s.count(old)}')
s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')

# Dashboard needs the revenue threshold/fallback path but no new hard content gate yet.
wf = Path('.github/workflows/dashboard.yml')
y = wf.read_text(encoding='utf-8')
env_anchor = "          V38_OPT_TARGETS: options_targets.json\n"
env_new = env_anchor + "          # Clinical-stage eligibility: missing fundamentals PASS + warning.\n          V38_BIO_REVENUE_MAX: '50000000'\n          V38_BIO_REVENUE_JSON: bio_revenue_audit.json\n"
if y.count(env_anchor) != 1:
    raise SystemExit(f'dashboard env anchor count={y.count(env_anchor)}')
y = y.replace(env_anchor, env_new, 1)
wf.write_text(y, encoding='utf-8')
