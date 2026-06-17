from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: str | Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    p = Path(path)
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not p.exists():
        return rows, [f"missing output file: {p}"]
    with p.open("r", encoding="utf-8") as handle:
        for idx, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {idx}: invalid JSONL object: {exc}")
                continue
            if not isinstance(row, dict):
                errors.append(f"line {idx}: JSONL row must be an object")
                continue
            rows.append(row)
    return rows, errors


def write_jsonl(path: str | Path, rows: List[Dict[str, Any]]) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
