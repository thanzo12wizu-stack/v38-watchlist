#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one occurrence, found {s.count(old)}: {old[:90]!r}")
    p.write_text(s.replace(old, new), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str, flags: int = re.S) -> None:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    out, n = re.subn(pattern, replacement, s, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f"{path}: regex expected one match, got {n}: {pattern[:100]}")
    p.write_text(out, encoding="utf-8")


# ---------------------------------------------------------------------------
# Companion: keep the research rank universe (DDV10), but expose the adopted
# DDV20 entry gate and canonical 11+1 / 3+1 structure.  Top12 is formed before
# DDV20, so rank13+ is never used to refill a DDV rejection.
# ---------------------------------------------------------------------------
replace_once(
    "build_v38_companion.py",
    '            "daily_dollar_volume_m": row.get("dvol"),\n            "sma50_gt_sma200": bool(row.get("ma5020")),',
    '            "daily_dollar_volume_m": row.get("dvol"),\n            "entry_ddv20_pass": _finite(row.get("dvol")) and float(row["dvol"]) >= 20,\n            "sma50_gt_sma200": bool(row.get("ma5020")),',
)
replace_once(
    "build_v38_companion.py",
    '                "dollar_volume_gte_10m": _finite(row.get("dvol")) and float(row["dvol"]) >= 10,',
    '                "dollar_volume_gte_10m_rank_pool": _finite(row.get("dvol")) and float(row["dvol"]) >= 10,\n                "dollar_volume_gte_20m_entry": _finite(row.get("dvol")) and float(row["dvol"]) >= 20,',
)
replace_once(
    "build_v38_companion.py",
    '            "selective_watch_semantics": "STOP/DEFENSE REOPEN TO SELECTIVE: RS189 ONLY; TOP4",\n            "selective_reopen_top4": [row["ticker"] for row in selective_order[:4]],\n            "attack_watch_status": "READY" if all_attack_watch_ready else "DATA REQUIRED",\n            "attack_watch_semantics": "STOP/DEFENSE REOPEN TO ATTACK: 70/30 STRICT LOO; TOP12",\n            "attack_reopen_top12": [row["ticker"] for row in attack_order[:12]] if all_attack_watch_ready else [],',
    '            "canonical_rule": "DDV20_VACANCY_TOP12_EARLY1_RS21_HIGH_ACCEL",\n            "total_slots_attack": 12,\n            "core_slots_attack": 11,\n            "early_slots_attack": 1,\n            "total_slots_selective": 4,\n            "core_slots_selective": 3,\n            "early_slots_selective": 1,\n            "ddv_entry_floor_m": 20,\n            "ddv_rank_pool_floor_m": 10,\n            "ddv_application": "RANK_FULL_DDV10_ELIGIBLE_UNIVERSE_THEN_TOP12_THEN_DDV20; NO_REFILL_BELOW_TOP12",\n            "selective_watch_semantics": "STOP/DEFENSE REOPEN TO SELECTIVE: RS189; TOP12 FIRST -> DDV20 -> CORE3 + EARLY1",\n            "selective_reopen_top4": [row["ticker"] for row in selective_order[:4]],\n            "selective_core_top3": [row["ticker"] for row in selective_order[:12] if row.get("entry_ddv20_pass")][:3],\n            "attack_watch_status": "READY" if all_attack_watch_ready else "DATA REQUIRED",\n            "attack_watch_semantics": "STOP/DEFENSE REOPEN TO ATTACK: 70/30 STRICT LOO; TOP12 FIRST -> DDV20 -> CORE11 + EARLY1",\n            "attack_reopen_top12": [row["ticker"] for row in attack_order[:12]] if all_attack_watch_ready else [],\n            "attack_core_top11": [row["ticker"] for row in attack_order[:12] if row.get("entry_ddv20_pass")][:11] if all_attack_watch_ready else [],',
)
replace_once(
    "build_v38_companion.py",
    '    sleeve_live = _load_json(sleeve_state_path, {})\n    sleeve_ready = _ready_live(sleeve_live, asof, "status")',
    '    sleeve_live = _load_json(sleeve_state_path, {})\n    sleeve_ready = _ready_live(sleeve_live, asof, "status")\n    early1_live = _load_json(Path("v38-early1-live.json"), {})\n    early1_ready = _ready_live(early1_live, asof, "status")',
)
replace_once(
    "build_v38_companion.py",
    '    return {\n        "schema": "v38-live-state-1",',
    '''    early1_state = dict(early1_live) if early1_ready else {
        "schema": "v38-early1-live-1", "asof": asof, "status": "DATA REQUIRED",
        "reason": "EARLY1_LIVE_REQUIRED",
    }
    early1_state["entry_allowed_now"] = bool(early1_ready and mode.name in {"ATTACK", "SELECTIVE"})
    early1_state["slot_plan"] = (
        "ATTACK: 本命11 + 先回り1 / SELECTIVE: 本命3 + 先回り1 / STOP・DEFENSE: 新規なし"
    )
    early1_state["total_slot_cap"] = 12 if mode.name == "ATTACK" else 4 if mode.name == "SELECTIVE" else 0
    early1_state["core_slot_cap"] = 11 if mode.name == "ATTACK" else 3 if mode.name == "SELECTIVE" else 0

    return {
        "schema": "v38-live-state-1",''',
)
replace_once(
    "build_v38_companion.py",
    '        "candidates": candidates,\n        "panic_reset": {',
    '        "candidates": candidates,\n        "early1": early1_state,\n        "panic_reset": {',
)
replace_once(
    "build_v38_companion.py",
    '            "strategy": normal_sleeve.get("strategy") if sleeve_ready else "PEAK30_PART25_R3",',
    '            "strategy": normal_sleeve.get("strategy") if sleeve_ready else "CANONICAL_DDV20_EARLY1_RS21_HIGH_ACCEL",',
)

# ---------------------------------------------------------------------------
# Normal-stock sleeve: migrate old holdings to CORE, then manage a distinct
# EARLY slot.  Existing positions are never force-trimmed merely because the
# mode cap falls.  New fills obey Top12->DDV20 and total cap 12/4.
# ---------------------------------------------------------------------------
replace_once(
    "build_v38_sleeve_live.py",
    '                "partial_done": bool(p.get("partial_done", False)),\n            }',
    '                "partial_done": bool(p.get("partial_done", False)),\n                "sleeve": str(p.get("sleeve") or "CORE"),\n                "early_sessions": int(p.get("early_sessions") or 0),\n            }',
)
replace_once(
    "build_v38_sleeve_live.py",
    '    current["positions"] = [dict(p) for p in previous.get("positions", [])]\n    current["pending"] = dict(previous.get("pending") or {"full_exits": [], "partial25": [], "entries": []})',
    '    current["positions"] = [dict(p) for p in previous.get("positions", [])]\n    for p in current["positions"]:\n        p.setdefault("sleeve", "CORE")\n        p.setdefault("early_sessions", 0)\n    current["pending"] = dict(previous.get("pending") or {"full_exits": [], "partial25": [], "entries": []})',
)

new_pending = r'''def _normal_pending(normal: dict[str, Any], companion: dict[str, Any], close_map: dict[str, float]) -> dict[str, Any]:
    positions = {p["symbol"]: p for p in normal["positions"]}
    for p in positions.values():
        p.setdefault("sleeve", "CORE")
        p.setdefault("early_sessions", 0)
    market = companion.get("market", {})
    mode = str(market.get("mode") or "STOP")
    total_cap = 12 if mode == "ATTACK" else 4 if mode == "SELECTIVE" else 0
    core_cap = 11 if mode == "ATTACK" else 3 if mode == "SELECTIVE" else 0
    early_cap = 1 if mode in {"ATTACK", "SELECTIVE"} else 0

    full_exits: list[dict[str, Any]] = []
    partials: list[dict[str, Any]] = []
    if mode == "DEFENSE":
        full_exits = [{"symbol": s, "reason": "NQSAR_RED"} for s in sorted(positions)]
    else:
        for sym, p in positions.items():
            close = close_map.get(sym)
            if close is None or not _finite(close):
                continue
            # Research order: Early expiry is evaluated before partial/stop.
            if str(p.get("sleeve") or "CORE") == "EARLY" and int(p.get("early_sessions") or 0) >= 10:
                full_exits.append({"symbol": sym, "reason": "EARLY_EXPIRY_D10"})
                continue
            peak = max(float(p["peak_close"]), float(close))
            p["peak_close"] = peak
            stop = max(float(p["entry_price"]) * 0.92, peak * 0.70)
            if float(close) <= stop:
                full_exits.append({"symbol": sym, "reason": "INITIAL_OR_PEAK30_STOP"})
            elif (not p.get("partial_done")) and float(close) >= float(p["entry_price"]) * 1.24:
                partials.append({"symbol": sym, "fraction": 0.25, "reason": "PARTIAL25"})

    exiting = {row["symbol"] for row in full_exits}
    ranked_rows = [row for row in companion.get("candidates", []) if row.get("final_rank") is not None]
    ranked_rows.sort(key=lambda row: int(row["final_rank"]))
    # Canonical VACANCY_TOP12: cut to Top12 BEFORE the DDV20 entry filter.
    top12 = ranked_rows[:12]
    liquid_top12 = [row for row in top12 if _finite(row.get("daily_dollar_volume_m")) and float(row["daily_dollar_volume_m"]) >= 20.0]
    core_take = [str(row["ticker"]) for row in liquid_top12[:core_cap]]
    core_set = set(core_take)

    promotions: list[str] = []
    if core_cap > 0:
        core_count = sum(
            str(p.get("sleeve") or "CORE") == "CORE" and sym not in exiting
            for sym, p in positions.items()
        )
        for sym, p in positions.items():
            if core_count >= core_cap:
                break
            if sym in exiting:
                continue
            if str(p.get("sleeve") or "CORE") == "EARLY" and sym in core_set:
                p["sleeve"] = "CORE"
                p["promoted_to_core_asof"] = str(companion.get("asof") or "")
                promotions.append(sym)
                core_count += 1

    surviving = {sym: p for sym, p in positions.items() if sym not in exiting}
    expected_total = len(surviving)
    core_count = sum(str(p.get("sleeve") or "CORE") == "CORE" for p in surviving.values())
    early_count = sum(str(p.get("sleeve") or "CORE") == "EARLY" for p in surviving.values())
    entries: list[dict[str, Any]] = []

    if total_cap > 0 and expected_total < total_cap and core_count < core_cap:
        for sym in core_take:
            if core_count >= core_cap or expected_total >= total_cap:
                break
            if sym in surviving:
                continue
            entries.append({"symbol": sym, "sleeve": "CORE", "signal_date": companion.get("asof")})
            expected_total += 1
            core_count += 1

    early = companion.get("early1") or {}
    early_ready = early.get("status") == "READY" and bool(early.get("entry_allowed_now"))
    if early_ready and early_cap > 0 and early_count < early_cap and expected_total < total_cap:
        for row in early.get("candidates") or []:
            sym = str(row.get("ticker") or "")
            if not sym or sym in surviving or any(e["symbol"] == sym for e in entries):
                continue
            entries.append({
                "symbol": sym, "sleeve": "EARLY", "signal_date": companion.get("asof"),
                "early_score": row.get("score"), "early_rank": row.get("rank"),
            })
            expected_total += 1
            early_count += 1
            break

    return {
        "full_exits": full_exits,
        "partial25": partials,
        "entries": entries,
        "entry_cap": total_cap,
        "core_cap": core_cap,
        "early_cap": early_cap,
        "promotions": promotions,
        "ddv_policy": "TOP12_THEN_DDV20_NO_REFILL_BELOW_TOP12",
        "early_policy": "RS21_HIGH_ACCEL_NOT_RED_BREADTH50_D10_DIRECT_PROMOTION",
    }
'''
regex_once(
    "build_v38_sleeve_live.py",
    r'def _normal_pending\(.*?\n\ndef _normal_mark',
    new_pending + '\n\ndef _normal_mark',
)

old_entry = '''        for sym0 in pending.get("entries", []):
            sym = str(sym0)
            if len(pos) >= cap or cash <= 1e-12 or sym in pos:
                continue
            px = _px(op, date, sym)
            if px is None:
                raise RuntimeError(f"NORMAL_ENTRY_OPEN_REQUIRED {sym}")
            amount = min(slot_cash, cash)
            if amount <= 1e-10:
                break
            cash -= amount
            pos[sym] = {
                "symbol": sym, "shares": amount / px, "entry_price": px,
                "entry_date": asof, "peak_close": px, "partial_done": False,
            }
'''
new_entry = '''        for entry0 in pending.get("entries", []):
            entry = entry0 if isinstance(entry0, dict) else {"symbol": str(entry0), "sleeve": "CORE"}
            sym = str(entry.get("symbol") or "")
            if len(pos) >= cap or cash <= 1e-12 or not sym or sym in pos:
                continue
            px = _px(op, date, sym)
            if px is None:
                raise RuntimeError(f"NORMAL_ENTRY_OPEN_REQUIRED {sym}")
            amount = min(slot_cash, cash)
            if amount <= 1e-10:
                break
            cash -= amount
            pos[sym] = {
                "symbol": sym, "shares": amount / px, "entry_price": px,
                "entry_date": asof, "peak_close": px, "partial_done": False,
                "sleeve": str(entry.get("sleeve") or "CORE"),
                "early_sessions": 0,
                "entry_signal_date": entry.get("signal_date"),
                "early_score": entry.get("early_score"),
                "early_rank": entry.get("early_rank"),
            }
        for p in pos.values():
            if str(p.get("sleeve") or "CORE") == "EARLY":
                p["early_sessions"] = int(p.get("early_sessions") or 0) + 1
'''
replace_once("build_v38_sleeve_live.py", old_entry, new_entry)
replace_once(
    "build_v38_sleeve_live.py",
    '                                 | set((prior_normal.get("pending") or {}).get("entries", []))\n                                 | {"SPY"})))',
    '                                 | {str(x.get("symbol") if isinstance(x, dict) else x) for x in (prior_normal.get("pending") or {}).get("entries", [])}\n                                 | {"SPY"})))',
)
replace_once(
    "build_v38_sleeve_live.py",
    '    current["strategy"] = "PEAK30_PART25_R3"',
    '    current["strategy"] = "CANONICAL_DDV20_EARLY1_RS21_HIGH_ACCEL"',
)

# ---------------------------------------------------------------------------
# V38 live workflow: build/cache Early1 before companion; stage it alongside
# the other V38-owned derivative files.
# ---------------------------------------------------------------------------
replace_once(
    ".github/workflows/v38-live.yml",
    '        v38-strict-loo-live.json\n        tqqq-panic-state.json',
    '        v38-strict-loo-live.json\n        v38-early1-live.json\n        tqqq-panic-state.json',
)
replace_once(
    ".github/workflows/v38-live.yml",
    '        build_v38_strict_loo_live.py\n        build_v38_tqqq_live.py',
    '        build_v38_strict_loo_live.py\n        build_v38_early1_live.py\n        build_v38_tqqq_live.py',
)
replace_once(
    ".github/workflows/v38-live.yml",
    '            build_v38_strict_loo_live.py \\\n            build_v38_tqqq_live.py\n          pytest -q \\\n            tests/test_v38_rules.py \\\n            tests/test_v38_companion.py \\\n            tests/test_v38_strict_loo_live.py \\\n            tests/test_v38_tqqq_live.py',
    '            build_v38_strict_loo_live.py \\\n            build_v38_early1_live.py \\\n            build_v38_tqqq_live.py\n          pytest -q \\\n            tests/test_v38_rules.py \\\n            tests/test_v38_companion.py \\\n            tests/test_v38_strict_loo_live.py \\\n            tests/test_v38_early1_live.py \\\n            tests/test_v38_tqqq_live.py',
)
insert_after_loo = '''      - name: Build strict LOO PIT live state
        run: |
          python build_v38_strict_loo_live.py \\
            --state state.json \\
            --sector-snapshot sector_snapshot.json \\
            --history v38-strict-loo-history.json \\
            --out v38-strict-loo-live.json
'''
early_step = insert_after_loo + '''
      - name: Restore canonical Early1 OHLCV cache
        uses: actions/cache@v5
        with:
          path: .cache/v38-early1
          key: ${{ runner.os }}-v38-early1-${{ github.run_id }}
          restore-keys: |
            ${{ runner.os }}-v38-early1-

      - name: Build canonical Early1 live signal
        shell: bash
        run: |
          set -euo pipefail
          python build_v38_early1_live.py \\
            --state state.json \\
            --universe universe.csv \\
            --industry industry_map.json \\
            --cache .cache/v38-early1/early1-ohlcv.pkl.gz \\
            --out v38-early1-live.json
'''
replace_once(".github/workflows/v38-live.yml", insert_after_loo, early_step)
replace_once(
    ".github/workflows/v38-live.yml",
    "          tqqq=json.loads(Path('tqqq-panic-state.json').read_text(encoding='utf-8'))\n          asof=str(state.get('date') or '')",
    "          tqqq=json.loads(Path('tqqq-panic-state.json').read_text(encoding='utf-8'))\n          early=json.loads(Path('v38-early1-live.json').read_text(encoding='utf-8'))\n          asof=str(state.get('date') or '')",
)
replace_once(
    ".github/workflows/v38-live.yml",
    "          if tqqq.get('schema') != 'v38-tqqq-panic-state-1' or tqqq.get('asof') != asof:\n              raise SystemExit(f'TQQQ mismatch: {tqqq.get(\"asof\")} != {asof}')",
    "          if tqqq.get('schema') != 'v38-tqqq-panic-state-1' or tqqq.get('asof') != asof:\n              raise SystemExit(f'TQQQ mismatch: {tqqq.get(\"asof\")} != {asof}')\n          if early.get('schema') != 'v38-early1-live-1' or early.get('asof') != asof or early.get('status') != 'READY':\n              raise SystemExit(f'EARLY1 mismatch/not ready: {early.get(\"asof\")} {early.get(\"status\")}')",
)

# Sleeve refresh consumes Early1 through the companion staged by v38-live.
replace_once(
    ".github/workflows/v38-sleeve-refresh.yml",
    '        v38-strict-loo-live.json\n        tqqq-panic-state.json',
    '        v38-strict-loo-live.json\n        v38-early1-live.json\n        tqqq-panic-state.json',
)
replace_once(
    ".github/workflows/v38-sleeve-refresh.yml",
    '            build_v38_companion.py \\\n            build_v38_strict_loo_live.py \\\n            v38_rules.py',
    '            build_v38_companion.py \\\n            build_v38_strict_loo_live.py \\\n            build_v38_early1_live.py \\\n            v38_rules.py',
)
replace_once(
    ".github/workflows/v38-sleeve-refresh.yml",
    '            tests/test_v38_companion.py',
    '            tests/test_v38_companion.py \\\n            tests/test_v38_early1_live.py',
)

# Final family promotion owns Early1 too.
replace_once(
    ".github/workflows/production-downstream-chain.yml",
    '        v38-strict-loo-live.json\n        tqqq-panic-state.json',
    '        v38-strict-loo-live.json\n        v38-early1-live.json\n        tqqq-panic-state.json',
)
replace_once(
    ".github/workflows/production-downstream-chain.yml",
    "          sleeve=json.loads(Path('v38-sleeve-state.json').read_text(encoding='utf-8'))\n          if str(state.get('date') or '') != target:",
    "          sleeve=json.loads(Path('v38-sleeve-state.json').read_text(encoding='utf-8'))\n          early=json.loads(Path('v38-early1-live.json').read_text(encoding='utf-8'))\n          if str(state.get('date') or '') != target:",
)
replace_once(
    ".github/workflows/production-downstream-chain.yml",
    "              'Sleeve': str(sleeve.get('asof') or ''),",
    "              'Sleeve': str(sleeve.get('asof') or ''),\n              'Early1': str(early.get('asof') or ''),",
)
replace_once(
    ".github/workflows/production-downstream-chain.yml",
    "          if sleeve.get('status') != 'READY':\n              raise SystemExit(f'Sleeve not READY: {sleeve.get(\"status\")}')",
    "          if early.get('status') != 'READY':\n              raise SystemExit(f'Early1 not READY: {early.get(\"status\")}')\n          if sleeve.get('status') != 'READY':\n              raise SystemExit(f'Sleeve not READY: {sleeve.get(\"status\")}')",
)

# ---------------------------------------------------------------------------
# Beginner-facing page. Keep the existing visual system, but replace jargon
# with 本命株 / 先回り株 and show the exact canonical mechanics.
# ---------------------------------------------------------------------------
replace_once(
    "command-center-v38.html",
    '<button data-tab="ranking">候補ランキング</button>',
    '<button data-tab="ranking">本命＋先回り候補</button>',
)
replace_once(
    "command-center-v38.html",
    '<span>通常個別株</span><b id="normalDecision">—</b>',
    '<span>本命＋先回り株</span><b id="normalDecision">—</b>',
)
replace_once(
    "command-center-v38.html",
    '<section id="ranking" class="panel"><div class="card"><div class="rank-intro"><div><div class="eyebrow">STOCK SELECTION</div><strong id="rankingTitle">候補順位</strong><div class="statusline" id="rankingSubtitle">—</div></div><span class="badge" id="rankingBadge">—</span></div><div class="picks" id="topPicks"></div></div>',
    '<section id="ranking" class="panel"><div class="card"><div class="rank-intro"><div><div class="eyebrow">MAIN LEADERS</div><strong id="rankingTitle">本命株の候補順位</strong><div class="statusline" id="rankingSubtitle">—</div></div><span class="badge" id="rankingBadge">—</span></div><div class="picks" id="topPicks"></div></div><div class="card"><div class="hdr"><h2>先回り1枠 ─ 次の主導株候補</h2><span class="badge" id="earlyBadge">RS21_HIGH_ACCEL</span></div><div class="explain" id="earlyExplain">直近5日で短期RSレーダーに新規浮上し、RS21・63日高値接近度・RS21加速度が強い銘柄を1つだけ先回りします。</div><div class="picks" id="earlyPick"></div></div>',
)
replace_once(
    "command-center-v38.html",
    '<th>$Vol(M)</th><th>50&gt;200</th>',
    '<th>$Vol(M)</th><th>DDV20 Entry</th><th>50&gt;200</th>',
)

# Replace the rules section details that changed.
replace_once(
    "command-center-v38.html",
    '<details class="rulebox"><summary>② Eligibility ─ そもそも候補に入れる株</summary><div class="rulebody">Price≥$5、Daily Dollar Volume≥$10M、SMA50&gt;SMA200、Close&gt;SMA200、RS189 percentile≥85、RS63 percentile≥85。<br>Biotechnology / Pharmaceuticals: Other のうち、時価総額&lt;$10B かつ Revenue TTM&lt;$50M の構造的小型Clinical Biotechだけ除外。Revenue欠落はfail-open。Theme名ではなくIndustryで判定する。</div></details>',
    '<details class="rulebox"><summary>② どんな株を本命候補にする？</summary><div class="rulebody">株価$5以上、上昇トレンド（SMA50&gt;SMA200、Close&gt;SMA200）、RS189とRS63がともにUniverse上位15%以内。小型Clinical Biotechの一部は除外。<br><br><b>実際に新規で買うにはDDV≥$20Mが必要</b>。ただし順位を作る母集団は研究時と同じDDV≥$10M。まず正式順位Top12を確定し、その12銘柄にDDV20を当てます。DDV20未満が落ちても13位以下を繰り上げません。</div></details>',
)
replace_once(
    "command-center-v38.html",
    '<details class="rulebox"><summary>③ Ranking ─ どれを優先して買う？</summary><div class="rulebody"><b>ATTACK</b>では次の正式式。<div class="formula">Final = 0.70 × Stock RS189 + 0.30 × strict LOO Peer Theme Score</div>Theme Scoreは「Theme RS63」「20日Rank Acceleration」「Theme構成銘柄の21EMA上比率」の等加重。候補銘柄自身Xは3成分すべてから除外（Leave-One-Out）し、自己押し上げを防ぐ。複数Themeなら最も高い有効Scoreを採用。<br><br><b>SELECTIVE</b>ではTheme加点を外し、RS189中心。<div class="note">STOP/DEFENSE中は復帰先を2本に分けて表示します。Blue/Green＋Breadth 50〜60%ならSELECTIVEなのでRS189 Top4、Breadth≥60%ならATTACKなので70/30 strict-LOO Top12。どちらも復帰条件成立前は買いシグナルではありません。</div></div></details>',
    '<details class="rulebox"><summary>③ 本命11＋先回り1 ─ どう選ぶ？</summary><div class="rulebody"><b>相場が強いATTACK</b>では合計12枠＝<b>本命11＋先回り1</b>。本命は<div class="formula">0.70 × Stock RS189 + 0.30 × strict LOO Peer Theme Score</div>で順位化。Theme ScoreはTheme RS63・20日Rank加速度・Theme21EMA上比率の等加重で、候補自身は計算から除外します。<br><br><b>慎重なSELECTIVE</b>では合計4枠＝<b>本命3＋先回り1</b>。本命はRS189中心。<br><br><b>先回り1枠</b>は<div class="formula">0.50 × RS21 + 0.25 × 63日高値接近度Percentile + 0.25 × RS21の20日加速度Percentile</div>直近5営業日で短期RSレーダーへ新規浮上した銘柄だけ。DDV20以上、最大1銘柄、最大10営業日。本命上位へ入れば売買せず本命へ昇格します。</div></details>',
)
replace_once(
    "command-center-v38.html",
    '<details class="rulebox"><summary>④ Entry / Exit ─ 買った後はどうする？</summary><div class="rulebody">候補は毎営業日更新。空き枠は引け後判定→翌寄り補充。順位低下・Theme低下・Breadth低下・Yellow・Top12落ちだけでは売らない。<br><br><b>初期Stop</b>：終値≤Entry×0.92 → 翌寄り全売却。<br><b>部分利確</b>：初めて終値≥Entry×1.24 → 翌寄り25%だけ利確（1回）。<br><b>Winner Trail</b>：残り75%は最高終値Peak Close×0.70。Final Stop=max(Entry×0.92, Peak×0.70)。<br><b>Red</b>：Portfolio Exitが最優先。<div class="note">すべて当日終値で判定し、注文は次営業日寄りで執行。PeakはIntraday Highではなく最高終値。</div></div></details>',
    '<details class="rulebox"><summary>④ 買った後はいつ売る？</summary><div class="rulebody">引け後に判定し、注文は翌営業日寄り。順位低下・Theme低下・Breadth低下・Yellow・Top12落ちだけでは売りません。<br><br><b>損切り</b>：終値≤Entry×0.92 → 翌寄り全売却。<br><b>最初の利確</b>：初めて終値≥Entry×1.24 → 翌寄り25%だけ利確。<br><b>大化け株を伸ばす</b>：残り75%は最高終値から30%下まで保有。Final Stop=max(Entry×0.92, Peak Close×0.70)。<br><b>先回り株</b>：10営業日以内に本命入りしなければ翌寄り退出。<br><b>NQSAR Red</b>：通常個別株は翌寄り全退避。</div></details>',
)

# Beginner mode descriptions.
replace_once(
    "command-center-v38.html",
    "function modeText(m){if(m.mode==='ATTACK')return['買える地合い','Blue/GreenかつBreadth 60%以上。通常株を最大12枠まで使える。','good'];if(m.mode==='SELECTIVE')return['選別して買える','Blue/GreenだがBreadthは50〜60%。通常株は合計最大4枠まで。','warn'];",
    "function modeText(m){if(m.mode==='ATTACK')return['買える地合い','Blue/GreenかつBreadth 60%以上。本命11＋先回り1の合計12枠。','good'];if(m.mode==='SELECTIVE')return['選別して買える','Blue/GreenだがBreadthは50〜60%。本命3＋先回り1の合計4枠。','warn'];",
)

new_render = r'''function coreEntryRows(kind){let all=[...(STATE?.candidates||[])];let rows;if(kind==='selective')rows=all.sort((a,b)=>(a.selective_watch_rank??999)-(b.selective_watch_rank??999));else if(kind==='attack')rows=all.filter(x=>x.attack_watch_rank!=null).sort((a,b)=>a.attack_watch_rank-b.attack_watch_rank);else rows=rankRows();return rows.slice(0,12).filter(x=>Number(x.daily_dollar_volume_m)>=20)}
function earlyCard(){let e=STATE?.early1||{},x=e.top1||(e.candidates||[])[0];$('earlyBadge').textContent=e.status==='READY'?'RS21_HIGH_ACCEL READY':'DATA REQUIRED';$('earlyExplain').textContent=e.status==='READY'?`1枠だけ先回り。DDV20以上・最大10営業日。本命入りすれば売らずに昇格。現在 ${e.entry_allowed_now?'Entry可能地合い':'新規Entry停止中'}。`:'先回り判定に必要なOHLCVが不足しています。';$('earlyPick').innerHTML=x?`<div class="pick"><div class="rankno">先回り #${x.rank??1}</div><div class="ticker">${esc(x.ticker)}</div><div class="score">${fmt(x.score,1)}</div><div class="pickline">RS21_HIGH_ACCEL ／ DDV ${fmt(x.daily_dollar_volume_m,1)}M</div><div class="why">RS21 ${fmt(x.rs21)} ／ 63日高値接近 ${fmt(x.high63_pct)} ／ RS21加速度 ${fmt(x.acc21_pct)}。${e.entry_allowed_now?'空き先回り枠があれば翌寄り候補。':'現在は市場Gateにより買わない。'}</div></div>`:'<div class="empty">現在、直近5日の先回り条件を満たすDDV20銘柄はありません。</div>'}
function renderRanking(){let rows=rankRows(),m=STATE.market,r=STATE.ranking||{},entry=m.mode==='ATTACK'||m.mode==='SELECTIVE';let ready=entry?(m.mode==='SELECTIVE'||r.strict_loo_live_status==='READY'):r.attack_watch_status==='READY';$('rankingTitle').textContent=entry?'本命株の買付優先順位':'再開時の本命候補';$('rankingSubtitle').textContent=entry?'正式順位Top12を先に作り、DDV20を通った銘柄だけを本命枠へ。13位以下からの穴埋めはしません。':'今は買わない。復帰時の本命候補と先回り候補を別々に表示します。';$('rankingBadge').textContent=ready?'正式ロジックで順位化':'DATA REQUIRED';$('rankStatus').textContent=ready?'順位READY':'DATA REQUIRED';$('quickRankTitle').textContent=entry?'今の本命＋先回り候補':'再開時の本命＋先回り候補';let kind=m.mode==='SELECTIVE'?'selective':'attack';let core=coreEntryRows(kind);let coreCap=m.mode==='SELECTIVE'?3:11;if(entry){$('quickRankExplain').textContent=`${m.mode==='ATTACK'?'本命11＋先回り1':'本命3＋先回り1'}。本命はTop12確定後にDDV20を適用。`;let top=ready?core.slice(0,3):[];$('quickPicks').innerHTML=top.map(x=>pickCard(x,kind)).join('')||'<div class="empty">現在の本命候補がありません。</div>';$('topPicks').innerHTML=top.map(x=>pickCard(x,kind)).join('')||'<div class="empty">現在の本命候補がありません。</div>'}else{let sel=coreEntryRows('selective').slice(0,3),atk=coreEntryRows('attack').slice(0,11);$('quickRankExplain').textContent='Blue/Greenへ戻りBreadth 50〜60%なら本命3＋先回り1、60%以上なら本命11＋先回り1。今は買いません。';$('quickPicks').innerHTML=`<div style="grid-column:1/-1"><div class="eyebrow">SELECTIVE復帰：本命3＋先回り1</div><div class="picks">${sel.map(x=>pickCard(x,'selective')).join('')}</div></div><div style="grid-column:1/-1"><div class="eyebrow">ATTACK復帰：本命11＋先回り1</div><div class="picks">${atk.slice(0,6).map(x=>pickCard(x,'attack')).join('')}</div></div>`;$('topPicks').innerHTML=atk.slice(0,3).map(x=>pickCard(x,'attack')).join('')||'<div class="empty">正式ATTACK順位に必要なデータが揃っていません。</div>'}earlyCard();let top12=new Set((kind==='selective'?[...rows].sort((a,b)=>(a.selective_watch_rank??999)-(b.selective_watch_rank??999)):[...rows].sort((a,b)=>(a.attack_watch_rank??999)-(b.attack_watch_rank??999))).slice(0,12).map(x=>x.ticker));$('candidateRows').innerHTML=rows.slice(0,50).map(x=>{let q=rankMeta(x),rot=rotationLabel(x),ddv20=Number(x.daily_dollar_volume_m)>=20,inside=top12.has(x.ticker),buy=entry?(inside?(ddv20?'本命候補':'DDV20未達→空席'):'Top12外→買わない'):'今は買わない';return`<tr><td>${q.rank??'—'}</td><td><a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(x.ticker)}" target="_blank" rel="noopener noreferrer" style="display:block;color:inherit;text-decoration:none;padding:9px 7px;margin:-9px -7px"><b>${esc(x.ticker)}</b></a></td><td>${q.score==null?'DATA REQUIRED':fmt(q.score,1)}</td><td>${fmt(x.rs189)}</td><td>${fmt(x.rs63)}</td><td>${x.daily_dollar_volume_m==null?'—':fmt(x.daily_dollar_volume_m,1)}</td><td>${ddv20?'PASS':'FAIL'}</td><td>${x.sma50_gt_sma200?'PASS':'FAIL'}</td><td>${(x.close_vs_sma200_pct??0)>0?'PASS':'FAIL'}</td><td>${esc(x.peer_theme||'—')}</td><td>${x.peer_theme_score==null?'—':fmt(x.peer_theme_score)}</td><td>${esc(rot)}</td><td>${buy}</td></tr>`}).join('')}
'''
regex_once(
    "command-center-v38.html",
    r'function renderRanking\(\)\{.*?\nfunction renderToday\(\)',
    new_render + 'function renderToday()',
)

# Simple static text corrections.
for old, new in [
    ('Daily Dollar Volume≥$10M', 'Daily Dollar Volumeの順位母集団≥$10M / Entry≥$20M'),
    ('RS189 Top4', 'RS189本命3＋先回り1'),
    ('70/30 strict-LOO Top12', '70/30 strict-LOO本命11＋先回り1'),
]:
    p=Path('command-center-v38.html'); s=p.read_text(encoding='utf-8'); p.write_text(s.replace(old,new),encoding='utf-8')

print('V38_CANONICAL_PATCH_APPLIED')
