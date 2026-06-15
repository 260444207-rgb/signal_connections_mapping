#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from common import (
    extract_index,
    iter_jsonl,
    load_pin_catalog,
    normalize_text,
    pins_for_part,
    resolve_catalog_key,
    simple_similarity,
    write_jsonl,
)


def score_candidate(row: Dict[str, Any], pin_name: str) -> Dict[str, Any]:
    pin_name = normalize_text(pin_name)
    source_port = normalize_text(row.get("source_port", ""))
    target_port = normalize_text(row.get("target_port", ""))

    score = 0.0
    basis: List[str] = []

    name_score = simple_similarity(source_port, pin_name)
    if name_score > 0:
        score += name_score * 0.45
        basis.append("source_port_pin_name_similarity")

    source_index = extract_index(source_port)
    pin_index = extract_index(pin_name)
    if source_index is not None and pin_index is not None and source_index == pin_index:
        score += 0.25
        basis.append("index_match")

    target_score = simple_similarity(target_port, pin_name)
    if target_score > 0:
        score += target_score * 0.15
        basis.append("target_port_similarity")

    if row.get("direction") in {"INPUT", "OUTPUT"}:
        score += 0.05
        basis.append("direction_available")

    return {
        "pin": pin_name,
        "score": round(min(score, 1.0), 4),
        "basis": basis,
    }


def generate_candidates(
    normalized_path: str | Path,
    pin_path: str | Path,
    output_path: str | Path,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    catalog = load_pin_catalog(pin_path)
    output_rows: List[Dict[str, Any]] = []

    for row in iter_jsonl(normalized_path):
        part_id = row.get("source_part_id", "")
        resolved_part_id = resolve_catalog_key(catalog, part_id)
        available_pins = pins_for_part(catalog, part_id)
        candidates = [score_candidate(row, pin) for pin in available_pins]
        candidates.sort(key=lambda item: item["score"], reverse=True)

        output_rows.append({
            "line_id": row["line_id"],
            "source_part_id": part_id,
            "resolved_part_id": resolved_part_id,
            "source_block_id": row.get("source_block_id", ""),
            "source_port": row.get("source_port", ""),
            "target_block_name": row.get("target_block_name", ""),
            "target_port": row.get("target_port", ""),
            "direction": row.get("direction", ""),
            "expansion_index": row.get("expansion_index", 1),
            "expansion_count": row.get("expansion_count", 1),
            "available_pins": available_pins,
            "candidates": candidates[:top_k],
        })

    write_jsonl(output_path, output_rows)
    return output_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--pins", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    rows = generate_candidates(args.normalized, args.pins, args.output, args.top_k)
    print(f"[OK] candidate mappings: {len(rows)} -> {args.output}")


if __name__ == "__main__":
    main()
