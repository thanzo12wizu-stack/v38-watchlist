# Research Operations

## Production policy

- Price and research retention: 10 years
- Primary expectancy window: 8 years
- Comparison windows: 10 / 8 / 5 / 3 years
- Forward horizons: 5 / 10 / 21 / 63 trading sessions
- Daily signals: retained for display
- Learning samples: first occurrence, then a 5-trading-session cooldown for the same ticker, archetype and setup
- Historical ranking: only outcomes available before each ranking date may be used

## Required GitHub settings

### `V38_PRIVATE_DASHBOARD_PASSPHRASE`
Required. Encrypts Intelligence, Research Dashboard, operational state and yearly research partitions.

### `SEC_USER_AGENT`
Required for a full SEC Company Facts refresh. Use a descriptive value containing an application name and a monitored contact address. Do not paste it into issues, source files or chat logs.

### `V38_PORTFOLIO_CSV_B64`
Required only for live portfolio actions. Build a CSV matching `portfolio.example.csv`, Base64-encode it locally, and store only the encoded value as an Actions secret. The workflow writes `portfolio.csv` only inside the runner and deletes it before commit.

### Optional price provider

- Variable: `V38_PRICE_PROVIDER`
- Secret: `FMP_API_KEY`
- Variable: `V38_FMP_PRICE_URL_TEMPLATE`

When they are absent, the configured default price adapter remains active. Provider absence must not be represented as a negative fundamental signal.

## Ten-year bootstrap

`Bootstrap complete ten-year research` automatically runs once when its workflow is first merged. It queues:

1. 14 bounded price-history warmup runs, at most 250 tickers per run.
2. One point-in-time research run for every year in the latest ten-year range, oldest first.

All Intelligence Engine builds share a non-cancelling concurrency group, so queued runs are processed serially. Each run saves the price cache immediately and resumes from the next short-history ticker.

Normal operation after bootstrap:

- Weekdays: incremental latest-session research
- Wednesday and Saturday: one rotating bounded historical slice
- Every completed run: encrypted partitions and privacy-safe coverage status

## Completion checks

`research-run-status.json` is authoritative for aggregate completion.

- `research_status = PASS`: latest process and required outputs completed
- `backfill_status = COMPLETE`: Signal and Ranking partitions exist for all ten target years
- `missing_years = []`: no target year is missing
- `model_audit_status = PASS` or `BUILDING`: normalized expectancy is valid or still accumulating outcomes

`research-readiness.json` separately reports whether SEC and Portfolio secrets are configured. It contains booleans only.

## Public-site boundary

The public export allowlist contains only:

- `index.html`
- `command-center.html`
- `intelligence-dashboard.html`
- `research-dashboard.html`
- `.nojekyll`
- `public-site-manifest.json`

Both private dashboards must be encrypted shells. JSON research data, operational history, external data, source code and portfolio files are excluded.

## Historical privacy

`privacy-audit-status.json` separates two questions:

1. Is the current main tree clean?
2. Do old reachable Git refs contain former private-data paths?

The current-tree check is a hard gate. Historical exposure is reported as `REVIEW_REQUIRED` because deleting old public history is irreversible and cannot guarantee removal from prior clones, forks or caches.

The preferred final topology is:

- Private source repository: code, workflows, encrypted state
- Clean public Pages repository: allowlisted HTML only

After the clean mirror is verified, make the source repository private. A history rewrite is a separate destructive operation and should only be performed with a verified backup and an explicit decision to invalidate old clones and branches.
