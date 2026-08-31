from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LEADERSHIP = ROOT / "leadership"
RESEARCH = LEADERSHIP / "research"
for p in (str(LEADERSHIP), str(RESEARCH), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_market_snapshot as market_snapshot  # noqa: E402
import rotation_live_snapshot as rotation_live  # noqa: E402
import validate_early_rotation as early  # noqa: E402

PRICE_FLOOR = 5.0
DVOL_FLOOR = 10_000_000.0
RS_MIN = 85.0
MIN_THEME_MEMBERS = 3
BIO_EXCLUDE_INDUSTRIES = {"Biotechnology", "Pharmaceuticals: Other"}
BIO_KEEP_MCAP = 10_000_000_000.0
BIO_REVENUE_MAX = 50_000_000.0
TARGET_ETFS = ["XBI", "XME", "SOXX", "IGV"]


def finite(v: Any) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    z = frame.copy()
    idx = pd.to_datetime(z.index)
    try:
        idx = idx.tz_localize(None)
    except TypeError:
        idx = idx.tz_convert(None)
    z.index = idx.normalize()
    return z[~z.index.duplicated(keep="last")].sort_index()


def close_volume_matrices(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close: dict[str, pd.Series] = {}
    volume: dict[str, pd.Series] = {}
    for sym, frame in frames.items():
        if frame is None or frame.empty or "Close" not in frame.columns:
            continue
        z = normalize_frame(frame)
        close[sym] = pd.to_numeric(z["Close"], errors="coerce")
        volume[sym] = pd.to_numeric(z.get("Volume", pd.Series(index=z.index, dtype=float)), errors="coerce")
    return pd.DataFrame(close).sort_index(), pd.DataFrame(volume).sort_index()


def structural_bio_exclusions(path: Path, symbols: set[str]) -> tuple[set[str], bool]:
    try:
        u = pd.read_csv(path)
        sym_col = "シンボル" if "シンボル" in u.columns else "symbol"
        ind_col = "業種" if "業種" in u.columns else "industry"
        mc_col = "時価総額" if "時価総額" in u.columns else "market_cap"
        rev_col = "売上高TTM" if "売上高TTM" in u.columns else "revenue_ttm"
        if not {sym_col, ind_col, mc_col, rev_col}.issubset(u.columns):
            return set(), False
        u[sym_col] = u[sym_col].astype(str).str.upper().str.strip()
        u = u.drop_duplicates(sym_col).set_index(sym_col)
        idx = u.index.intersection(sorted(symbols))
        ind = u.loc[idx, ind_col].astype(str)
        mc = pd.to_numeric(u.loc[idx, mc_col], errors="coerce")
        rev = pd.to_numeric(u.loc[idx, rev_col], errors="coerce")
        # Exact audited rule: missing revenue fails open.
        mask = ind.isin(BIO_EXCLUDE_INDUSTRIES) & (mc < BIO_KEEP_MCAP) & rev.notna() & (rev < BIO_REVENUE_MAX)
        return set(idx[mask]), True
    except Exception:
        return set(), False


def replacement_percentile(value: float, reference: np.ndarray, theme_index: int) -> float | None:
    if not np.isfinite(value):
        return None
    ref = np.asarray(reference, float)
    finite_ref = ref[np.isfinite(ref)]
    if not len(finite_ref):
        return None
    sorted_ref = np.sort(finite_ref)
    count = float(np.searchsorted(sorted_ref, value, side="right"))
    original = ref[theme_index]
    if np.isfinite(original) and original <= value:
        count -= 1.0
    count += 1.0
    denom = float(len(sorted_ref)) + (0.0 if np.isfinite(original) else 1.0)
    return count / denom * 100.0 if denom > 0 else None


def strict_loo_latest(close: pd.DataFrame, snapshot: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Exact current-taxonomy Full3 LOO replication for the latest session.

    Candidate is excluded from Theme63 return, 20-session rank acceleration,
    and 21EMA breadth. Multiple memberships use the maximum valid score.
    This is current s2t taxonomy, never historical PIT taxonomy.
    """
    theme_members_all, stock_themes = early.extract_theme_members(snapshot)
    stock_set = set(close.columns)
    theme_members = {
        t: [s for s in members if s in stock_set]
        for t, members in theme_members_all.items()
    }
    theme_members = {t: m for t, m in theme_members.items() if len(m) >= MIN_THEME_MEMBERS}
    if not theme_members or len(close) < 84:
        return {}, {"status": "DATA_REQUIRED", "reason": "insufficient themes/history"}

    ret = close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    ret = ret.where(ret > -0.999999)
    theme_daily: dict[str, pd.Series] = {}
    for theme, members in theme_members.items():
        part = ret[members]
        count = part.notna().sum(axis=1)
        theme_daily[theme] = part.mean(axis=1, skipna=True).where(count >= MIN_THEME_MEMBERS)
    normal_ret = pd.DataFrame(theme_daily, index=close.index)
    min_periods = int(math.ceil(63 * 0.8))
    normal63 = np.expm1(np.log1p(normal_ret.where(normal_ret > -0.999999)).rolling(63, min_periods=min_periods).sum())
    normal_pct = normal63.rank(axis=1, pct=True, method="average") * 100.0
    normal_delta20 = normal_pct - normal_pct.shift(20)

    themes = list(normal63.columns)
    theme_pos = {t: i for i, t in enumerate(themes)}
    latest_i = len(close.index) - 1
    prior_i = latest_i - 20
    if prior_i < 0:
        return {}, {"status": "DATA_REQUIRED", "reason": "20-session acceleration unavailable"}
    ref63_now = normal63.iloc[latest_i].to_numpy(float)
    ref63_prior = normal63.iloc[prior_i].to_numpy(float)
    ref_delta_now = normal_delta20.iloc[latest_i].to_numpy(float)

    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid_b = close.notna() & ema21.notna()
    above_b = (close > ema21).where(valid_b)

    by_stock: dict[str, list[dict[str, Any]]] = {}
    for n_theme, theme in enumerate(themes, start=1):
        members = theme_members[theme]
        ti = theme_pos[theme]
        vals = ret[members].to_numpy(float)
        valid = np.isfinite(vals)
        sums = np.where(valid, vals, 0.0).sum(axis=1)
        counts = valid.sum(axis=1)
        vb = valid_b[members].to_numpy(bool)
        ab_raw = above_b[members].astype(float).to_numpy()
        ab = np.nan_to_num(ab_raw, nan=0.0, posinf=0.0, neginf=0.0)
        total_valid = vb.sum(axis=1)
        total_above = ab.sum(axis=1)

        for j, sym in enumerate(members):
            den = counts - valid[:, j].astype(np.int16)
            num = sums - np.where(valid[:, j], vals[:, j], 0.0)
            peer_daily = np.divide(num, den, out=np.full(len(close), np.nan), where=den >= 2)
            peer_log = np.log1p(np.where(peer_daily > -0.999999, peer_daily, np.nan))
            peer63 = pd.Series(peer_log, index=close.index).rolling(63, min_periods=min_periods).sum()
            peer63 = np.expm1(peer63.to_numpy(float))

            p_now = replacement_percentile(peer63[latest_i], ref63_now, ti)
            p_prior = replacement_percentile(peer63[prior_i], ref63_prior, ti)
            peer_delta = p_now - p_prior if p_now is not None and p_prior is not None else None
            accel_pct = replacement_percentile(float(peer_delta) if peer_delta is not None else np.nan, ref_delta_now, ti)
            peer_valid = int(total_valid[latest_i] - int(vb[latest_i, j]))
            peer_above = float(total_above[latest_i] - float(ab[latest_i, j]))
            breadth = peer_above * 100.0 / peer_valid if peer_valid >= 2 else None
            score = None
            if p_now is not None and accel_pct is not None and breadth is not None and all(np.isfinite(x) for x in (p_now, accel_pct, breadth)):
                score = (p_now + accel_pct + breadth) / 3.0
            by_stock.setdefault(sym, []).append({
                "theme": theme,
                "theme_rs63_pct": p_now,
                "theme_acceleration_pct": accel_pct,
                "theme_breadth21": breadth,
                "peer_theme_score": score,
                "peer_members": peer_valid,
            })
        if n_theme % 25 == 0 or n_theme == len(themes):
            print(f"STRICT_LOO {n_theme}/{len(themes)}", flush=True)

    out: dict[str, dict[str, Any]] = {}
    for sym in close.columns:
        memberships = by_stock.get(sym, [])
        valid_scores = [m for m in memberships if m.get("peer_theme_score") is not None and finite(m.get("peer_theme_score"))]
        selected = max(valid_scores, key=lambda m: (float(m["peer_theme_score"]), str(m["theme"]))) if valid_scores else None
        out[sym] = {
            "memberships": len(stock_themes.get(sym, [])),
            "valid_memberships": len(valid_scores),
            "selected": selected,
        }
    return out, {
        "status": "LIVE_CURRENT_TAXONOMY",
        "taxonomy": "CURRENT_S2T_NOT_PIT",
        "asof": str(close.index[-1].date()),
        "themes": len(themes),
        "mapped_stocks": len(stock_themes),
        "scored_stocks": sum(1 for x in out.values() if x.get("selected")),
        "formula": "candidate-excluded Theme63 percentile + candidate-excluded 20d rank-acceleration percentile + candidate-excluded Breadth21, equal-weighted / 3; max valid membership",
    }


def market_mode(close: pd.DataFrame, sma50: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Any]:
    nobs = close.notna().sum(axis=1)
    floor = max(5, min(30, int(max(1, close.shape[1]) * 0.20)))
    v50 = sma50.notna().sum(axis=1)
    breadth = close.gt(sma50).sum(axis=1) / v50.replace(0, np.nan) * 100.0
    breadth = breadth.where(v50 >= np.maximum(floor, nobs * 0.45))
    b = float(breadth.loc[asof]) if asof in breadth.index and finite(breadth.loc[asof]) else None

    color = None
    nq_asof = None
    try:
        import audit_rsi30_mc_nqsar as market_audit
        start = str((asof - pd.Timedelta(days=90)).date())
        end = str((asof + pd.Timedelta(days=4)).date())
        nq = market_audit.build_nqsar(start, end)
        q = nq.loc[nq.index <= asof]
        if not q.empty:
            nq_asof = str(q.index[-1].date())
            color = str(q.iloc[-1]["nq_color"])
    except Exception as exc:
        print(f"NQSAR_DATA_REQUIRED {type(exc).__name__}: {exc}", flush=True)

    if color is None or b is None:
        mode = "DATA_REQUIRED"
        limit = None
    elif color == "Red":
        mode, limit = "DEFENSE", 0
    elif color == "Yellow":
        mode, limit = "STOP", 0
    elif color in {"Blue", "Green"} and b >= 60.0:
        mode, limit = "ATTACK", 12
    elif color in {"Blue", "Green"} and b >= 50.0:
        mode, limit = "SELECTIVE", 4
    else:
        mode, limit = "STOP", 0
    return {
        "mode": mode,
        "nqsar": color,
        "nqsar_asof": nq_asof,
        "breadth50": b,
        "breadth_valid": int(v50.loc[asof]) if asof in v50.index else None,
        "breadth_observed": int(nobs.loc[asof]) if asof in nobs.index else None,
        "new_entry_limit": limit,
        "selective_existing_positions_not_force_trimmed": True,
    }


def fail_reasons(sym: str, latest: pd.Timestamp, close: pd.DataFrame, dvol: pd.DataFrame, sma50: pd.DataFrame, sma200: pd.DataFrame, rs63: pd.DataFrame, rs189: pd.DataFrame, bio_excluded: set[str]) -> list[str]:
    reasons: list[str] = []
    def v(frame: pd.DataFrame) -> float | None:
        try:
            x = frame.at[latest, sym]
            return float(x) if finite(x) else None
        except Exception:
            return None
    px, dv, s50, s200, r63, r189 = v(close), v(dvol), v(sma50), v(sma200), v(rs63), v(rs189)
    if px is None or px < PRICE_FLOOR: reasons.append("PRICE_LT_5_OR_MISSING")
    if dv is None or dv < DVOL_FLOOR: reasons.append("DVOL20_LT_10M_OR_MISSING")
    if s50 is None or s200 is None or not (s50 > s200): reasons.append("SMA50_NOT_ABOVE_SMA200")
    if px is None or s200 is None or not (px > s200): reasons.append("CLOSE_NOT_ABOVE_SMA200")
    if r189 is None or r189 < RS_MIN: reasons.append("RS189_LT_85_OR_MISSING")
    if r63 is None or r63 < RS_MIN: reasons.append("RS63_LT_85_OR_MISSING")
    if sym in bio_excluded: reasons.append("STRUCTURAL_SMALL_CLINICAL_BIOTECH")
    return reasons


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--period", default="15mo")
    ap.add_argument("--batch-size", type=int, default=80)
    args = ap.parse_args()
    root = args.root.resolve()
    args.output.mkdir(parents=True, exist_ok=True)

    universe_rows = market_snapshot.load_universe(root / "universe.csv")
    source_symbols = [r.symbol for r in universe_rows]
    print(f"V38_READONLY source_universe={len(source_symbols)}", flush=True)
    frames, failed = market_snapshot.download_history(source_symbols, batch_size=args.batch_size, period=args.period, pause=0.10)
    close, volume = close_volume_matrices(frames)
    if close.shape[1] < 3000 or len(close) < 200:
        raise RuntimeError(f"insufficient current universe history: {close.shape}")
    latest = pd.Timestamp(close.index[-1])

    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    vol20 = volume.rolling(20, min_periods=20).mean()
    dvol = close * vol20
    ret63 = close / close.shift(63) - 1.0
    ret189 = close / close.shift(189) - 1.0
    bio_excluded, bio_metadata_ok = structural_bio_exclusions(root / "universe.csv", set(close.columns))
    if not bio_metadata_ok:
        raise RuntimeError("formal structural-biotech metadata unavailable")
    base_pool = (close >= PRICE_FLOOR) & (dvol >= DVOL_FLOOR)
    if bio_excluded:
        ex = [s for s in bio_excluded if s in base_pool.columns]
        base_pool.loc[:, ex] = False
    rs63 = ret63.where(base_pool & ret63.notna()).rank(axis=1, pct=True, method="average") * 100.0
    rs189 = ret189.where(base_pool & ret189.notna()).rank(axis=1, pct=True, method="average") * 100.0
    eligible = base_pool & (sma50 > sma200) & (close > sma200) & (rs189 >= RS_MIN) & (rs63 >= RS_MIN)

    snapshot = json.loads((root / "sector_snapshot.json").read_text(encoding="utf-8"))
    loo, loo_meta = strict_loo_latest(close, snapshot)
    if loo_meta.get("status") != "LIVE_CURRENT_TAXONOMY":
        raise RuntimeError(f"strict LOO unavailable: {loo_meta}")

    current = []
    for sym in close.columns:
        r189 = float(rs189.at[latest, sym]) if finite(rs189.at[latest, sym]) else None
        r63 = float(rs63.at[latest, sym]) if finite(rs63.at[latest, sym]) else None
        lo = loo.get(sym, {})
        selected = lo.get("selected") if isinstance(lo.get("selected"), dict) else None
        peer = float(selected["peer_theme_score"]) if selected and finite(selected.get("peer_theme_score")) else None
        attack_score = 0.70 * r189 + 0.30 * (peer if peer is not None else 50.0) if r189 is not None else None
        reasons = fail_reasons(sym, latest, close, dvol, sma50, sma200, rs63, rs189, bio_excluded)
        current.append({
            "symbol": sym,
            "eligible": bool(eligible.at[latest, sym]),
            "fail_reasons": reasons,
            "price": float(close.at[latest, sym]) if finite(close.at[latest, sym]) else None,
            "dvol20_usd": float(dvol.at[latest, sym]) if finite(dvol.at[latest, sym]) else None,
            "sma50": float(sma50.at[latest, sym]) if finite(sma50.at[latest, sym]) else None,
            "sma200": float(sma200.at[latest, sym]) if finite(sma200.at[latest, sym]) else None,
            "rs189": r189,
            "rs63": r63,
            "peer_theme": selected.get("theme") if selected else None,
            "peer_theme_score": peer,
            "peer_theme_score_used": peer if peer is not None else 50.0,
            "peer_theme_status": "STRICT_LOO_CURRENT_TAXONOMY" if selected else "NO_VALID_THEME_NEUTRAL50",
            "theme_rs63_pct": selected.get("theme_rs63_pct") if selected else None,
            "theme_acceleration_pct": selected.get("theme_acceleration_pct") if selected else None,
            "theme_breadth21": selected.get("theme_breadth21") if selected else None,
            "attack_score": attack_score,
            "selective_score": r189,
        })
    all_df = pd.DataFrame(current)
    eligible_df = all_df[all_df["eligible"]].copy()
    eligible_df["attack_rank"] = eligible_df["attack_score"].rank(method="first", ascending=False).astype("Int64")
    eligible_df["selective_rank"] = eligible_df["selective_score"].rank(method="first", ascending=False).astype("Int64")
    rank_map = eligible_df.set_index("symbol")[["attack_rank", "selective_rank"]].to_dict("index")
    all_df["attack_rank"] = all_df["symbol"].map(lambda s: rank_map.get(s, {}).get("attack_rank"))
    all_df["selective_rank"] = all_df["symbol"].map(lambda s: rank_map.get(s, {}).get("selective_rank"))

    mkt = market_mode(close, sma50, latest)
    matrix = pd.read_csv(root / "leadership/research/rotation_live/latest_matrix.csv")
    rotation_by = matrix.set_index("ticker").to_dict("index") if "ticker" in matrix.columns else {}
    holdings, holdings_diag = rotation_live.fetch_all_holdings(rotation_live.requests.Session())
    holdings = holdings[holdings["sector_etf"].isin(TARGET_ETFS)].copy()
    holdings["symbol"] = holdings["symbol"].astype(str).str.upper()
    holding_lookup: dict[str, list[dict[str, Any]]] = {}
    for row in holdings.to_dict("records"):
        holding_lookup.setdefault(str(row["symbol"]), []).append(row)

    rows: list[dict[str, Any]] = []
    by_symbol = all_df.set_index("symbol").to_dict("index")
    for etf in TARGET_ETFS:
        rot = rotation_by.get(etf, {})
        h = holdings[holdings["sector_etf"] == etf]
        for hr in h.to_dict("records"):
            sym = str(hr.get("symbol") or "").upper()
            rec = by_symbol.get(sym)
            if rec is None:
                rows.append({
                    "etf": etf, "rotation_state": rot.get("state"), "symbol": sym,
                    "holding_weight_pct": hr.get("weight_pct"), "v38_status": "DATA_REQUIRED",
                    "fail_reasons": "PRICE_HISTORY_UNAVAILABLE",
                })
                continue
            if not bool(rec["eligible"]):
                status = "CONTEXT_ONLY_NOT_ELIGIBLE"
            elif mkt["mode"] in {"ATTACK", "SELECTIVE"}:
                status = "FORMAL_V38_CANDIDATE_WHEN_CAPACITY"
            elif mkt["mode"] in {"STOP", "DEFENSE"}:
                status = "V38_ELIGIBLE_BUT_MARKET_STOPPED"
            else:
                status = "DATA_REQUIRED"
            rank = rec.get("attack_rank") if mkt["mode"] == "ATTACK" else rec.get("selective_rank") if mkt["mode"] == "SELECTIVE" else None
            rows.append({
                "etf": etf,
                "rotation_state": rot.get("state"),
                "rotation_price_score": rot.get("matrix_price_score"),
                "rotation_internal_score": rot.get("matrix_internal_score"),
                "rotation_internal_delta20": rot.get("matrix_internal_delta20"),
                "rotation_flow20_usd": rot.get("flow_20d_usd"),
                "symbol": sym,
                "holding_weight_pct": hr.get("weight_pct"),
                **rec,
                "formal_market_mode": mkt["mode"],
                "mode_rank": rank,
                "v38_status": status,
                "execution_note": "read-only candidate context; actual entry still requires available capacity and next-open execution",
            })
    out_df = pd.DataFrame(rows)
    # Useful presentation order only; this does not create a new score.
    out_df["_eligible_sort"] = out_df.get("eligible", False).fillna(False).astype(int)
    out_df["_mode_rank_sort"] = pd.to_numeric(out_df.get("mode_rank"), errors="coerce").fillna(1e9)
    out_df = out_df.sort_values(["etf", "_eligible_sort", "_mode_rank_sort"], ascending=[True, False, True]).drop(columns=["_eligible_sort", "_mode_rank_sort"])
    out_df.to_csv(args.output / "rotation_v38_readonly_crosscheck.csv", index=False)

    summary = []
    for etf in TARGET_ETFS:
        q = out_df[out_df.etf == etf]
        formal = q[q.v38_status == "FORMAL_V38_CANDIDATE_WHEN_CAPACITY"]
        eligible_names = q[q.get("eligible", False).fillna(False).astype(bool)]
        summary.append({
            "etf": etf,
            "rotation_state": rotation_by.get(etf, {}).get("state"),
            "members": int(len(q)),
            "formal_eligible": int(len(eligible_names)),
            "formal_candidates_when_capacity": int(len(formal)),
            "top_candidates": [
                {
                    "symbol": r["symbol"],
                    "mode_rank": None if pd.isna(r.get("mode_rank")) else int(r["mode_rank"]),
                    "rs189": r.get("rs189"),
                    "rs63": r.get("rs63"),
                    "peer_theme": r.get("peer_theme"),
                    "peer_theme_score": r.get("peer_theme_score"),
                    "attack_score": r.get("attack_score"),
                }
                for _, r in formal.head(10).iterrows()
            ],
        })

    report = {
        "schema": 1,
        "research_only": True,
        "asof": str(latest.date()),
        "market_mode": mkt,
        "formal_rules": {
            "price_floor": PRICE_FLOOR,
            "dvol20_floor_usd": DVOL_FLOOR,
            "sma_rule": "SMA50>SMA200 and Close>SMA200",
            "rs189_min": RS_MIN,
            "rs63_min": RS_MIN,
            "structural_biotech": "industry in Biotechnology/Pharmaceuticals: Other AND mcap<$10B AND known revenue<$50M; missing revenue fail-open",
            "attack_rank": "0.70*Stock RS189 + 0.30*strict LOO Peer Theme; no valid Theme => neutral 50",
            "selective_rank": "Stock RS189 only",
        },
        "loo": loo_meta,
        "coverage": {
            "source_universe": len(source_symbols),
            "downloaded": int(close.shape[1]),
            "failed": len(set(failed)),
            "formal_eligible": int(all_df.eligible.sum()),
            "structural_bio_excluded": len(bio_excluded),
            "holdings_rows": int(len(holdings)),
        },
        "industry_summary": summary,
        "guardrails": [
            "Rotation contributes zero points to V38 ranking and is not a Gate.",
            "Strict LOO is current s2t taxonomy only; historical PIT taxonomy is not claimed.",
            "FORMAL_V38_CANDIDATE_WHEN_CAPACITY is not BUY; actual entry still requires formal market mode, free slot/capacity, and next-open execution.",
            "No Rotation state forces an exit from an existing V38 position.",
        ],
    }
    (args.output / "rotation_v38_readonly_crosscheck.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
