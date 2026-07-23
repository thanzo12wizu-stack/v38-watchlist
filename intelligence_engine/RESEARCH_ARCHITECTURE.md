# V38 Historical Research Architecture — Phase 1–8

## Purpose

The research layer discovers and validates entry candidates by combining:

1. point-in-time financial change,
2. relative-strength level, acceleration and persistence,
3. technical entry quality,
4. forward expectancy and downside paths,
5. data confidence and explicit hard blocks.

It does not replace the existing Command Center. It adds a research and selection engine beside it.

## Point-in-time rule

A historical trading date may use a financial observation only when:

```text
available_at <= trading_date
```

`available_at` is the SEC filing date when available. Period end alone is never treated as the date on which the market knew the result. Direct quarterly facts take priority. Cumulative H1/9M facts may be converted to a quarter only by subtracting an earlier cumulative observation from the same fiscal start.

Every fact retains ticker, metric, value, period start/end, filing date, available date, form, accession, accounting standard, source, provider, derivation flag and confidence.

## Five-year storage model

The repository does not commit plaintext research data. The private workflow keeps five rolling calendar years in encrypted, year-partitioned bundles.

```text
data/intelligence/research/
  facts/year=YYYY.jsonl.gz
  signals/year=YYYY.jsonl.gz
  outcomes/year=YYYY.jsonl.gz
  rankings/year=YYYY.jsonl.gz
  manifest.json
  expectancy.json
  current_rankings.json
```

The workflow encrypts each annual partition separately. This avoids a single file growing beyond GitHub's practical file-size limits and allows a damaged or missing year to be rebuilt independently.

Full OHLCV is not duplicated into the research store. It remains in the resumable price cache and can be rebuilt through a licensed price provider later. The compact store preserves the facts, candidate state and forward labels required to reproduce research conclusions.

## Feature families

### Financial quality

- EPS and revenue growth
- gross and operating margin direction
- FCF growth and FCF margin
- dilution quality
- cash, debt and net cash when available
- growth stability and evidence coverage

### Financial change

- EPS acceleration
- revenue acceleration
- margin change
- FCF change
- financial phase transition

### Leadership quality

- QQQ-relative RS21/63/126/189/252
- 21-day RS change and slope
- RS63/126/189 rank change
- top-10/top-20 persistence
- downside resilience
- sector and industry relative strength

### Entry quality

- trend alignment
- pivot distance and pivot quality
- contraction and participation
- supply risk
- extension
- stop distance
- reward/risk

## Archetypes

Financial phases:

- `ACCELERATING`
- `COMPOUNDING`
- `INFLECTING`
- `STABLE`
- `DECELERATING`
- `MARGIN_PRESSURE`
- `DILUTING`
- `DATA_INSUFFICIENT`

RS archetypes:

- `NEW_LEADER`
- `ACCELERATING_LEADER`
- `ESTABLISHED_LEADER`
- `REACCELERATING`
- `FADING_LEADER`
- `FALSE_LEADERSHIP`

Candidate archetypes:

- `EMERGING_LEADER`
- `QUALITY_COMPOUNDER`
- `FUNDAMENTAL_BREAKOUT`
- `REACCELERATION`
- `TURNAROUND`
- `DETERIORATION_ALERT`

## Outcome labels

Signals receive 5/10/21/63-session labels when settled:

- absolute return
- QQQ excess return
- MFE and MAE
- stop hit
- +25% target hit and time to target
- progress/pivot level hit and time to progress

The outcome date must precede any training cutoff used by walk-forward validation.

## Expectancy qualification

Research is grouped by archetype, setup, regime, financial phase, RS phase and risk buckets. Each group reports sample count, win rate, mean/median excess return, P10/P5 downside, profit factor, MFE/MAE, stop/target rates, bootstrap confidence interval and concentration.

- `QUALIFIED`: sufficient sample, positive mean and positive bootstrap lower bound
- `PROMISING`: positive mean with moderate sample, not yet approved as an edge
- `EXPLORATORY`: insufficient or unstable evidence

Only `QUALIFIED` expectancy can materially adjust the composite rank. `PROMISING` receives a smaller adjustment. Missing expectancy is neutral.

## Phase 8 ranking

The ranking keeps separate components:

```text
Fundamental Quality
Fundamental Change
Leadership Quality
Entry Quality
Risk Fit
Expected Edge
Data Confidence
```

Hard blocks remain outside the score:

- broken long trend
- stop too wide
- reward/risk too low
- fundamental deterioration
- fading or false leadership
- earnings window when known

## Backfill operation

Manual workflow inputs support:

- incremental daily research,
- five-year price extension in bounded ticker batches,
- an optional calendar year for bounded signal rebuilding,
- configurable trading-day stride.

Recommended initial population is year-by-year and batch-by-batch. Re-running the same year is safe because annual partitions are upserted by stable keys.

## Known limitation

Until a licensed point-in-time universe including delisted securities is connected, historical results are exploratory and retain survivorship bias because the current universe is projected backward. The provider interfaces are deliberately separated so that a licensed FMP or other vendor feed can replace price, estimate, event and ownership inputs without changing the research contracts.
