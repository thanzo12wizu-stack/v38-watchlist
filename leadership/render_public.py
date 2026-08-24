from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from leadership.prebreakout_overlay import apply_prebreakout_overlay
    from leadership.render_structured import render_html
    from leadership.structure_overlay import apply_structure_overlay
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    from prebreakout_overlay import apply_prebreakout_overlay
    from render_structured import render_html
    from structure_overlay import apply_structure_overlay


def _prebreakout_copy(page: str) -> str:
    replacements = {
        "主導グループの初動と主導株ブレイクを優先。伸びた株は追わない。": "主導株の発火前を優先。Pivot直下で締まった銘柄を先に見る。発火済みは追わない。",
        "上位グループだけ。構造が悪いSupply直下は突破待ち。": "上位グループだけ。発火前READY/COILEDを優先し、発火済みは追わない。",
        "<span>今入れる</span>": "<span>発火前READY</span>",
        "<span>待機</span>": "<span>発火前監視</span>",
        "<h2>今、入れる</h2>": "<h2>発火前・最優先</h2>",
        "主導性 × 構造 × 主導株ブレイク。Supply直下は原則ここから外す。": "主導株 × Pivotまで0〜4% × RS高位/加速 × Supply吸収 × Demand支持。ブレイクする前だけを表示。",
        "<h2>強いが、まだ待つ</h2>": "<h2>発火前・次点</h2>",
        "主導性はあるが、Supply突破・押し目・初動条件を待つ。": "COILED/監視。Pivotまでの距離や吸収がもう一段整えばREADY。",
        "Supply＝未突破20/50日Pivot。Demand＝21EMA・50SMA・63VWAP・突破済Pivotのうち直下の支持。Supply直前でRS加速・低出来高テスト、またはブレイク成立を吸収として評価。": "発火前候補＝未突破20/50日Pivotまでの距離、主導度、RS63/21、RS加速、Supply吸収、Demand支持、出来高乾きを統合。発火済みは候補リストから除外。",
    }
    for old, new in replacements.items():
        page = page.replace(old, new)
    return page


def render_public_html(model: dict) -> str:
    structured = apply_structure_overlay(model)
    enriched = apply_prebreakout_overlay(structured)
    return _prebreakout_copy(render_html(enriched))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render V38-style Leadership with pre-breakout candidates first")
    parser.add_argument("--model", type=Path, default=Path("leadership/dist/leadership.json"))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist/index.html"))
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    structured = apply_structure_overlay(model)
    enriched = apply_prebreakout_overlay(structured)
    args.model.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_prebreakout_copy(render_html(enriched)), encoding="utf-8")


if __name__ == "__main__":
    main()
