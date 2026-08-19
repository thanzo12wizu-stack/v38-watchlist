from pathlib import Path
import re

bp = Path('build_dashboard.py')
s = bp.read_text(encoding='utf-8')

# 1) Master universe: scan all eligible US listings once, then keep stock/dr after structured-type filtering.
old = '''        flt = [{"left": "type", "operation": "equal", "right": payload_type},
               {"left": "exchange", "operation": "in_range", "right": UNIVERSE_EXCHANGES},
               {"left": "market_cap_basic", "operation": "egreater", "right": UNIVERSE_MIN_MCAP},
               {"left": "close", "operation": "egreater", "right": UNIVERSE_MIN_PRICE}]
'''
new = '''        flt = [{"left": "exchange", "operation": "in_range", "right": UNIVERSE_EXCHANGES},
               {"left": "market_cap_basic", "operation": "egreater", "right": UNIVERSE_MIN_MCAP},
               {"left": "close", "operation": "egreater", "right": UNIVERSE_MIN_PRICE}]
        if payload_type:
            flt.insert(0, {"left": "type", "operation": "equal", "right": payload_type})
'''
if s.count(old) != 1:
    raise SystemExit(f'universe filter anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''    raw = []
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
new = '''    # Scan the exchange set once without a type filter. TradingView returns stock/dr/fund;
    # structured post-filtering below keeps only stock + dr and removes preferred/warrant/unit/right.
    # This avoids silently losing ADR/ADS/Registry Shares such as ASML/ARM/SKHY.
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
if s.count(old) != 1:
    raise SystemExit(f'universe raw-scan anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# 2) VWAP near = observation filter only. ADR20 adaptive: floor 2%, 0.5x ADR20, hard cap 5%.
old = '    near = bool(np.isfinite(dist) and abs(dist) <= 0.02)\n'
new = '''    # Observation-only near zone: adapt to ordinary 20-day average range, capped so
    # high-volatility names cannot be called "near" from structurally distant prices.
    # touch/support/reclaim semantics remain unchanged.
    try:
        _adr20 = (((aligned["h"] - aligned["l"]) / aligned["c"])
                  .replace([np.inf, -np.inf], np.nan).dropna().tail(20).mean())
        _adr20 = float(_adr20) if np.isfinite(_adr20) else 0.0
    except Exception:
        _adr20 = 0.0
    _near_threshold = min(0.05, max(0.02, 0.5 * _adr20))
    near = bool(np.isfinite(dist) and abs(dist) <= _near_threshold)
'''
if s.count(old) != 1:
    raise SystemExit(f'VWAP near anchor count={s.count(old)}')
s = s.replace(old, new, 1)

bp.write_text(s, encoding='utf-8')

# 3) Same-session stale-source protection in workflow.
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
if sync not in y:
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

          # Same-session stale-run guard: a later options/data-artifact commit is harmless,
          # but a later generation/input change means this run was built from obsolete logic.
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
if persist_new not in y:
    if y.count(persist_anchor) != 1:
        raise SystemExit(f'persist anchor count={y.count(persist_anchor)}')
    y = y.replace(persist_anchor, persist_new, 1)

# Downstream public steps must not publish a run deliberately skipped for source drift.
y = y.replace("if: steps.build.outputs.skipped != 'true'\n        run: |\n          python scripts/privacy_audit.py", "if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'\n        run: |\n          python scripts/privacy_audit.py", 1)
y = y.replace("- name: Export allowlisted public site\n        if: steps.build.outputs.skipped != 'true'", "- name: Export allowlisted public site\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'", 1)
y = y.replace("- name: Publish clean public mirror\n        if: steps.build.outputs.skipped != 'true'", "- name: Publish clean public mirror\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'", 1)
y = y.replace("if: steps.build.outputs.skipped != 'true' && steps.publish.outcome == 'failure'", "if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true' && steps.publish.outcome == 'failure'", 1)

wf.write_text(y, encoding='utf-8')
