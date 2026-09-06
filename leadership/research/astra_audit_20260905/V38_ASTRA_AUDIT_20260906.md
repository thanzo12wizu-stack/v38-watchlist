# V38 全体再監査 — 2026年9月6日

**まだ変更には証拠不足。** 固定ソース・再計算・原artifact回収を分離した監査報告。

## 1. GitHub workflow全棚卸し

結論は **まだ変更には証拠不足**。研究候補はGross100のDDV20・Early1 RS21_HIGH_ACCELだが、現行liveの置換を支持する同条件・完全連動台帳での証拠は揃っていない。

監査は2026年9月6日。mainはe32eff1bf460ffd517bb042c7fbc36e4f5f8844e、leader研究は898a684142239fa77ce6dd28b2c35b43e3b188ec、sector研究は24e2677b83877da29e19f1c034c9bde3f5c0ece5へ固定した。別スレッドによるmain更新を本監査の変更と混同しない。

198 branch、branch別workflow 2,794行、現存308パス・426 blob版、履歴にのみ残る74パス、合計382パスを棚卸しした。収集したrun索引775件、詳細ログ265 run / 299 job、artifact 247件。GitHubから202件を回収しSHA-256を照合、期限切れ45件中3件はローカルZIPと完全一致した。残る42件は元artifact未回収。到達可能なGit履歴を対象とし、GitHubの未参照・消失オブジェクトや未取得の全runまで回収できたとは主張しない。

添付CSVはworkflow名、ファイル、branch、Production/Research、目的、trigger、データパス、run/artifact依存、出力、Python、最終成功run、現存状態を収録。Simulator未同定・後継関係未確定は明記し、自動推測した採用判定で埋めていない。全ファイルの棚卸しと、全研究の実験意味の完全同定は別であり、後者は未完了。

mainの20件は dashboard / dispatch-dashboard-mc15-once / implement-mc15-once / inspect-mc15-impl-once / leadership-command / options-chart-data / options-time-tests-once / options / production-downstream-chain / publish-public-site / restore-production-chain-once / rotation-divergence-live / rotation-live / rotation-stock-context-live / unified-dashboard / v38-audit-check / v38-final-publish-once / v38-live / v38-sleeve-recover-once / v38-sleeve-refresh（各.yml）。

通常経路はDashboard成功→下流chain→V38→Sleeve→Rotation等。既存Dashboardのbuilder/HTMLを通常の下流処理が書き戻す経路は確認しなかった。chainはREADY・coverage・as-of確認後にV38出力6ファイルをmainへ昇格する。Options入力をDashboardが読む依存は存在する。

ただし保守用onceは例外。implement-mc15-onceはbuild_dashboard.pyをmainへ書ける。restore系にもソース・state書込みがあり、v38-final-publish-onceはDashboardをdispatchできる。「通常下流から逆流しない」と「保守経路を含め逆流が構造上不可能」は同義ではない。今回は修正・dispatchしていない。

一次資料：[監査対象 main e32eff1](https://github.com/thanzo12wizu-stack/v38-watchlist/tree/e32eff1bf460ffd517bb042c7fbc36e4f5f8844e)

## 2. Dashboard-native rule全棚卸し

Rulebook以外を起点にbuild_dashboard.py、command-center.htmlのJS、参照state、workflowを逆引きした。63のルール群を dashboard_native_rules.csv、198のmetric式を dashboard_metric_inventory.csv、3ソース木の4,002関数を source_function_catalog.csv に収録した。ルール群は行単位の全条件と同義ではない。

既存Dashboardは通常株70%／レバレッジ30%の配分系。NQSAR Blue/Green/Yellowで通常株係数100%、Redで0。レバレッジはBlue100%、Green50%、Yellow/Red0、緊急ロックで半減。SOXL保有もTQQQ余地へ作用する。V38の12/4/0 Market Modeとは別実装。

既存の通常株追跡・Positions JSは初期stop Entry×0.75、peak×0.70、3Rが+75%に対応する。V38の−8%・+24%で25%利確と同一ではない。追跡state・警告・手動ポジション表示をbroker実約定とみなせない。隔週・Red解除・初期空状態で候補を更新し、rank24等の継続条件がある。これをV38のrank低下Exit禁止に上書き解釈しない。

緊急ロックはequity.csvのNAV DD≤−28%かつ対QQQ円換算12か月相対≤−12%。解除はDD>−20%かつ相対>−8%。欠損では前状態を保持する。SOXLはSOXXの50MA帯・50/100MAと3分割の別階層。

F1/F2/F3、MRI/MC、FTD、VIX sequence、A/D、breadth、金利、earnings/options、setup、週足stage、W30の多くは表示・候補説明・手動判断用。画面に表示されることだけを通常株Hard Gateの証拠にしない。Stock Windowという独立した現行関数は固定mainで同定できず、過去全実装に存在しなかったとは断定しない。

一次資料：[監査対象 main e32eff1](https://github.com/thanzo12wizu-stack/v38-watchlist/tree/e32eff1bf460ffd517bb042c7fbc36e4f5f8844e)

## 3. 30週線ルール完全解剖

### 正確な計算と時刻

build_dashboard.py の _drop_unconfirmed_week（2082行付近）、weinstein_stage（2125行付近）、w30_breakout（2193行付近）が一次資料。日足Closeを resample("W-FRI").last() で週次終値へ集約し、その30本の単純平均を取る。150営業日SMAではない。金曜以前なら当週を落とす。通常は週途中に当週終値で更新しないが、金曜の日足が入力へ入ると確定週として使用する。

祝日金曜の特例補正はない。2025年4月17日木曜までの入力では4月11日週を最後とし、4月21日には4月18日ラベルの週を使用する。セッションカレンダーによる「その週の最終取引日」とweekday判定には差がある。入力データが確定日足であることが前提で、intradayを別途約定判定には用いない。

### Cross・Stage・状態

Aboveは週Close>30週SMA、Cross upは当週Aboveかつ前週非Above。直近14週（0〜13週前）のCrossを探索し、最低55週・価格5ドル等を要求する。傾きはMAが4週前以上なら上向き側。Above/Below×傾きでWeinstein stage 1〜4を構成する。連続数週Aboveを待つ確認方式ではない。

FULLは週騰落≥6%、MA乖離≥5%、52週最安週終値から≥50%。PARTP/PARTMにも週騰落≥6%・MA乖離≥5%が必要で、その上でPARTPは同安値比30〜50%、PARTMは30%未満。MA乖離<1%ならWEAK、安値比≥50%かつ乖離≥3%等でPOS、それ以外はCROSS。52週高安は週終値系列のmax/minでありintraday高安ではない。

FULLのS/A/Bは52週最高終値比≤−30%を2点、週騰落≥10%を1点、乖離≥10%を1点として、3点以上S・1点以上A・それ以外B。

状態機械のEntry基準はsignal週Close。exec_next_open=Trueという定数は実際の基準価格に使われず、翌週寄りというUI説明との不一致がある。最初4週の週Closeがsignal週Lowを割るE1、signal Close×0.90以下のE2でDEAD。8週以降の後続週High最大進捗<5%でSTALL。STALLは後の進捗で戻り得る。PBはpost高値がEntry比≥5%、週Low≤MA×1.03、Close≥MA。PB後にpost高値をCloseで超えるRESUME等がある。PART/CROSSからの昇格は現在の52週最安終値比50%到達で、Early→Core昇格とは無関係。

aliveは最新Close>MA。単なるBelowとDEADは別。画面のMA割れE4説明を自動全売却と解釈しない。Reclaim/Failed breakoutという新しい取引条件は合成していない。既存のPB/RESUME/DEADと、他のVWAP reclaim・日足breakout failureも別物。

### 対象と接続

銘柄metric、W30候補一覧、詳細stage/badgeへ作用。表示床は価格≥5、DDV≥10M、時価総額≥1B、異常/除外条件等で、時価総額欠損は通さない。現在の時価総額を過去へ適用するならPITではない。指数イベント検証には同じ週集計をQQQ/SPY/Nasdaq Compositeへ適用したが、その検証用適用を既存の売買経路と混同しない。

W30出力からCURRENT30、Core Entry/Exit、Market Modeへの接続は確認されない。週足Stage2はsetup分類・表示へ入るが、それだけでExposure gateとはならない。CURRENT30にW30が内包されている証拠はなく、既存W30を表示から外してもPortfolio露出は変わらない。

### 独立した10回答

1. 真の30本週終値SMAとCross後の状態機械。
2. 上記3関数とW30定数群で計算。
3. 候補・詳細表示・setup分類に作用。自動Exposure接続は確認なし。
4. 固定mainでコード・表示は現役。
5. 週足stageには関連計算があるがCURRENT30 lockには未内包。
6. Cross後returnは正でも少数・重複観測・相場依存。独立した売買edgeは未確定。
7. QQQ W30をPortfolio/TQQQへ追加するgateは今回悪化。個別株gateの微改善も有意とはいえない。
8. 現行表示ルールを外すPortfolio差は接続上ゼロ。情報表示の価値まではゼロと断定しない。
9. 29/31週等の最適化は実施していない。期間依存性の完全検証は未完。
10. 現行表示は維持。売買gateへの変更は推奨しない。

W30X_STATSのFULL +30%到達43.6%・n=1136等はハードコード値。元データと完全再現が揃っておらずE：NOT REPRODUCED。

StageはAbove＋非下向き=2、Above＋下向き=1、Below/equal＋非下向き=3、Below/equal＋下向き=4。RESUME★は押し目前進捗≥9%、再始動週騰落≥7%、旧signalの52週最高終値比≤−15%を追加で使う。

一次資料：[監査対象 main e32eff1](https://github.com/thanzo12wizu-stack/v38-watchlist/tree/e32eff1bf460ffd517bb042c7fbc36e4f5f8844e)

## 4. 過去研究の系譜

研究の識別子は名称だけでなく「workflow path＋run＋head SHA＋入力artifact＋simulator関数」とする。同じordinary-stock-market-mode-robustness.ymlがMarket Mode、refill、Theme、LOO、Exit等の別実験に上書き再利用されていた。最新runだけでは旧結論を失うためRulebook参照の13 runを追加回収した。

| 系列 | 主な経路 | 監査上の扱い |
|---|---|---|
| 通常株 | Market Mode→refill/no-prune→Theme→strict LOO→weights/components→Exit | 古い11 artifactは期限切れ。詳細JSONログとコードを保持、完全再実行とはしない |
| Reset | RS189/RSI30→portfolio/robust→strength threshold→strict frozen | Run33130536827を固定。旧headlineとは分離 |
| TQQQ | current hierarchy→panic seed→Stage56 mandate | Run33080590798を固定。現行MC15尺度変更とは分離 |
| Gross100 | allocation→DDV/refill→Early slots→promotion→liquidity aligned→component/reset再点検 | 旧53%の母体。今回同母体再計算と新しい時刻整合検証 |
| Early/Radar | discovery/context→candidate/rank depth→slot capture→delay/bottleneck→liquidity label audit | ラベル未来成績をEntryへ使わず、発見と実Entryを分離 |
| Ignition/Pioneer | hidden/quality/post→volume/base/supply dry-up | recovered研究資料。個々の最終採用は再実行なしに昇格しない |
| Theme/Sector/Leadership | sector stock→flow/cycle/combination→regeneration/warning→unique edge | 静的taxonomyと母体差に注意。構成要素順位を総合CAGR順位へ置換しない |
| 金利 | rate/policy条件15案のentry-only block/cap4 | 重複探索せず原結果を確認。新OOSとはしない |

履歴のみの74 workflowはhistorical_workflows.csv、全系列はworkflow_unique_paths.csv、回収表はrecovered_result_tablesへ収録。自動分類のOtherやSimulator未同定は未解決として残す。

一次資料：[原artifact回収 Run 34000536960](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/34000536960)

## 5. 再現できた結果

固定Reset：Run33130536827 / rsi-strong-stock-threshold-interaction-audit、SHA-256 6db59e07c5eb3c248de0748b9d7f8c43183f96fc80f739faee8250246b10d59d。

固定TQQQ：Run33080590798 / tqqq-stage56-mandate-fx-tax、SHA-256 b6df441dae8be5bb6f6f5ceb7771472545e20b270c7016c1a7936915f8f7482d。

研究Run33972198145は3595銘柄の取得入力をfreeze。Python3.11 / pandas3.0.5 / numpy2.4.6 / scipy1.17.1 / yfinance1.7.0。Early0 51.800289%、Early1 53.217238%、NO_PROMOTE 52.755863%を旧annualization式で再計算した。Early1の最新同母体記録53.217241%と丸め誤差水準で一致した。

取引計測を追加したrun34000784634は通常株仮想sleeveの元NAVとの差最大8.88e−16。取引計測によって売買を変更していない。入力manifest、日次return、期間表、bootstrap、取引eventを保存した。

原artifactを回収して数字を読めたことは「今回コードを再実行して再現」とは別。205件のartifact回収を205研究のBT再実行と表記しない。

一次資料：[固定入力による再計算 Run 33972198145](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/33972198145)

## 6. 再現できなかった結果

旧Early1 53.636620%の当時OHLCV・全取引差分、Reset旧headline平均6.20%/Win72.3%/PF4.71、W30X_STATS固定統計、期限切れ42件の元ZIPは完全再現できていない。

現行liveとDashboard-nativeを含む、同一資金台帳での完全移植BTも未完。今回の新検証は独立仮想sleeveの決定を使って資金配分するため、資金不足が後の候補・株数・stop状態へ及ぼす再帰的feedbackまで再現していない。現行本番のCAGRとして50.02%や53.22%を引用しない。

Portfolio全体の2026 availableは3月20日まで。指数W30イベントは9月4日まで。固定4H/TQQQ入力の終端を越えて9月時点までPortfolioが検証されたとはしない。

一次資料：[原artifact回収 Run 34000536960](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/34000536960)

## 7. 現在本番ルール

通常株はNQSARと通常株Universe BreadthがHard Gate。Blue/Green＋≥60%でATTACK最大12、50〜60%でSELECTIVE総容量4、<50%またはYellowでSTOP新規0・既存保持、Redで翌寄り退避。SELECTIVEは「毎日4件追加」ではない。既存12を4へ強制trimしない。Red解除はBlue/Green＋breadth≥50%で翌寄り資格復活、FTD/MC57追加待機なし。

Eligibility：価格≥5、DDV≥10M、SMA50>SMA200、Close>SMA200、RS189/63各≥85 percentile、構造的clinical biotech除外。biotech判定の業種・時価総額・売上条件と欠損処理があり、文字ラベルだけの除外ではない。ATTACKは70%RS189＋30%strict LOO peer Theme、SELECTIVEはTheme加点なし。Theme Full3はRS63・20日rank acceleration・21EMA breadth等加重。

通常Exitは初期Entry×0.92、初回Entry×1.24で翌寄り25%利確、残りはmax(Entry×0.92, PeakClose×0.70)。Rank/Theme/Breadth低下・Yellow・隔週だけで売らない。−8%は終値判定であり損失を8%に保証する約定ではない。

ResetはRS63_TOP3_RISE30_SIGTOP3、2.9%×最大4、同Theme2、20日固定・cooldown20、追加/ナンピンなし、MC/NQSAR Hard Gateなし。通常Exitを流用しない。

CURRENT30はbase30%からslow/fast/MC lock・強気100%・panic・transition等で変わる。slowはQQQがSMA200とVWAP252を5日下回る等、fastは10日DD≤−6.5%＋EMA21下、MC lockは<25と解除≥35等。QQQ30週SMAは含まれない。

Panic SeedはVIX≥23、(QQQ−SMA50)/ATR14≤−0.5、QQQ10日DD≤−2%のAND。age≤30、4H RSI14 TOUCH30、当日MC≥20でF80、target=max(hierarchy,80%)。MC<20またはD10で解除。配分はReset→TQQQ80保護→通常株→TQQQ extra、gross≤100%。現行mainはSELECTIVE_FILL_NO_ZERO_OVERRIDE相当の余地補充を既に持ち、native target0は復活させない。

**重要な尺度差**：現行mri_frameは57ETF×12指標、EMA2 Rawを過去3780sessionの平均・標準偏差からlogistic変換するMC15系。build_v38_tqqq_liveはmc57という変数名のままこれを参照し、旧20/25/35/65等の閾値を適用する。daily_log移行もある。Stage56の旧MC入力と現在の数値尺度を同一と扱えない。ここが本番と旧研究を直結できない主要理由。

一次資料：[監査対象 main e32eff1](https://github.com/thanzo12wizu-stack/v38-watchlist/tree/e32eff1bf460ffd517bb042c7fbc36e4f5f8844e)

## 8. 研究上ベスト

今回再実行したGross100候補集合での暫定首位はDDV20 / VACANCY_TOP12 / Early1 RS21_HIGH_ACCEL / NOT_RED / 最大10日 / Core直接昇格 / frozen Reset / Stage56 M30_TOUCH30_F80_D10 / SELECTIVE_FILL_NO_ZERO_OVERRIDE。

ただし実装上ATTACKはCore11＋Early1、SELECTIVEはCore3＋Early1。Core12にEarly1を上乗せする13枠ではない。NOT_REDだけでなくEarly枠生成側がBreadth≥50を必要とする。DDV20は元のDDV10母集団で作ったTop12へ後から適用し、DDV20でrank母集団を作り直す別engineとは異なる。10日満期処理と昇格の順序、昇格後もEntry/Peakを維持する点も固定する。

これは「全研究・現行liveを通じて確定した最適解」ではなくB：研究採用候補。Early1とEarly0の差のbootstrap区間はゼロをまたぐ。大リーダー早期捕捉目標も十分達成していない。

一次資料：[固定入力による再計算 Run 33972198145](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/33972198145)

## 9. Dashboard / V38 / Gross100差分

| Rule | Dashboard | 現行V38 | Gross100候補 | 推奨 |
| --- | --- | --- | --- | --- |
| Market Mode | NQ配分係数・隔週候補 | 12/4/STOP/Red退避 | 同系、Early容量もbreadth制約 | A 維持 |
| 30週線 | 候補/状態/表示 | 通常株・CURRENT30 hard gateなし | 元engineにも追加なし | A 表示維持 / D 全体gate追加 |
| Trend/Risk Lock | NAV相対DD・SOXL等 | CURRENT30 slow/fast/MC等 | 固定Stage56ターゲット | A 維持、尺度同定必要 |
| Core DDV | 10M | 10M | 20M（Top12作成後filter） | B 20M候補 |
| Core slots | 別候補配分 | ATTACK12/SELECTIVE4 | Early1時11+1/3+1 | B 枠内予約 |
| Refill | 隔週/回復等 | vacancy型 | VACANCY_TOP12 | A 維持 |
| Ranking | RS系候補 | ATTACK70/30、SELECTIVE RS | 同系strict LOO | A 維持 |
| Theme | 表示/分類 | Full3 LOO加点 | 同系、静的taxonomy | A 維持/PIT課題 |
| Exit | −25%等の別追跡 | −8%/+24%25%/peak−30% | 同系 | A V38維持 |
| Early | 同名setupと区別 | 通常株Early袖なし | 1枠 | B |
| Early Score | 非同一 | なし | RS21_HIGH_ACCEL | B |
| Early Gate | 非同一 | なし | NOT_RED＋breadth容量 | B |
| Early Hold | 非同一 | なし | 10営業日 | B |
| Promotion | W30状態昇格は別 | なし | Core直接昇格 | B 未確定 |
| Reset | 別表示 | strict 2.9%×4・20日 | frozen strict | A、旧headline E |
| TQQQ normal | 旧Dashboard階層 | CURRENT30・MC15入力 | Stage56旧入力 | C 同値未確認 |
| Panic Trigger | 別経路 | Seed＋4H Touch30＋MC≥20 | M30_TOUCH30_F80_D10 | A 条件維持/C尺度 |
| Panic Exit | 別経路 | MC<20 or D10 | 同名旧尺度 | C |
| Allocation | 70/30等 | Reset→80保護→Core→extra | Gross100 SAME_DAY_GROSS | C 会計再構築 |

Aは今回変更せず維持する勧告であり、単体edgeが全て証明されたという意味ではない。

一次資料：[監査対象 main e32eff1](https://github.com/thanzo12wizu-stack/v38-watchlist/tree/e32eff1bf460ffd517bb042c7fbc36e4f5f8844e)

## 10. Early1 53.64%問題

旧run33877667359 / commit6f5105cd9d5fa143b47e1babdf5a4e44a555b7c4：Early1 53.636620%、Early0 51.763499%、NO_PROMOTE 53.046031%。最新同母体run33970208065 / commit898a684：Early1 53.217241%、Early0 51.800291%。今回Early1 53.217238%を再計算した。差は約0.41938 percentage point。

これらは2016年1月4日〜2026年3月20日の全期間CAGR。2021〜2025だけの値ではない。ソース関数・universeファイルに旧→新で説明可能な変更は見つからず、固定Reset/TQQQも同じ。Python/主要ライブラリの固定条件も照合した。

旧Early entry222→新223、stop50→51、Core647・昇格9は同じ。Yahoo取得ではLEG/WILC/CMII等の失敗差があるが、旧OHLCVと全eventを凍結していなかったため、Corporate Action、価格訂正、欠損履歴等へ0.41938ptを一意に帰属できない。**原因は未解決。Yahoo差が原因と断定しない。**

さらにstandardized表のCAGRは252/n、元headline再現は252/(n−1)。Early1の標準表53.191782%と元式53.217238%の差約0.02546ptは計算式差で説明できるが、旧53.64との差とは別。

提示された旧Score＋Liquidity52.93%・現行LIQ51.70%は今回の固定条件と一致しない。今回は50.873746%・51.919070%。出所条件が同定されるまで同じ順位表に転記しない。

一次資料：[旧53.64% Run 33877667359](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/33877667359)

## 11. 同一Engineランキング

### L1：旧Gross100会計の再現

Simulator ID＝GROSS100_LEGACY_898a684。静的3595候補、2016-01-04〜2026-03-20、SAME_DAY_GROSS、BASE、VACANCY_TOP12、NOT_RED＋breadth容量、固定Reset/TQQQ。BASEは通常株無コスト、Resetは元系列5bp、TQQQは配分差5bp。security単位の一律5bpではない。下表CAGR/MDD単位は%。

| Strategy | CAGR_pct | MDD_pct | Sharpe | Calmar |
| --- | --- | --- | --- | --- |
| EARLY1 | 53.2172 | -26.5841 | 1.6100 | 2.0018 |
| NO_PROMOTE | 52.7559 | -28.0070 | 1.6013 | 1.8837 |
| CORE_DDV50 | 52.1200 | -31.5181 | 1.5709 | 1.6537 |
| EARLY1_CURRENT_LIQ | 51.9191 | -27.6066 | 1.5853 | 1.8807 |
| EARLY0 | 51.8003 | -26.5263 | 1.5812 | 1.9528 |
| EARLY2 | 51.2256 | -26.3677 | 1.5734 | 1.9427 |
| EARLY1_LEGACY_LIQ | 50.8737 | -28.7069 | 1.5591 | 1.7722 |
| CORE_DDV20_REFILL | 50.0338 | -27.8278 | 1.5398 | 1.7980 |
| CORE_DDV10 | 49.1394 | -25.4676 | 1.5184 | 1.9295 |

通常株/Resetのclose NAV returnと当日処理後grossを合成し、TQQQはopen-openと別のshiftを使う。当日全退避してgross0になると、その日のsleeve損益を割当ゼロで落とし得る。LAG1へ置換するだけでは分母も変わり、完全な修正ではない。turn_o/turn_r欠損やsleeve総額差だけのALL5コストを実銘柄Turnoverと扱わない。

### C1：取引時刻を揃えた研究検証

Simulator ID＝CAUSAL_OPEN_REPLICATION。同じ静的Universe・Core条件・固定Reset/TQQQ。前日情報で翌寄りの資金配分を決め、次の寄りまでのreturnを得る。security単位のweight driftを考慮した売買額へ5bp。2016-01-04〜2026-03-20の2567 open区間、gross≤100%。独立仮想sleeveの判断を利用する制約は残る。

| variant | cagr | mdd | sharpe | calmar |
| --- | --- | --- | --- | --- |
| EARLY1 | 50.02% | -28.10% | 1.3800 | 1.7802 |
| CORE_DDV50 | 49.18% | -33.18% | 1.3449 | 1.4823 |
| EARLY1_CURRENT_LIQ | 48.97% | -29.59% | 1.3642 | 1.6551 |
| EARLY0 | 48.65% | -28.77% | 1.3548 | 1.6913 |
| EARLY2 | 48.07% | -27.03% | 1.3468 | 1.7785 |
| EARLY1_LEGACY_LIQ | 48.04% | -29.72% | 1.3432 | 1.6162 |
| CORE_DDV20_REFILL | 46.91% | -29.61% | 1.3214 | 1.5843 |
| CORE_DDV10 | 45.78% | -27.58% | 1.2957 | 1.6598 |

Early1の年率TurnoverはΣ|銘柄weight売買差|で約25.09倍、Early0約23.43倍。往復取引回数ではない。現行live相当、Dashboard-native相当はこの台帳へ完全移植しておらずN/A。最終本番候補の確定順位もN/A。

### S1：別の通常株のみengine

run33967352413、2021〜2025、DDV20でrankを作り直すWITHIN12、Reset/TQQQなし。Early0 20.340688%、Early1 LIQ_ACCEL 16.685820%、Early1 BASE 12.051477%。これはL1/C1とは母体・期間・score・配分が異なるため、同列ランキング禁止。

一次資料：[固定入力による再計算 Run 33972198145](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/33972198145)

## 12. OOS / Bootstrap / Robustness

### 時系列

以下はC1 Early1・5bp。2026行は3月までを年率換算した値で、年全体のreturnではない。年率式は252/n、Sharpeは日次平均/標準偏差×√252、Calmar=CAGR/|MDD|。PF列がある日次表はpositive日次return総和/negative総和でありtrade PFと異なる。

| period | n | cagr | mdd | sharpe | sortino | calmar |
| --- | --- | --- | --- | --- | --- | --- |
| FULL | 2567 | 50.02% | -28.10% | 1.3800 | 2.0207 | 1.7802 |
| 2016_2020 | 1259 | 55.12% | -26.39% | 1.5027 | 2.2684 | 2.0889 |
| 2021_2025 | 1255 | 47.43% | -28.10% | 1.3264 | 1.9031 | 1.6878 |
| 2022_2025 | 1003 | 50.18% | -20.60% | 1.4438 | 2.1226 | 2.4364 |
| 2022_2026_AVAILABLE | 1056 | 47.33% | -20.60% | 1.3553 | 1.9741 | 2.2981 |
| 2016 | 252 | 33.14% | -13.26% | 1.4440 | 2.1727 | 2.4986 |
| 2017 | 251 | 30.98% | -12.76% | 1.3109 | 1.7171 | 2.4286 |
| 2018 | 251 | 22.49% | -26.39% | 0.7347 | 1.0662 | 0.8522 |
| 2019 | 252 | 47.56% | -12.58% | 1.5740 | 2.4136 | 3.7811 |
| 2020 | 253 | 183.81% | -23.30% | 2.4089 | 3.8505 | 7.8902 |
| 2021 | 252 | 36.95% | -27.82% | 0.9849 | 1.3388 | 1.3280 |
| 2022 | 251 | -7.95% | -17.30% | -0.2939 | -0.3677 | -0.4594 |
| 2023 | 250 | 53.45% | -17.67% | 1.6500 | 2.6164 | 3.0242 |
| 2024 | 252 | 102.47% | -16.53% | 1.9969 | 3.0149 | 6.1998 |
| 2025 | 250 | 77.80% | -14.13% | 1.8178 | 2.6374 | 5.5052 |
| 2026 | 53 | 2.56% | -18.57% | 0.2853 | 0.3880 | 0.1376 |

### 不確実性とコスト

C1 Early1−Early0のCAGR差は+1.37pt。20日block 90%区間[−2.01,+4.76]pt、60日[−1.65,+4.57]pt、year cluster[−1.51,+4.89]pt。改善となる再標本化割合は73.0%/76.4%/77.3%で、真の優位性の確率と読まない。既に研究で見た期間は新OOSではない。新しいwalk-forward確証は作れていない。

C1 Early1の0/5/10/20bp CAGRは51.91/50.02/48.16/44.50%。全targetを1日遅らせると40.39%、MDD−30.36%。これはEntry-only遅延と別であり、後者を完了としない。通常株取引の最悪例は−45.02%で、終値stopがgap/急落損失を限定しないことも確認した。

Universeは現在の静的3595。全NaN17銘柄、年内の有効履歴中央値は2016年2269、2025年3388。取得列の存在を有効OHLCV coverageと混同しない。delistingを含む完全PIT Universeではなくsurvivorship・現行taxonomy・現在企業属性の汚染が残る。strict LOOでも歴史taxonomyの未来情報は消えない。新台帳の保有銘柄return欠損fallbackは0だが、そもそもUniverseから欠けた銘柄の影響は測れない。

### 30週線Forward Return

QQQ/SPY/Nasdaq Compositeに5/10/20/40/60/126営業日を計算。Bull/Bear/Sidewaysは日足200SMAと傾きに基づく研究層別、High VIX≥23・Low<20、NQSAR/breadthは固定入力終端まで。金利のローカル追加層別は2023年以降・1日lag・非vintage。原表示そのものの売買成績とは異なる。

QQQ Cross upは14例、20日平均+2.08%、60日+7.34%、126日+13.16%（13例）。無条件60日は+5.07%、126日+10.70%。Cross downも60日+9.43%でありBelow=悪いと単純化できない。SPY up16例の60日+4.37%、IXIC up15例+7.76%。Above/Belowの日次反復観測は重複し、独立標本数ではない。詳細全horizon・層別はw30_forward_returns.csv。

### 構成要素とW30追加・除去

下表はC1・5bp・固定仮想ポジションをcashへ落とす比較。資金再配分も後続Entryのfeedbackもないため、差を足し算できる「因果的CAGR寄与」と呼ばない。Core/Reset/TQQQ/Earlyを除去し、W30 gateを追加した。

| variant | cagr | mdd | sharpe | sortino | calmar | turnover_per_year_full |
| --- | --- | --- | --- | --- | --- | --- |
| BASE | 50.02% | -28.10% | 1.3800 | 2.0207 | 1.7802 | 25.0852 |
| WITHOUT_CORE | 38.27% | -24.98% | 1.5143 | 2.3889 | 1.5324 | 13.0236 |
| WITHOUT_EARLY | 48.10% | -26.86% | 1.3739 | 2.0099 | 1.7907 | 22.1067 |
| WITHOUT_RESET | 47.01% | -28.51% | 1.3285 | 1.9456 | 1.6486 | 24.2755 |
| WITHOUT_TQQQ | 13.86% | -30.27% | 0.7643 | 1.0779 | 0.4580 | 15.9451 |
| ONLY_CORE | 9.96% | -33.81% | 0.6199 | 0.8627 | 0.2947 | 12.2515 |
| ONLY_EARLY | 1.55% | -8.91% | 0.3732 | 0.6641 | 0.1738 | 3.1278 |
| ONLY_RESET | 2.14% | -4.69% | 1.0536 | 1.7773 | 0.4574 | 0.7458 |
| ONLY_TQQQ | 33.52% | -25.44% | 1.4259 | 2.2557 | 1.3176 | 9.1247 |
| QQQ_W30_ABOVE_ALL | 34.06% | -38.98% | 1.0827 | 1.5364 | 0.8738 | 22.4901 |
| QQQ_W30_ABOVE_TQQQ | 39.66% | -28.10% | 1.2032 | 1.7115 | 1.4112 | 23.9564 |
| QQQ_W30_RISING_TQQQ | 40.63% | -28.10% | 1.2255 | 1.7524 | 1.4457 | 24.3606 |
| STOCK_OWN_W30_ABOVE_CORE_EARLY | 50.34% | -28.10% | 1.3903 | 2.0388 | 1.7916 | 24.8720 |
| ALL_TARGETS_DELAY_1 | 40.39% | -30.36% | 1.1774 | 1.6946 | 1.3301 | 27.2888 |

QQQ Above30週を全体へ課すとCAGR34.06%、MDD−38.98%。TQQQだけでも39.66%。個別株自身のAbove30週は50.34%で+0.32ptにとどまり、20日block差区間[−0.46,+1.14]pt、60日[−0.54,+1.21]pt。追加を支持する十分な証拠はない。29/31週へ最適化していない。

未完は、現行Dashboard/V38完全移植、MC尺度を揃えたrisk lock除去、Market Mode/Breadth/Theme/Exit/Allocationの同一台帳factorial、Entry-only遅延、Portfolio CAGRのsymbol cluster、完全PIT/delisting、独立新OOS、全周辺factorの統一感度検証。取引単位symbol clusterとPortfolio bootstrapを取り違えない。

一次資料：[30週線・構成要素検証 Run 34000047770](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/34000047770)

## 13. 大リーダー早期捕捉

旧capture run33881097773の確認期間2021〜2025では、将来年率+200〜400%群66件の捕捉50%、run-up+30%以内は全対象の3.03%、+50%以内7.58%、Entry時run-up中央値143.94%。+400%以上8件は捕捉50%でも+50%以内0%、中央値257.22%。年Top5の25件は捕捉52%、+50%以内0%。発見Radarの+50%以内90.9%を実Entry率と置き換えない。

取り逃しはEarly slot occupiedが+200〜400%群27件、年Top5で9件。単純増枠はCAGRを悪化させた。発見→Candidate→slot→Entryの詰まりが残り、将来大リーダーを+30〜50%までに買う目的は未達。

今回の通常株仮想sleeve取引統計（5bp、部分利確込み、Early由来は昇格後も追跡）：

| cohort | n | symbols | mean | win | pf | worst | best |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ALL | 870 | 527 | 3.10% | 43.91% | 1.6337 | -45.02% | 215.80% |
| CORE | 647 | 402 | 3.78% | 42.19% | 1.7189 | -30.36% | 215.80% |
| EARLY | 223 | 193 | 1.14% | 48.88% | 1.2959 | -45.02% | 117.34% |
| EARLY_NOT_PROMOTED | 214 | 189 | 1.35% | 49.07% | 1.3736 | -26.99% | 117.34% |
| EARLY_PROMOTED | 9 | 8 | -3.81% | 44.44% | 0.6062 | -45.02% | 32.20% |

Earlyは223件・193銘柄、約21.9 entry/年。Core647件・約63.5 entry/年。昇格9件の平均−3.81%、PF0.61という小標本だけから昇格廃止とは言えない。NO_PROMOTEとの差には枠の再利用と他取引の変化も含まれる。

Early symbol cluster5000回の平均損益90%区間[−0.32,+2.78]%、PF[0.925,1.811]。これは仮想通常株取引cohortの期待値であり、資金制約後のGross100台帳のPFではない。

一次資料：[取引別再現 Run 34000784634](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/34000784634)

## 14. 採用 / 棄却 / 保留

| 分類 | 対象 | 根拠・限定 |
|---|---|---|
| A 本番維持推奨 | V38 Market Mode、rank等で売らないExit、strict Reset、gross上限、W30表示 | 今回変更を支持する証拠なし。全単体edge証明という意味ではない |
| B 研究採用候補 | DDV20、Early1 RS21_HIGH_ACCEL、10日、直接昇格、Top12 vacancy | 固定母体の暫定候補。完全連動台帳・独立検証待ち |
| C Monitor | 個別株W30 gate、CURRENT30/MC15尺度、金利shock cap/block、他未同定系列 | 微改善/尺度差/不確実性。自動採用しない |
| D 棄却（今回置換案として） | Early単純増枠、Early DDV50 hard gate、LIQ_ACCEL置換、QQQ W30全体gate | 今回悪化またはlabel DDVとの機械的整合で見かけ改善 |
| D 旧研究上の非採用 | SMA10/EMA21 Low通常Exit、BE8等 | 元artifact未回収のものはログ確認に限定。完全再現扱いしない |
| E NOT REPRODUCED | 旧53.64完全一致、Reset旧headline、W30固定統計、元証拠不足の棄却主張 | 根拠数字の完全再現がない |

旧Exit run33250255780の同母体全期間はHard8のみ18.54%、SMA10 7.56%、EMA21 Low15.38%、ATR2 17.76%、wide proxy21.04%。wide proxyはその後のpartial込み現行Exitと同一ではない。BE8/8週間強制保有/ATR2/Rank・Theme Exit/隔週rebal/Breadth trim/Yellow売却/Theme Hard Gate/MC通常株gate/Panic時NQSAR禁止は、原結果回収状況を含めて再現不能ならEを併記する。全項目の同一新engine再検証は未実施。

Pioneer finalは別銘柄群596の4/4条件5例等と小標本、Fisher p≈0.33。強い最終採用根拠ではない。金利15案では旧HOLDOUT名の2022〜2026でduration shock blockが31.55%対baseline26.24%だが差p≈0.316、過去に見た期間。新たな本番Hard Gateへ採用しない。

一次資料：[原artifact回収 Run 34000536960](https://github.com/thanzo12wizu-stack/v38-watchlist/actions/runs/34000536960)

## 15. 本番へ反映するなら何を変えるか

変更を検討する順序は、まず研究側でMC15と旧MC57の定義・history・閾値対応を固定し、現行CURRENT30を完全再現すること。次に実際の資金・株数・約定・手数料・cash・昇格を一つの台帳へ統合し、現行live相当をbaselineにする。SAME_DAY_GROSSの数字を本番期待CAGRへ移さない。

その同じ台帳でDDV10→20だけ、Early0→Early1だけ、昇格だけを順に比較する。DDV20のfilter順と枠内予約を固定し、旧研究に無い13枠案へすり替えない。W30は表示維持、全体/TQQQ gate追加は見送る。Reset/TQQQの旧headlineを目的関数にしない。

研究候補の採用には、現行再現、欠損/holiday/gap処理、実銘柄cost、PIT限界の明示、未使用期間での事前固定検証が必要。現時点ではDDV20/Early1が有力でも、現行全体を研究bestへ変更した方がよいとは結論できない。

一次資料：[監査対象 main e32eff1](https://github.com/thanzo12wizu-stack/v38-watchlist/tree/e32eff1bf460ffd517bb042c7fbc36e4f5f8844e)

## 16. 本番変更せず終了

**最終結論：まだ変更には証拠不足。**

現行：V38のDDV10・Market Mode・現行Exit・strict Reset・CURRENT30 hierarchy。研究上の暫定候補：DDV20＋Early1 RS21_HIGH_ACCEL＋10日＋Core昇格のGross100。ただし53%の旧会計、現在のMC尺度差、静的Universe、Early差の不確実性があり、本番置換の証拠は不足する。

30週線は発掘・定義分離できた。150日線ではなく、現行では売買露出へ接続されていない。QQQ gate追加は今回の同条件比較で悪化。現行表示を維持する。

main、build_dashboard.py、command-center.html、command-center-v38.html、Unified Dashboard、Rotation/Options本番、Production workflow、公開ページ、live state、更新パイプラインは本監査では変更していない。実行・保存したコードとworkflowは research/astra-v38-full-audit-20260905 の研究範囲。未完項目は本文と証拠台帳に残し、全研究の完全再現完了とは表記しない。

報告ファイルは構造検証済み。実ブラウザが利用できず、画面描画・操作の検証は未実施。

一次資料：[監査対象 main e32eff1](https://github.com/thanzo12wizu-stack/v38-watchlist/tree/e32eff1bf460ffd517bb042c7fbc36e4f5f8844e)