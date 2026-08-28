#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import OrderedDict, defaultdict
import json
from pathlib import Path
import re
from typing import Any

from naming_common import (
    CONNECTION_FIELDS,
    REQUIRED_FIELDS,
    is_connection_sheet,
    parse_connection_id,
    resolve_columns,
    text,
)
from xlsx_io import read_workbook_rows


MODEL_RULES_START = "<!-- MODEL_TASK_RULES_START -->"
MODEL_RULES_END = "<!-- MODEL_TASK_RULES_END -->"
CLASSIFICATION_RULES_START = "<!-- SIGNAL_CLASSIFICATION_RULES_START -->"
CLASSIFICATION_RULES_END = "<!-- SIGNAL_CLASSIFICATION_RULES_END -->"
TYPE_RULE_MARKERS = {
    "DIGITAL": ("<!-- DIGITAL_NAMING_RULES_START -->", "<!-- DIGITAL_NAMING_RULES_END -->"),
    "RF": ("<!-- RF_NAMING_RULES_START -->", "<!-- RF_NAMING_RULES_END -->"),
    "POWER": ("<!-- POWER_NAMING_RULES_START -->", "<!-- POWER_NAMING_RULES_END -->"),
    "GROUND": ("<!-- GROUND_NAMING_RULES_START -->", "<!-- GROUND_NAMING_RULES_END -->"),
}
DIRECT_NET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,30}$")
PLACEHOLDER_NET_NAME_RE = re.compile(r"^LINE(?:_|$)", re.IGNORECASE)


def naming_rules_path() -> Path:
    return Path(__file__).resolve().parents[1] / "rules" / "net_naming_rules.md"


def extract_rule_list(
    content: str,
    start: str,
    end: str,
    rules_path: Path,
    *,
    required: bool,
) -> list[str]:
    if start not in content or end not in content:
        raise ValueError(f"命名规则缺少标记 {start} / {end}: {rules_path}")
    section = content.split(start, 1)[1].split(end, 1)[0]
    rules = [line.strip()[2:].strip() for line in section.splitlines() if line.strip().startswith("- ")]
    if required and not rules:
        raise ValueError(f"命名规则标记区为空 {start}: {rules_path}")
    return rules


def load_model_rule_bundle(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else naming_rules_path()
    content = rules_path.read_text(encoding="utf-8")
    return {
        "general": extract_rule_list(
            content, MODEL_RULES_START, MODEL_RULES_END, rules_path, required=True
        ),
        "classification": extract_rule_list(
            content,
            CLASSIFICATION_RULES_START,
            CLASSIFICATION_RULES_END,
            rules_path,
            required=True,
        ),
        "by_signal_type": {
            signal_type: extract_rule_list(content, start, end, rules_path, required=False)
            for signal_type, (start, end) in TYPE_RULE_MARKERS.items()
        },
    }


def load_model_rules(path: str | Path | None = None) -> list[str]:
    return load_model_rule_bundle(path)["general"]


def is_legal_direct_net_name(value: str) -> bool:
    candidate = text(value)
    return bool(
        DIRECT_NET_NAME_RE.fullmatch(candidate)
        and not PLACEHOLDER_NET_NAME_RE.match(candidate)
    )


class UnionFind:
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left, right) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def polarity_of(*values: str) -> str:
    tokens = " ".join(text(value).upper() for value in values)
    if re.search(r"(?:^|[_\-])P(?:$|[_\-])", tokens):
        return "P"
    if re.search(r"(?:^|[_\-])N(?:$|[_\-])", tokens):
        return "N"
    return ""


def endpoint_key(block_id: str, block_name: str, port: str) -> tuple[str, str]:
    return (text(block_id) or text(block_name), text(port))


def pin_key(block_id: str, block_name: str, pin: str) -> tuple[str, str] | None:
    block = text(block_id) or text(block_name)
    pin = text(pin)
    return (block, pin) if block and pin else None


def add_endpoint(endpoints: OrderedDict, block_id: str, block_name: str, port: str, pin: str = "") -> None:
    key = endpoint_key(block_id, block_name, port)
    if not any(key):
        return
    current = endpoints.setdefault(key, {
        "id": text(block_id),
        "block": text(block_name),
        "port": text(port),
        "pin": "",
    })
    if text(pin):
        current["pin"] = text(pin)


def merged_group(connection_ids: list[str], connections: OrderedDict) -> dict[str, Any]:
    endpoints: OrderedDict = OrderedDict()
    pins: OrderedDict = OrderedDict()
    output_pins: OrderedDict = OrderedDict()
    refs = []
    suffixes = []
    bus_members = []
    polarities = []
    connection_names = []
    analysis_notes = []
    connection_details = []
    for connection_id in connection_ids:
        item = connections[connection_id]
        for key, endpoint in item["endpoints"].items():
            current = endpoints.setdefault(key, dict(endpoint))
            if endpoint.get("pin"):
                current["pin"] = endpoint["pin"]
        for key in item["pin_keys"]:
            pins.setdefault(key, {"block": key[0], "pin": key[1]})
        for key in item["output_pin_keys"]:
            output_pins.setdefault(key, {"block": key[0], "pin": key[1]})
        refs.extend(item["refs"])
        if item["numeric_suffix"] and item["numeric_suffix"] not in suffixes:
            suffixes.append(item["numeric_suffix"])
        if item["bus_member"] and item["bus_member"] not in bus_members:
            bus_members.append(item["bus_member"])
        for polarity in item["polarities"]:
            if polarity not in polarities:
                polarities.append(polarity)
        for connection_name in item["connection_names"]:
            if connection_name not in connection_names:
                connection_names.append(connection_name)
        for analysis in item["analysis_notes"]:
            if analysis not in analysis_notes:
                analysis_notes.append(analysis)
        connection_details.append({
            "connection_id": connection_id,
            "connection_names": list(item["connection_names"]),
            "analysis_notes": list(item["analysis_notes"]),
            "endpoints": list(item["endpoints"].values()),
        })
    valid_connection_names = [name for name in connection_names if is_legal_direct_net_name(name)]
    return {
        "connection_ids": connection_ids,
        "suffix": suffixes[0] if len(suffixes) == 1 else "",
        "bus_members": bus_members,
        "polarity": polarities[0] if len(polarities) == 1 else "",
        "connection_names": connection_names,
        "valid_connection_names": valid_connection_names,
        "analysis_notes": analysis_notes,
        "connection_details": connection_details,
        "pins": list(pins.values()),
        "output_pins": list(output_pins.values()),
        "ends": list(endpoints.values()),
        "refs": refs,
        "pin_keys": set(pins),
        "output_pin_keys": set(output_pins),
    }


def prepare_naming(input_path: str | Path, task_dir: str | Path) -> dict[str, Any]:
    input_path = Path(input_path).resolve()
    task_dir = Path(task_dir).resolve()
    task_dir.mkdir(parents=True, exist_ok=True)
    model_rule_bundle = load_model_rule_bundle()
    connections: OrderedDict[str, dict[str, Any]] = OrderedDict()
    errors: list[dict[str, str]] = []

    for sheet_name, rows in read_workbook_rows(input_path).items():
        headers = {text(value): column for column, value in rows.get(1, {}).items() if text(value)}
        columns = resolve_columns(headers)
        if not is_connection_sheet(columns):
            continue
        missing = sorted(REQUIRED_FIELDS - set(columns))
        if missing:
            errors.append({"sheet": sheet_name, "message": f"缺少必需字段: {', '.join(missing)}"})
            continue
        if columns["net_name"] != 13:
            errors.append({"sheet": sheet_name, "message": "网络命名必须是标准 13 列信号接口列表的第 13 列"})
            continue
        for row_number, cells in rows.items():
            if row_number == 1:
                continue
            values = {field: text(cells.get(columns[field], "")) for field in CONNECTION_FIELDS}
            connection_id = values["connection_id"]
            if not connection_id:
                if any(values.values()):
                    errors.append({"sheet": sheet_name, "message": f"第 {row_number} 行连线ID为空"})
                continue
            parsed = parse_connection_id(connection_id)
            item = connections.setdefault(connection_id, {
                **parsed,
                "endpoints": OrderedDict(),
                "pin_keys": set(),
                "output_pin_keys": set(),
                "polarities": set(),
                "connection_names": [],
                "analysis_notes": [],
                "refs": [],
            })
            pin = text(cells.get(columns["pin"], ""))
            add_endpoint(item["endpoints"], values["source_block_id"], values["source_block_name"], values["source_port"], pin)
            add_endpoint(item["endpoints"], values["target_block_id"], values["target_block_name"], values["target_port"])
            source_pin_key = pin_key(values["source_block_id"], values["source_block_name"], pin)
            if source_pin_key:
                item["pin_keys"].add(source_pin_key)
                if values["direction"].upper() == "OUTPUT":
                    item["output_pin_keys"].add(source_pin_key)
            polarity = polarity_of(values["source_port"], values["target_port"], pin)
            if polarity:
                item["polarities"].add(polarity)
            connection_name = values["connection_name"]
            if connection_name and connection_name not in item["connection_names"]:
                item["connection_names"].append(connection_name)
            analysis = text(cells.get(columns["analysis"], ""))
            if analysis and analysis not in item["analysis_notes"]:
                item["analysis_notes"].append(analysis)
            item["refs"].append({"sheet": sheet_name, "row": row_number})

    connection_ids = list(connections)
    naming_union = UnionFind(connection_ids)
    suffix_buckets: dict[tuple[tuple[str, str], str, str], list[str]] = defaultdict(list)
    for connection_id, item in connections.items():
        suffix = item["numeric_suffix"]
        if not suffix:
            continue
        for anchor in item["output_pin_keys"]:
            # #成员仍是不同物理网络；只有相同 #成员才能按 _数字后缀合并。
            suffix_buckets[(anchor, suffix, item["bus_member"])].append(connection_id)
    for bucket in suffix_buckets.values():
        for connection_id in bucket[1:]:
            naming_union.union(bucket[0], connection_id)

    components: OrderedDict[str, list[str]] = OrderedDict()
    for connection_id in connection_ids:
        components.setdefault(naming_union.find(connection_id), []).append(connection_id)

    groups: list[dict[str, Any]] = []
    for index, component_ids in enumerate(components.values(), 1):
        group = merged_group(component_ids, connections)
        group["id"] = f"G{index:04d}"
        valid_names = group["valid_connection_names"]
        group["name_conflict"] = len(valid_names) > 1
        if len(valid_names) == 1:
            group["fixed_net_name"] = valid_names[0]
        elif group["name_conflict"]:
            group["fixed_net_name"] = ""
            errors.append({
                "sheet": "",
                "message": (
                    f"{group['id']} 同一命名组存在多个不同的合法连线名称，无法直接采用: "
                    + ", ".join(valid_names)
                ),
            })
        else:
            group["fixed_net_name"] = ""
        groups.append(group)

    family_union = UnionFind(range(len(groups)))
    pin_to_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    bus_to_groups: dict[str, list[int]] = defaultdict(list)
    for group_index, group in enumerate(groups):
        for anchor in group["output_pin_keys"]:
            pin_to_groups[anchor].append(group_index)
        for connection_id in group["connection_ids"]:
            item = connections[connection_id]
            if item["bus_family"]:
                bus_to_groups[item["bus_family"]].append(group_index)
    for bucket in list(pin_to_groups.values()) + list(bus_to_groups.values()):
        unique = list(dict.fromkeys(bucket))
        for group_index in unique[1:]:
            family_union.union(unique[0], group_index)

    families: OrderedDict[int, list[int]] = OrderedDict()
    for group_index in range(len(groups)):
        families.setdefault(family_union.find(group_index), []).append(group_index)

    tasks_path = task_dir / "naming_groups.jsonl"
    automatic_path = task_dir / "automatic_decisions.jsonl"
    model_decisions_path = task_dir / "naming_decisions.jsonl"
    index_path = task_dir / "row_index.json"
    report_path = task_dir / "prepare_report.json"
    if model_decisions_path.exists():
        model_decisions_path.unlink()
    row_index: dict[str, dict[str, Any]] = {
        group["id"]: {
            "connection_ids": group["connection_ids"],
            "refs": group["refs"],
            "decision_source": (
                "connection_name" if group["fixed_net_name"]
                else "conflict" if group["name_conflict"]
                else "model"
            ),
            "fixed_net_name": group["fixed_net_name"],
        }
        for group in groups
    }
    automatic_decisions = [
        {
            "id": group["id"],
            "net_name": group["fixed_net_name"],
            "basis": "连线名称非空且为合法网络名，按最高优先级逐字采用。",
            "source": "connection_name",
        }
        for group in groups
        if group["fixed_net_name"]
    ]
    with automatic_path.open("w", encoding="utf-8") as handle:
        for decision in automatic_decisions:
            handle.write(json.dumps(decision, ensure_ascii=False) + "\n")
    model_group_count = 0
    model_family_count = 0
    with tasks_path.open("w", encoding="utf-8") as handle:
        for family_number, group_indexes in enumerate(families.values(), 1):
            task_groups = []
            fixed_names = []
            for group_index in group_indexes:
                group = groups[group_index]
                if group["fixed_net_name"]:
                    fixed_names.append({"id": group["id"], "net_name": group["fixed_net_name"]})
                    continue
                if group["name_conflict"]:
                    continue
                task_groups.append({
                    "id": group["id"],
                    "connection_ids": group["connection_ids"],
                    "suffix": group["suffix"],
                    "bus_members": group["bus_members"],
                    "polarity": group["polarity"],
                    "connection_names": group["connection_names"],
                    "analysis_notes": group["analysis_notes"],
                    "connection_details": group["connection_details"],
                })
            if task_groups:
                model_family_count += 1
                model_group_count += len(task_groups)
                handle.write(json.dumps({
                    "family_id": f"F{family_number:04d}",
                    "signal_types": list(TYPE_RULE_MARKERS),
                    "rules": model_rule_bundle["general"],
                    "classification_rules": model_rule_bundle["classification"],
                    "type_naming_rules": model_rule_bundle["by_signal_type"],
                    "fixed_names": fixed_names,
                    "groups": task_groups,
                }, ensure_ascii=False) + "\n")
    index_path.write_text(json.dumps({"input": str(input_path), "groups": row_index}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ERROR" if errors else "PASS",
        "input": str(input_path),
        "family_count": len(families),
        "group_count": len(groups),
        "automatic_group_count": len(automatic_decisions),
        "model_group_count": model_group_count,
        "model_family_count": model_family_count,
        "connection_id_count": len(connections),
        "tasks": str(tasks_path),
        "automatic_decisions": str(automatic_path),
        "model_decisions": str(model_decisions_path),
        "rules_source": str(naming_rules_path()),
        "row_index": str(index_path),
        "errors": errors,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="合法连线名称直接采用；其余按命名组汇总两端 pin 后生成四类信号模型任务")
    parser.add_argument("--input", required=True)
    parser.add_argument("--task-dir", required=True)
    args = parser.parse_args()
    report = prepare_naming(args.input, args.task_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
