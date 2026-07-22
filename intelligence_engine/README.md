# Investment Intelligence Engine

既存Command Centerを変更せず横に置く、将来のアプリ/API向けデータ基盤です。`build_dashboard.py`をimport・更新・上書きしません。

## 実装済み

- QQQ対比RS: 21/63/126/189/252日
- 各RSの直近21日改善度
- ADR、出来高金額、出来高比、52週高値距離
- `yfinance`の分割取得、取得率・失敗診断、QQQ必須化
- 日本語ユニバース列（シンボル、セクター、時価総額）対応
- SEC Company Facts bulkから対象銘柄だけ抽出
- US-GAAP / IFRSのタグ経路分離
- 単四半期値の優先とH1/9M累計値からの差分復元
- EPS・売上成長、加速度、利益率、FCF、希薄化
- 欠損を0点扱いしないpercentile scoring
- Candidate / Emerging / Compounder / Breakout / Turnaround
- バージョン付きスコアポリシー
- 軽量index、上位銘柄詳細JSON、日付別履歴
- 5/10/21/63営業日のQQQ超過リターン検証基盤
- 入力診断、出力契約検証、静的リリースゲート
- 将来のAI narrative、13F、estimate revision用nullableフィールド

## 安全境界

出力先は`data/intelligence/`と`data/sec_companyfacts/`のみです。独立workflowが失敗しても既存ダッシュボードのworkflow・HTML・stateには影響しません。SEC識別情報が未設定でも価格・RS基盤は生成でき、財務項目は欠損として扱います。

## 実行

```bash
python -m intelligence_engine.release_check --root .
python -m intelligence_engine.sec_bulk --universe universe.csv
python -m intelligence_engine.pipeline --universe universe.csv --prices prices.pkl
python -m intelligence_engine.validate_outputs --root data/intelligence
python -m intelligence_engine.query --sort score_emerging --limit 20
```

`prices.pkl`が存在しない場合は`yfinance`から取得します。本番でSECを利用する場合、GitHub Secret `SEC_USER_AGENT`にSECが連絡可能な名称とメールアドレスを設定してください。

## 出力契約

- `data/intelligence/manifest.json`
- `data/intelligence/index.json`
- `data/intelligence/stocks/<TICKER>.json`
- `data/intelligence/history/YYYY-MM-DD.json`

`schema_version`は`1.0`、`score_policy_version`は`1.0.0`。将来のアプリは未知のoptional fieldを無視し、未知のmajor versionを拒否する設計です。

## 候補抽出思想

RS189単独ではなく、確立済みリーダー、短中期加速、業績変曲、ブレイク準備を別経路で拾います。IFRS企業や財務欠損企業はcoverage/confidenceを下げますが、自動的に0点や除外にはしません。スコアを売買判断へ接続する前に、日付別snapshotと前方リターン検証で有効性を確認します。
