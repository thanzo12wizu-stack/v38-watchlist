# Trade Journal Almanac Sidecar

## 目的

Almanac版を、既存Command Centerおよび既存Trade Journalとは別の成果物として検証する。
既存画面を置き換えず、比較・評価・段階導入できる状態を維持する。

## 分離契約

Almanac版は以下だけを使用する。

- 実行モジュール: `kaview.run`
- 15銘柄デモ: `kaview.demo`
- 出力先: `kaview/artifacts/`
- 自動更新: なし（完成・受入までは既存workflowへ接続しない）
- 公開入口: なし（既存Command Hubへ追加しない）
- 実データと暗号化状態はリポジトリへ含めず、利用者側で管理

以下には書き込まない。

- `artifacts/`
- `data/intelligence/`
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
python -m kaview.demo \
  --output kaview/artifacts \
  --starting-equity-jpy 7300000
```

実データの場合:

```bash
python -m kaview.run \
  --input kaview/data \
  --output kaview/artifacts \
  --require-live-data
```

`--require-live-data`では実口座総資産または資産履歴がない限り、架空の730万円を表示せず「実データ接続待ち」を出す。

## 更新経路

完成・受入まではローカルの明示実行だけを使用する。GitHub Actionsは追加せず、既存の`dashboard.yml`、`intelligence-engine.yml`、`publish-public-site.yml`からもKaviewを呼ばない。

1. 必要なCSVを`kaview/data`へ配置
2. 必要な場合だけ既存Intelligenceの出力を読み取り専用入力として指定
3. `python -m kaview`で`kaview/artifacts`へ生成
4. 入力平文をcommitしない

既存の`equity.csv`は`date / equity`を`date / equity_jpy`へ変換して自動利用する。過去ファイルに混在するタブ区切りと空白区切りの両方を読み、同日の秘密資産履歴がある場合は秘密入力を優先する。最新資産日から7日を超えた場合は、当日値へ複製せず`PARTIAL / 要更新`として表示する。

## 採用判断

Kaviewは既存版と分離した状態で確認する。完成・受入後に限り、既存Command Hubへの統合方法を別途決める。
