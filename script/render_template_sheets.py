#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Any, List

from common import iter_jsonl, ensure_dir, FINAL_HEADERS
from generate_net_name import generate_net_name

SKIP_SHEETS = {"BLOCK_INFO", "LINK_INFO", "链路信息", "说明", "README", "INDEX", "目录"}
MULTI_RESULT_CONNECTION_ID_SEPARATOR = "#"

def decision_selected_pins(decision: Dict[str, Any]) -> List[str]:
    pins = decision.get("selected_pins")
    if isinstance(pins, list) and pins:
        return [str(pin).strip() for pin in pins if str(pin).strip()]
    pin = str(decision.get("selected_pin", "") or "").strip()
    return [pin] if pin else []

def decision_list_value(decision: Dict[str, Any], key: str, index: int, default: str = "") -> str:
    values = decision.get(key)
    if isinstance(values, list) and index < len(values):
        return str(values[index] or "")
    return str(decision.get(key[:-1] if key.endswith("s") else key, default) or default)

def is_placeholder_net_name(value: str) -> bool:
    """LINE/line 类名称是画图工具默认连线名，不能作为有效网络名。"""
    text = str(value or "").strip()
    return bool(text) and "line" in text.lower()

def final_net_name(decision: Dict[str, Any], normalized: Dict[str, Any], index: int, selected_pin: str) -> str:
    """
    生成最终网络名。
    硬约束：没有原理图 pin 时网络名必须为空；LINE 类默认连线名不能覆盖网络命名。
    """
    if not str(selected_pin or "").strip():
        return ""

    decision_net_name = decision_list_value(decision, "net_names", index)
    if decision_net_name and not is_placeholder_net_name(decision_net_name):
        return decision_net_name

    return generate_net_name(normalized, selected_pin)

def expanded_connection_id(base_connection_id: str, original_connection_id: str, should_expand: bool, index: int) -> str:
    if not should_expand:
        return original_connection_id
    base = str(base_connection_id or original_connection_id or "").strip()
    return f"{base}{MULTI_RESULT_CONNECTION_ID_SEPARATOR}{index + 1}" if base else str(index + 1)

def build_final_rows_by_template_sheet(normalized_path: str | Path, decisions_path: str | Path) -> Dict[str, List[Dict[str, Any]]]:
    """
    按 normalized_connection.output_sheet_name 分组。
    注意：output_sheet_name 来自输入框图 Excel 的原 sheet 名，不允许按 block_id/group 自行分组。
    """
    decisions = {d["line_id"]: d for d in iter_jsonl(decisions_path)}
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for n in iter_jsonl(normalized_path):
        sheet_name = n.get("output_sheet_name") or n.get("source_sheet_name")
        if not sheet_name:
            raise ValueError(f"normalized row missing output_sheet_name/source_sheet_name: {n.get('line_id')}")
        d = decisions.get(n["line_id"], {})
        connection_name = n.get("connection_name", "") or ""
        selected_pins = decision_selected_pins(d) or [""]
        should_expand = len(selected_pins) > 1
        base_connection_id = n.get("base_connection_id") or n.get("connection_id", "")

        for idx, selected_pin in enumerate(selected_pins):
            # 网络命名：统一调用 generate_net_name 模块兜底；无 pin 时强制为空。
            net_name = final_net_name(d, n, idx, selected_pin)
            connection_id = expanded_connection_id(
                base_connection_id,
                n.get("connection_id", ""),
                should_expand,
                idx,
            )

            row = {
                "源Block标识": n.get("source_block_id", ""),
                "源Block名称": n.get("source_block_name", ""),
                "源Port": n.get("source_port", ""),
                "目的Block标识": n.get("target_block_id", ""),
                "目的Block名称": n.get("target_block_name", ""),
                "目的Port": n.get("target_port", ""),
                "连线ID": connection_id,
                "连线名称": connection_name,
                "连线方向": n.get("direction", ""),
                "原理图Pin脚": selected_pin,
                "分析说明": decision_list_value(d, "analyses", idx, d.get("analysis", "")),
                "映射置信度": decision_list_value(d, "confidences", idx, d.get("confidence", "")),
                "网络命名": net_name,
            }
            grouped.setdefault(sheet_name, []).append(row)

    return grouped

def clear_sheet_values(ws):
    # 保留 sheet 本身，删除旧内容后从第一行重建标准结果表。
    if ws.max_row:
        ws.delete_rows(1, ws.max_row)

def write_rows(ws, rows: List[Dict[str, Any]]):
    clear_sheet_values(ws)
    ws.append(FINAL_HEADERS)
    for row in rows:
        ws.append([row.get(h, "") for h in FINAL_HEADERS])

    # 简单格式，避免强依赖复杂样式
    try:
        from openpyxl.styles import Font, Alignment
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(40, max(10, max_len + 2))
    except Exception:
        pass

def render_template_sheets(template_excel: str | Path, normalized_path: str | Path, decisions_path: str | Path, output_excel: str | Path) -> Dict[str, Any]:
    """
    正式信号接口列表输出：
    1. 复制输入框图 Excel 的 sheet 结构。
    2. 只向输入 Excel 已存在的器件 sheet 写入分析结果。
    3. 不根据 block_id/group/source_sheet 自行创建新 sheet。
    4. 不把所有结果合并到一个总 sheet。
    """
    from openpyxl import load_workbook

    template_excel = Path(template_excel)
    output_excel = Path(output_excel)
    ensure_dir(output_excel.parent)

    wb = load_workbook(template_excel)
    grouped = build_final_rows_by_template_sheet(normalized_path, decisions_path)

    input_sheets = set(wb.sheetnames)
    missing_in_template = sorted([s for s in grouped.keys() if s not in input_sheets])

    # 严格模式：不能创建新 sheet，避免“自己分组输出”
    if missing_in_template:
        raise ValueError(
            "以下输出 sheet 不存在于输入框图表格中，禁止自动创建新 sheet："
            + ", ".join(missing_in_template)
        )

    written_sheets = []
    for sheet_name in wb.sheetnames:
        if sheet_name.upper() in SKIP_SHEETS:
            written_sheets.append({"sheet_name": sheet_name, "row_count": "preserved"})
            continue
        rows = grouped.get(sheet_name, [])
        # 输入有这个器件 sheet，就保留该 sheet；有分析结果则写入，无结果则写入空表头。
        ws = wb[sheet_name]
        write_rows(ws, rows)
        written_sheets.append({"sheet_name": sheet_name, "row_count": len(rows)})

    wb.save(output_excel)
    wb.close()

    return {
        "output_excel": str(output_excel),
        "written_sheets": written_sheets,
        "missing_in_template": missing_in_template,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-excel", required=True, help="输入框图 Excel，输出必须严格沿用它的 sheet 分页")
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--output-excel", required=True)
    args = parser.parse_args()

    result = render_template_sheets(args.template_excel, args.normalized, args.decisions, args.output_excel)
    print(f"[OK] rendered template sheets -> {result['output_excel']}")
    for item in result["written_sheets"]:
        print(f"  - {item['sheet_name']}: {item['row_count']} rows")

if __name__ == "__main__":
    main()
