# V38 Leadership Cycle 追加監査 2026-09-02

## Scope

- 本番/main/UIは変更していない。
- 研究branch: `research/leadership-cycle-audit-20260902`
- PIT event study: 2016-01-04 through 2026-08-31
- Universe downloaded: 3,595 symbols
- Discovery: through 2021-12-31
- Confirmation: from 2022-01-03
- Current production-style definitions were reconstructed for F1/F2/F3, Leader Temperature and Momentum Run.

## Reproducible runs

| Audit | Run | Artifact | Result |
|---|---:|---:|---|
| Full PIT leadership cycle | 33584137835 | 9829530088 | success |
| Red/depth/correction diagnostics | 33584647352 | 9829775298 | success |
| Modern-exit warning overlay | 33584888636 | 9829885352 | success |
| Threshold/matched-control/membership robustness | 33586052560 | 9830182374 | success |
| Broad combination audit | 33588638996 | 9831104161 | success |
| Prespecified 26-combination audit | 33589225177 | 9831261219 | success |
| Stress-to-regeneration robustness | 33589430869 | 9831351779 | success |
| Repair/regeneration transition audit | 33589923463 | 9831459103 | success |

## Final conclusions

### 1. Hard Gate remains NQSAR + stock 50MA Breadth

F1/F2/F3 overlays were tested on the current ordinary-stock mechanics using close-based -8% initial stop, +24% Partial25, Peak Close -30%, Red next-open exit, daily vacancy refill and one-way 0.1% cost.

The warning overlays did not improve the adopted portfolio. In the strict LOO Theme30 Attack comparison, reducing Attack capacity when F1+F2 were active reduced Confirmation CAGR by about 2.77 percentage points while Confirmation MDD was effectively unchanged. Block bootstrap probability of beating the baseline was about 4.2%.

Therefore F1/F2/F3 remain context indicators and must not be promoted to ordinary-stock Hard Gates.

### 2. F2 and Momentum Run are one information family

Spearman correlation between F2 and Momentum Run fade share:

- Full: 0.884
- Discovery: 0.872
- Confirmation: 0.897

Interpretation: F2 should be the quantitative Fade meter; Momentum Run is useful as the stock-level decomposition/detail, not a second independent vote.

### 3. F1 is an internal attrition indicator, not an independent trading predictor

F1 often appears earlier than later leadership damage: across correction-sequence tests F1 preceded F2 in about 70% of Discovery observations and 78% of Confirmation observations where both were present.

However, after matching controls by current NQSAR color, stock Breadth bucket, QQQ 20-session return bucket and Discovery/Confirmation split, F1>=30% did not show stable incremental 60-day QQQ return, DD10 or Red-transition information in Confirmation. Thus the useful interpretation is internal leadership attrition/context, not an exposure instruction.

### 4. F3 depth effect is largely regime-dependent

Unmatched/PIT tests still show high F3 states co-occurring with larger future drawdowns, especially in the recent sample. But F3 is strongly related to stock Breadth (Spearman about -0.61 full, -0.62 Confirmation).

After matching on NQSAR, Breadth and recent QQQ return, Confirmation F3>=60% had DD10 probability 35.3% versus 40.0% in matched controls; no stable incremental depth edge was confirmed. Therefore the old standalone 1.84x-style headline should not be presented as independent predictive power.

F3 can remain a descriptive `DAMAGE` meter: it explains how broad/deep leader damage is, but should not be sold as a separate forecast engine.

### 5. Leader Temperature is an exhaustion/context meter, not a bottom timer

The current rolling/PIT Temperature definition did not reproduce the old `median 18 days before bottom / ~60% hit` claim. QQQ >=10% correction episodes did not support that timing headline.

Low Temperature remains useful descriptively: it identifies unusually depleted leadership. But after matching on NQSAR, Breadth and recent QQQ weakness, neither Temp<=10 nor Temp<=15 produced stable independent Confirmation alpha. Therefore use `EXHAUSTION` language and remove any precise bottom-timing promise.

High Temperature remains descriptive strength; it should not be treated as a top signal.

### 6. F2>=40% + Temperature<=15 is robust as a stressed/exhaustion state, not as alpha

Frozen candidate: `F2>=40% AND Leader Temperature<=15`.

Unconditional 60-session QQQ return:

- Discovery: +9.34% mean, +9.74% median, n=12
- Confirmation: +8.87% mean, +10.20% median; 9 observations have a full 60-session horizon

QQQ minus SPY 60-session mean:

- Discovery: +1.93%
- Confirmation: +1.30%

But matched-control comparison removes the apparent independent edge:

- Discovery QQQ60 event-minus-matched: +0.98pp; 90% bootstrap interval -4.78pp to +6.72pp
- Confirmation QQQ60 event-minus-matched: -0.67pp; 90% bootstrap interval -7.04pp to +6.34pp

Therefore this combination is suitable only as a descriptive `DAMAGE × EXHAUSTION` state. It must not become an automatic buy, exposure increase, or Hard Gate.

### 7. Threshold neighborhood does not support precise optimization

F2 thresholds 30/40/50%, Temperature thresholds 10/15/20 and cooldowns 20/40 sessions were tested. The general pattern of positive medium-term returns after stressed/exhausted states appears in both Discovery and Confirmation, but matched-control excess is unstable and confidence intervals overlap zero.

Do not optimize a precise threshold from Confirmation. If the state is displayed, keep the simple frozen 40%/15 definition or present broader bands.

### 8. Membership perturbation weakens the alpha claim but preserves the stress-state interpretation

Deterministic cross-sectional membership perturbation for the frozen F2>=40% / Temp<=15 state:

| Universe fraction | Symbols | Confirmation QQQ60 mean | QQQ-SPY60 | DD10 probability |
|---:|---:|---:|---:|---:|
| 50% | 1,814 | +5.39% | +0.89% | 66.7% |
| 75% | 2,703 | +3.97% | -0.18% | 66.7% |
| 100% | 3,595 | +8.87% | +1.30% | 44.4% |

The return/excess magnitude is sensitive to membership, so it is not a robust alpha signal. The state remains associated with substantial drawdown risk and later recovery, which supports its use as market-context information.

This perturbation does not eliminate true survivorship bias. The repository does not contain a complete historical delisted/removed-stock PIT membership source, so that limitation remains explicit.

### 9. Leadership is not a rigid F1 -> F2 -> F3 -> Exhaustion chain

Correction-sequence pairwise ordering across 8/10/12% QQQ correction definitions:

- F1 before F2: Discovery 70%, Confirmation 77.8%
- F2 before F3: Discovery 50%, Confirmation 52.9%
- F3 before Exhaustion: Discovery 83.3%, Confirmation 93.8%
- F2 before Exhaustion: Discovery 62.5%, Confirmation 75%

Recommended architecture:

- `ATTRITION`: F1; often early internal leadership turnover
- `FADE`: F2, with Momentum Run as detail
- `DAMAGE`: F3; parallel damage dimension, not a guaranteed step after F2
- `EXHAUSTION`: low Leader Temperature; tends to occur late in deeper correction sequences

Do not implement these as an additive score or enforce a rigid state-machine order.

### 10. Additional combination search did not justify a new static composite signal

The later combination audits deliberately avoided an unrestricted threshold search.

- 26 prespecified economic combinations were tested across Discovery/Confirmation with matched controls, cooldown sensitivity and BH multiple-testing correction. Finalists: 0.
- 15 repair/regeneration transition candidates were tested against controls from the same transition family, with Discovery/Confirmation direction consistency, 95% bootstrap intervals and BH FDR q<=0.10 required. Finalists: 0.

Therefore no F1/F2/F3/Temperature AND-count, additive score, rigid sequence or warning-capacity rule should be added. Further retrospective combination mining is more likely to create overfit than useful independent information.

### 11. Leadership Regeneration is frozen only as a prospective OOS research candidate

A later exploratory audit found a plausible transition pattern after leadership exhaustion. Because this pattern was discovered retrospectively, Confirmation is robustness evidence rather than pristine OOS evidence. It is therefore not an adopted alpha signal.

To prevent future threshold drift, the research candidate is frozen on 2026-09-02 as follows:

1. **Prior exhaustion:** in the strictly prior 40 trading sessions, `Leader Temperature <= 15` occurred at least once.
2. **Fade repair today:** F2 crosses from `>=40%` on the previous session to `<40%` today.
3. **Market confirmation today:** NQSAR is `Blue` or `Green` and stock 50MA Breadth is `>=50%` (`ATTACK` or `SELECTIVE`).
4. **Event de-duplication:** use a 20-session cooldown for research event counting.
5. **Primary forward endpoint:** QQQ 60-session return versus a pre-specified matched control; QQQ-SPY 60-session excess and QQQ 60-session MDD are secondary context metrics. 20/40-session returns are diagnostic only.

The full-universe retrospective TEMP-only pattern had:

- Discovery: 7 events; available 60-session outcomes were positive in all 7; mean QQQ60 about +11.24%.
- Confirmation: 7 events; 6 had a completed 60-session horizon; those 6 were positive; mean QQQ60 about +8.00%.
- Matched-control QQQ60 difference was positive in both eras, but the standard split-matched 95% intervals still touched/crossed zero. A +/-2-year matched-control variant was stronger in Confirmation, but that does not convert retrospective discovery into prospective evidence.
- QQQ-SPY excess did not show a stable independent edge, so this should be interpreted as possible broad market/leadership repair rather than a Nasdaq-specific alpha claim.

`F3>=60%` OR low Temperature was also explored and produced some stronger recent-sample numbers, but F3 did not add sufficiently stable independent information. It is deliberately **not** included in the frozen forward candidate to avoid expanding degrees of freedom after seeing the data.

Do not change these frozen thresholds based on future retrospective re-optimization. Any revised candidate should be logged as a new version with a new forward-test start date.

### 12. Data-quality guard for live interpretation

The late-August/early-September diagnostic tail showed degraded stock-derived coverage in the research diagnostic path. It must not be used as the live source of truth for current F1/Breadth state. The production acquisition path remains the live-state source unless separately revalidated.

This data-quality issue does not create the frozen Regeneration result: the latest retrospective Regeneration event in the audited sample was 2026-08-06, before the degraded diagnostic tail.

## Adoption decision after the additional audit

1. Keep ordinary-stock Hard Gate unchanged: NQSAR + stock 50MA Breadth.
2. Do not use F1/F2/F3/Temperature to trim holdings or reduce new-entry capacity.
3. Merge the conceptual role of F2 and Momentum Run to avoid double counting.
4. Reword F3 as `Damage breadth/depth`, without independent 1.84x predictive headline.
5. Reword Leader Temperature low side as `Exhaustion`, removing 18-day/~60% bottom-timing language.
6. `F2>=40% + Temp<=15` may be displayed as `Damage x Exhaustion` context only; no automatic action.
7. No static combination or repair transition passed the final independent-signal criteria.
8. `Leadership Regeneration v1` is frozen for prospective OOS observation only; it is not a Hard Gate, exposure instruction, TQQQ trigger, ranking modifier, or production trading rule.
9. No production implementation is authorized by this audit itself.
