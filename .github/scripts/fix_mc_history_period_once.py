from pathlib import Path

p = Path('build_dashboard.py')
s = p.read_text(encoding='utf-8')

repls = [
    ('"""Market Conditions history card: recent ~6 months only, compact mobile-safe layout."""',
     '"""Market Conditions history card: common CHART_LB window, compact mobile-safe layout."""'),
    ('    # MC15 needs long history for the score, but the chart itself should stay a\n    # recent-regime view. Never render the full calibration history here.\n    view = list(ts[-126:])',
     '    # MC15 needs long history for the score, but the chart display uses the same\n    # common window as the other trend sparklines.\n    view = list(ts[-CHART_LB:])'),
    ('Market Conditionsの推移・直近約6か月（80 Strong Bull / 65 Bull / 55 Weak Bull / 45 Neutral / 35 Weak Bear / 20 Bear）',
     'Market Conditionsの推移・{_span_label(view)}（80 Strong Bull / 65 Bull / 55 Weak Bull / 45 Neutral / 35 Weak Bear / 20 Bear）'),
]

for old, new in repls:
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'expected exactly one target, found {n}: {old[:80]!r}')
    s = s.replace(old, new, 1)

if 'view = list(ts[-126:])' in s:
    raise SystemExit('six-month hardcode still present in MC history renderer')
if 'view = list(ts[-CHART_LB:])' not in s:
    raise SystemExit('CHART_LB MC history window missing')

p.write_text(s, encoding='utf-8')
print('aligned Market Conditions history period to CHART_LB only')
