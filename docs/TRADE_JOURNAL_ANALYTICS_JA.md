# Trade Journal & Portfolio Analytics

## 目的

Command Centerが出した候補と、実際に行った取引・保有・資産推移を同じ正本で管理するサイドカーです。取引履歴を見栄えよく並べるだけでなく、どの地合い・セットアップ・ルールで利益と損失が発生したかを検証します。

既存Command Centerの生成処理や本番HTMLは変更しません。入力CSV/JSONと保存済みresearch signalsを読み、独立した静的HTML・PNG・CSV・Markdownを生成します。

## 実装済み

### Phase 1

- Trade Journal
- 入出金調整後の資産推移
- 月次ヒートマップ
- 現在保有一覧
- セクター・テーマ配分
- 勝率、平均利益、平均損失、PF、期待値、平均R、CAGR、Sharpe、最大DD、Recovery Factor、ルール遵守率
- 1200×675の日次投稿カード

### Phase 2

- 保有評価額×含み損益Treemap
- ドローダウン曲線
- セットアップ別分析
- NQ色別分析
- 買った候補と見送った候補の10日後比較
- 1200×675のポートフォリオ投稿カード

### Phase 3

- 直近60観測の銘柄相関を使った相関調整後Portfolio Heat
- RED/YELLOW新規、ストップ過大、低RR、決算接近、3ATR超、ギャップ追い、含み損追加、過大リスクの検知
- 数値根拠から生成する週次レビュー
- Command Center候補と実際のエントリーの照合
- 投稿文、日次カード、ポートフォリオカードの自動生成

## 入力

`data/trade_journal/` に以下を置きます。空テンプレートはコマンドで生成できます。

```bash
python -m intelligence_engine.trade_journal_run --init-templates
```

### trades.csv

必須に近い項目:

- `ticker`
- `entry_date`, `exit_date`
- `entry_price`, `exit_price`
- `quantity`

精度を上げる項目:

- `point_value`, `fx_to_jpy`, `fees_jpy`, `taxes_jpy`
- `stop_price`, `target_price`
- `setup`, `nq_color`, `sector`, `theme`
- `rule_followed`, `mistake_type`
- `mfe_pct`, `mae_pct`

米国株は`fx_to_jpy`に約定時または集計用のドル円を入れます。先物等は`point_value`も入れます。損益額を直接持っている場合は`net_pnl_jpy`を追加すると、その値を正本として使います。

### equity.csv

- `date`
- `equity_jpy`
- `cash_jpy`
- `deposits_jpy`
- `withdrawals_jpy`

資産曲線は入出金を差し引いた`adjusted_equity_jpy`で評価します。equity.csvがない場合は、開始資産と決済済みトレードから簡易曲線を作ります。

### holdings.csv または既存Portfolio JSON

- `ticker`, `quantity`
- `entry_price`, `current_price`, `fx_to_jpy`
- `stop_price`
- `sector`, `theme`
- `entry_date`, `setup`, `nq_color`

既存のDefensive Risk形式にある`account_equity_jpy`、`available_cash_jpy`、`holdings[].market_value_jpy`、`holdings[].stop_fraction`も読めます。`stop_fraction × market_value_jpy`を予定損失としてHeatへ接続します。

### candidates.csv またはresearch signals

- `date`, `ticker`, `rank`
- `forward_10d_return`, `qqq_excess_10d`
- `setup`, `nq_color`, `sector`, `theme`

CSVがない場合は`data/intelligence/research/signals/*.jsonl.gz`の最新日を候補として読みます。実際の`trades.entry_date + ticker`と一致した候補を「買った候補」と判定します。

### 価格履歴

`prices.pkl`が存在する場合、保有銘柄の直近60観測リターン相関を計算します。ない場合は相関を仮定せず、独立ケースとして表示し、レポートに注記します。

## 実行

```bash
python -m intelligence_engine.trade_journal_run \
  --input data/trade_journal \
  --output artifacts/trade-journal \
  --starting-equity-jpy 7300000 \
  --portfolio config/portfolio.json \
  --rules config/trade_journal.example.json \
  --research-root data/intelligence/research \
  --prices prices.pkl
```

動作確認用:

```bash
python -m intelligence_engine.trade_journal_run --demo
```

## 出力

- `index.html`: スマホ対応の分析ダッシュボード
- `daily_card.png`: 日次投稿カード
- `portfolio_card.png`: ポートフォリオTreemapカード
- `social_post_ja.txt`: 投稿文
- `weekly_review.md`: 週次コーチ
- `summary.json`: KPIとHeat
- `equity_curve.csv`, `monthly_returns.csv`
- `setup_analysis.csv`, `regime_analysis.csv`
- `missed_trade_analysis.csv`, `candidate_vs_actual.csv`
- `rule_violations.csv`
- `sector_allocation.csv`, `theme_allocation.csv`
- `holding_correlations.csv`

## 計算上の注意

- PFは実現損益の正の合計÷負の合計絶対値です。
- Rは`net_pnl_jpy ÷ planned_risk_jpy`です。
- planned riskは`|entry-stop| × quantity × point_value × fx_to_jpy`です。
- 相関調整Heatは、各銘柄Heatベクトルを`h`、相関行列を`C`として`sqrt(h' C h)`です。全銘柄が完全相関なら名目Heatと一致します。
- ルール項目が未記録の場合、逸脱と断定しません。明示されたデータだけを検査します。
- 週次レビューは外部LLMを使わない決定論的生成です。数値が同じなら文章も同じになり、捏造を避けます。

## 既存Command Centerとの役割分担

- Command Center: 市場、セクター、候補、エントリー適性
- Trade Journal: 実際に何を買い、どう終わり、何が再現性を持ったか
- Portfolio Analytics: 現在の集中、Heat、相関、含み損益
- Share Studio: 投稿カードと投稿文

銘柄選定ロジックを二重化せず、既存候補を実績検証へ戻すことを優先します。
