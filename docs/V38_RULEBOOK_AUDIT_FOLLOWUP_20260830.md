# V38 第三者検証フォローアップ（2026-08-30）

この文書は `docs/V38_RULEBOOK_AUDIT_20260830.md` に対する第三者検証指摘の追補であり、既存Dashboardの本番切替を意味しない。

## 修正済み

- Clinical Biotech eligibility：研究仕様の構造条件へ一致。
  - Industry = `Biotechnology` または `Pharmaceuticals: Other`
  - Market Cap < $10B
  - 既知Revenue TTM < $50M
  - Revenue欠落はfail-open
- ATTACK候補一覧：LOO live未接続時は `RS189_PREVIEW_ONLY_UNTIL_LOO_LIVE` と明示し、Top50をFinal Rank / executable buy listとして扱わない。
- TQQQ panic public route：`tqqq-panic-state.json` はliveファイルが存在する場合のみpublic exportへ含めるoptional allowlistに追加。4H/CURRENT30 live生成自体は依然DATA REQUIRED。

## Build / Deployステータスの区分

過去Run `33312016467` のSUCCESSは以下を意味する。

- Build / validation：PASS
- main generated-state persistence：PASS
- Public export creation：PASS
- Public mirror push：SKIPPED / NOT CONFIGURED（`PUBLIC_REPOSITORY` / `PUBLIC_TOKEN`未設定時）

したがって `Run SUCCESS = public mirror deploy成功` とは表現しない。公開URLが最新commitと一致することは、deploy経路が実際に構成された後に別途HTTP/manifestで確認する。

## 未解決のまま維持

- strict LOO Peer Theme live calculation
- CURRENT30 hierarchy live target
- 4H RSI periodic generation
- Panic F80 Allocation Priority
- RSI30 headline `+6.20% / 72.3% / PF4.71`
- Historical PIT Theme taxonomy
- 本番Dashboard切替

## Breadth coverage guard

監査版は現状 `valid50 >= 30 and coverage >= 45%` でfail-closedする。これはデータ欠損時の安全guardとして機能するが、第三者指摘どおり研究コードと完全同型であることの独立証明はまだ完了していない。現行データは3748/3748 coverageで実判定への影響はないため、`LOW / VERIFY BEFORE PRODUCTION SWITCH` とする。
