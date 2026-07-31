# V38 Trade Journal Almanac

## 目的
既存Command Centerの候補選定、Portfolio Doctor、NQゲート、セクター・テーマ、価格データと、実際の取引・資産推移・規律を一つの実績管理システムで照合する。

過去を眺める日記ではなく、過去の記録から今日の意思決定と将来の期待値を改善するためのAlmanacとして設計する。

出力の中心は外部CSSや別HTMLを必要としない`index.html`。今日、資産、保有、取引履歴、エッジ分析、振り返り、共有を一つのHTMLに収録する。

## デザイン
Command Centerとの系列感を残しつつ、Trade Journalは長期間読み返す運用記録帳として独自のAlmanacデザインを採用する。

- 暖色の紙面背景、細い罫線、抑制したブルー
- セリフ体の見出しと固定幅数字による記録帳らしい階層
- 影を多用せず、小さな角丸と高密度なカードを使用
- 最大幅760pxのスマートフォン中心設計
- タブ、本文、グラフ、配分、カードの横スクロールを禁止
- タブは1段目4項目、2段目3項目の固定グリッド
- 15〜30銘柄でも比較できる集中度ランキングを使用し、Treemapは主画面から外す
- 保有一覧は要点を表示し、タップした銘柄だけ詳細を展開する

## 1ファイル・実リンクタブ
ファイルは`index.html`一つだが、全セクションを縦積み表示しない。上部タブで選択した画面だけを表示する。

1. 今日
2. 資産
3. 保有
4. 履歴
5. エッジ
6. 振り返り
7. 共有

各タブは`button`ではなく`href="#..."`を持つ実リンク。URLハッシュ、再読み込み、戻る・進むに対応する。JavaScriptが無効でも`:target`で一画面だけを開ける。

日次カードとポートフォリオカードはBase64で`index.html`内にも埋め込み、単一ファイルで持ち運べる。

## 今日の運用判断
「発注OK」をHeatだけで判定しない。

優先順位は次の通り。

1. Stop逸脱銘柄がある場合は撤退確認を優先
2. NQが赤・不明・黄なら新規発注停止
3. 相関調整Heatが上限帯なら新規発注停止
4. Stop接近、イベント接近、相関Heat高めなら条件付き
5. 上記がなければ新規発注可能

今日タブには本日・月初来・年初来・最大DD、相関調整Heat、名目Heat、Stop逸脱、Stop接近、イベント接近、保有数を表示する。今日見る銘柄はStopまでの距離が近い順。

## 15〜30銘柄への対応
集中度は全銘柄を配分順に表示する。銘柄名、配分、含み損益を常時比較できる。

保有詳細はリスク順に並べ、初期表示を8銘柄に限定する。残りは「残りN銘柄を表示」で展開する。全銘柄を隠さず、初期画面だけを短くする。

各保有カードの初期表示:

- Ticker
- Setup / Sector
- 含み損益
- 配分
- 保有日数
- Stop距離

展開後:

- 現在値、Entry、Stop
- Heat、評価額
- Theme、Entry日
- Event Risk

Stopを下回った銘柄には`STOP逸脱`を表示する。

## 資産分析
資産曲線は決済損益の単純累積ではなく、`equity.csv`の入出金調整後の日次口座評価額を使用する。

期間選択:

- 1か月
- 3か月
- 6か月
- YTD
- 1年
- 全期間
- 任意期間

選択期間に応じてリターン、PF、勝率、平均R、最大DD、取引数、資産曲線、月次リターンを再計算する。

## 取引履歴
直近20件を初期表示し、20件ずつ追加する。数百件になっても全件を一度に縦積みしない。

検索・絞り込み:

- Ticker / Sector / Theme / Exit理由
- Setup
- NQ色
- 勝ち / 負け

## エッジ分析
期間、分析軸、並び替え、最小サンプル数を自由に変更する。

分析軸:

- Setup
- NQ環境
- Sector
- Theme
- エントリー曜日
- 保有日数帯
- R倍数帯
- Setup × NQ

表示指標:

- 件数
- 勝率
- PF
- 平均R

最小件数未満は薄色で表示する。ランキング行をタップすると取引履歴へ移動する。PFや勝率単独で採用せず、件数と平均Rを同時に確認する。

## 既存Command Centerとの自動連携
### 自動で同期するもの
Trade Journalの更新は、既存の`Intelligence Engine (sidecar)`内でCommand Centerデータ生成後に続けて実行される。専用ワークフローを増やさず、既存3本の運用構成を維持する。

- NQ色・市場状態
- Entry Candidates
- 現在の保有とPortfolio Doctor診断
- セクター・テーマ
- Stop、保有日数、含み損益、リスク寄与
- `prices.pkl`による相関
- Command Center更新日時

同期元は`data/intelligence/index.json`および互換コンポーネントJSON。公開リポジトリへ平文を残さず、最終HTMLは既存の秘密鍵でロックし、履歴は`private/trade-journal-state.enc.json`へ暗号化して保存する。

### 自動では推定しないもの
Command Centerの候補情報だけから、実際に約定した取引を推測しない。

以下は証券口座データまたはCSVが必要。

- 実際のEntry・Exit・株数・約定価格
- 手数料・税
- 部分利確
- 入出金
- 実口座の総資産

任意のGitHub Secrets:

- `V38_ACCOUNT_EQUITY_JPY`: 現在の実口座資産
- `V38_TRADE_JOURNAL_CSV_B64`: Base64化した取引履歴CSV
- `V38_EXECUTIONS_CSV_B64`: Base64化した約定明細CSV
- `V38_EQUITY_HISTORY_CSV_B64`: Base64化した資産履歴CSV
- `V38_HOLDINGS_CSV_B64`: Base64化した実保有CSV
- `V38_CASH_FLOWS_CSV_B64`: Base64化した入出金CSV

`V38_PRIVATE_DASHBOARD_PASSPHRASE`は前提の必須Secret。Almanac本体と継続履歴の暗号化に既存の値をそのまま使う。未設定時は、平文を公開せずロック済みプレースホルダーだけを出す。

リポジトリの既存`equity.csv`は自動で資産履歴へ取り込む。`date / equity / us_pct`形式、過去に混在したタブ・空白区切りの両方へ対応する。`V38_EQUITY_HISTORY_CSV_B64`の同日行がある場合はSecret側を優先する。最新資産日が7日超前なら、その値を今日の残高へ複製せず`PARTIAL`として鮮度警告を残し、今日画面は「資産データ要更新」として新規発注可能を表示しない。

### 秘密CSVの最小列

| Secret | 最小列 | 用途 |
|---|---|---|
| `V38_EXECUTIONS_CSV_B64` | `execution_id,position_id,ticker,action,executed_at,price,quantity` | 推奨。分割Entry・部分Exitを約定単位で保持 |
| `V38_TRADE_JOURNAL_CSV_B64` | `trade_id,ticker,side,entry_date,exit_date,entry_price,exit_price,quantity` | 完結取引を直接投入 |
| `V38_EQUITY_HISTORY_CSV_B64` | `date,equity_jpy` | 日次総資産。任意で`cash_jpy,deposits_jpy,withdrawals_jpy` |
| `V38_HOLDINGS_CSV_B64` | `ticker,quantity,entry_price,current_price,fx_to_jpy,stop_price` | 証券口座の実保有をCommand Center推定より優先 |
| `V38_CASH_FLOWS_CSV_B64` | `flow_id,date,type,amount_jpy` | `type`は`DEPOSIT`または`WITHDRAWAL` |

約定CSVでは`side`を`LONG`または`SHORT`で指定できる。省略時は同じ`position_id`のEntryから補完する。`action`はLONGの`BUY / SELL`、SHORTの`SELL / COVER`に加えて`BTO / STC / STO / BTC`を受け付ける。`point_value,fx_to_jpy,fees_jpy,taxes_jpy,stop_price,target_price,setup,nq_color,sector,theme`は任意列。

macOS / LinuxでSecret値を作る例:

```bash
base64 < executions.csv | tr -d '\n'
```

PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("executions.csv"))
```

約定明細は`position_id`単位で集約する。2分割エントリー、複数回の部分利確、手数料、税を一つの完結トレードへまとめ、まだ残玉があるポジションは完結トレード数へ入れない。同じ`execution_id`を再取込しても重複しない。

Command Center候補は日次履歴として蓄積し、Research Outcomesの10日後結果が確定した時点で自動付与する。実トレードは同一Tickerの直近候補（Entry日まで5日以内）へ結び付け、買った候補と見送った候補を同じ10日窓で比較する。

口座資産が未接続で過去の暗号化資産履歴もない場合、架空の円金額で本番版を作らず、セットアップ待ちとして扱う。

## 主な出力
- `index.html`
- `daily_card.png`
- `portfolio_card.png`
- `social_post_ja.txt`
- `weekly_review.md`
- `summary.json`
- 正規化取引・保有・資産・月次・Setup・地合い・候補比較・逸脱・配分・相関CSV
- Drawdown局面一覧、相関上位ペア、約定取込ステータス

## 安全性
- デモデータを実績として扱わない。
- 架空の口座残高や約定を本番データへ混ぜない。
- 損益はPoint Value、FX、手数料、税を反映する。
- 資産曲線は入出金を運用益として数えない。
- Stop逸脱を他の好条件で相殺しない。
- Command Center候補を約定として数えない。
- 自動売買や注文発注は行わない。
- 平文の取引・資産・保有データを公開リポジトリへ保存しない。
- 週次レビューはAI生成を装わず、保存データからの自動集計として表示する。
