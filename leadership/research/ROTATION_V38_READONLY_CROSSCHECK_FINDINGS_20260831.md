# Rotation → formal V38 read-only crosscheck — 2026-08-31

Research only. This document does not change main, UI, V38 gates, ranking, entries, exits, or TQQQ.

## Reproducible run

- Workflow: `Rotation V38 Readonly Crosscheck`
- Successful run: `33357516795`
- Artifact: `9745645274`
- Market / price as-of: `2026-08-28`
- Source universe: 3,858
- Daily history downloaded: 3,828
- Formal eligible names in whole universe: 128
- Structural small-clinical-biotech exclusions: 115
- strict LOO themes: 281 valid themes from current `sector_snapshot.json['s2t']`
- LOO taxonomy status: `CURRENT_S2T_NOT_PIT`

## Formal current Market Mode

- NQSAR: `Yellow`
- all-stock >SMA50 Breadth: `54.2404%`
- breadth valid: 3,785 / observed 3,825
- Formal normal-stock mode: `STOP`
- New normal-stock entries: `0`

Therefore a positive Rotation state never overrides the formal V38 market gate. Existing positions are not force-trimmed merely because Breadth is 50–60%; Yellow stops new entries but is not a Rotation exit rule.

## Formal eligibility / ranking contract reproduced

Eligibility:

- Price >= $5
- 20-session dollar volume >= $10M
- SMA50 > SMA200
- Close > SMA200
- RS189 percentile >= 85
- RS63 percentile >= 85
- structural small Clinical Biotech exclusion: Biotechnology / Pharmaceuticals: Other AND market cap < $10B AND known revenue < $50M; missing revenue fails open

Attack ranking:

`0.70 * Stock RS189 + 0.30 * strict LOO Peer Theme Score`

Strict LOO excludes the candidate from all three Peer Theme components:

- Theme 63-session return percentile
- 20-session Theme-rank acceleration percentile
- Theme >21EMA breadth

Multiple memberships use the highest valid peer-only score. No valid Theme uses neutral 50 only in the final Attack rank calculation.

Selective ranking remains Stock RS189 only.

## Current Industry → formal V38 result

| ETF | Rotation state | Members | Formal eligible | New entries now |
| --- | --- | ---: | ---: | ---: |
| XBI | CURRENT_STRENGTH | 148 | 17 | 0 (Market STOP) |
| XME | EARLY_ROTATION_WATCH | 40 | 0 | 0 |
| SOXX | INTERNAL_WEAK_FLOW_OUT | 30 | 0 | 0 |
| IGV | INTERNAL_LEAD_WATCH | 106 | 4 | 0 (Market STOP) |

The `formal eligible` column means the stock passes the stock-level rules and would enter the formal ranking universe when market mode permits. It is not a BUY label.

## Highest current formal candidates inside these ETFs

### XBI

Top Attack ranks among current XBI holdings that pass formal Eligibility:

1. MRNA — RS189 99.74 / RS63 99.92 / strict LOO `mRNA/ワクチン` 85.69 / Attack score 95.53 / whole-universe Attack rank 1
2. TWST — RS189 99.62 / RS63 99.54 / strict LOO `ゲノミクス/シーケンシング` 83.99 / Attack score 94.93 / rank 2
3. SLS — rank 13
4. ERAS — rank 15
5. IOVA — rank 19
6. IMMX — rank 20

Other XBI formal-eligible names: ORKA, CDNA, RVMD, APGE, CGEM, TVTX, KYMR, ACHV, BHVN, TGTX, PTGX.

Important Theme/Leader intersections from the preceding Leadership-context research:

- IMMX: existing Leadership `Medical - Development Biotech = EMERGING`, formal V38 eligible, whole-universe Attack rank 20.
- ACHV: same EMERGING group, formal V38 eligible, Attack rank 79.
- CADL / REPL: existing Leadership leaders but fail formal V38 because of structural small-clinical-biotech exclusion and therefore receive no tradable-pool RS rank.
- MRNA: formal V38 rank 1, but its existing Leadership group (`Medical - Revenue Biotech`) was LOSING. This is a useful example that Theme/Leadership context and formal Stock selection are separate lenses.

### IGV

Formal eligible current holdings:

- RNG — RS189 97.60 / RS63 97.27 / strict LOO `コラボレーションSaaS` 81.12 / Attack score 92.66 / whole-universe Attack rank 9. Existing Leadership group `Comp Sftwr - Enterprise = EMERGING`, role LEADER.
- FIVN — RS189 90.38 / RS63 92.65 / strict LOO `AIエンタープライズSaaS` 62.19 / Attack rank 107. Existing group EMERGING, role LEADER.
- PANW — formal eligible but Peer Theme score is weaker; existing group is MATURE.
- ZETA — formal eligible; existing `Computer Sftwr-Database = EMERGING`, role PIONEER, but strict LOO score is weaker and Attack rank is 126.

Several visually strong IGV Leadership names are correctly rejected by formal V38 because RS189 < 85 despite strong shorter RS: TEAM, PATH, MANH, CRM, BRZE, ESTC, BOX.

## Why XME and SOXX do not become V38 buys

XME has zero formal-eligible current holdings. Examples:

- FCX: RS189 92.60 but RS63 73.15 → fails RS63 >= 85 despite strong `銅鉱山` strict LOO score 86.24.
- SXC: RS189 87.04 but RS63 69.16 → fails RS63.
- NEM: RS189 81.14 / RS63 72.90 and SMA50 not above SMA200.
- USAR: RS189 80.75 / RS63 3.95 and trend filters fail.

This confirms that `XME Early Rotation` stays WATCH only and cannot pull weak stocks through V38 Eligibility.

SOXX also has zero formal-eligible current holdings. Long-term RS remains high in several names, but short RS is weak across the leaders:

- MU: RS189 99.53 / RS63 28.53
- MRVL: 97.95 / 50.13
- AMD: 96.92 / 19.62
- ALAB: 94.61 / 13.57
- AMAT: 93.20 / 44.16

All fail RS63 >= 85. This is consistent with the independent `INTERNAL_WEAK_FLOW_OUT` Rotation warning and does not require Rotation to become a stock Gate.

## Guardrail conclusion

The intended hierarchy is now reproducible in a live research run:

1. Rotation = WHERE/context.
2. NQSAR + all-stock Breadth = WHEN.
3. Formal Eligibility + Stock RS189/RS63 = WHAT can enter the candidate pool.
4. Attack only: strict current-taxonomy LOO Peer Theme adds 30% to rank.
5. Rotation contributes zero points to ranking and never forces an exit.

On 2026-08-28 the hierarchy gives a particularly useful result: XBI has the strongest Rotation context and multiple high-quality formal stock candidates, but NQSAR Yellow makes the actual normal-stock action `NO NEW ENTRY` until the formal market mode reopens.
