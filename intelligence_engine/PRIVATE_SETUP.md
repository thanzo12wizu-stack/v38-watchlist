# Private Intelligence Dashboard Setup

The detailed Intelligence Dashboard is designed for personal use. The public repository must never contain plaintext candidate JSON, portfolio data, observation history, external event data, or licensed price data.

## One-time required secret

Create the following GitHub Actions repository secret:

```text
V38_PRIVATE_DASHBOARD_PASSPHRASE
```

Requirements:

- at least 12 characters
- use a unique passphrase not used for another account
- do not store it in repository files, Actions variables, issues, or commit messages

The production workflow derives an encryption key with PBKDF2-SHA256 and encrypts the complete static dashboard and operational state with AES-256-GCM. The passphrase is entered in the browser and the dashboard is decrypted locally. It is not sent to a server.

Without this secret, the public URL shows only a locked placeholder and does not publish detailed intelligence data.

## Optional private portfolio input

The private portfolio CSV can be supplied through this Actions secret:

```text
V38_PORTFOLIO_CSV_B64
```

Create a CSV based on `portfolio.example.csv`, then base64-encode the entire file. The workflow decodes it only inside the runner and removes it before commit.

Supported fields:

```text
ticker
weight
entry_date
entry_price_1
entry_price_2
shares_1
shares_2
entry_stage
first_pivot_date
second_pivot_date
trail_method
partial_profit_done
strategy
```

## Current personal research provider

Default:

```text
V38_PRICE_PROVIDER=yfinance
```

This path is for personal research only. Price cache and detailed derived data are not committed by the Intelligence workflow.

## Future FMP migration

When a licensed Financial Modeling Prep plan is purchased, configure:

Repository Actions variable:

```text
V38_PRICE_PROVIDER=fmp
V38_FMP_PRICE_URL_TEMPLATE=<licensed endpoint template>
```

Repository Actions secret:

```text
FMP_API_KEY=<licensed API key>
```

The URL template is deliberately configuration-driven because FMP endpoints and plan entitlements may change. It must include `{symbol}` and may include `{from}`, `{to}`, and `{apikey}` placeholders.

Example shape only—not a promise that this endpoint is covered by a particular plan:

```text
https://example-provider-endpoint/{symbol}?from={from}&to={to}&apikey={apikey}
```

Before enabling FMP, verify the purchased plan permits the intended internal use, caching, derived analytics, and any form of display. The system does not treat API access as redistribution permission.

## Public/private boundary

Public and safe to keep in the repository:

- source code
- tests
- theme taxonomy
- empty portfolio template
- encrypted dashboard HTML
- encrypted operational-state bundle

Never commit in plaintext:

- `data/intelligence/`
- `data/external/`
- `portfolio.csv`
- paid provider responses
- API keys
- private dashboard passphrase

The production workflow enforces this boundary before pushing generated outputs.
