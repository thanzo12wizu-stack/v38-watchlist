from pathlib import Path
import re

p = Path('build_dashboard.py')
s = p.read_text(encoding='utf-8')

pat = re.compile(r"def _svg_mri\(ts\):\n.*?\n(?=def _sec_rows\()", re.S)
m = pat.search(s)
if not m:
    raise SystemExit('Market Conditions chart function not found')

new = r'''def _svg_mri(ts):
    """Market Conditions history card: recent ~6 months only, compact mobile-safe layout."""
    if not ts or len(ts) < 5:
        return ""

    # MC15 needs long history for the score, but the chart itself should stay a
    # recent-regime view. Never render the full calibration history here.
    view = list(ts[-126:])
    ys = [float(v) for _, v in view]
    n = len(ys)
    last = ys[-1]
    band_lab = mri_band(last)[0].replace("（過熱・反落注意⚠）", "")

    Wd, Ht = 680, 214
    pl, pr, pt, pb = 8, 42, 8, 8
    iw = Wd - pl - pr
    ih = Ht - pt - pb

    def X(i):
        return pl + i * iw / max(1, n - 1)

    def Y(v):
        vv = max(0.0, min(100.0, float(v)))
        return pt + (100.0 - vv) * ih / 100.0

    zones = [(0, 20, "#ef4444"), (20, 45, "#f97316"), (45, 55, "#64748b"),
             (55, 80, "#22c55e"), (80, 100, "#16a34a")]
    zr = ''.join(
        f'<rect x="{pl}" y="{Y(hi):.1f}" width="{iw}" height="{Y(lo)-Y(hi):.1f}" fill="{c}" opacity="0.055"/>'
        for lo, hi, c in zones
    )
    grid_vals = (20, 35, 45, 55, 65, 80)
    gl = ''.join(
        f'<line x1="{pl}" x2="{Wd-pr}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" stroke="#94a3b8" stroke-opacity="0.18" stroke-width="1"/>'
        f'<text x="{Wd-pr+6}" y="{Y(g)+3.5:.1f}" font-size="10" fill="#94a3b8" opacity="0.9">{g}</text>'
        for g in grid_vals
    )
    pts = ' '.join(f'{X(i):.1f},{Y(v):.1f}' for i, v in enumerate(ys))
    svg = (
        f'<svg viewBox="0 0 {Wd} {Ht}" preserveAspectRatio="none" aria-label="Market Conditions recent history" '
        f'style="display:block;width:100%;height:214px;overflow:visible">'
        f'{zr}{gl}'
        f'<polyline points="{pts}" fill="none" stroke="#34d399" stroke-width="2.25" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{X(n-1):.1f}" cy="{Y(last):.1f}" r="3.8" fill="#34d399"/>'
        f'</svg>'
    )

    # Five evenly-spaced labels are readable on phones and still show the span.
    k = min(5, n)
    idxs = sorted(set(round(i * (n - 1) / max(1, k - 1)) for i in range(k)))
    labs = []
    for j, idx in enumerate(idxs):
        d = pd.Timestamp(view[idx][0])
        lab = f'{d.month}/{d.day}'
        align = 'left' if j == 0 else 'right' if j == len(idxs)-1 else 'center'
        labs.append(f'<span style="text-align:{align};white-space:nowrap">{lab}</span>')
    axis = (
        f'<div class="mc-history-axis" style="display:grid;grid-template-columns:repeat({len(labs)},1fr);'
        f'gap:0;margin:4px 42px 0 8px;font-size:11px;line-height:1;color:#7c8178">'
        + ''.join(labs) + '</div>'
    )

    return (
        f'<div class="card mc-history-card" style="padding-bottom:14px">'
        f'<style>'
        f'.mc-history-card .chd{{margin-bottom:2px}}'
        f'.mc-history-card .cxpl{{margin:0 0 4px}}'
        f'.mc-history-card .chart{{margin-top:0;padding-top:0}}'
        f'.mc-history-card .cxpl summary{{padding-top:2px;padding-bottom:2px}}'
        f'@media(max-width:640px){{.mc-history-card{{padding-top:14px!important;padding-bottom:10px!important}}'
        f'.mc-history-card .chart svg{{height:196px!important}}'
        f'.mc-history-card .mc-history-axis{{font-size:10px!important;margin-top:3px!important}}}}'
        f'</style>'
        f'<div class="chd"><h2>Market Conditions 推移</h2>'
        f'<div class="chd-now" style="color:#7ff0a8"><b>{last:.0f}</b><span>{band_lab}</span></div></div>'
        f'<details class="cxpl"><summary>読み方</summary>'
        f'<div class="cxpl-b">Market Conditionsの推移・直近約6か月（80 Strong Bull / 65 Bull / 55 Weak Bull / 45 Neutral / 35 Weak Bear / 20 Bear）</div></details>'
        f'<div class="chart">{svg}{axis}</div></div>'
    )


'''

s2, nsub = pat.subn(new, s, count=1)
if nsub != 1:
    raise SystemExit(f'unexpected replacement count: {nsub}')

# Guardrails: this patch is intentionally limited to the MC history renderer.
if s2.count('def _svg_mri(ts):') != 1:
    raise SystemExit('duplicate _svg_mri after patch')
if 'mc-history-card' not in s2 or 'ts[-126:]' not in s2:
    raise SystemExit('patched MC history markers missing')

p.write_text(s2, encoding='utf-8')
print('patched Market Conditions history card only')
