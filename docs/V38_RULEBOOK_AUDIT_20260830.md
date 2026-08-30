# V38 運用ルール全面再監査（2026-08-30）

## 結論

通常個別株の最新版は、`NQSAR + 全株50MA Breadth` による4 Mode、日次候補更新、Attack時のStock70/LOO Peer Theme30、Selective時のRS189、終値判定の−8%・+24%で25%一回・Peak Close−30%、Redの次回寄り全退避で整合した。

TQQQはRun `33080590798` の候補 `M30_TOUCH30_F80_D10` を特定した。厳密にはStrict Crash Seed後の `age <= 30`（Seed日=0）に4H RSI `TOUCH30`、かつ新規発動日に `MC57>=20` を要求する。F80は固定80%ではなく、既存 `CURRENT30` hierarchy targetに対する80% Floor（`max(underlying target, 0.80)`）。Active中は`MC57<20`またはD10で終了する。

`CURRENT30`は常時30%固定ではない。Stage56 summaryの定義どおり「通常Exposure 30%と既存risk locksを含むhierarchy target」であり、Stage34由来のrisk lock・MC/NQSAR/Trend等で0%や別Exposureになり得る。Panic F80 overlay自体はNQSARをEntry Gateにしないが、Underlying `CURRENT30` hierarchyがNQSAR等を使うこととは両立する。

RSI30 Panic Resetの「Confirmation平均6.20%・Win 72.3%・PF 4.71」は、指定Run群の成果物から完全一致する1本を回収できなかった。このため研究候補としてMonitor表示に止め、自動売買へ接続しない。

既存 `command-center.html` と `build_dashboard.py` はユーザー指示により変更していない。監査版は `command-center-v38.html` として隔離した。旧Dashboardには旧Core12等の表示が残るため、監査版の運用根拠として使用してはならない。

## ステータス定義

| 表記 | 意味 |
|---|---|
| 研究で確認済み | 指定成果物内の同一Simulator比較・再計算で確認 |
| 研究候補 | 成果物は支持するが、OOS・データ・配分優先順位などの制約あり |
| 未確認 / NOT REPRODUCED | 指定数値または完全な実運用経路を再現できない |
| 本番実装済み | 独立した監査版EngineとUnit Fixtureに実装済み |

## Rule監査結果

| Rule | 研究 | 再現 | 実装 | 判定・備考 |
|---|---|---|---|---|
| Attack: Blue/Green + Breadth≥60 → 12 | 研究候補 | PASS | 監査版実装済み | 既存12保有を維持可能 |
| Selective: 50≤Breadth<60 → 新規保有可能総数4 | 研究候補 | PASS | 監査版実装済み | 既存8/5/4→追加0、既存3→1、既存0→4。4超を強制Trimしない |
| Stop: Breadth<50 / Yellow | 研究候補 | PASS | 監査版実装済み | 新規0、既存継続 |
| Defense: Red | 研究候補 | PASS | 監査版実装済み | 通常個別株のみ次回寄り全退避 |
| Red解除後の即時復帰 | 研究候補 | PASS | Fixture済み | FTD/MC57/3日/5日待ちなし |
| 全株50MA Breadth | 研究で確認済み | PASS | 監査版実装済み | 57ETF Breadthを二重Gateにしない |
| Breadth coverage guard | 研究コード確認 | PASS | 監査版実装済み | 不足時は新規だけfail closed |
| Eligibility | 研究で確認済み | PASS | State builder実装済み | Price≥5、DVOL≥10M、50>200、Close>200、RS189/63≥85、小型Clinical Biotech除外 |
| Attack Stock70 / Theme30 | 研究で確認済み | PASS（研究値） | LIVE DATA REQUIRED | 静的旧DashboardにLOO履歴がないため近似せず空欄 |
| LOO Peer Theme | 研究で確認済み | PASS | LIVE DATA REQUIRED | 自己寄与除去は確認。現在taxonomyの過去適用問題とは別 |
| Theme Full3 | 研究で確認済み | PASS | LIVE DATA REQUIRED | RS63 + 20d Acceleration + Breadth21の等加重 |
| Granular Theme | 研究で確認済み | PASS | Schema準備 | Broad Sector加点なし。min5/min10でedge低下 |
| Selective RS189 ranking | 研究で確認済み | PASS | 監査版実装済み | Theme加点なし |
| 日次候補更新 | 研究で確認済み | PASS | 監査版は旧Dashboard更新時に再計算 | 隔週待ちを不採用 |
| Rank/Theme低下売却なし | 研究で確認済み | PASS | Engine/Fixture済み | Top12外・Breadth低下・Yellowも売却理由にしない |
| −8% initial stop | 研究で確認済み | PASS | Engine/Fixture済み | 当日終値≤Entry×0.92でSignal、次営業日寄り全売却 |
| +24%で25%一回 | 研究で確認済み | PASS | Engine/Fixture済み | 初回当日終値≥Entry×1.24でSignal、次営業日寄り25%売却。Signal時点では未約定 |
| Peak Close−30% | 研究で確認済み | PASS | Engine/Fixture済み | Final=max(Entry×.92,最高終値×.70)。Intraday High不使用、次営業日寄り残り全売却 |
| Partial後のEntry/Peak継続 | 研究仕様 | PASS | Engine/Fixture済み | Entry PriceとPeak Closeをリセットしない |
| BE8 | 棄却 | PASS | 未実装 | CAGR/MDD/Bootstrapで悪化 |
| 8週間強制保有 | 棄却 | PASS | 未実装 | Bootstrap約48.5%、複雑性に見合わず |
| 10SMA/21EMA/ATR2通常Exit | 棄却 | PASS | 未実装 | 裁量Swingとは別ルール |
| RSI30 Panic Reset | 研究候補 | NOT REPRODUCED（見出し数値） | Monitorのみ | 自動売買未接続 |
| Theme-free RS189 RSI30 | 研究で確認済み | PASS | Monitor候補 | Main12枠へ混在させない |
| CURRENT30 hierarchy | 研究で確認済み | PASS（定義） | LIVE DATA REQUIRED | 常時30%固定ではない。通常Exposure30%＋既存risk locks/hierarchy |
| Strict Crash Seed | 研究で確認済み | PASS | Engine/Schema済み | VIX≥23、ATR乖離≤−0.5、10d DD≤−2% |
| `M30_TOUCH30_F80_D10` Entry | 研究候補 | PASS | Engine/Schema済み | `age<=30`（Seed day=0）＋TOUCH30＋MC57≥20。RISE30ではない |
| F80 Floor | 研究候補 | PASS | Engine/Fixture済み | `max(CURRENT30 hierarchy target, 80%)`。80.0%固定ではない |
| D10 / MC57<20 Exit | 研究候補 | PASS | Engine/Fixture済み | Active中。いずれも次回寄り |
| Panic overlayとNQSAR | 研究コード確認 | PASS | Engine/文言済み | Panic発動をNQSARで禁止しない。Underlying hierarchyのNQSAR使用は残る |
| Gross≤100% / Allocation | 研究候補 | NOT REPRODUCED（Priority） | Requested/Executable分離表示 | 他Sleeveの自動Trim順位は未実装。F80本番配分は未完成 |

## 使用したRun / Artifact / Commit

| 研究 | Run ID | Artifact ID | Script commit | Workflow commit |
|---|---:|---:|---|---|
| Theme Ranking | 33231641311 | 9708723800 | c90c42b85226b43c89dcb28aef5e551fcfcab93a | bd0bf33489a7b37ae67082ce645ee61e74d337b3 |
| Theme Attack-only | 33232030266 | 9708841479 | 4c4ac21641b018512d6beff141232a6481bf956a | 97c1ce3128cbefc4a6304ee7d83c71f331ccd7b1 |
| Theme Group Size | 33232320424 | 9708955177 | 8cccd7c32b13f66b2a102b46c75cbdb475d027ef | 4f55ede83a345642ddb56b2478c6d72c3375c933 |
| Leave-One-Out | 33240190205 | 9711172105 | c840f907917ee15afddbb90208411a3b75bb7c72 / dtype 5482468a332709bb1069285c888d41cc9c21c014 | d8770ef89d9b634d81466da04879cf590d6879da |
| Theme Weight/Component | 33240520678 | 9711273297 | f43d24798500748e36a94e53b75984bd8f779fb2 | bae9a66f9de9a97579a05d036589cd3990bb31ed |
| Pair Ablation | 33240833226 | 9711365135 | 7d9f92033ec2f0c5d0c2b1170824bcba683fbdac | 8c75bde811225c7aafdc2075cd9919fe78aaa88b |
| Exit Trail | 33250255780 | 9714301604 | 90f1cccef4202c719d447d5239b57b6cc134c265 | db824c6c251927c6c39e5102f2733172657d9417 |
| Exit Sensitivity | 33250880314 | 9714502988 | e701ff9b776c3b1e723f44882f48ad9bc620a9a6 | 96c0e4d7a19ce2cb2dc5d654412275d938644296 |
| Exit Overlays | 33250923735 | 9714434710 | e687f8e702716924321173fb3fc1bed7912346d4 | d3ff1679cf6576829106ccb2e3f18382ffdbabc9 |
| RSI initial | 33056967545 | 9640423844 | 8c9959e31699a113da1130b62d79da9792d1a22a | 同commit内workflow |
| RSI strength final | 33130536827 | 9670229132 | 1b1d0e3b4f140e98257f18bb3e93c94eb9491ac9 | 同commit内workflow |
| Market RS189 integration | 33133427031 | 9671218139 | 22717429676301c2ec6cd8a767d04645d4153e33 | 同commit内workflow |
| TQQQ Stage56 | 33080590798 | 9649902954 | 4e0d813863f6663e09837de437e33cb9809f6a1b | 同commit内workflow |

TQQQのscript pathは `research/tqqq_stage56_mandate_portfolio_audit.py`、workflowは `.github/workflows/tqqq-stage56-mandate-audit.yml`、summaryは `tqqq_stage56_summary.json`。採用候補名は `M30_TOUCH30_F80_D10`。4H barは5分足から09:30–13:30と13:30–16:00（partial）を構成し、Wilder RSI14を計算する。`touch30=(RSI<=30) & (prior RSI>30)`で、`RISE30`とは別Variant。

通常個別株Mode最終候補はRun `33216929035`、Job `99002542944`、Artifact `9703815077`、commit `e42019f1e17e7e593e983098ff9b245274b6ddc5`、script `research/rulebook_v3/audit_normal_stock_final_robustness_v6.py`、Variant `FINAL_N4_NO_REPAIR`。日次候補比較はRun `33229660388` / Artifact `9708127211` / commit `20cfdaff216f7077c4c9f848cc62fba72762119a` / script `leadership/research/audit_ordinary_stock_rebalance_vs_trail.py` / Variant `TRAIL_DAILY_CANDIDATES`。RefillとPruneの分離はRun `33229961070` / Artifact `9708215997` / commit `cc3fc983635d46225fbacce1218a2f75c787f9b7` / script `audit_ordinary_stock_rebalance_isolation.py`、日次Refresh下のPrune廃止はRun `33230203593` / Artifact `9708309654` / commit `2a76f9b0b77f47a12909ef9dc28ca99aa3432245` / script `audit_ordinary_stock_prune_under_daily_refresh.py` / Variant `NO_BIWEEKLY_PRUNE`。

## 数値再現

通常個別株Theme/Exitのequity variant 65本を成果物から再計算し、65/65 PASS。最大絶対差はCAGR 0、MDD `2.22e-16`、Sharpe `1.33e-15`、Rolling252 positive ratio 0、Worst rolling252 `2.22e-16`。これは機械的再現性であり、将来CAGRの主張ではない。

LOO比較はRS189 baseline CAGR 21.60% / MDD −56.25% / Sharpe .732、LOO Theme30 Attack-only CAGR 28.70% / MDD −33.25% / Sharpe .985、block20 win約82%。サイトでは期待CAGRとして表示しない。

Market-wide RS189 RSI30はConfirmation平均約3.14%、Win約54.6%、MAE約−10.81%、Integrated max1 CAGR約3.61%、MDD約−2.54%を再現した。

RSI Run再確認では、Run `33130536827` の主Variant群に `RS63_TOP3_RISE30`、`RS63_TOP1_RISE30`、`DUAL_TOP3_RISE30`、Signal時Strength条件付きVariantがあり、Run `33133427031` にはMarket-wide `RS189 cutoff × RSI cutoff`、Portfolio `P4_RS_PRIORITY_NO_GROUP_CAP`、統合 `THEME_PRIORITY_MARKET_CAP0/1/2` がある。しかし指定Headline `+6.20% / 72.3% / PF4.71` と完全一致する単一Variantは成果物で特定できないため **NOT REPRODUCED** のまま、期待数値をルールブックから除外した。再現済みの4-slot年率寄与約`+2.3236%`・DD約`−1.6147%`は後続の統合成果物に由来する別結果で、Headline Confirmationとは結び付けない。

## 追加検証

既存成果物で十分な箇所は再バックテストせず、次だけ追加した。

1. 65 equity variantsの指標再計算。
2. Mode境界・Selective no-trim・coverage guardのFixture。
3. close→next-openの−8%、部分利確一回、Peak Close、Red override Fixture。
4. Strict Seed / `age<=30`（Day0含む）/ TOUCH30 / MC57 Entry・Exit / D10 / F80 Floor Fixture。
5. CURRENT30 Underlying、Panic requested、Other sleeves、Available capacity、Executable targetの分離Fixture。
6. 既存Dashboardを入力にしたcompanion state builderが元HTMLを書き換えない回帰テスト。

## 最新ルールブック

1. TQQQのStage56比較基準は`CURRENT30` hierarchy（通常Exposure 30%＋既存risk locks）で、常時30%固定ではない。
2. 通常個別株ModeはAttack 12 / Selectiveの新規保有可能総数4 / Stop新規0 / Defense次回寄り全退避。Selectiveは既存4超をTrimせず、4以上から追加もしない。
3. AttackはStock RS189 70% + LOO Peer Theme Full3 30%。Full3はPeer-only RS63 percentile・20日Rank Acceleration percentile・Peer Breadth21の等加重。複数Themeは有効Score最大、欠落は中立50。SelectiveはRS189。
4. 候補は毎営業日引け後更新、空き枠を次営業日寄りで補充。
5. Entry後は順位・Theme・Breadth低下・Yellowでは売らない。
6. Exitはすべて当日終値判定→次営業日寄り執行。−8%、初回+24%で25%、残75%を最高終値−30%。Partial後もEntry/Peakを維持し、NQSAR RedがPortfolio override。
7. RSI30 Resetは独立Sleeve。完全再現までMonitor。
8. Panic TQQQ候補は`M30_TOUCH30_F80_D10`。Strict Seed後`age<=30`（Seed day=0）＋TOUCH30＋MC57≥20で翌寄り発動し、Underlying targetを最低80%へ引き上げる。Active中MC57<20またはD10で終了。Panic overlayをNQSARで禁止しないがUnderlying hierarchyはNQSAR等を使う。
9. Gross≤100%。Requested F80とExecutable exposureを分離し、同時発火時の自動削減優先順位は未確認のため実装しない。よってPanic F80の資金配分は未完成。

## 実装ファイルとmain差分

| File | 変更 |
|---|---|
| `v38_rules.py` | 監査済み状態遷移を独立実装 |
| `build_v38_companion.py` | 既存HTMLをread-only入力にし、全株Breadth・Mode・Eligibilityを生成 |
| `v38-live-state.json` | 現在の監査版state |
| `command-center-v38.html` | 既存デザイン系統の別ページ。Mode、Capacity、Position、Candidate、TQQQ、RSI Resetを分離表示 |
| `tqqq-panic-state.example.json` | exact 4H routeの入力schema |
| `tests/test_v38_rules.py` | 運用ルールFixture |
| `tests/test_v38_companion.py` | 分離・coverage・ranking回帰 |
| `.github/workflows/dashboard.yml` | 既存Dashboard生成後に別stateだけを生成・検証・保存 |
| `scripts/export_public_site.py` | 既存URLを維持したまま監査版の別URLをallowlist追加 |

`command-center.html`、`build_dashboard.py`の差分は0。既存Dashboardは維持した。

## UI変更箇所

既存UIは変更なし。別ページに以下を追加した。

- Market Modeの現在値・理由・Breadth coverage・既存数・New Entry Capacity。
- 通常PositionのEntry / Current / Return / Peak Close / Initial Stop / Peak30 / Partial / Exit Trigger / Red override。
- CandidateのRS189 / RS63 / Peer Theme / Theme3要素 / Final Rank / Eligibility / Entry status。
- RSI30 RESETを独立カード化。
- TQQQ CURRENT30 hierarchy / Seed / Seed age / 4H TOUCH30 / MC57 Entry Gate・Active Exit / F80 Floor / Underlying・Requested・Other sleeves・Available・Executable / Hold days / VIX / ATR deviation / DD10。
- 既存Dashboardは同ページ内iframeまたは別画面で参照可能。

## テスト結果

- V38 Unit/Fixture: 30 PASS。全回帰では76 PASS。
- 全test実行では既存のworkflow inventory 2件がFAIL（one-off workflow残存 / artifact@v4）。今回差分以前からの既知不整合で、対象外workflowを勝手に削除していない。
- Python compile: PASS。
- HTML required IDs: PASS。
- Inline JavaScript syntax (`node --check`): PASS。
- `git diff -- command-center.html build_dashboard.py`: 差分0。
- Playwright visual screenshot: browser binaryが環境に無く未実施。HTML構造・JS構文検査で代替したが、最終公開前に実ブラウザ確認が必要。

## 既知の未解決事項

1. 現在の2026 Theme taxonomyを過去へ適用したtaxonomy lookahead。
2. Exact LOO Themeのlive計算にはpeer historical return、20日rank history、21EMA breadth historyが必要。旧静的Dashboardには無いためDATA REQUIRED表示。
3. RSI30 Panic Resetの指定見出し数値の完全一致。
4. Panic F80と他Sleeve同時発火時の削減優先順位。Requested/Executable計算は実装したが自動trimは未実装。Panic F80の本番資金配分は未完成。
5. TQQQ exact 4H data file `tqqq-panic-state.json` の定期生成・配信経路。
6. 既存Dashboardには旧ルール表示が残る。監査版へ本番切替するまでは混同リスクがある。

## Theme taxonomy lookahead

LOOは候補銘柄自身がTheme Return/Breadth/Accelerationを押し上げる自己循環を除去する。一方、2026年時点のTheme membershipを2016年等へ遡及適用する問題は除去しない。この二つは別のbiasである。historical taxonomy snapshotがないため、Theme overlayは「研究で確認済みの相対比較」かつ「taxonomy lookahead未解決」と表示する。

## 研究結果 → 採用ルール → 実装箇所

| Rule | Script / Variant | Run / Artifact / Commit | 採用・実装 |
|---|---|---|---|
| Breadth 60/50、Attack12 / Selective4 | `research/rulebook_v3/audit_normal_stock_final_robustness_v6.py` / `FINAL_N4_NO_REPAIR` | `33216929035` / `9703815077` / `e42019f1e17e7e593e983098ff9b245274b6ddc5` | `market_mode` |
| Selective強制Trimなし | 同上（`active_trim=False`） | 同上 | `new_entry_capacity`。既存8/5/4→0、3→1、0→4 Fixture |
| Red解除即復帰 | `audit_ordinary_stock_market_mode_robustness.py` / `SELECTIVE_4_OF_12` 対 `RECOVERY_SCHEDULED_ONLY` | `33219295140` / `9704668587` / `b99c83f2de33ea118e84ad6d6bfeca4e61c915f4` | `market_mode`。追加確認日なし |
| Daily candidate refresh | `audit_ordinary_stock_rebalance_vs_trail.py` / `TRAIL_DAILY_CANDIDATES` 対 `TRAIL_BIWEEKLY_CANDIDATES` | `33229660388` / `9708127211` / `20cfdaff216f7077c4c9f848cc62fba72762119a` | 旧Dashboard更新後に毎営業日state再生成 |
| Vacancyを翌寄り随時補充 | 同script（`len(pos)<capacity`ならlatest cacheから次Session Open） | 同上 | Capacity/UI。注文経路は次営業日寄り |
| RefillとPruneの分離 | `audit_ordinary_stock_rebalance_isolation.py` / `NO_PRUNE_DAILY_CANDIDATES_VACANCY_FILL` | `33229961070` / `9708215997` / `cc3fc983635d46225fbacce1218a2f75c787f9b7` | Rank低下をExit入力にしない |
| 隔週Rank Prune廃止 | `audit_ordinary_stock_prune_under_daily_refresh.py` / `NO_BIWEEKLY_PRUNE` 対 `WITH_BIWEEKLY_PRUNE` | `33230203593` / `9708309654` / `2a76f9b0b77f47a12909ef9dc28ca99aa3432245` | `evaluate_normal_close`にrank/theme入力なし |
| 全株50MA Breadth | Market-mode codeのvalid SMA50 denominator＋coverage guard | `33216929035` / `9703815077` | `build_v38_companion.build_state`。57ETFは追加Gateにしない |
| LOO Theme30 | `audit_ordinary_stock_theme_leave_one_out.py` / `LEAVE_ONE_OUT_THEME30_ATTACK_ONLY` | `33240190205` / `9711172105` / `c840f907…`＋dtype `5482468…` | Attack 70/30。候補自身をReturn/Accel/Breadth21から除外 |
| 複数Theme / 欠落 | 同script：`np.fmax`でmax、欠落時`use_ps=50.0` | 同上 | `select_peer_theme` / `attack_rank_score` / UI method欄 |
| Full3・Weight30 | `FULL_W30`、Pair ablation `FULL_W30` | `33240520678` / `9711273297`; `33240833226` / `9711365135` | `peer_theme_score`、Candidate schema。Live値はDATA REQUIRED |
| Initial/Partial/Peak30 Exit | Exit sensitivity / overlays：`PEAK30`, `PART25_R3` | `33250880314` / `9714502988`; `33250923735` / `9714434710` | 終値Signal→次Open execution、Partial後Entry/Peak維持 |
| BE8 / 8週 / 10SMA / 21EMA棄却 | Exit trail/overlay variants | `33250255780`, `33250923735` | 実装なし |
| RSI30 Headline | `RS63_TOP3_RISE30`等を再確認したが指定3数値一致なし | `33130536827` / `9670229132` | **NOT REPRODUCED**。Monitorのみ、期待数値非表示 |
| Market RS189 RSI30 | RS cutoff×RSI cutoff、`P4_RS_PRIORITY_NO_GROUP_CAP`、`THEME_PRIORITY_MARKET_CAP0/1/2` | `33133427031` / `9671218139` / `22717429676301c2ec6cd8a767d04645d4153e33` | Optional Monitor。Main12枠へ混在させない |
| Panic TQQQ | `tqqq_stage56_mandate_portfolio_audit.py` / `M30_TOUCH30_F80_D10` | `33080590798` / `9649902954` / `4e0d813863f6663e09837de437e33cb9809f6a1b` | `tqqq_panic_entry/exit`、F80 Floor、MC57 Entry/Exit、age≤30 Day0含む |
| CURRENT30 hierarchy | Stage56 summary `existing hierarchy target with 30% normal exposure and its risk locks` | 同上＋Stage34 `current_trace()` | 常時30%とは実装しない。Underlying targetはLIVE DATA REQUIRED |
| Gross 100 / Allocation | Stage56はstock/Resetとの売却優先順位を検証していない | NOT REPRODUCED | Requested/Other/Available/Executableを分離。自動Trimなし |
