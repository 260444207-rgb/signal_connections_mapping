#!/usr/bin/env python
"""Check and optionally fix signal-interface net-name consistency."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
LOCAL_DEPS = ROOT / ".local_pydeps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))
NAMING_SCRIPT_DIR = REPO_ROOT / "network_naming_skill" / "scripts"
if NAMING_SCRIPT_DIR.exists():
    sys.path.insert(0, str(NAMING_SCRIPT_DIR))

try:
    from openpyxl import load_workbook
except ImportError as exc:  # pragma: no cover - exercised only on missing env deps
    raise SystemExit(
        "openpyxl is required. Install it or keep the repo .local_pydeps directory available."
    ) from exc

try:
    from generate_net_name import generate_net_name
except ImportError as exc:  # pragma: no cover - exercised only if repo layout changes
    raise SystemExit(
        "generate_net_name.py is required from network_naming_skill/scripts."
    ) from exc


REQUIRED_HEADERS = {
    "源Block标识",
    "源Block名称",
    "源Port",
    "目的Block标识",
    "目的Block名称",
    "目的Port",
    "连线ID",
    "连线名称",
    "连线方向",
    "原理图Pin脚",
    "网络命名",
}

FORMAT_RE = re.compile(r"^[A-Z0-9_]+(?:\[[A-Za-z0-9]+:[A-Za-z0-9]+\])?$")
PLACEHOLDER_RE = re.compile(r"^LINE(?:[_ -]?\d+)?(?:_[PN])?$", re.IGNORECASE)
CONNECTION_SUFFIX_RE = re.compile(r"#(\d+)$")
CONNECTION_UNDERSCORE_GROUP_RE = re.compile(r"_(\d+)(?:\D*)?$")
NON_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9]+")


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def base_connection_id(connection_id: str) -> str:
    return CONNECTION_SUFFIX_RE.sub("", text(connection_id))


def suffix_index(connection_id: str) -> int | None:
    match = CONNECTION_SUFFIX_RE.search(text(connection_id))
    return int(match.group(1)) if match else None


def same_pin_connection_group(connection_id: str) -> str:
    """
    同 pin OUTPUT 检查使用的组号。

    规则：连线 ID 包含下划线，且下划线后能提取到相同数字，则认为属于同一组。
    无法提取组号时退回完整连线 ID，避免把不确定记录误并组。
    """
    value = text(connection_id)
    match = CONNECTION_UNDERSCORE_GROUP_RE.search(value)
    return match.group(1) if match else value


def is_placeholder_name(name: str) -> bool:
    return bool(PLACEHOLDER_RE.fullmatch(text(name)))


def has_to_segment(name: str) -> bool:
    return "TO" in [part for part in text(name).upper().split("_") if part]


def is_format_valid(name: str) -> bool:
    value = text(name)
    return bool(value) and bool(FORMAT_RE.fullmatch(value)) and not has_to_segment(value)


def is_effective_name(name: str) -> bool:
    return is_format_valid(name) and not is_placeholder_name(name)


def normalize_name(*parts: str) -> str:
    raw = "_".join(text(part) for part in parts if text(part))
    raw = raw.replace("[", "_").replace("]", "_")
    normalized = NON_NAME_CHARS_RE.sub("_", raw).upper()
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "NET"


def alias_from_sheet(sheet_name: str) -> str:
    return normalize_name(sheet_name)


def alias_from_block_name(block_name: str) -> str:
    return normalize_name(block_name)


def normalized_connection_for_record(record: "Record") -> dict[str, Any]:
    return {
        "connection_name": record.connection_name,
        "source_block_id": record.source_block_id,
        "source_block_name": record.source_block_name,
        "source_port": record.source_port,
        "target_block_id": record.target_block_id,
        "target_block_name": record.target_block_name,
        "target_port": record.target_port,
        "direction": record.direction,
        "link_family_id": record.link_family_id,
        "link_instance_id": record.link_instance_id,
        "base_connection_id": record.base_connection_id,
        "expansion_index": record.expansion_index,
        "expansion_count": record.expansion_count,
    }


@dataclass
class Record:
    sheet: str
    row_number: int
    source_block_id: str
    source_block_name: str
    source_port: str
    target_block_id: str
    target_block_name: str
    target_port: str
    connection_id: str
    connection_name: str
    direction: str
    pin: str
    net_name: str
    base_connection_id: str = ""
    expansion_index: int = 1
    expansion_count: int = 1
    line_id: str = ""
    base_line_id: str = ""
    selected_pin: str = ""
    decision_net_name: str = ""
    link_family_id: str = ""
    link_instance_id: str = ""
    proposed_net_name: str = ""
    issues: list[str] = field(default_factory=list)

    @property
    def row_key(self) -> str:
        return f"{self.sheet}!{self.row_number}"

    @property
    def exact_connection_key(self) -> str:
        return self.connection_id

    @property
    def endpoint_key(self) -> tuple[tuple[str, str], tuple[str, str]]:
        endpoints = [
            (self.source_block_id, self.source_port),
            (self.target_block_id, self.target_port),
        ]
        return tuple(sorted(endpoints))  # type: ignore[return-value]

    @property
    def physical_key(self) -> str:
        # 完整连线 ID（含 # 后缀）就是命名组键；同 ID 的所有器件端点必须同名。
        return self.connection_id

    @property
    def output_source_pin_key(self) -> tuple[str, str, str]:
        return (self.sheet, self.source_block_id, self.pin)


class IntermediateIndex:
    def __init__(self, intermediate_dir: Path | None):
        self.normalized: list[dict[str, Any]] = []
        self.decisions_by_line: dict[str, dict[str, Any]] = {}
        self.norm_by_line: dict[str, dict[str, Any]] = {}
        self.norm_by_endpoint: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        if intermediate_dir:
            self._load(intermediate_dir)

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _load(self, intermediate_dir: Path) -> None:
        self.normalized = self._load_jsonl(intermediate_dir / "normalized_connections.jsonl")
        decisions = self._load_jsonl(intermediate_dir / "model_resolved_decisions.jsonl")
        for row in self.normalized:
            line_id = text(row.get("line_id"))
            if line_id:
                self.norm_by_line[line_id] = row
            key = self._endpoint_lookup_key(row)
            if key:
                self.norm_by_endpoint[key].append(row)
        for row in decisions:
            line_id = text(row.get("line_id"))
            if line_id:
                self.decisions_by_line[line_id] = row

    def _endpoint_lookup_key(self, row: dict[str, Any]) -> tuple[str, str, str, str, str, str] | None:
        sheet = text(row.get("source_sheet_name") or row.get("output_sheet_name"))
        base_id = text(row.get("base_connection_id") or base_connection_id(text(row.get("connection_id"))))
        if not sheet or not base_id:
            return None
        return (
            sheet,
            base_id,
            text(row.get("source_block_id")),
            text(row.get("source_port")),
            text(row.get("target_block_id")),
            text(row.get("target_port")),
        )

    def enrich(self, record: Record) -> None:
        base_id = base_connection_id(record.connection_id)
        exact_line_id = f"{record.sheet}:{record.row_number - 1}:{record.connection_id}"
        base_line_id_guess = f"{record.sheet}:{record.row_number - 1}:{base_id}"
        norm = self.norm_by_line.get(exact_line_id) or self.norm_by_line.get(base_line_id_guess)
        if norm is None:
            key = (
                record.sheet,
                base_id,
                record.source_block_id,
                record.source_port,
                record.target_block_id,
                record.target_port,
            )
            candidates = self.norm_by_endpoint.get(key, [])
            norm = candidates[0] if candidates else None

        record.base_connection_id = base_id
        record.expansion_index = suffix_index(record.connection_id) or 1
        record.proposed_net_name = record.net_name

        if norm:
            record.line_id = text(norm.get("line_id"))
            record.base_line_id = text(norm.get("base_line_id"))
            record.base_connection_id = text(norm.get("base_connection_id")) or record.base_connection_id
            record.expansion_index = (
                suffix_index(record.connection_id)
                or int(norm.get("expansion_index") or record.expansion_index or 1)
            )
            record.expansion_count = int(norm.get("expansion_count") or 1)
            record.link_family_id = text(norm.get("link_family_id"))
            record.link_instance_id = text(norm.get("link_instance_id"))
            decision = self.decisions_by_line.get(record.line_id) or self.decisions_by_line.get(record.base_line_id)
            if decision:
                self._apply_decision(record, decision)

    def _apply_decision(self, record: Record, decision: dict[str, Any]) -> None:
        idx = max(record.expansion_index - 1, 0)
        selected_pins = decision.get("selected_pins")
        net_names = decision.get("net_names")
        if isinstance(selected_pins, list) and idx < len(selected_pins):
            record.selected_pin = text(selected_pins[idx])
        else:
            record.selected_pin = text(decision.get("selected_pin"))
        if isinstance(net_names, list) and idx < len(net_names):
            record.decision_net_name = text(net_names[idx])
        else:
            record.decision_net_name = text(decision.get("net_name"))


def default_intermediate_dir(input_path: Path) -> Path | None:
    sibling = input_path.parent.parent / "intermediate"
    if input_path.parent.name.lower() == "output" and sibling.exists():
        return sibling
    direct = input_path.parent / "intermediate"
    if direct.exists():
        return direct
    cwd_intermediate = Path.cwd() / "intermediate"
    if cwd_intermediate.exists():
        return cwd_intermediate
    return None


def read_records(input_path: Path, index: IntermediateIndex) -> tuple[Any, list[Record], dict[str, int]]:
    wb = load_workbook(input_path)
    records: list[Record] = []
    net_col_by_sheet: dict[str, int] = {}
    for ws in wb.worksheets:
        header_values = [text(cell.value) for cell in ws[1]]
        header_index = {name: idx + 1 for idx, name in enumerate(header_values) if name}
        if not REQUIRED_HEADERS.issubset(set(header_index)):
            continue
        net_col_by_sheet[ws.title] = header_index["网络命名"]
        for row_number in range(2, ws.max_row + 1):
            def get(header: str) -> str:
                return text(ws.cell(row=row_number, column=header_index[header]).value)

            if not get("连线ID") and not get("网络命名"):
                continue
            record = Record(
                sheet=ws.title,
                row_number=row_number,
                source_block_id=get("源Block标识"),
                source_block_name=get("源Block名称"),
                source_port=get("源Port"),
                target_block_id=get("目的Block标识"),
                target_block_name=get("目的Block名称"),
                target_port=get("目的Port"),
                connection_id=get("连线ID"),
                connection_name=get("连线名称"),
                direction=get("连线方向").upper(),
                pin=get("原理图Pin脚"),
                net_name=get("网络命名"),
            )
            index.enrich(record)
            records.append(record)
    return wb, records, net_col_by_sheet


def build_block_sheet_alias(records: list[Record]) -> dict[str, str]:
    source_sheets: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.source_block_id:
            source_sheets[record.source_block_id].add(record.sheet)
    aliases: dict[str, str] = {}
    for block_id, sheets in source_sheets.items():
        if len(sheets) == 1:
            aliases[block_id] = alias_from_sheet(next(iter(sheets)))
    return aliases


def block_alias(block_id: str, block_name: str, aliases: dict[str, str]) -> str:
    if block_id in aliases:
        return aliases[block_id]
    by_name = alias_from_block_name(block_name)
    return by_name if by_name else normalize_name("BLK", block_id)


def preferred_orientation(records: list[Record]) -> Record:
    outputs = [record for record in records if record.direction == "OUTPUT"]
    if outputs:
        return outputs[0]
    return records[0]


def generated_name(records: list[Record], aliases: dict[str, str], used: set[str] | None = None) -> str:
    source = preferred_orientation(records)
    candidate = generate_net_name(
        normalized_connection_for_record(source),
        source.selected_pin or source.pin,
    )
    if used is None:
        return candidate
    candidate = uniquify(candidate, used, source)
    used.add(candidate)
    return candidate


def uniquify(candidate: str, used: set[str], record: Record) -> str:
    if candidate not in used:
        return candidate
    suffix = normalize_name("L", record.connection_id)
    with_line = normalize_name(candidate, suffix)
    if with_line not in used:
        return with_line
    idx = record.expansion_index
    while True:
        with_idx = normalize_name(with_line, str(idx))
        if with_idx not in used:
            return with_idx
        idx += 1


def canonical_for_group(records: list[Record], aliases: dict[str, str]) -> tuple[str, str]:
    # 优先保留组级命名 skill 已生成的有效名称；只有全组都为空或占位时才兜底生成。
    for record in records:
        if record.proposed_net_name and not is_placeholder_name(record.proposed_net_name) and is_format_valid(record.proposed_net_name):
            return record.proposed_net_name, "existing_group_decision"
    return generated_name(records, aliases), "generated_block_port"


def collect_format_issues(records: list[Record]) -> list[dict[str, Any]]:
    issues = []
    for record in records:
        if not record.net_name:
            issues.append(issue(record, "empty_net_name", "网络名为空"))
            continue
        if is_placeholder_name(record.net_name):
            issues.append(issue(record, "placeholder_net_name", "网络名是 LINE 占位名"))
        elif not is_format_valid(record.net_name):
            reason = "网络名格式不合规"
            if has_to_segment(record.net_name):
                reason = "网络名包含 TO 连接词"
            issues.append(issue(record, "format_invalid", reason))
    return issues


def issue(record: Record, kind: str, message: str, **extra: Any) -> dict[str, Any]:
    data = {
        "kind": kind,
        "message": message,
        "sheet": record.sheet,
        "row": record.row_number,
        "connection_id": record.connection_id,
        "net_name": record.net_name,
    }
    data.update(extra)
    return data


def endpoint_subgroups(records: list[Record]) -> list[list[Record]]:
    by_endpoint: dict[tuple[tuple[str, str], tuple[str, str]], list[Record]] = defaultdict(list)
    for record in records:
        by_endpoint[record.endpoint_key].append(record)
    return list(by_endpoint.values())


def collect_connection_mismatches(records: list[Record]) -> list[dict[str, Any]]:
    groups = []
    by_connection: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.connection_id:
            by_connection[record.connection_id].append(record)
    for connection_id, rows in sorted(by_connection.items()):
        net_names = sorted({record.net_name for record in rows})
        if len(rows) > 1 and len(net_names) > 1:
            groups.append(
                {
                    "connection_id": connection_id,
                    "net_names": net_names,
                    "rows": [row_summary(record) for record in rows],
                    "endpoint_subgroups": [
                        [row_summary(record) for record in subgroup] for subgroup in endpoint_subgroups(rows)
                    ],
                }
            )
    return groups


def collect_physical_groups(records: list[Record]) -> dict[str, list[Record]]:
    by_physical: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.connection_id:
            by_physical[record.physical_key].append(record)
    return by_physical


def collect_physical_mismatches(records: list[Record]) -> list[dict[str, Any]]:
    groups = []
    for key, rows in sorted(collect_physical_groups(records).items(), key=lambda item: str(item[0])):
        net_names = sorted({record.proposed_net_name for record in rows})
        if len(rows) > 1 and len(net_names) > 1:
            groups.append(
                {
                    "physical_key": repr(key),
                    "net_names": net_names,
                    "rows": [row_summary(record) for record in rows],
                }
            )
    return groups


def collect_duplicate_groups(records: list[Record]) -> list[dict[str, Any]]:
    by_net: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.proposed_net_name:
            by_net[record.proposed_net_name].append(record)

    duplicate_groups = []
    for net_name, rows in sorted(by_net.items()):
        physical_keys = {record.physical_key for record in rows}
        connection_ids = {record.connection_id for record in rows}
        if len(rows) <= 1 or (len(physical_keys) <= 1 and len(connection_ids) <= 1):
            continue
        output_rows = [record for record in rows if record.direction == "OUTPUT"]
        source_keys = {record.output_source_pin_key for record in output_rows}
        legal_fanout = bool(output_rows) and len(source_keys) == 1
        if legal_fanout:
            continue
        duplicate_groups.append(
            {
                "net_name": net_name,
                "connection_ids": sorted(connection_ids),
                "reason": "OUTPUT源Pin不同或缺少OUTPUT行",
                "rows": [row_summary(record) for record in rows],
            }
        )
    return duplicate_groups


def collect_same_pin_direction_groups(records: list[Record]) -> list[dict[str, Any]]:
    """
    每个 sheet 内，检查多条连接指向同一个原理图 pin 时的网络名约束。

    - INPUT：同 sheet + 同 pin 的多条连接，网络名必须不同。
    - OUTPUT：同 sheet + 同 pin 的多条连接，先按连线 ID 的下划线数字分组；
      同组内网络名必须相同，不同组间网络名必须不同。
    """
    by_sheet_pin_direction: dict[tuple[str, str, str], list[Record]] = defaultdict(list)
    for record in records:
        if not record.pin:
            continue
        if record.direction not in {"INPUT", "OUTPUT"}:
            continue
        by_sheet_pin_direction[(record.sheet, record.pin, record.direction)].append(record)

    issues: list[dict[str, Any]] = []
    for (sheet, pin, direction), rows in sorted(by_sheet_pin_direction.items()):
        if len(rows) <= 1:
            continue

        if direction == "INPUT":
            by_net: dict[str, list[Record]] = defaultdict(list)
            for record in rows:
                by_net[record.proposed_net_name].append(record)
            conflicts = {
                net_name: net_rows
                for net_name, net_rows in by_net.items()
                if net_name and len(net_rows) > 1
            }
            if conflicts:
                issues.append(
                    {
                        "kind": "same_pin_input_net_must_differ",
                        "message": "同一 sheet 同一 INPUT pin 被多条连接指向时，网络名必须不同",
                        "sheet": sheet,
                        "pin": pin,
                        "direction": direction,
                        "conflicting_net_names": sorted(conflicts),
                        "rows": [row_summary(record) for record in rows],
                    }
                )
            continue

        by_group: dict[str, list[Record]] = defaultdict(list)
        for record in rows:
            by_group[same_pin_connection_group(record.connection_id)].append(record)

        same_group_conflicts = []
        for group_id, group_rows in sorted(by_group.items()):
            net_names = sorted({record.proposed_net_name for record in group_rows if record.proposed_net_name})
            if len(group_rows) > 1 and len(net_names) > 1:
                same_group_conflicts.append(
                    {
                        "group_id": group_id,
                        "net_names": net_names,
                        "rows": [row_summary(record) for record in group_rows],
                    }
                )

        by_net_across_groups: dict[str, set[str]] = defaultdict(set)
        for group_id, group_rows in by_group.items():
            for record in group_rows:
                if record.proposed_net_name:
                    by_net_across_groups[record.proposed_net_name].add(group_id)
        cross_group_conflicts = [
            {
                "net_name": net_name,
                "group_ids": sorted(group_ids),
            }
            for net_name, group_ids in sorted(by_net_across_groups.items())
            if len(group_ids) > 1
        ]

        if same_group_conflicts or cross_group_conflicts:
            issues.append(
                {
                    "kind": "same_pin_output_group_net_rule",
                    "message": "同一 sheet 同一 OUTPUT pin：同组网络名必须相同，不同组网络名必须不同",
                    "sheet": sheet,
                    "pin": pin,
                    "direction": direction,
                    "connection_groups": {
                        group_id: [row_summary(record) for record in group_rows]
                        for group_id, group_rows in sorted(by_group.items())
                    },
                    "same_group_conflicts": same_group_conflicts,
                    "cross_group_conflicts": cross_group_conflicts,
                }
            )
    return issues


def row_summary(record: Record) -> dict[str, Any]:
    return {
        "sheet": record.sheet,
        "row": record.row_number,
        "connection_id": record.connection_id,
        "base_connection_id": record.base_connection_id,
        "expansion_index": record.expansion_index,
        "direction": record.direction,
        "source": f"{record.source_block_id}:{record.source_port}",
        "target": f"{record.target_block_id}:{record.target_port}",
        "pin": record.pin,
        "net_name": record.net_name,
        "proposed_net_name": record.proposed_net_name,
    }


def propose_mismatch_and_placeholder_fixes(records: list[Record], aliases: dict[str, str]) -> list[dict[str, Any]]:
    fixes = []
    physical_groups = collect_physical_groups(records)
    for key, rows in sorted(physical_groups.items(), key=lambda item: str(item[0])):
        names = {record.proposed_net_name for record in rows}
        has_placeholder = any(is_placeholder_name(record.proposed_net_name) for record in rows)
        needs_consistency_fix = len(names) > 1
        if not has_placeholder and not needs_consistency_fix:
            continue
        target_name, basis = canonical_for_group(rows, aliases)
        changed = []
        for record in rows:
            if record.proposed_net_name != target_name:
                changed.append(
                    {
                        "sheet": record.sheet,
                        "row": record.row_number,
                        "from": record.proposed_net_name,
                        "to": target_name,
                    }
                )
                record.proposed_net_name = target_name
        if changed:
            fixes.append(
                {
                    "kind": "physical_consistency",
                    "basis": basis,
                    "physical_key": repr(key),
                    "changes": changed,
                }
            )
    return fixes


def propose_duplicate_fixes(records: list[Record], aliases: dict[str, str]) -> list[dict[str, Any]]:
    fixes = []
    used = {record.proposed_net_name for record in records if record.proposed_net_name}
    by_net: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.proposed_net_name:
            by_net[record.proposed_net_name].append(record)

    for net_name, rows in sorted(by_net.items()):
        physical_keys = {record.physical_key for record in rows}
        connection_ids = {record.connection_id for record in rows}
        if len(rows) <= 1 or (len(physical_keys) <= 1 and len(connection_ids) <= 1):
            continue
        output_rows = [record for record in rows if record.direction == "OUTPUT"]
        source_keys = {record.output_source_pin_key for record in output_rows}
        legal_fanout = bool(output_rows) and len(source_keys) == 1
        if legal_fanout:
            continue

        by_physical: dict[str, list[Record]] = defaultdict(list)
        for record in rows:
            by_physical[record.physical_key].append(record)

        group_changes = []
        for _, physical_rows in sorted(by_physical.items(), key=lambda item: str(item[0])):
            # The current duplicate name is no longer available to this group.
            used.discard(net_name)
            target_name = generated_name(physical_rows, aliases, used)
            for record in physical_rows:
                if record.proposed_net_name != target_name:
                    group_changes.append(
                        {
                            "sheet": record.sheet,
                            "row": record.row_number,
                            "from": record.proposed_net_name,
                            "to": target_name,
                        }
                    )
                    record.proposed_net_name = target_name
        if group_changes:
            fixes.append({"kind": "duplicate_net_name", "net_name": net_name, "changes": group_changes})
    return fixes


def build_report(
    records: list[Record],
    fixes: list[dict[str, Any]],
    format_issues: list[dict[str, Any]],
    raw_mismatches: list[dict[str, Any]],
    physical_mismatches: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    same_pin_direction_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    changed_count = sum(1 for record in records if record.proposed_net_name != record.net_name)
    status = (
        "PASS"
        if not format_issues and not physical_mismatches and not duplicates and not same_pin_direction_groups
        else "FAIL"
    )
    return {
        "status": status,
        "summary": {
            "row_count": len(records),
            "format_issue_count": len(format_issues),
            "raw_connection_mismatch_group_count": len(raw_mismatches),
            "actionable_physical_mismatch_group_count": len(physical_mismatches),
            "duplicate_group_count": len(duplicates),
            "same_pin_direction_group_count": len(same_pin_direction_groups),
            "proposed_change_count": changed_count,
            "applied_fix_count": len(fixes),
        },
        "format_issues": format_issues,
        "connection_mismatch_groups": raw_mismatches,
        "physical_mismatch_groups": physical_mismatches,
        "duplicate_groups": duplicates,
        "same_pin_direction_groups": same_pin_direction_groups,
        "fixes": fixes,
    }


def save_workbook(wb: Any, records: list[Record], net_col_by_sheet: dict[str, int], output_path: Path) -> None:
    for record in records:
        if record.proposed_net_name == record.net_name:
            continue
        ws = wb[record.sheet]
        ws.cell(row=record.row_number, column=net_col_by_sheet[record.sheet]).value = record.proposed_net_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def report_as_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# 网络名一致性检查报告",
        "",
        f"- 状态: {report['status']}",
        f"- 总行数: {summary['row_count']}",
        f"- 格式问题: {summary['format_issue_count']}",
        f"- 连线ID原始不匹配组: {summary['raw_connection_mismatch_group_count']}",
        f"- 需统一物理组: {summary['actionable_physical_mismatch_group_count']}",
        f"- 重名组: {summary['duplicate_group_count']}",
        f"- 同 sheet 同 pin 方向规则问题: {summary['same_pin_direction_group_count']}",
        f"- 拟修改行数: {summary['proposed_change_count']}",
        "",
    ]
    if report["format_issues"]:
        lines.extend(["## 格式问题", ""])
        for item in report["format_issues"][:100]:
            lines.append(
                f"- {item['sheet']}!{item['row']} `{item['connection_id']}`: "
                f"`{item['net_name']}` ({item['message']})"
            )
        lines.append("")
    if report["connection_mismatch_groups"]:
        lines.extend(["## 不匹配组", ""])
        for group in report["connection_mismatch_groups"][:50]:
            lines.append(f"- 连线ID `{group['connection_id']}`: {', '.join(f'`{n}`' for n in group['net_names'])}")
        lines.append("")
    if report["duplicate_groups"]:
        lines.extend(["## 重名组", ""])
        for group in report["duplicate_groups"][:50]:
            lines.append(
                f"- 网络名 `{group['net_name']}`: 连线ID {', '.join(f'`{n}`' for n in group['connection_ids'])}"
            )
        lines.append("")
    if report["same_pin_direction_groups"]:
        lines.extend(["## 同 sheet 同 pin 方向规则问题", ""])
        for group in report["same_pin_direction_groups"][:50]:
            lines.append(
                f"- {group['sheet']} `{group['pin']}` {group['direction']}: {group['message']}"
            )
        lines.append("")
    if report["fixes"]:
        lines.extend(["## 修正提案", ""])
        for fix in report["fixes"][:100]:
            lines.append(f"- {fix['kind']}: {len(fix['changes'])} 行")
        lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".md":
        path.write_text(report_as_markdown(report), encoding="utf-8")
    else:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def print_console_summary(report: dict[str, Any], fix: bool, output_path: Path | None) -> None:
    summary = report["summary"]
    print("=" * 60)
    print("网络名一致性检查报告")
    print("=" * 60)
    print(f"状态: {report['status']}")
    print(f"总行数: {summary['row_count']}")
    print(f"格式问题: {summary['format_issue_count']}")
    print(f"连线ID原始不匹配组: {summary['raw_connection_mismatch_group_count']}")
    print(f"需统一物理组: {summary['actionable_physical_mismatch_group_count']}")
    print(f"重名组: {summary['duplicate_group_count']}")
    print(f"同 sheet 同 pin 方向规则问题: {summary['same_pin_direction_group_count']}")
    print(f"拟修改行数: {summary['proposed_change_count']}")
    if fix:
        print(f"已写出: {output_path}")
    else:
        print("未启用 --fix，未修改 Excel。")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check signal-interface net-name consistency.")
    parser.add_argument("--input", "-i", required=True, help="输入 signal_interface.xlsx")
    parser.add_argument("--intermediate-dir", help="包含 normalized_connections.jsonl/model_resolved_decisions.jsonl 的目录")
    parser.add_argument("--output", "-o", help="--fix 时写出的 Excel；不填则覆盖输入文件")
    parser.add_argument("--report", help="报告输出路径，支持 .json 或 .md")
    parser.add_argument("--fix", "-f", action="store_true", help="写回自动修正项")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    intermediate_dir = Path(args.intermediate_dir).resolve() if args.intermediate_dir else default_intermediate_dir(input_path)
    index = IntermediateIndex(intermediate_dir)
    wb, records, net_col_by_sheet = read_records(input_path, index)
    aliases = build_block_sheet_alias(records)

    format_issues = collect_format_issues(records)
    raw_mismatches = collect_connection_mismatches(records)
    physical_mismatches = collect_physical_mismatches(records)
    duplicates = collect_duplicate_groups(records)
    same_pin_direction_groups = collect_same_pin_direction_groups(records)

    fixes: list[dict[str, Any]] = []
    fixes.extend(propose_mismatch_and_placeholder_fixes(records, aliases))
    fixes.extend(propose_duplicate_fixes(records, aliases))
    report = build_report(
        records,
        fixes,
        format_issues,
        raw_mismatches,
        physical_mismatches,
        duplicates,
        same_pin_direction_groups,
    )

    output_path = Path(args.output).resolve() if args.output else input_path
    if args.fix:
        save_workbook(wb, records, net_col_by_sheet, output_path)
    if args.report:
        write_report(report, Path(args.report).resolve())
    print_console_summary(report, args.fix, output_path if args.fix else None)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
