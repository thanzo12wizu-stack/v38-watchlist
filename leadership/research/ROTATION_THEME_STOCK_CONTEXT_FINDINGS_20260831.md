# Rotation Theme → Stock Context Findings — 2026-08-31

Research-only. No production UI, main branch, V38 Gate, ranking, exit, or TQQQ rule is changed by this work.

## Reproducibility

- Research branch: `research/rotation-exact-flow-internals-20260831`
- Final workflow run: `33356232757`
- Final artifact: `9745299695` (`rotation-theme-stock-context-research`)
- Leadership market as-of: `2026-08-28`
- Leadership coverage: 3,858 source-universe stocks; 3,828 with valid market data; RS63 3,778; RS189 3,613; confidence `HIGH`.
- Current ETF membership: exact current provider holdings.
- Important limitation: the existing Leadership JSON exports up to 15 stocks per group. Counts below are **ETF membership ∩ exported group top-15**, not full-universe coverage.
- Legacy Leadership `entry` metadata is deliberately excluded from Rotation outputs. Formal V38 Eligibility/Ranking remains a separate layer.

## Current Industry → Theme → Stock context

### XBI — CURRENT_STRENGTH

- Rotation: Price 93.3 / Internal 80.0 / Internal Δ20 +53.3pt.
- Exact 20D Fund Flow: +$981.8M.
- Current holdings: 148.
- Intersections with existing Leadership group top-15: 27.
- Existing EMERGING/LEADING leaders in the intersection: 4.
- Concentration of the current top-down context: **Medical - Development Biotech / EMERGING**.
- Existing Leadership leaders in that group and in XBI: `CADL`, `IMMX`, `REPL`, `ACHV`.
- These are context candidates only. No Rotation buy signal or V38 Entry decision is created here.

Interpretation: XBI is the cleanest current example of Sector/Industry context and existing Theme leadership pointing in the same direction. The evidence is current-state evidence, not proven predictive Alpha from Industry-level PIT history.

### XME — EARLY_ROTATION_WATCH

- Rotation: Price 43.3 / Internal 93.3 / Internal Δ20 +73.3pt.
- Exact 20D Fund Flow: +$334.2M.
- Current holdings: 40.
- Intersections with existing Leadership group top-15: 19.
- Existing EMERGING/LEADING leaders in the intersection: 2.
- Current EMERGING group represented inside XME: **Energy-Coal**.
- Existing leaders: `SXC`, `HCC`.

`FCX` is an XME constituent and an existing Leadership leader, but its current group (`Mining-Metal Ores`) is `LOSING`, not EMERGING/LEADING. Therefore the illustrative chain "Materials → Copper → FCX" is **not confirmed by the current data** and must not be manufactured.

Interpretation: XME remains WATCH. Internal participation and Flow are ahead of Price, but the currently emerging sub-theme is Coal rather than a broad Metals/Copper confirmation.

### SOXX — INTERNAL_WEAK_FLOW_OUT

- Rotation: Price 53.3 / Internal 26.7.
- Exact 20D Fund Flow: -$3.632B (-8.71% of AUM).
- Current holdings: 30.
- Intersections with existing Leadership group top-15: 21.
- Existing EMERGING/LEADING leaders in the intersection: **0**.
- Semiconductor groups represented in the intersection are currently `LOSING`.

Examples such as `NVDA`, `AMD`, `MU`, `INTC`, `AMAT`, `LRCX`, `KLAC`, `TSM` can retain strong long-horizon RS in places, but the current short/intermediate Leadership context is not confirming a new semiconductor leadership wave.

Interpretation: the top-down chain correctly refuses to turn residual price/long-RS strength into a current Theme/Stock leadership call when Internal participation and Fund Flow disagree.

### IGV — INTERNAL_LEAD_WATCH

- Rotation: Price 50.0 / Internal 86.7 / Internal Δ20 0.0pt.
- Exact 20D Fund Flow: **+$80.1M**.
- Current holdings: 106.
- Intersections with existing Leadership group top-15: 66.
- Existing EMERGING/LEADING leaders in the intersection: 10.
- Strong current groups represented inside IGV:
  - **Comp Sftwr - Enterprise / EMERGING**: `RNG`, `TEAM`, `FIVN`, `PATH`, `MANH`, `CRM`, `BRZE`
  - **Computer Sftwr-Database / EMERGING**: `ZETA`, `ESTC`, `BOX`

The earlier illustrative hypothesis "IGV ETF outflow but strong internals = Redemption Divergence" is **not the current state** because current exact 20D IGV Flow is modestly positive. The system should therefore say `INTERNAL_LEAD_WATCH`, not force the old example label.

Interpretation: software internals are much stronger than price momentum and several existing Leadership groups are emerging. This is useful context, but not a Rotation-created Entry signal.

## What this proves operationally

The research pipeline can now reproduce the intended hierarchy without adding a second stock-ranking system:

`Exact ETF Flow + Price + Internal` → `Rotation state` → `current ETF membership` → `existing Leadership group phase` → `existing Leadership Leader/Pioneer + RS context`.

It also correctly produces negative evidence:

- XME does not automatically become "Copper → FCX" merely because XME Flow/Internal improve.
- SOXX does not surface semiconductor leaders merely because some long-horizon RS remains high.
- IGV is not called Redemption Divergence when current exact Flow is positive.

## Guardrails retained

1. Industry ETF internal history still uses current holdings backcast until live history matures; SOXX/IGV historical iShares `asOfDate` was not PIT-capable in QA.
2. Industry states are context/WATCH diagnostics, not predictive trading signals.
3. No Rotation stock score is introduced.
4. No legacy Leadership Entry status is exposed through the Rotation join.
5. Formal V38 Eligibility/Ranking, NQSAR/Breadth permission, exits, TQQQ, and Gross100 remain untouched and separate.
