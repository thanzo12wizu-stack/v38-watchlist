# Leadership Command

独立した主導セクター・主導株探索フロー。

## Decision flow

`MARKET → ROTATION → GROUP → PIONEER / LEADER → ENTRY`

## Read-only inputs

- `state.json`
- `sector_snapshot.json`
- `industry_map.json`
- `earnings.json`
- `universe.csv`

既存 `build_dashboard.py` は import / 実行しない。既存生成物へ書き戻さない。

## Outputs

`leadership/dist/` に以下を生成する。

- `index.html`
- `leadership.json`
- `diagnostics.json`

生成物は source repo へ commit しない。

## Public boundary

公開は専用の `LEADERSHIP_PUBLIC_REPOSITORY` / `LEADERSHIP_PUBLIC_TOKEN` が両方設定された場合だけ行う。未設定時は build + artifact preview だけで終了し、既存公開サイトには触れない。
