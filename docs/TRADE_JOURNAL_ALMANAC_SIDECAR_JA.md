# Trade Journal Almanac Sidecar

## 目的

Almanac版を、既存Command Centerおよび既存Trade Journalとは別の成果物として検証する。
既存画面を置き換えず、比較・評価・段階導入できる状態を維持する。

## 分離契約

Almanac版は以下だけを使用する。

- 実行モジュール: `intelligence_engine.trade_journal_almanac_run`
- 15銘柄デモ: `intelligence_engine.trade_journal_almanac_demo15`
- 出力先: `artifacts/trade-journal-almanac/`
- ワークフロー: `Trade Journal Almanac Sidecar`
- Artifact名: `trade-journal-almanac-sidecar`

以下には書き込まない。

- `artifacts/trade-journal/`
- `artifacts/intelligence/`
- 既存Command CenterのHTML
- 既存Trade JournalのHTML
- 既存公開先

入力の正規化・分析ロジックはTrade Journalエンジンと共有するが、レンダリングと成果物の公開単位は独立させる。

## 画面設計

- 暖色のAlmanacデザイン
- スマートフォンを第一対象とした最大幅760px
- 7つの実リンクタブ
- タブ横スクロールなし
- 15銘柄ではStop距離が近い順に表示
- 初期8銘柄、残りは明示操作で展開
- 入出金調整後の日次口座評価額を資産曲線に使用
- 取引履歴は20件ずつ追加表示
- エッジ分析は期間・軸・並べ替え・最小件数を変更可能

## 実行

```bash
python -m intelligence_engine.trade_journal_almanac_demo15 \
  --output artifacts/trade-journal-almanac \
  --starting-equity-jpy 7300000
```

実データの場合:

```bash
python -m intelligence_engine.trade_journal_almanac_run \
  --input data/trade_journal \
  --output artifacts/trade-journal-almanac \
  --starting-equity-jpy 7300000
```

## 採用判断

Almanac版は既存版と並行して確認する。既存版の削除、公開先の切替、既存リンクの変更は、この分離実装には含めない。
