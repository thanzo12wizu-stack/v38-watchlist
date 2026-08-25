#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("build_dashboard.py")
s = p.read_text(encoding="utf-8")

old_aux = '''    breadth_arrow = "↑" if breadth_delta10 > 2.0 else ("↓" if breadth_delta10 < -2.0 else "→")
    return dict(cur=cur, hl=hl, slope=slope_dir, bear_n=bear_n, bear_flags=bear_flags,
                peak=peak, drop=drop, hi20=hi20,
                breadth_delta10=breadth_delta10, breadth_arrow=breadth_arrow)'''
new_aux = '''    breadth_arrow = "↑" if breadth_delta10 > 2.0 else ("↓" if breadth_delta10 < -2.0 else "→")
    _component_keys = ("ret5","ret21","ret63","ret252",
                       "above10","above20","above50","above200",
                       "ma20_gt_50","ma50_gt_200","dd_score","within10")
    components = {}
    for _k in _component_keys:
        try:
            _v = float(last.get(_k, np.nan))
            components[_k] = _v if np.isfinite(_v) else None
        except Exception:
            components[_k] = None
    try:
        mc_coverage = float(last.get("mc_coverage", np.nan))
    except Exception:
        mc_coverage = np.nan
    return dict(cur=cur, hl=hl, slope=slope_dir, bear_n=bear_n, bear_flags=bear_flags,
                peak=peak, drop=drop, hi20=hi20,
                breadth_delta10=breadth_delta10, breadth_arrow=breadth_arrow,
                components=components, mc_coverage=mc_coverage)'''
if s.count(old_aux) != 1:
    raise SystemExit(f"mri_auxiliary anchor count={s.count(old_aux)}")
s = s.replace(old_aux, new_aux, 1)

panel_re = re.compile(
    r'    _kj = \{"short":"モメンタム".*?\n    banner = sar_pill',
    re.S,
)
new_panel = '''    _component_groups = (
        ("モメンタム", (("ret5","1Wプラス"),("ret21","1Mプラス"),("ret63","3Mプラス"),("ret252","1Yプラス"))),
        ("Breadth", (("above10","10SMA上"),("above20","20SMA上"),("above50","50SMA上"),("above200","200SMA上"))),
        ("トレンド構造", (("ma20_gt_50","20SMA > 50SMA"),("ma50_gt_200","50SMA > 200SMA"))),
        ("Damage", (("dd_score","52週高値DDスコア"),("within10","52週高値10%以内"))),
    )
    _components = aux.get("components") or {}
    _bd_rows = []
    for _grp, _items in _component_groups:
        _bd_rows.append(f'<div class="mgrp">{_grp}</div>')
        for _k, _lab in _items:
            _v = _components.get(_k)
            if _v is None or not np.isfinite(float(_v)):
                _bd_rows.append(
                    f'<div class="mrow"><span class="mk2">{_lab}</span><span class="mraw">—</span>'
                    f'<span class="mbar"></span><span class="mpts">—</span></div>')
                continue
            _v = float(_v)
            _pct = max(0.0, min(100.0, _v))
            _bd_rows.append(
                f'<div class="mrow"><span class="mk2">{_lab}</span>'
                f'<span class="mraw">{_v:.1f}</span>'
                f'<span class="mbar"><i style="width:{_pct:.0f}%"></i></span>'
                f'<span class="mpts">{_v/12.0:.1f}点</span></div>')

    _bd_rows.append('<div class="mgrp">コンテキスト（MC点数には不算入）</div>')
    _cov = aux.get("mc_coverage", np.nan)
    try:
        _cov = float(_cov)
    except Exception:
        _cov = np.nan
    if np.isfinite(_cov):
        _cov_n = int(round(len(MC_MARKET_TICKERS) * _cov / 100.0))
        _bd_rows.append(
            f'<div class="mrow"><span class="mk2">57ETFカバレッジ</span>'
            f'<span class="mraw">{_cov:.1f}%</span>'
            f'<span class="mbar"><i style="width:{max(0.0,min(100.0,_cov)):.0f}%"></i></span>'
            f'<span class="mpts">{_cov_n}/{len(MC_MARKET_TICKERS)}</span></div>')
    _bd10 = float(aux.get("breadth_delta10", 0.0) or 0.0)
    _bd_arrow = aux.get("breadth_arrow", "→")
    _bd_rows.append(
        f'<div class="mrow"><span class="mk2">Breadth 10日変化</span>'
        f'<span class="mraw">{_bd_arrow} {_bd10:+.1f}pt</span>'
        f'<span class="mbar"></span><span class="mpts">score外</span></div>')

    _bchips = ("".join(f'<span class="bfl on">{lab}</span>' for lab in _blit)
               + "".join(f'<span class="bfl off">{lab}</span>' for lab in _boff))
    bear_sec = (f'<div class="mgrp">警戒 {aux["bear_n"]}/4</div>'
                f'<div class="bflags">{_bchips or "<span class=bfl off>—</span>"}</div>')
    mri_bd = (f'<div id="mri-bd" class="mri-bd" onclick="event.stopPropagation()">'
              f'<div class="mbd-h">MARKET CONDITIONS 内訳（57ETF × 12指標・完全等加重）</div>'
              + "".join(_bd_rows) + bear_sec
              + '<div class="mnote">各指標は0–100、12指標を完全等加重。右端は各指標の総合点への寄与。Breadth 10日変化はscore外。もう一度タップで閉じる ▴</div></div>')
    banner = sar_pill'''
s, n = panel_re.subn(new_panel, s, count=1)
if n != 1:
    raise SystemExit(f"Market Conditions panel anchor count={n}")

required = (
    'score_keys = ("ret5","ret21","ret63","ret252",',
    '"above10","above20","above50","above200",',
    '"ma20_gt_50","ma50_gt_200","dd_score","within10")',
    'raw = pd.concat([p[k] for k in score_keys], axis=1).mean(axis=1, skipna=True)',
    'score = raw.ewm(span=2,adjust=False).mean()',
    'assert len(MC_MARKET_TICKERS) == 57',
    '1Wプラス',
    '57ETFカバレッジ',
    'Breadth 10日変化',
)
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit(f"post-patch invariant missing: {missing}")

p.write_text(s, encoding="utf-8")
print("Market Conditions detail-only patch applied")
