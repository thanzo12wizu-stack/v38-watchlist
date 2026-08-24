from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

try:
    from leadership.render_japanese import render_html
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    from render_japanese import render_html


PHASE_JA = {
    "EMERGING": "新興",
    "LEADING": "主導",
    "MATURE": "成熟",
    "LOSING": "失速",
}


def _esc(value: Any) -> str:
    return html.escape(str("—" if value is None else value), quote=True)


def _phase_class(value: Any) -> str:
    key = str(value or "").lower()
    return key if key in {"emerging", "leading", "mature", "losing"} else "losing"


def _group_row(group: dict[str, Any]) -> str:
    phase = str(group.get("phase") or "")
    phase_ja = PHASE_JA.get(phase, phase or "—")
    pioneer = group.get("pioneer_score")
    breadth = group.get("breadth_score")
    leader_breakouts = group.get("leader_breakouts")
    leaders = group.get("leaders")
    return (
        f'<button class="leadrow granular phase-{_esc(_phase_class(phase))}" data-group="{_esc(group.get("name"))}">'
        f'<span class="phasebadge">{_esc(phase_ja)}</span>'
        f'<span class="leadname">{_esc(group.get("name"))}</span>'
        f'<span class="leadscore">{_esc(group.get("score"))}</span>'
        f'<span class="leaddetail">P {_esc(pioneer)} · B {_esc(breadth)} · BO {_esc(leader_breakouts)} · 主導株 {_esc(leaders)}</span>'
        f'</button>'
    )


def add_full_group_visibility(page: str, model: dict[str, Any]) -> str:
    """Expose all granular groups without changing the compact top-8 hierarchy."""
    groups = list(model.get("groups") or [])
    if not groups:
        return page

    active = [g for g in groups if str(g.get("phase") or "") in {"EMERGING", "LEADING"}]
    active_html = "".join(_group_row(g) for g in active) or '<div class="empty">現在の新興・主導グループはありません。</div>'
    all_html = "".join(_group_row(g) for g in groups)
    section = f'''
<section class="card groupaudit">
  <div class="board-title"><h2>全主導グループ</h2><small>{len(active)} / {len(groups)}</small></div>
  <div class="sub">新興・主導を上限なしで表示。P=先導性、B=広がり、BO=先導/主導株の20・50日ブレイク。</div>
  <div class="leadlist activegroups">{active_html}</div>
  <details class="datafold allgroupsfold"><summary>全Industry Group（{len(groups)}）</summary><div class="leadlist allgroups">{all_html}</div></details>
</section>
'''
    marker = '<section class="card">\n  <h2>主導セクター</h2>'
    if marker not in page:
        raise RuntimeError("Leadership public renderer anchor not found")
    page = page.replace(marker, section + "\n" + marker, 1)
    css = '''
.groupaudit .board-title{margin-bottom:7px}
.groupaudit .activegroups{max-height:560px;overflow:auto;padding-right:2px}
.groupaudit .granular .leaddetail{font-variant-numeric:tabular-nums}
.allgroupsfold{margin-top:10px;border-top:1px solid #182131;padding-top:8px}
.allgroups{margin-top:8px;max-height:620px;overflow:auto;padding-right:2px}
'''
    return page.replace('</style>', css + '\n</style>', 1)


def render_public_html(model: dict[str, Any]) -> str:
    return add_full_group_visibility(render_html(model), model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Japanese V38-style Leadership public page")
    parser.add_argument("--model", type=Path, default=Path("leadership/dist/leadership.json"))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist/index.html"))
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_public_html(model), encoding="utf-8")


if __name__ == "__main__":
    main()
