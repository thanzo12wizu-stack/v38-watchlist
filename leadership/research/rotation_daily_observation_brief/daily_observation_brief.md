# V38 Rotation Daily Observation Brief — 2026-08-28

**RESEARCH ONLY / deterministic formatter / no LLM signal generation**

## 1. WHEN — Formal V38 Market Mode

- NQSAR: **Yellow**
- Breadth50: **54.24%**
- Market Mode: **STOP**
- V38 ACTION: **NORMAL ENTRY = 0。Rotation/Themeが強くても通常個別株の新規Entryはしない。**
- Rotation forced exit: **NO**

## 2. WHERE — Observation

- 20D Flow leaders: XBI +982M / XLI +381M / XME +334M / XLY +174M
- 20D Flow laggards: SOXX -3.63B / XLF -3.26B / XLK -1.09B / XLP -362M

### 本流候補 / Current Strength
_現在の価格・内部の同時強さ。将来Alphaや買いを意味しない_
- XBI: CURRENT_STRENGTH | Price 93.3 | Internal 80.0 (20D 53.3) | Flow20 +982M
- XLB: CURRENT_STRENGTH | Price 77.3 | Internal 81.8 (20D 45.5) | Flow20 +92M

### 保留 / Early & Internal Lead WATCH
_WATCH ONLY; price confirmation or broader alignment待ち_
- IGV: INTERNAL_LEAD_WATCH | Price 50.0 | Internal 86.7 (20D 0.0) | Flow20 +80M
- XLC: INTERNAL_LEAD_WATCH | Price 27.3 | Internal 81.8 (20D 63.6) | Flow20 -132M
- XME: EARLY_ROTATION_WATCH | Price 43.3 | Internal 93.3 (20D 73.3) | Flow20 +334M

### Flow流入・内部未追随
_WATCH ONLY; Flowだけで昇格しない_
- XLI: FLOW_INTERNAL_DIVERGENCE_WATCH | Price 63.6 | Internal 27.3 (20D -27.3) | Flow20 +381M

### 内部弱＋Flow流出
_弱化診断。Distributionとは断定しない_
- SOXX: INTERNAL_WEAK_FLOW_OUT | Price 53.3 | Internal 26.7 (20D 13.3) | Flow20 -3.63B
- XLP: INTERNAL_WEAK_FLOW_OUT | Price 59.1 | Internal 45.5 (20D 0.0) | Flow20 -362M
- XLRE: INTERNAL_WEAK_FLOW_OUT | Price 45.5 | Internal 18.2 (20D -18.2) | Flow20 -127M

### 分配警戒
_PIT検証条件に基づく警戒Context。Rotationによる強制売却なし_
- XLE: DISTRIBUTION_DETERIORATION_WARNING | Price 90.9 | Internal 72.7 (20D -27.3) | Flow20 -297M
- XLF: DISTRIBUTION_DETERIORATION_WARNING | Price 77.3 | Internal 63.6 (20D -27.3) | Flow20 -3.26B

### Redemption Divergence
_Flow流出だけでDistributionと誤分類しない_
- XLV: REDEMPTION_DIVERGENCE | Price 68.2 | Internal 90.9 (20D 18.2) | Flow20 -95M

### 崩れ
_PriceとInternalがともに弱い_
- XLU: WEAK_BREAKDOWN | Price 9.1 | Internal 9.1 (20D 0.0) | Flow20 -45M
- XLY: WEAK_BREAKDOWN | Price 22.7 | Internal 36.4 (20D -18.2) | Flow20 +174M

### Mixed / Hold
_方向不一致または閾値未達_
- XLK: MIXED_HOLD | Price 59.1 | Internal 54.5 (20D 27.3) | Flow20 -1.09B

### DATA REQUIRED
_上流入力不足_
- none

### Unknown upstream state
_未知stateは勝手に意味付けしない_
- none

## 3. WHY — Macro consistency hypotheses

- Facts: 米10年金利 4.73（20観測変化 -0.02） / 米10年実質金利 2.42（20観測変化 -0.05） / FRB Broad Dollar Index 118.06（20観測変化 -2.65） / VIX 14.43 / Fear & Greed 54 / neutral
- 仮説: Fear & Greed内部は分裂（Fear=market_momentum_sp500, stock_price_strength, safe_haven_demand / Greed=stock_price_breadth, put_call_options, junk_bond_demand）。Headline単独では市場内部を代表しない。
- DATA REQUIRED: DXY（FRB Broad DollarをDXYへ代用しない） / 米ハイイールド社債スプレッド / 米投資適格社債スプレッド

## 4. Theme → Stock — Formal V38 context

### IGV — formal eligible 4
- RNG | Rank 9 | RS189 97.60 | RS63 97.27 | strict LOO Theme: コラボレーションSaaS (81.12)
- FIVN | Rank 106 | RS189 90.38 | RS63 92.65 | strict LOO Theme: AIエンタープライズSaaS (62.19)
- PANW | Rank 122 | RS189 94.57 | RS63 88.99 | strict LOO Theme: 8. デジタルインフラ・先進テック (40.66)
- ZETA | Rank 126 | RS189 89.14 | RS63 90.21 | strict LOO Theme: AIデータ基盤/データクラウド (42.86)

### XBI — formal eligible 17
- MRNA | Rank 1 | RS189 99.74 | RS63 99.92 | strict LOO Theme: mRNA/ワクチン (85.57)
- TWST | Rank 2 | RS189 99.62 | RS63 99.54 | strict LOO Theme: ゲノミクス/シーケンシング (83.87)
- SLS | Rank 13 | RS189 99.96 | RS63 93.19 | strict LOO Theme: 6. バイオ・ヘルスケア (73.39)
- ERAS | Rank 15 | RS189 99.83 | RS63 92.98 | strict LOO Theme: 6. バイオ・ヘルスケア (73.45)
- IMMX | Rank 19 | RS189 99.10 | RS63 96.18 | strict LOO Theme: 6. バイオ・ヘルスケア (73.28)

### Existing Leadership context (no new Rotation rank)
- XLY: Leisure-Travel Booking→ABNB
- XLE: Oil&Gas-Field Services→SLB / Oil&Gas-Refining/Mktg→VLO / Oil&Gas-Refining/Mktg→MPC / Oil&Gas-Refining/Mktg→PSX
- XLV: Medical-Products→DXCM / Medical - Research→CRL / Medical - Research→RVTY / Computer Sftwr-Medical→VEEV
- XLK: Comp Sftwr - Enterprise→CRM
- XBI: Medical - Development Biotech→CADL / Medical - Development Biotech→IMMX / Medical - Development Biotech→REPL / Medical - Development Biotech→ACHV
- XME: Energy-Coal→SXC / Energy-Coal→HCC
- IGV: Comp Sftwr - Enterprise→RNG / Comp Sftwr - Enterprise→TEAM / Comp Sftwr - Enterprise→FIVN / Comp Sftwr - Enterprise→PATH / Comp Sftwr - Enterprise→MANH

## 5. V38 ACTION

- **NORMAL ENTRY = 0。Rotation/Themeが強くても通常個別株の新規Entryはしない。**
- WATCH ONLY: IGV / XLC / XME / XLI
- WEAK/FLOW-OUT WATCH: SOXX / XLP / XLRE — Distributionとは断定しない
- DISTRIBUTION WATCH: XLE / XLF — Rotationによる強制売却なし
- Formal eligible names above are context only; **BUY label is not generated**.

## 6. State transitions / Data quality

- State transition history: DATA REQUIRED / recorded history insufficient
- Input alignment: **OK** (Rotation=2026-08-28 / V38=2026-08-28)
- Industry internal trend history: CURRENT_HOLDINGS_BACKCAST_PROXY_UNTIL_LIVE_HISTORY_MATURES
- strict LOO taxonomy: CURRENT_S2T_NOT_PIT

### Guardrails
- No LLM or free-text model computes a signal; all labels come from upstream numeric state.
- Rotation contributes zero points to V38 ranking and is not a Gate.
- Industry ETF Rotation states are descriptive/WATCH only until PIT membership history is validated.
- INTERNAL_WEAK_FLOW_OUT is not relabeled Distribution; it remains a separate diagnostic state.
- DISTRIBUTION_WARNING and DISTRIBUTION_DETERIORATION_WARNING are warning/context states and never force a V38 exit.
- Formal eligible context is not BUY; entry still requires formal Market Mode, capacity, and next-open execution.
- Missing inputs remain DATA REQUIRED; no proxy is silently substituted.
