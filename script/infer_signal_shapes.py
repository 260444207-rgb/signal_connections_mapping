#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List

from common import (
    iter_jsonl,
    load_pin_catalog,
    normalize_text,
    pins_for_part,
    write_jsonl,
)

GENERIC_RULE_TERMS = {
    "LINE",
    "INPUT",
    "OUTPUT",
    "GPIO",
    "ALERT",
    "OUT",
    "IN",
    "CLK",
    "CTRL",
    "SIG",
}


def load_candidate_map(path: str | Path) -> Dict[str, Dict[str, Any]]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    return {row["line_id"]: row for row in iter_jsonl(path)}


def read_rule_text(path: str | Path | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def text_blob(row: Dict[str, Any]) -> str:
    return " ".join([
        normalize_text(row.get("source_part_id", "")),
        normalize_text(row.get("source_block_id", "")),
        normalize_text(row.get("source_block_name", "")),
        normalize_text(row.get("source_port", "")),
        normalize_text(row.get("target_block_id", "")),
        normalize_text(row.get("target_block_name", "")),
        normalize_text(row.get("target_port", "")),
        normalize_text(row.get("connection_id", "")),
        normalize_text(row.get("connection_name", "")),
        normalize_text(row.get("user_link_info", "")),
        normalize_text(row.get("device_role_info", "")),
    ])


def bus_width_from_text(text: str) -> int:
    text = normalize_text(text)
    widths: List[int] = []
    for m in re.finditer(r"\[(\d+)\s*:\s*(\d+)\]", text):
        widths.append(abs(int(m.group(1)) - int(m.group(2))) + 1)
    for m in re.finditer(r"(?:^|[^A-Z0-9])\*(\d+)(?:$|[^A-Z0-9])", text, re.I):
        widths.append(int(m.group(1)))
    for m in re.finditer(r"\b(?:BUS|DATA|GPIO)\s*\[?(\d+)\s*[-_~:]\s*(\d+)\]?\b", text, re.I):
        widths.append(abs(int(m.group(1)) - int(m.group(2))) + 1)
    return max(widths) if widths else 1


def explicit_bus_reason(row: Dict[str, Any]) -> tuple[int, List[str]]:
    if int(row.get("expansion_count", 1) or 1) > 1:
        # normalize_connections has already materialized these members.
        return 1, []
    blob = " ".join([
        normalize_text(row.get("source_port", "")),
        normalize_text(row.get("target_port", "")),
        normalize_text(row.get("connection_name", "")),
    ])
    width = bus_width_from_text(blob)
    reasons: List[str] = []
    if bus_width_from_text(blob) > 1:
        reasons.append("bus width notation in connection text")
    return width, reasons


def normalize_pin_base(pin: str) -> str:
    text = normalize_text(pin).upper()
    text = re.sub(r"([_\-])(?:P|N|POS|NEG|PLUS|MINUS)$", "", text)
    text = re.sub(r"(?:_P|_N)$", "", text)
    return text


def pin_polarity(pin: str) -> str:
    text = normalize_text(pin).upper()
    if re.search(r"([_\-]|^)(P|POS|PLUS)$", text):
        return "P"
    if re.search(r"([_\-]|^)(N|NEG|MINUS)$", text):
        return "N"
    return ""


def differential_pin_pairs(pins: List[str]) -> Dict[str, Dict[str, str]]:
    pairs: Dict[str, Dict[str, str]] = {}
    for pin in pins:
        aliases = [alias for alias in re.split(r"[/,，;；]+", normalize_text(pin)) if alias]
        for alias in aliases:
            polarity = pin_polarity(alias)
            if not polarity:
                continue
            base = normalize_pin_base(alias)
            if not base:
                continue
            pairs.setdefault(base, {})[polarity] = pin
    return {base: pair for base, pair in pairs.items() if "P" in pair and "N" in pair}


def token_set(value: str) -> set[str]:
    text = normalize_text(value).upper()
    extras: List[str] = []
    if "RFIN" in text or "RF_IN" in text:
        extras.extend(["RF", "IN"])
    if "RFOUT" in text or "RF_OUT" in text:
        extras.extend(["RF", "OUT"])
    if "DAC" in text:
        extras.append("DAC")
    if "ADC" in text:
        extras.append("ADC")
    tokens = [x for x in re.split(r"[^A-Z0-9]+", text) if x]
    return {x for x in tokens + extras if not x.isdigit() and len(x) >= 2}


def best_matching_diff_pair(row: Dict[str, Any], pins: List[str]) -> Dict[str, Any]:
    pairs = differential_pin_pairs(pins)
    if not pairs:
        return {}
    row_tokens = token_set(" ".join([
        str(row.get("source_port", "")),
        str(row.get("target_port", "")),
        str(row.get("connection_name", "")),
    ]))
    best: Dict[str, Any] = {}
    best_score = 0
    for base, pair in pairs.items():
        base_tokens = token_set(base)
        score = len(row_tokens & base_tokens)
        if score > best_score:
            best_score = score
            best = {
                "pin_pair_base": base,
                "pins": [pair["P"], pair["N"]],
                "score": score,
            }
    return best if best_score >= 2 else {}


def has_explicit_differential_marker(row: Dict[str, Any]) -> bool:
    blob = text_blob(row).upper()
    return bool(re.search(r"(^|[_\-\s])(P|N)([_\-\s]|$)|\bDP\b|\bDN\b|DIFF|差分|P/N", blob))


def looks_like_differential_function(row: Dict[str, Any]) -> bool:
    blob = text_blob(row).upper()
    return bool(re.search(r"\b(RFIN|RFOUT|RF_IN|RF_OUT|DAC|ADC|AFE|IQ|CLK)\d*", blob))


def iter_rule_sections(rule_text: str) -> List[str]:
    matches = list(re.finditer(r"^### RULE:\s*(.+?)\s*$", rule_text, flags=re.MULTILINE))
    sections: List[str] = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        if title.startswith("<"):
            continue
        start = match.start()
        next_rule = matches[idx + 1].start() if idx + 1 < len(matches) else len(rule_text)
        after_title = rule_text[match.end():]
        next_heading = re.search(r"^##\s+", after_title, flags=re.MULTILINE)
        next_section = match.end() + next_heading.start() if next_heading else len(rule_text)
        next_source = re.search(r"<!--\s*SOURCE:", after_title, flags=re.IGNORECASE)
        next_source_start = match.end() + next_source.start() if next_source else len(rule_text)
        end = min(next_rule, next_section, next_source_start)
        sections.append(rule_text[start:end].strip())
    return sections


def rule_hint_chunks(section: str) -> List[str]:
    """将一个 RULE 按 #### 子标题切开，并把适用条件头部带入每个局部块。"""
    subsection_matches = list(re.finditer(r"^####\s+.+$", section, flags=re.MULTILINE))
    if not subsection_matches:
        return [section]
    header = section[:subsection_matches[0].start()].strip()
    chunks = []
    for idx, match in enumerate(subsection_matches):
        end = subsection_matches[idx + 1].start() if idx + 1 < len(subsection_matches) else len(section)
        chunks.append((header + "\n" + section[match.start():end]).strip())
    return chunks


def matching_rule_hint(row: Dict[str, Any], rule_text: str) -> Dict[str, Any]:
    """
    自然语言规则只用于前置形态提示，不在脚本里做 pin 裁决。
    如果规则文本中同时出现当前连接关键词和“差分/总线”等描述，则返回提示。
    """
    if not rule_text:
        return {}
    sections = iter_rule_sections(rule_text)
    raw_terms = [
        ("part", normalize_text(row.get("source_part_id", ""))),
        ("source_port", normalize_text(row.get("source_port", ""))),
        ("target_port", normalize_text(row.get("target_port", ""))),
        ("connection_name", normalize_text(row.get("connection_name", ""))),
        ("link_family", normalize_text(row.get("link_family_id", ""))),
    ]
    row_terms = []
    for kind, value in raw_terms:
        term = value.upper()
        if len(term) < 3:
            continue
        if term.startswith("LINE"):
            continue
        if term.isdigit():
            continue
        row_terms.append((kind, term))
        stripped_index = re.sub(r"\d+$", "", term)
        if stripped_index and stripped_index != term and len(stripped_index) >= 3:
            row_terms.append((kind, stripped_index))
    matched_terms: List[str] = []
    hints: List[str] = []
    matched_rule_titles: List[str] = []
    strong_hint = False
    for section in sections:
        title = section.splitlines()[0].strip() if section.splitlines() else ""
        for chunk in rule_hint_chunks(section):
            upper_chunk = chunk.upper()
            section_terms = [(kind, term) for kind, term in row_terms if term and term in upper_chunk]
            if not section_terms:
                continue
            section_hints = []
            if re.search(r"差分|P/N|(?:_P|_N)\b|DIFFERENTIAL", upper_chunk):
                section_hints.append("differential")
            if re.search(r"总线|BUS|拆分|位宽|BIT|BITS", upper_chunk):
                section_hints.append("bus")
            if not section_hints:
                continue
            specific_terms = [
                term for kind, term in section_terms
                if kind in {"source_port", "target_port", "connection_name"}
                and term not in GENERIC_RULE_TERMS
            ]
            if specific_terms:
                strong_hint = True
            matched_terms.extend(term for _, term in section_terms)
            hints.extend(section_hints)
            if title and title not in matched_rule_titles:
                matched_rule_titles.append(title)
    if not hints:
        return {}
    return {
        "matched_terms": sorted(set(matched_terms))[:8],
        "matched_rule_titles": matched_rule_titles[:5],
        "shape_hints": sorted(set(hints)),
        "strong_shape_hint": strong_hint,
        "basis": "matched_natural_language_rule_block_contains_shape_hint",
    }


def infer_signal_shape_for_row(
    row: Dict[str, Any],
    candidate_mapping: Dict[str, Any],
    source_pins: List[str],
    rule_text: str,
) -> Dict[str, Any]:
    bus_width, bus_reasons = explicit_bus_reason(row)
    diff_pair = best_matching_diff_pair(row, source_pins)
    rule_hint = matching_rule_hint(row, rule_text)

    reasons: List[str] = []
    evidence: Dict[str, Any] = {}
    shape = "scalar"
    expected_count = 1
    confidence = "auto_high"
    needs_model_shape_review = False

    if bus_width > 1:
        shape = "bus"
        expected_count = bus_width
        reasons.extend(bus_reasons)
    elif has_explicit_differential_marker(row):
        shape = "differential"
        expected_count = 2
        reasons.append("explicit differential marker in connection text")
    elif looks_like_differential_function(row) and diff_pair:
        shape = "differential"
        expected_count = 2
        reasons.append("RF/DAC/ADC-like connection and source pin list has matching P/N pair")
        evidence["matched_differential_pin_pair"] = diff_pair
    elif rule_hint.get("strong_shape_hint") and "differential" in rule_hint.get("shape_hints", []) and diff_pair:
        shape = "differential"
        expected_count = 2
        confidence = "rule_hint"
        reasons.append("natural language rule suggests differential and source pin list has matching P/N pair")
        evidence["matched_differential_pin_pair"] = diff_pair

    if rule_hint:
        evidence["matched_rule_shape_hint"] = rule_hint
    if not source_pins:
        evidence["source_pins_available"] = False
        if shape in {"bus", "differential"}:
            confidence = "model_hint"
            needs_model_shape_review = True
    else:
        evidence["source_pins_available"] = True

    if shape == "scalar" and rule_hint.get("strong_shape_hint"):
        confidence = "model_hint"
        needs_model_shape_review = True
        reasons.append("natural language rule has shape hint but automatic evidence is insufficient")

    expected_connection_ids = []
    base_connection_id = row.get("base_connection_id") or row.get("connection_id", "")
    if expected_count and expected_count > 1:
        expected_connection_ids = [f"{base_connection_id}#{idx}" for idx in range(1, expected_count + 1)]

    return {
        "shape": shape,
        "expected_physical_pin_count": expected_count,
        "is_expanded_member": False,
        "parent_line_id": row.get("line_id", ""),
        "member_index": 1,
        "member_count": expected_count,
        "member_role": "",
        "line_id_expansion_policy": "selected_pins_array_then_render_connection_id_suffix" if expected_count > 1 else "single_output_row",
        "connection_id_suffix_separator": "#" if expected_count > 1 else "",
        "expected_output_connection_ids": expected_connection_ids,
        "confidence": confidence,
        "needs_model_shape_review": needs_model_shape_review,
        "reasons": reasons,
        "evidence": evidence,
    }


def expanded_rows_for_signal_shape(row: Dict[str, Any], signal_shape_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    count = int(signal_shape_info.get("expected_physical_pin_count", 1) or 1)
    if count <= 1:
        updated = dict(row)
        updated["signal_shape"] = signal_shape_info["shape"]
        updated["expected_physical_pin_count"] = 1
        updated["signal_shape_info"] = signal_shape_info
        return [updated]

    parent_line_id = row.get("line_id", "")
    base_connection_id = row.get("base_connection_id") or row.get("connection_id", "")
    member_rows: List[Dict[str, Any]] = []
    for index in range(1, count + 1):
        member = dict(row)
        member_info = dict(signal_shape_info)
        member_role = ""
        if signal_shape_info.get("shape") == "differential":
            member_role = "P" if index == 1 else "N" if index == 2 else str(index)

        member["parent_line_id"] = parent_line_id
        member["line_id"] = f"{parent_line_id}#{index}"
        member["base_line_id"] = row.get("base_line_id") or parent_line_id
        member["connection_id"] = f"{base_connection_id}#{index}" if base_connection_id else str(index)
        member["base_connection_id"] = base_connection_id
        member["shape_expansion_index"] = index
        member["shape_expansion_count"] = count
        member["shape_member_role"] = member_role
        member["signal_shape"] = signal_shape_info["shape"]
        member["expected_physical_pin_count"] = 1

        member_info["is_expanded_member"] = True
        member_info["parent_line_id"] = parent_line_id
        member_info["parent_expected_physical_pin_count"] = count
        member_info["expected_physical_pin_count"] = 1
        member_info["member_index"] = index
        member_info["member_count"] = count
        member_info["member_role"] = member_role
        member_info["line_id_expansion_policy"] = "already_expanded_before_mapping"
        member_info["current_output_connection_id"] = member["connection_id"]
        member["signal_shape_info"] = member_info
        member_rows.append(member)
    return member_rows


def infer_signal_shapes(
    normalized_path: str | Path,
    candidates_path: str | Path,
    pins_path: str | Path,
    output_normalized_path: str | Path,
    report_path: str | Path,
    rules_path: str | Path | None = None,
) -> List[Dict[str, Any]]:
    catalog = load_pin_catalog(pins_path)
    candidates_by_id = load_candidate_map(candidates_path)
    rule_text = read_rule_text(rules_path)
    rows = list(iter_jsonl(normalized_path))
    enriched: List[Dict[str, Any]] = []
    reports: List[Dict[str, Any]] = []

    for row in rows:
        part_id = row.get("source_part_id", "")
        source_pins = pins_for_part(catalog, part_id)
        candidate_mapping = candidates_by_id.get(row.get("line_id", ""), {})
        signal_shape_info = infer_signal_shape_for_row(row, candidate_mapping, source_pins, rule_text)
        expanded_rows = expanded_rows_for_signal_shape(row, signal_shape_info)
        enriched.extend(expanded_rows)
        reports.append({
            "line_id": row.get("line_id", ""),
            "expanded_line_ids": [expanded.get("line_id", "") for expanded in expanded_rows],
            "source_part_id": part_id,
            "source_port": row.get("source_port", ""),
            "target_port": row.get("target_port", ""),
            "connection_id": row.get("connection_id", ""),
            "base_connection_id": row.get("base_connection_id", ""),
            "connection_name": row.get("connection_name", ""),
            "signal_shape_info": signal_shape_info,
        })

    write_jsonl(output_normalized_path, enriched)
    write_jsonl(report_path, reports)
    return enriched


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer scalar/bus/differential shape before semantic pin mapping.")
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--candidates", default="")
    parser.add_argument("--pins", required=True)
    parser.add_argument("--output-normalized", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--rules", default="")
    args = parser.parse_args()

    rows = infer_signal_shapes(
        args.normalized,
        args.candidates,
        args.pins,
        args.output_normalized,
        args.report,
        args.rules or None,
    )
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row.get("signal_shape", "scalar")] = counts.get(row.get("signal_shape", "scalar"), 0) + 1
    print(f"[OK] inferred signal shapes: {counts} -> {args.output_normalized}")


if __name__ == "__main__":
    main()
