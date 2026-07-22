# Investment Intelligence Engine

既存Command Centerを変更せず横に置く、将来のアプリ/API向けデータ基盤です。`build_dashboard.py`をimport・更新・上書きしません。

## 実装済み

- QQQ対比RS: 21/63/126/189/252日
- 各RSの直近21日改善度
- ADR、出来高金額、出来高比、52週高値距離
- SEC Company Facts bulkから対象銘柄だけ抽出
- US-GAAP / IFRSのタグ経路分離
- 単四半期値の優先とH1/9M累計値からの差分復元
- EPS・売上成長、加速度、利益率、FCF、希薄化
- 欠損を0点扱いしないpercentile scoring
- Candidate / Emerging / Compounder / Breakout / Turnaround
- 軽量index、上位銘柄詳細JSON、日付別履歴
- 将来のAI narrative、13F、estimate revision用nullableフィールド

## 安全境界

出力先は`data/intelligence/`と`data/sec_companyfacts/`のみです。独立workflowが失敗しても既存ダッシュボードのworkflow・HTML・stateには影響しません。

## 実行

```bash
python -m intelligence_engine.sec_bulk --universe universe.csv
python -m intelligence_engine.pipeline --universe universe.csv --prices prices.pkl
python -m intelligence_engine.query --sort score_emerging --limit 20
```

本番ではGitHub Secret `SEC_USER_AGENT`に、SECが連絡可能な実際の名称とメールアドレスを設定してください。

## 出力契約

- `data/intelligence/manifest.json`
- `data/intelligence/index.json`
- `data/intelligence/stocks/<TICKER>.json`
- `data/intelligence/history/YYYY-MM-DD.json`

schema_versionは現在`1.0`。将来のアプリは未知のoptional fieldを無視し、未知のmajor versionを拒否する設計とします。

## 候補抽出思想

RS189単独ではなく、確立済みリーダー、短中期加速、業績変曲、ブレイク準備を別経路で拾います。IFRS企業や財務欠損企業はcoverage/confidenceを下げますが、自動的に0点や除外にはしません。
