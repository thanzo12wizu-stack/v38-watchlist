# Rotation Actionability Decision — 2026-09-05

Status: **RESEARCH COMPLETE FOR CURRENT ACTIONABILITY QUESTIONS**

Branch: `research/rotation-exit-overlay-20260905`

## Production decision

**No production V38 / Command Center / Leadership trading rule changes are justified by this research.**

Rotation should remain a **market-analysis / relative-opportunity-cost layer**, not a hard stock entry gate, individual-stock exit trigger, forced cash signal, or automatic sector-allocation rule.

The strongest reproducible result is narrower:

> A strong-looking sector whose constituent internals have deteriorated can subsequently lag SPY on a relative basis. This does not imply that the sector must fall in absolute terms, and it does not imply that a selected individual leader inside that sector should be sold or avoided.

## Decision table

| Proposed use | Decision | Evidence / reason |
|---|---|---|
| Sector Distribution warning as analytical context | **KEEP** | Strict PIT 11-sector evidence robustly identifies subsequent relative lag vs SPY. |
| Sell held V38 leader when its sector deteriorates | **REJECT** | Direct exits materially reduced CAGR and often cut leaders that continued higher. |
| Tighten V38 winner trail when sector deteriorates | **REJECT** | Strict PIT tighter trails did not improve realized exits; broad sensitivity was not robust. |
| Sell only after sector warning + stock SMA10 / EMA21 Low / RS63 / peak-DD confirmation | **REJECT** | Stock-confirmed variants did not robustly beat adopted exit; several were materially worse. |
| Block fresh V38 leader entries in warned sectors | **REJECT** | Strict PIT apparent W10 gain was only 3 blocked decisions with very low coverage and contradicted broad sensitivity; blocked names often rose strongly over 40–63 sessions. |
| Sell sector ETF to cash when Distribution warning appears | **REJECT** | Warning predicts relative lag, not reliable absolute loss; warned sector ETFs remained positive on average. |
| Move warned sector ETF allocation to SPY every time state changes | **REJECT AS TRADING RULE** | Zero-cost 2024+ results improved slightly, but turnover was high and 5 bp per traded dollar erased the advantage. Results were also not stable across discovery / recent periods. |
| Use Rotation to describe relative capital-efficiency / distribution risk | **KEEP** | This directly matches the robust PIT evidence without extrapolating it into unsupported stock actions. |

## Core strict-PIT evidence

### Distribution Trap

Definition: `PriceScore >= 70`, `InternalScore < 50`, `20D Flow/AUM <= 0`.

Prior strict PIT event study, 2024+:

- 20D sector excess vs SPY: about **-1.02%**
- 40D sector excess vs SPY: about **-1.72%**
- 27-neighbor parameter grid: negative at 20D and 40D throughout
- block-bootstrap and sector-cluster evidence supported the negative direction

This is the strongest warning state found.

### Internal deterioration

Definition family: high PriceScore with large 20-session InternalScore decline.

Baseline `PriceScore >= 70`, `Internal delta20 <= -20pt`, `Flow/AUM <= 0`:

- 2024+ 20D excess about **-1.03%**; one block CI crossed zero
- 2024+ 40D excess about **-2.17%**; stronger support
- parameter grid remained negative

Use as deterioration context, not as forced trading action.

## Individual-stock exit research

Workflow run: `33957889694`
Artifact: `9967023576`

Adopted-exit BASE reproduction, 2024+:

- CAGR **72.20%**
- MDD **-17.73%**

Rotation exit overlays:

- extra 25% profit-taking on W10 warning: CAGR about **70.31%**
- extra 25% profit-taking on W20 warning: about **70.37%**
- full exit on W20: about **65.77%**
- full exit after W10 persistence: about **65.15%**
- full exit on W20 + Flow out: about **67.48%**

Tighter 25% / 20% winner trails touched warnings but did not produce a useful improvement in the strict PIT run.

Important behavioral finding: sector deterioration frequently occurred **weeks before** the adopted stock exit. Median warning-to-adopted-exit delay was roughly 35 sessions, mean roughly 42 sessions. Strong leaders such as NVDA, META, WDC, STX, RCL and FICO could continue to run after sector deterioration.

Strict PIT coverage limitation: only about **11.5% of held position-days** had contemporaneous audited sector state; roughly **8.5% of trades** could be mapped under the strict historical S&P 500 membership guard. Therefore narrow stock-level PIT results must not be overgeneralized.

## Broad current-classification sensitivity

Workflow run: `33958265166`

Current-sector mapping is **look-ahead sensitivity only**, not primary evidence.

Latest mapping validation was roughly 84% coverage of common names and about 93% accuracy among classified names.

Almost all direct exit variants were worse. The only tiny positive case, dynamic 20% trail after W10 deterioration, moved 2024+ CAGR only from about 72.20% to 72.63% and had only about 56% block-bootstrap win probability. This is not robust enough for adoption.

## Sector warning + stock-confirmation research

Workflow run: `33958430511`
Artifact: `9967227083`

Tested sector warning followed by stock-specific confirmation:

- SMA10 break
- EMA21 Low break
- RS63 percentile < 85
- Peak drawdown 10%
- Peak drawdown 15%

No variant robustly improved the adopted exit. Several materially reduced returns. Conclusion: adding a stock confirmation does not rescue the sector-warning exit concept.

## New-entry block research

Workflow run: `33959234645`
Artifact: `9967461902`

Held stocks and all adopted exits were left unchanged; only new candidates in warned sectors could be skipped.

Strict PIT W10 deterioration block:

- 2024+ CAGR about **72.78%** vs BASE **72.20%**
- only **3 blocked decisions**
- block-bootstrap win probability about **68%**
- strict candidate mapping coverage was very low

Those three blocked names had mean 20D return around **-7.45%**, but mean 63D return around **+27.38%**.

Broad current-classification sensitivity contradicted the apparent strict-PIT gain:

- W10 block 2024+ CAGR about **68.33%** vs BASE 72.20%
- 46 blocked decisions
- deduplicated blocked candidates had mean 63D return about **+12.75%** and mean 63D maximum upside about **+40.4%**

Therefore sector deterioration must not be a hard gate for fresh leaders.

## Sector ETF absolute-vs-relative timing

Workflow run: `33959194682`
Artifact: `9967378464`

This test separates `sell to cash` from `lag SPY`.

For 2024+ Distribution Trap events (`n=46`), warned sector ETFs still produced positive average absolute returns:

- 20D: about **+0.96%**
- 40D: about **+1.63%**
- 63D: about **+2.80%**

But they lagged SPY:

- 20D excess: about **-1.18%**
- 40D excess: about **-1.62%**
- 63D excess: about **-2.19%**

The relative-lag confidence intervals remained negative under sector-cluster and time-block resampling.

Therefore the correct interpretation is **relative opportunity cost / rotation away risk**, not an absolute bearish or cash-exit forecast.

## Sector-allocation overlay research

Workflow run: `33959739983`
Artifact: `9967567294`

Independent QA: metrics were recomputed directly from the uploaded equity curves. Maximum absolute discrepancy vs the stored JSON metrics was approximately **3.3e-15**.

Design:

- equal target weight `1/11` across XLB/XLC/XLE/XLF/XLI/XLK/XLP/XLRE/XLU/XLV/XLY
- prior-close warning
- warned sector's `1/11` weight moved to SPY from the next open
- no threshold search; only previously researched warning definitions
- transaction-cost stress: 0 / 5 / 10 bp per warning-driven traded dollar

2024+ sector-EW BASE:

- CAGR **16.54%**
- MDD **-16.16%**
- Sharpe **1.23**

SPY benchmark:

- CAGR **21.43%**
- MDD **-19.77%**
- Sharpe **1.27**

### Zero-cost overlay

- W20 deterioration -> SPY: CAGR **16.97%**, bootstrap win probability vs sector EW about **71.6%**
- W20 + Flow out -> SPY: CAGR **16.95%**, win probability about **76.7%**
- Distribution Trap -> SPY: CAGR **16.79%**, win probability about **71.1%**

These are small improvements in the 2024+ confirmation slice, not broad robust dominance. Discovery and/or recent slices were inconsistent.

### With 5 bp per traded dollar

All three overlays fell below the sector-EW baseline:

- W20 -> SPY: CAGR **15.72%**
- W20 + Flow out -> SPY: **16.28%**
- Distribution Trap -> SPY: **16.05%**
- BASE: **16.54%**

The reason is turnover:

- W20: about **20.26x annual gross warning-driven traded notional**
- W20 + Flow out: about **10.26x**
- Distribution Trap: about **11.30x**

Thus the robust event-level relative-lag finding does **not** automatically translate into a profitable daily/state-change allocation rule after modest friction.

## Final interpretation for Rotation UI / analysis

Recommended semantics:

- `Distribution / deterioration warning` = **relative opportunity-cost risk / internals weakening while headline price remains strong**
- `Flow out` = supporting diagnostic, not a standalone sell order
- `5D / 10D participation change` = observation only
- `Internal lead / recovery` = observation; not early-buy validation
- held Leadership names = keep evaluating under their own V38 / Leadership stock rules

Do **not** translate Rotation into these statements without new evidence:

- “sell this leader now”
- “do not buy any leader from this sector”
- “move to cash”
- “this sector will fall”
- “rotate the portfolio automatically on every warning change”

## Theme56 limitation

The strongest causal/actionability evidence above is from an audited **11-sector strict-PIT** framework with historical sector membership and exact flow methodology. It is **not Theme56 PIT validation**.

Theme56 can display analogous patterns as evidence-aware context, but should label them as 11-sector PIT analogues / extrapolations rather than claiming Theme56-specific validated alpha.

## Final disposition

**KEEP Rotation as a descriptive, evidence-ranked market intelligence layer.**

**REJECT using Rotation as a V38 stock gate or stock exit rule.**

**REJECT forced cash exits and the tested high-turnover Sector-to-SPY allocation overlay.**

No production implementation is authorized by this research memo.
