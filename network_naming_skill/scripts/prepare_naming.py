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
    return {
        "connection_ids": connection_ids,
        "suffix": suffixes[0] if len(suffixes) == 1 else "",
        "bus_members": bus_members,
        "polarity": polarities[0] if len(polarities) == 1 else "",
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
    index_path = task_dir / "row_index.json"
    report_path = task_dir / "prepare_report.json"
    row_index: dict[str, dict[str, Any]] = {}
    with tasks_path.open("w", encoding="utf-8") as handle:
        for family_number, group_indexes in enumerate(families.values(), 1):
            task_groups = []
            for group_index in group_indexes:
                group = groups[group_index]
                row_index[group["id"]] = {
                    "connection_ids": group["connection_ids"],
                    "refs": group["refs"],
                }
                task_groups.append({
                    key: value
                    for key, value in group.items()
                    if key not in {"refs", "pin_keys", "output_pin_keys"}
                })
            handle.write(json.dumps({"family_id": f"F{family_number:04d}", "groups": task_groups}, ensure_ascii=False) + "\n")
    index_path.write_text(json.dumps({"input": str(input_path), "groups": row_index}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "status": "ERROR" if errors else "PASS",
        "input": str(input_path),
        "family_count": len(families),
        "group_count": len(groups),
        "connection_id_count": len(connections),
        "tasks": str(tasks_path),
        "row_index": str(index_path),
        "errors": errors,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="仅按相同 OUTPUT Block+实际pin 与连线ID _数字后缀建立命名组；#成员联合分析")
    parser.add_argument("--input", required=True)
    parser.add_argument("--task-dir", required=True)
    args = parser.parse_args()
    report = prepare_naming(args.input, args.task_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
