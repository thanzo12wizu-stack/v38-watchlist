# Investment Intelligence Engine — Architecture Contract v1.0

## 1. Purpose

Build an app-ready investment intelligence foundation while preserving the existing Command Center as an independent consumer. The engine owns facts, normalized features, scores, history and stable JSON contracts. The dashboard remains presentation-only and must never become the source of truth.

## 2. Non-negotiable safety boundary

- `build_dashboard.py`, existing workflows, portfolio state and current HTML generation are not dependencies of the engine.
- The engine writes only below `data/intelligence/`.
- Missing or failed intelligence output must not prevent the existing dashboard from building.
- Consumers must treat intelligence JSON as optional and versioned.
- Raw SEC bulk data is cached, never committed.
- No AI-generated claim is mixed into factual fields.

## 3. Data flow

```text
Repository price cache + universe
          SEC Company Facts
                 |
                 v
        source adapters
                 |
                 v
       normalized facts layer
                 |
                 v
        feature computation
                 |
                 v
     cross-sectional ranking
                 |
                 v
       archetype score layer
                 |
                 v
 versioned JSON + dated history
                 |
        +--------+--------+
        |                 |
 Command Center      future API/app
```

## 4. Layers

### L0 — Source adapters

Inputs are repository-owned price/universe files and public filing data. Every adapter must expose diagnostics and fail with a clear contract error rather than silently guessing structure.

### L1 — Normalized facts

Facts are point-in-time values with source, period end, filing date and accession where available. Cumulative fiscal values must not be presented as standalone quarters. Direct-quarter observations take precedence over derived quarters.

### L2 — Features

Initial feature families:

- Price leadership: QQQ-relative 21/63/126/189/252-day returns
- Leadership acceleration: 21-day change in each RS horizon
- Tradability: price, ADR%, dollar volume and relative volume
- Position: 52-week-high distance
- Earnings: EPS growth and acceleration
- Demand: revenue growth and acceleration
- Operating quality: gross and operating margin direction
- Cash generation: FCF growth
- Capital structure: share-count change and dilution flags

Every feature may be missing. Missing values are not automatically bearish.

### L3 — Scores

Scores are cross-sectional percentiles from 0 to 100 and include data confidence. Initial archetypes:

- Candidate: balanced leadership and fundamental improvement
- Emerging: short/intermediate leadership acceleration plus improving fundamentals
- Compounder: durable earnings, margins, cash generation and longer-horizon leadership
- Breakout: leadership, liquidity, participation and proximity to highs
- Turnaround: measurable rate-of-change improvement from a weaker base

Weights are configuration, not hard-coded product truth. They must later be validated against forward excess returns and downside behavior.

### L4 — History and change detection

Store dated compact snapshots. Change detection is a first-class feature:

- score changes
- RS-rank changes
- earnings and revenue acceleration changes
- margin-direction changes
- newly appearing or disappearing data

### L5 — Narrative extensions

Future AI output is stored separately from facts and scores with model/version/time/source metadata. Planned objects:

- bull case
- bear case
- catalysts
- risks
- moat and competitive position
- story strength and story change

Narrative must never overwrite raw facts.

### L6 — Institutional and estimate extensions

13F, insider activity, buybacks, issuance and paid estimate-revision feeds plug into separate adapters. Absence of a paid estimate feed must be explicit; it must not be proxied with fabricated estimates.

## 5. Stable output contract

`data/intelligence/index.json` is the lightweight discovery endpoint.

Required top-level fields:

- `schema_version`
- `generated_at`
- `stocks`

Each stock requires:

- `ticker`
- `features`
- `scores`
- `confidence`

Detailed ticker files may add fields but must not break the index contract. Breaking changes require a new schema major version.

## 6. Consumer contract

The existing dashboard may later load `index.json` behind a feature flag:

1. File absent: render unchanged legacy dashboard.
2. File invalid: log warning and render unchanged legacy dashboard.
3. File valid: add an isolated Intelligence view only.

No legacy selection, allocation, stop or portfolio logic may depend on intelligence scores until separately backtested and approved.

## 7. CI gates

Pull requests:

- install package
- run isolated tests
- inspect real repository input shapes without mutation
- upload diagnostics artifact
- never download SEC data
- never write or commit generated intelligence data

Default branch/manual schedule:

- repeat validation
- refresh/cache SEC data when required
- build sidecar
- validate JSON contract
- commit only `data/intelligence/`

## 8. Validation roadmap

Before using a score for trading decisions, evaluate 5/10/21/63-day forward returns against QQQ and industry peers, including win rate, average excess return, adverse excursion, tail loss, turnover and regime stability. Weight changes must be walk-forward and versioned.

## 9. App readiness

The JSON contract is designed to map later to endpoints such as:

- `/v1/stocks/{ticker}`
- `/v1/rankings/emerging`
- `/v1/rankings/breakout`
- `/v1/changes/story`
- `/v1/search`

The future app must consume the same contract as the dashboard; it must not scrape rendered HTML.

## 10. Version policy

- Architecture contract: semantic versioning
- Output schema: independent semantic versioning
- Score configuration: explicit version and effective date
- Data and narrative provenance: retained per observation

This document is the design source of truth. Implementation changes that violate it require an explicit architecture revision rather than an ad hoc exception.
