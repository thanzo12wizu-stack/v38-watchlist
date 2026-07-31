# Trade Journal Almanac Sidecar

## 目的

Almanac版を、既存Command Centerおよび既存Trade Journalとは別の成果物として検証する。
既存画面を置き換えず、比較・評価・段階導入できる状態を維持する。

## 分離契約

Almanac版は以下だけを使用する。

- 実行モジュール: `intelligence_engine.trade_journal_almanac_run`
- 15銘柄デモ: `intelligence_engine.trade_journal_almanac_demo15`
- 出力先: `artifacts/trade-journal-almanac/`
- 自動更新: 既存の `Intelligence Engine (sidecar)` に統合
- 公開入口: 暗号化済み `trade-journal-almanac.html`
- 暗号化履歴: `private/trade-journal-state.enc.json`

以下には書き込まない。

- `artifacts/trade-journal/`
- `artifacts/intelligence/`
- 既存Command CenterのHTML
- 既存Trade JournalのHTML
- 既存3画面の公開ファイル

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
  --require-live-data
```

`--require-live-data`では実口座総資産または資産履歴がない限り、架空の730万円を表示せず「実データ接続待ち」を出す。

## 自動更新経路

GitHub Actionsの本番ワークフローは3本のまま維持する。Almanac専用の4本目は作らない。

1. `private/trade-journal-state.enc.json`を復号
2. リポジトリ既存の`equity.csv`とSecretsのCSVをIDで差分取込
3. `data/intelligence/index.json`から地合い・候補・Portfolio Doctorを同期
4. Almanacを生成
5. `trade-journal-almanac.html`をAES-256-GCMでロック
6. 履歴を`private/trade-journal-state.enc.json`へ再暗号化
7. 平文の`data/trade_journal`を削除してからcommit

実行に使うワークフローを削除せず、`dashboard.yml`、`intelligence-engine.yml`、`publish-public-site.yml`の3本だけを運用する。

既存の`equity.csv`は`date / equity`を`date / equity_jpy`へ変換して自動利用する。過去ファイルに混在するタブ区切りと空白区切りの両方を読み、同日の秘密資産履歴がある場合は秘密入力を優先する。最新資産日から7日を超えた場合は、当日値へ複製せず`PARTIAL / 要更新`として表示する。

## 採用判断

Almanac版は既存版と並行して確認する。既存版を削除・置換せず、Command Hubに4つ目の独立入口だけを追加する。
