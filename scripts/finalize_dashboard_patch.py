from pathlib import Path

bp = Path('build_dashboard.py')
s = bp.read_text(encoding='utf-8')

# 1) Master universe: scan eligible US listings without a scanner-level type filter.
# TradingView classifies legitimate foreign listings such as ARM/ASML/SKHY as type=dr;
# scanner-level type filtering has proven unreliable for this endpoint.
old_filter = '''        flt = [{"left": "type", "operation": "equal", "right": payload_type},
               {"left": "exchange", "operation": "in_range", "right": UNIVERSE_EXCHANGES},
               {"left": "market_cap_basic", "operation": "egreater", "right": UNIVERSE_MIN_MCAP},
               {"left": "close", "operation": "egreater", "right": UNIVERSE_MIN_PRICE}]
'''
new_filter = '''        flt = [{"left": "exchange", "operation": "in_range", "right": UNIVERSE_EXCHANGES},
               {"left": "market_cap_basic", "operation": "egreater", "right": UNIVERSE_MIN_MCAP},
               {"left": "close", "operation": "egreater", "right": UNIVERSE_MIN_PRICE}]
        if payload_type:
            flt.insert(0, {"left": "type", "operation": "equal", "right": payload_type})
'''
if old_filter in s:
    if s.count(old_filter) != 1:
        raise SystemExit(f'universe filter anchor count={s.count(old_filter)}')
    s = s.replace(old_filter, new_filter, 1)
elif new_filter not in s:
    raise SystemExit('universe filter anchor not found')

old_scan = '''    raw = []
    for _typ in ("stock", "dr"):
        try:
            raw.extend(_scan_type(_typ, with_revenue=True))
        except Exception as _e:
            # Fundamental column outage must not break the universe. Retry without it.
            sys.stderr.write("[universe] total_revenue付き%s scan失敗(%s) -> revenue無しで再試行\\n"
                             % (_typ, type(_e).__name__))
            try:
                raw.extend(_scan_type(_typ, with_revenue=False))
            except Exception as _e2:
                sys.stderr.write("[universe] %s scan失敗: %s\\n" % (_typ, type(_e2).__name__))
'''
new_scan = '''    # Scan the exchange set once without a type filter, then keep only stock/dr below.
    # This prevents valid ADR/ADS/Registry Shares from disappearing at scanner ingress.
    raw = []
    try:
        raw.extend(_scan_type(None, with_revenue=True))
    except Exception as _e:
        # Fundamental-column outage must not break the universe. Retry without revenue.
        sys.stderr.write("[universe] total_revenue付きall scan失敗(%s) -> revenue無しで再試行\\n"
                         % type(_e).__name__)
        try:
            raw.extend(_scan_type(None, with_revenue=False))
        except Exception as _e2:
            sys.stderr.write("[universe] all scan失敗: %s\\n" % type(_e2).__name__)
'''
if old_scan in s:
    if s.count(old_scan) != 1:
        raise SystemExit(f'universe raw-scan anchor count={s.count(old_scan)}')
    s = s.replace(old_scan, new_scan, 1)
elif new_scan not in s:
    raise SystemExit('universe raw-scan anchor not found')

# Enforce stock/dr after the broad scan. Prefer inserting beside the row mapping so all
# later security-description sanitation remains intact.
row_anchor = '        r = {columns[i]: data[i] for i in range(min(len(columns), len(data)))}\n'
row_guard = '''        r = {columns[i]: data[i] for i in range(min(len(columns), len(data)))}
        if str(r.get("type") or "").strip().lower() not in {"stock", "dr"}:
            continue
'''
if row_guard not in s:
    if s.count(row_anchor) != 1:
        raise SystemExit(f'universe row anchor count={s.count(row_anchor)}')
    s = s.replace(row_anchor, row_guard, 1)

# 2) VWAP near is an observation/display filter only.
# ADR20 = ordinary 20-day average (High-Low)/Close; floor 2%, 0.5x ADR20, cap 5%.
old_near = '    near = bool(np.isfinite(dist) and abs(dist) <= 0.02)\n'
new_near = '''    # Observation-only near zone. touch/support/reclaim semantics remain unchanged.
    try:
        _adr20 = (((aligned["h"] - aligned["l"]) / aligned["c"].replace(0, np.nan))
                  .replace([np.inf, -np.inf], np.nan).dropna().tail(20).mean())
        _adr20 = float(_adr20) if np.isfinite(_adr20) else 0.0
    except Exception:
        _adr20 = 0.0
    _near_threshold = min(0.05, max(0.02, 0.5 * _adr20))
    near = bool(np.isfinite(dist) and abs(dist) <= _near_threshold)
'''
if old_near in s:
    if s.count(old_near) != 1:
        raise SystemExit(f'VWAP near anchor count={s.count(old_near)}')
    s = s.replace(old_near, new_near, 1)
elif '_near_threshold = min(0.05, max(0.02, 0.5 * _adr20))' not in s:
    raise SystemExit('VWAP near anchor not found and adaptive rule not present')

bp.write_text(s, encoding='utf-8')

# 3) Same-session stale-source protection.
wf = Path('.github/workflows/dashboard.yml')
y = wf.read_text(encoding='utf-8')

setup_anchor = '''      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
'''
sync = '''      - name: Sync latest main before build
        shell: bash
        run: |
          set -euo pipefail
          git fetch --depth=1 origin main
          git reset --hard origin/main
          echo "V38_BUILD_SOURCE_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"

'''
if 'V38_BUILD_SOURCE_SHA=$(git rev-parse HEAD)' not in y:
    if y.count(setup_anchor) != 1:
        raise SystemExit(f'setup anchor count={y.count(setup_anchor)}')
    y = y.replace(setup_anchor, sync + setup_anchor, 1)

persist_anchor = '''          git config user.name "github-actions[bot]"
          git config user.email \\
            "41898282+github-actions[bot]@users.noreply.github.com"

          # --- なぜrebaseをやめたか -------------------------------------------
'''
persist_new = '''          git config user.name "github-actions[bot]"
          git config user.email \\
            "41898282+github-actions[bot]@users.noreply.github.com"
          echo "source_drift=false" >> "$GITHUB_OUTPUT"

          # Same-session stale-run guard. Artifact-only/options commits are harmless;
          # generation/input changes mean this run was built from obsolete logic.
          git fetch --depth=1 origin main
          if [[ -n "${V38_BUILD_SOURCE_SHA:-}" ]] && \\
             ! git diff --quiet "$V38_BUILD_SOURCE_SHA" origin/main -- \\
               build_dashboard.py .github/workflows/dashboard.yml \\
               scripts/export_public_site.py scripts/privacy_audit.py \\
               sar_state.txt equity.csv; then
            echo "::warning::source drift after build; skip persistence/public publish for stale same-session run"
            echo "source_drift=true" >> "$GITHUB_OUTPUT"
            echo "source_sha=$V38_BUILD_SOURCE_SHA" >> "$GITHUB_OUTPUT"
            exit 0
          fi

          # --- なぜrebaseをやめたか -------------------------------------------
'''
if 'source drift after build; skip persistence/public publish' not in y:
    if y.count(persist_anchor) != 1:
        raise SystemExit(f'persist anchor count={y.count(persist_anchor)}')
    y = y.replace(persist_anchor, persist_new, 1)

repls = [
    ("      - name: Audit public privacy boundary\n        if: steps.build.outputs.skipped != 'true'",
     "      - name: Audit public privacy boundary\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'"),
    ("      - name: Export allowlisted public site\n        if: steps.build.outputs.skipped != 'true'",
     "      - name: Export allowlisted public site\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'"),
    ("      - name: Publish clean public mirror\n        if: steps.build.outputs.skipped != 'true'",
     "      - name: Publish clean public mirror\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'"),
]
for old, new in repls:
    if new not in y:
        if old not in y:
            raise SystemExit('downstream stale-guard anchor missing: ' + old.splitlines()[0])
        y = y.replace(old, new, 1)

old_fail = "if: steps.build.outputs.skipped != 'true' && steps.publish.outcome == 'failure'"
new_fail = "if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true' && steps.publish.outcome == 'failure'"
if old_fail in y and new_fail not in y:
    y = y.replace(old_fail, new_fail, 1)

wf.write_text(y, encoding='utf-8')