from __future__ import annotations

from collections import OrderedDict
from copy import copy
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"x": MAIN_NS, "r": DOC_REL_NS, "pr": PKG_REL_NS}
CELL_REF_RE = re.compile(r"([A-Z]+)(\d+)")

ET.register_namespace("", MAIN_NS)


def column_number(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + ord(char) - 64
    return value


def column_letters(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//x:t", NS)) for item in root.findall("x:si", NS)]


def _sheet_paths(archive: ZipFile) -> OrderedDict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pr:Relationship", NS)
    }
    result: OrderedDict[str, str] = OrderedDict()
    for sheet in workbook.findall("x:sheets/x:sheet", NS):
        target = targets[sheet.attrib[f"{{{DOC_REL_NS}}}id"]].replace("\\", "/")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = str(PurePosixPath("xl") / target)
        result[sheet.attrib["name"]] = str(PurePosixPath(path))
    return result


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", NS))
    value_node = cell.find("x:v", NS)
    value = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s" and value:
        return shared[int(value)]
    return value


def read_workbook_rows(path: str | Path) -> OrderedDict[str, dict[int, dict[int, str]]]:
    result: OrderedDict[str, dict[int, dict[int, str]]] = OrderedDict()
    with ZipFile(path) as archive:
        shared = _shared_strings(archive)
        for sheet_name, sheet_path in _sheet_paths(archive).items():
            root = ET.fromstring(archive.read(sheet_path))
            rows: dict[int, dict[int, str]] = {}
            for row in root.findall(".//x:sheetData/x:row", NS):
                row_number = int(row.attrib["r"])
                cells: dict[int, str] = {}
                for cell in row.findall("x:c", NS):
                    match = CELL_REF_RE.fullmatch(cell.attrib.get("r", ""))
                    if match:
                        cells[column_number(match.group(1))] = _cell_value(cell, shared)
                rows[row_number] = cells
            result[sheet_name] = rows
    return result


def _set_inline_string(row: ET.Element, row_number: int, column: int, value: str) -> None:
    ref = f"{column_letters(column)}{row_number}"
    existing = None
    for cell in row.findall("x:c", NS):
        if cell.attrib.get("r") == ref:
            existing = cell
            break
    if existing is None:
        existing = ET.Element(f"{{{MAIN_NS}}}c", {"r": ref})
        inserted = False
        for index, cell in enumerate(list(row)):
            match = CELL_REF_RE.fullmatch(cell.attrib.get("r", ""))
            if match and column_number(match.group(1)) > column:
                row.insert(index, existing)
                inserted = True
                break
        if not inserted:
            row.append(existing)
    for child in list(existing):
        existing.remove(child)
    existing.attrib["t"] = "inlineStr"
    inline = ET.SubElement(existing, f"{{{MAIN_NS}}}is")
    text_node = ET.SubElement(inline, f"{{{MAIN_NS}}}t")
    if value.startswith(" ") or value.endswith(" "):
        text_node.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
    text_node.text = value


def patch_workbook(input_path: str | Path, output_path: str | Path, changes: dict[str, dict[tuple[int, int], str]]) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(input_path, "r") as source, ZipFile(output_path, "w", ZIP_DEFLATED) as target:
        sheet_paths = _sheet_paths(source)
        changes_by_path = {sheet_paths[name]: values for name, values in changes.items()}
        for info in source.infolist():
            data = source.read(info.filename)
            sheet_changes = changes_by_path.get(info.filename)
            if sheet_changes:
                root = ET.fromstring(data)
                sheet_data = root.find("x:sheetData", NS)
                if sheet_data is None:
                    raise ValueError(f"worksheet missing sheetData: {info.filename}")
                rows = {int(row.attrib["r"]): row for row in sheet_data.findall("x:row", NS)}
                for (row_number, column), value in sheet_changes.items():
                    row = rows.get(row_number)
                    if row is None:
                        row = ET.Element(f"{{{MAIN_NS}}}row", {"r": str(row_number)})
                        sheet_data.append(row)
                        rows[row_number] = row
                    _set_inline_string(row, row_number, column, value)
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(copy(info), data)
