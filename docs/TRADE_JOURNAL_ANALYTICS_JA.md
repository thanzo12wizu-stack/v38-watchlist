# Trade Journal Analytics

## 目的
既存Command Centerの候補選定、Portfolio、NQゲート、運用ルールを正本として利用し、実際の取引・資産・保有・規律・見送った候補を一つの運用実績システムで照合する。

既存Command Center本体は変更しない。Trade Journal Analyticsは独立サイドカーとしてHTML、PNG、CSV、JSON、Markdownを生成する。

## 画面構成

### 1. 今日
朝晩の確認を一画面で完結する。

- 本日、月初来、年初来リターン
- 総損益、PF、最大DD
- 相関調整Heat、名目Heat、Gross Exposure、最大リスククラスター
- NQ色に基づく新規可否
- 現金比率、保有数、ルール逸脱件数
- 日次確認用の保有一覧

### 2. 資産
長期の結果と下方リスクを確認する。

- 入出金調整後資産曲線
- ドローダウン曲線
- 月次ヒートマップ
- 勝率、平均利益、平均損失、Payoff、期待値、平均保有日数
- CAGR、Sharpe、Recovery Factor、規律遵守率

### 3. ポートフォリオ
現在の建玉と集中リスクを確認する。

- Treemap（面積＝評価額、色＝含み損益）
- セクター配分
- テーマ配分
- 相関調整Portfolio Heat
- 保有一覧、Stop、Heat、保有日数、Setup

### 4. 取引履歴
Trade Journalの実データを確認する。

- Entry、Exit、Ticker、Setup、NQ色
- 損益率、R、円損益、保有日数、Exit理由、規律
- Ticker・Setup・Exit理由の検索
- Setup、NQ色、勝敗によるフィルター
- フィルター後件数の表示

### 5. エッジ分析
自分の期待値が残る条件を確認する。

- セットアップ別の件数、勝率、PF、平均R、平均騰落、平均日数、損益
- NQ色別の同指標
- Missed Trade集計
- Command Center候補と実売買の照合
- 候補の10日後リターン、QQQ超過、実現リターン、Capture差

### 6. 振り返り
重大なルール違反と改善点を確認する。

- 赤・黄地合いエントリー
- ストップ過大、予定RR不足
- 決算接近、過熱、ギャップ追い
- 含み損への追加、1トレードリスク超過
- 自己申告のルール逸脱
- 数値根拠だけから生成するAI週次レビュー
- 入力ソースとフォールバックの明示

### 7. 共有
分析画面とは分離した投稿用出力を確認する。

- 1200×675の日次成績カード
- 1200×675のポートフォリオカード
- 投稿文プレビュー
- 投稿文コピー
- PNGと生成済みテキストの保存

## タブ操作

- タブは画面上部に固定し、スマートフォンでは横スクロールする。
- 選択タブはURLハッシュへ保存される。
- 再読み込みや共有URLでも同じタブを復元する。
- すべてのタブ内容を一枚に縦積みしない。

## 入力

### 取引履歴
`data/trade_journal/trades.csv`

主要項目:

- `trade_id`
- `ticker`
- `side`
- `entry_date`, `exit_date`
- `entry_price`, `exit_price`, `quantity`
- `fx_to_jpy`, `point_value`
- `fees_jpy`, `tax_jpy`
- `stop_price`, `target_price`
- `setup`, `nq_color`, `sector`, `theme`
- `exit_reason`, `rule_followed`, `mistake_type`

### 資産履歴
`data/trade_journal/equity.csv`

- `date`
- `equity_jpy`
- `cash_jpy`
- `deposit_jpy`
- `withdrawal_jpy`

### 保有
`data/trade_journal/holdings.csv`または既存Portfolio JSON。

### 候補履歴
`data/trade_journal/candidates.csv`または`data/intelligence/research/signals`。

### 相関
`prices.pkl`から直近60観測のリターン相関を使用する。取得できない場合は独立仮定とし、その旨をデータソース欄に表示する。

## 出力

- `index.html`
- `daily_card.png`
- `portfolio_card.png`
- `social_post_ja.txt`
- `weekly_review.md`
- `summary.json`
- `trades_normalized.csv`
- `holdings_normalized.csv`
- `equity_curve.csv`
- `monthly_returns.csv`
- `setup_analysis.csv`
- `regime_analysis.csv`
- `missed_trade_analysis.csv`
- `candidate_vs_actual.csv`
- `rule_violations.csv`
- `sector_allocation.csv`
- `theme_allocation.csv`
- `holding_correlations.csv`

## 安全性

- 重要入力がない場合に架空の口座残高や損益を表示しない。
- デモはCI・表示確認用で、実績として扱わない。
- 損益はPoint Value、FX、手数料、税を反映する。
- 資産曲線は入出金を運用益として数えない。
- 重大なルール違反を好条件で相殺しない。
- 自動売買や注文発注は行わない。
