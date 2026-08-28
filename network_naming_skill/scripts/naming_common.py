from __future__ import annotations

import re
from typing import Any


COLUMN_ALIASES = {
    "source_block_id": ["源Block标识", "起始Block标识", "起止Block标识"],
    "source_block_name": ["源Block名称", "起始Block名称"],
    "source_port": ["源Port", "起始Port"],
    "target_block_id": ["目的Block标识", "目标Block标识", "终止Block标识"],
    "target_block_name": ["目的Block名称", "目标Block名称", "终止Block名称"],
    "target_port": ["目的Port", "目标Port", "终止Port"],
    "connection_id": ["连线ID", "连线标识"],
    "connection_name": ["连线名称"],
    "direction": ["连线方向"],
    "pin": ["原理图Pin脚"],
    "analysis": ["分析说明"],
    "net_name": ["网络命名"],
}
CONNECTION_FIELDS = [
    "source_block_id", "source_block_name", "source_port",
    "target_block_id", "target_block_name", "target_port",
    "connection_id", "connection_name", "direction",
]
REQUIRED_FIELDS = set(CONNECTION_FIELDS) | {"pin", "analysis", "net_name"}


def text(value: Any) -> str:
    return str(value or "").strip()


def resolve_columns(headers: dict[str, int]) -> dict[str, int]:
    resolved = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in headers:
                resolved[field] = headers[alias]
                break
    return resolved


def is_connection_sheet(columns: dict[str, int]) -> bool:
    return "connection_id" in columns or "source_port" in columns


NUMERIC_SUFFIX_RE = re.compile(r"_([0-9]+)$")


def parse_connection_id(connection_id: str) -> dict[str, str]:
    """解析命名后缀与总线成员；# 不是命名组分隔符。"""
    value = text(connection_id)
    logical_id, bus_member = value, ""
    if "#" in value:
        logical_id, bus_member = value.rsplit("#", 1)
        logical_id = logical_id or value
    match = NUMERIC_SUFFIX_RE.search(logical_id)
    return {
        "connection_id": value,
        "logical_id": logical_id,
        "numeric_suffix": match.group(1) if match else "",
        "bus_member": bus_member,
        "bus_family": logical_id if bus_member else "",
    }
