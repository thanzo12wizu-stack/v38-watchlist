# V38 運用ルール全面再監査（2026-08-30）

## 結論

通常個別株の最新版は、`NQSAR + 全株50MA Breadth` による4 Mode、日次候補更新、Attack時のStock70/LOO Peer Theme30、Selective時のRS189、終値判定の−8%・+24%で25%一回・Peak Close−30%、Redの次回寄り全退避で整合した。

TQQQはRun `33080590798` のStrict Crash Seed / 4H RSI TOUCH30 / F80 / D10 / MC57<20を特定した。F80はF100より絶対リターン最大という意味ではなく、下方リスクとの折衷候補である。NQSARをPanic TQQQのHard Gateにはしない。

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
| Selective: 50≤Breadth<60 → 新規上限4 | 研究候補 | PASS | 監査版実装済み | 4は保有上限ではない。既存8でも強制トリムなし |
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
| −8% initial stop | 研究で確認済み | PASS | Engine/Fixture済み | 終値≤Entry×0.92 → 次回寄り |
| +24%で25%一回 | 研究で確認済み | PASS | Engine/Fixture済み | 2回目は発火しない |
| Peak Close−30% | 研究で確認済み | PASS | Engine/Fixture済み | Intraday high不使用、残75%を次回寄り全売却 |
| BE8 | 棄却 | PASS | 未実装 | CAGR/MDD/Bootstrapで悪化 |
| 8週間強制保有 | 棄却 | PASS | 未実装 | Bootstrap約48.5%、複雑性に見合わず |
| 10SMA/21EMA/ATR2通常Exit | 棄却 | PASS | 未実装 | 裁量Swingとは別ルール |
| RSI30 Panic Reset | 研究候補 | NOT REPRODUCED（見出し数値） | Monitorのみ | 自動売買未接続 |
| Theme-free RS189 RSI30 | 研究で確認済み | PASS | Monitor候補 | Main12枠へ混在させない |
| 通常TQQQ 30% | 研究候補 | PASS | Engine定数/表示済み | NQSAR単純連動なし |
| Strict Crash Seed | 研究で確認済み | PASS | Engine/Schema済み | VIX≥23、ATR乖離≤−0.5、10d DD≤−2% |
| 4H RSI TOUCH30 → F80 | 研究候補 | PASS | Engine/Schema済み | 正確な4H routeがない日はDATA REQUIRED |
| D10 / MC57<20 Exit | 研究候補 | PASS | Engine/Fixture済み | いずれも次回寄り |
| Gross≤100% | 研究候補 | PASS | cap関数/Fixture済み | 自動トリム優先順位はNOT REPRODUCEDのため未実装 |

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
| RSI initial | 33056967545 | 9640423844 | Run参照 | Run参照 |
| RSI strength final | 33130536827 | 9670229132 | Run参照 | Run参照 |
| Market RS189 integration | 33133427031 | 9671218139 | Run参照 | Run参照 |
| TQQQ Stage56 | 33080590798 | 9649902954 | 4e0d813863f6663e09837de437e33cb9809f6a1b | 同commit内workflow |

TQQQのscript pathは `research/tqqq_stage56_mandate_portfolio_audit.py`、workflowは `.github/workflows/tqqq-stage56-mandate-audit.yml`。主要summaryはArtifact内のStage56 mandate/portfolio summary。4H barは5分足から09:30–13:30と13:30–16:00（partial）を構成し、Wilder RSI14を計算する。

通常個別株Modeの追加識別子はRun `33216929035`、Job `99002542944`、Artifact `9703815077`、commit `e42019…`。日次候補比較はRun `33229660388` / Artifact `9708127211`、rank prune比較はRuns `33229961070`, `33230203593` / Artifacts `9708215997`, `9708309654`。

## 数値再現

通常個別株Theme/Exitのequity variant 65本を成果物から再計算し、65/65 PASS。最大絶対差はCAGR 0、MDD `2.22e-16`、Sharpe `1.33e-15`、Rolling252 positive ratio 0、Worst rolling252 `2.22e-16`。これは機械的再現性であり、将来CAGRの主張ではない。

LOO比較はRS189 baseline CAGR 21.60% / MDD −56.25% / Sharpe .732、LOO Theme30 Attack-only CAGR 28.70% / MDD −33.25% / Sharpe .985、block20 win約82%。サイトでは期待CAGRとして表示しない。

Market-wide RS189 RSI30はConfirmation平均約3.14%、Win約54.6%、MAE約−10.81%、Integrated max1 CAGR約3.61%、MDD約−2.54%を再現した。

## 追加検証

既存成果物で十分な箇所は再バックテストせず、次だけ追加した。

1. 65 equity variantsの指標再計算。
2. Mode境界・Selective no-trim・coverage guardのFixture。
3. close→next-openの−8%、部分利確一回、Peak Close、Red override Fixture。
4. Strict Seed / TOUCH30 / D10 / MC57 / Gross cap Fixture。
5. 既存Dashboardを入力にしたcompanion state builderが元HTMLを書き換えない回帰テスト。

## 最新ルールブック

1. 通常TQQQは30%。通常個別株budgetは最大70%。
2. 通常個別株ModeはAttack 12 / Selective新規4 / Stop新規0 / Defense次回寄り全退避。
3. AttackはStock RS189 70% + LOO Peer Theme Full3 30%。SelectiveはRS189。
4. 候補は毎営業日引け後更新、空き枠を次営業日寄りで補充。
5. Entry後は順位・Theme・Breadth低下・Yellowでは売らない。
6. Exitは終値−8%、+24%で25%一回、残75%を最高終値−30%。NQSAR RedがPortfolio override。
7. RSI30 Resetは独立Sleeve。完全再現までMonitor。
8. Panic TQQQはStrict Seed→30日以内TOUCH30→翌寄り80%、最大10日、MC57<20早期Exit。NQSAR非Gate。
9. Gross≤100%。同時発火時の自動削減優先順位は未確認のため実装しない。

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
- TQQQ CURRENT30 / Seed / 4H Trigger / F80 / Hold days / MC57 / VIX / ATR deviation / DD10。
- 既存Dashboardは同ページ内iframeまたは別画面で参照可能。

## テスト結果

- V38 Unit/Fixture: 20 PASS。Workflow inventory以外の全回帰: 66 PASS。
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
4. Panic F80と他Sleeve同時発火時の削減優先順位。Gross capは実装したが自動trimは未実装。
5. TQQQ exact 4H data file `tqqq-panic-state.json` の定期生成・配信経路。
6. 既存Dashboardには旧ルール表示が残る。監査版へ本番切替するまでは混同リスクがある。

## Theme taxonomy lookahead

LOOは候補銘柄自身がTheme Return/Breadth/Accelerationを押し上げる自己循環を除去する。一方、2026年時点のTheme membershipを2016年等へ遡及適用する問題は除去しない。この二つは別のbiasである。historical taxonomy snapshotがないため、Theme overlayは「研究で確認済みの相対比較」かつ「taxonomy lookahead未解決」と表示する。

## 研究結果 → 採用ルール → 実装箇所

| 研究結果 | 採用ルール | 実装箇所 |
|---|---|---|
| Mode robustness / immediate trim悪化 | 60/50閾値、Selective no-trim | `v38_rules.market_mode`, `new_entry_capacity`, Engine card |
| 全株Breadthと57ETFが高相関 | 全株50MAのみHard Gate | `build_v38_companion.build_state` |
| LOO Theme30がbaseline改善 | Attack 70/30、peer-only | Candidate schema。Live値はDATA REQUIRED |
| W45の優位不明確 | Theme weight 30% | Rulebook / Candidate note |
| Full3がpairより安定 | RS63+Accel+Breadth21 | Candidate columns / DATA REQUIRED guard |
| daily refresh > biweekly | 毎営業日更新・次回寄り補充 | State再生成 / Capacity表示 |
| rank prune非優位 | 順位・Theme低下で売らない | `evaluate_normal_close`にrank/theme入力なし |
| Peak25–35 plateau | 中央Peak30 | `NormalPosition.peak30_stop` |
| Partial25がMDD改善 | +24%で25%一回 | `evaluate_normal_close` / Positions UI |
| BE8大幅悪化 | 建値Stop移動なし | Fixture `test_plus8...` |
| 8週間ルール勝率約48.5% | 不採用 | 実装なし |
| Theme RSI30 > Market RS189 RSI30 | Theme版をMain候補、market版Optional | RESET Monitor（自動接続なし） |
| F100よりF80がrisk compromise | Panic時80%、100%不採用 | TQQQ Engine / `PANIC_TQQQ_WEIGHT` |
| D10 / MC57<20 | 最大10日、MC57早期Exit | `tqqq_panic_exit` |
| NQSARでPanicを塞ぐと反発逸失 | Panic TQQQにNQSAR Gateなし | `tqqq_panic_entry`にNQSAR入力なし |
