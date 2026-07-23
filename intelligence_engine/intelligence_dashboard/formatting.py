from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

EMPTY_TEXT = {"", "—", "None", "null", "NULL", "UNKNOWN", "N/A", "nan"}


def present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    if isinstance(value, str):
        return value.strip() not in EMPTY_TEXT
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def esc(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value if present(item)]
        return html.escape(" / ".join(values)) if values else "—"
    if isinstance(value, dict):
        values = [f"{key}:{item}" for key, item in value.items() if present(item)]
        return html.escape(" / ".join(values)) if values else "—"
    return html.escape(str(value))


def num(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
        if not math.isfinite(number):
            return "—"
        return f"{number:,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def money(value: Any) -> str:
    try:
        number = float(value)
        if not math.isfinite(number):
            return "—"
        return f"${number:,.2f}"
    except (TypeError, ValueError):
        return "—"


def pct(value: Any, digits: int = 1, *, decimal: bool = False, signed: bool = False) -> str:
    try:
        number = float(value)
        if not math.isfinite(number):
            return "—"
        if decimal:
            number *= 100
        sign = "+" if signed and number > 0 else ""
        return f"{sign}{number:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt(value: Any, kind: str) -> str:
    if kind == "pct":
        return pct(value, decimal=True)
    if kind == "pct_raw":
        return pct(value)
    if kind == "pct_signed":
        return pct(value, signed=True)
    if kind == "pct_decimal_signed":
        return pct(value, decimal=True, signed=True)
    if kind == "money":
        return money(value)
    if kind == "num":
        return num(value)
    if kind == "int":
        return num(value, 0)
    return esc(value)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def unwrap(value: Any, key: str) -> Any:
    if not isinstance(value, dict):
        return value
    wrappers = {
        "sector_rotation": ("sectors",),
        "theme_intelligence": ("themes",),
        "entry_candidates": ("candidates",),
        "external_data": ("records",),
        "leader_board": ("boards",),
    }
    for candidate in wrappers.get(key, ()):
        if candidate in value:
            return value.get(candidate) or []
    return value


def load_payload(input_path: Path) -> dict:
    combined = read_json(input_path)
    if isinstance(combined, dict):
        combined.setdefault("dashboard_input_status", "INDEX")
        return combined

    root = input_path.parent
    payload: dict[str, Any] = {
        "dashboard_input_status": "BOOTSTRAP_NO_INDEX",
        "manifest": {"dashboard_input_status": "BOOTSTRAP_NO_INDEX"},
    }
    file_map = {
        "market_state": "market_state.json",
        "sector_rotation": "sector_rotation.json",
        "theme_intelligence": "theme_intelligence.json",
        "portfolio_doctor": "portfolio_doctor.json",
        "morning_brief": "morning_brief.json",
        "expectancy_rankings": "expectancy_rankings.json",
        "robust_expectancy": "robust_expectancy.json",
        "leader_transitions": "leader_transitions.json",
        "leader_board": "leader_board.json",
        "data_quality": "data_quality.json",
        "entry_candidates": "entry_candidates.json",
        "external_data": "external_data.json",
    }
    for key, filename in file_map.items():
        value = read_json(root / filename)
        if value is not None:
            payload[key] = unwrap(value, key)
            if isinstance(value, dict) and not payload.get("generated_at"):
                payload["generated_at"] = value.get("generated_at")
    payload["manifest"]["bootstrap_sections"] = [
        key for key in payload if key not in {"dashboard_input_status", "manifest", "generated_at"}
    ]
    return payload


def as_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def partition(candidates: list[dict]) -> dict[str, list[dict]]:
    output = {"ACTIONABLE": [], "READY": [], "AVOID": []}
    for item in candidates:
        status = item.get("decision_status")
        if status not in output:
            status = "ACTIONABLE" if item.get("actionable") else "READY"
        output[status].append(item)
    for status in output:
        output[status].sort(
            key=lambda item: (
                -float(item.get("final_rank_score") or item.get("score_entry") or 0),
                str(item.get("ticker") or ""),
            )
        )
    return output


def status_ja(status: str) -> str:
    return {"ACTIONABLE": "発注可能", "READY": "準備", "AVOID": "回避"}.get(status, status)


def friendly_status(status: Any) -> str:
    mapping = {
        "NO_SETTLED_OBSERVATIONS": "実運用結果を蓄積中。履歴バックテストを優先表示しています。",
        "NO_PRIOR_HISTORY": "前日Snapshot未蓄積。価格履歴比較を使用しています。",
        "PRICE_HISTORY": "価格履歴5営業日比較",
        "OK": "稼働中",
        "PASS": "正常",
        "WARN": "警告あり",
        "NO_POSITIONS": "Portfolio未設定",
        "EMPTY": "データ未設定",
    }
    return mapping.get(str(status), str(status or "—"))
