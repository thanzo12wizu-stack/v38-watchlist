# V38 Signal Ledger — Trade Journal & Portfolio Analytics

## 目的
既存Command Centerの候補選定、Portfolio Doctor、NQゲート、セクター・テーマ、価格データと、実際の取引・資産推移・規律を一つの運用台帳で照合する。

出力の中心は外部CSS・外部画像・別ページを必要としない`index.html`。今日、資産、ポートフォリオ、取引履歴、エッジ分析、振り返り、共有を一つのHTML内に収録する。

## デザイン
一般的な黒背景・紫グラデーション・丸いカード型ダッシュボードは使用しない。

- コンセプト: **Editorial Trading Terminal / 専用運用台帳**
- 暖色の紙面、黒い罫線、コバルトブルー、アシッドライム
- セクション番号付きの明確な視線導線
- 丸いカード、ガラス表現、過剰な影を撤去
- 数字、表、リスク表示を優先した高密度レイアウト
- 日次カードとポートフォリオカードも同一デザイン言語で生成

## 1ファイル構成
上部ナビゲーションは同じHTML内のアンカーへ移動する。

1. 今日 / OPERATIONS
2. 資産 / EQUITY LEDGER
3. ポートフォリオ / POSITION BOOK
4. 取引履歴 / TRADE TAPE
5. エッジ分析 / EDGE LAB
6. 振り返り / CONTROL ROOM
7. 共有 / PUBLISH

JavaScriptが無効なファイルプレビューでも全セクションを閲覧できる。日次カードとポートフォリオカードはBase64で`index.html`内にも埋め込む。

## 既存Command Centerとの自動連携
### 自動で同期するもの
`Private Trade Journal`ワークフローは`Intelligence Engine (sidecar)`の正常終了後に実行される。

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
- `V38_EQUITY_HISTORY_CSV_B64`: Base64化した資産履歴CSV

口座資産が未接続で過去の暗号化資産履歴もない場合、架空の円金額で本番版を作らず、セットアップ待ちとして扱う。

## 画面内容
### 今日
本日・月初来・年初来、総損益、PF、最大DD、NQゲート、相関調整Heat、Gross Exposure、保有一覧。

### 資産
入出金調整後資産曲線、ドローダウン、月次ヒートマップ、勝率、平均利益・損失、Payoff、期待値、CAGR、Sharpe、Recovery Factor。

### ポートフォリオ
Treemap、セクター・テーマ配分、名目Heat、相関調整Heat、Stop、保有日数、Setup、含み損益。

### 取引履歴
Entry、Exit、Ticker、Setup、NQ色、損益率、R、円損益、保有日数、Exit理由、規律。Ticker・Setup・NQ・勝敗で検索・絞り込みできる。

### エッジ分析
セットアップ別、NQ色別、Missed Trade、Command Center候補と実売買、10日後QQQ超過、Capture差。

### 振り返り
ルール逸脱、決算接近、過熱、ギャップ追い、含み損追加、リスク超過、AI週次レビュー、データソース。

### 共有
1200×675の日次カード、ポートフォリオカード、投稿文プレビューとコピー。

## 入力ファイル
- `data/trade_journal/trades.csv`
- `data/trade_journal/equity.csv`
- `data/trade_journal/holdings.csv`
- `data/trade_journal/candidates.csv`
- `data/trade_journal/market_context.csv`
- `data/intelligence/index.json`
- `prices.pkl`

## 主な出力
- `index.html`
- `daily_card.png`
- `portfolio_card.png`
- `social_post_ja.txt`
- `weekly_review.md`
- `summary.json`
- 正規化取引・保有・資産・月次・Setup・地合い・候補比較・逸脱・配分・相関CSV

## 安全性
- デモデータを実績として扱わない。
- 架空の口座残高や約定を本番データへ混ぜない。
- 損益はPoint Value、FX、手数料、税を反映する。
- 資産曲線は入出金を運用益として数えない。
- 重大なルール違反を他の好条件で相殺しない。
- 自動売買や注文発注は行わない。
- 平文の取引・資産・保有データを公開リポジトリへ保存しない。
