from __future__ import annotations

from collections import OrderedDict
from copy import copy
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
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


XML_PREFIX = rb"(?:[A-Za-z_][A-Za-z0-9_.-]*:)?"
ILLEGAL_XML_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _element_pattern(tag: bytes, attribute: bytes, value: str) -> re.Pattern[bytes]:
    escaped_value = re.escape(value.encode("ascii"))
    return re.compile(
        rb"<" + XML_PREFIX + tag + rb"\b"
        rb"(?=[^>]*\b" + attribute + rb"=(?:\"" + escaped_value + rb"\"|'" + escaped_value + rb"'))"
        rb"[^>]*(?:/>|>.*?</" + XML_PREFIX + tag + rb"\s*>)",
        re.DOTALL,
    )


def _inline_cell(cell_xml: bytes | None, ref: str, value: str, prefix: bytes = b"") -> bytes:
    value = ILLEGAL_XML_CHARS_RE.sub("", str(value or ""))
    encoded_value = escape(value).encode("utf-8")
    space = b' xml:space="preserve"' if value.startswith(" ") or value.endswith(" ") else b""
    if cell_xml:
        opening = re.match(rb"<" + XML_PREFIX + rb"c\b[^>]*", cell_xml)
        if not opening:
            raise ValueError(f"无法解析单元格 {ref}")
        opening_tag = opening.group(0)
        prefix_match = re.match(rb"<(?P<prefix>[A-Za-z_][A-Za-z0-9_.-]*:)?c\b", opening_tag)
        prefix = prefix_match.group("prefix") or b""
        opening_tag = re.sub(rb"\s+t=(?:\"[^\"]*\"|'[^']*')", b"", opening_tag)
    else:
        opening_tag = b"<" + prefix + b'c r="' + ref.encode("ascii") + b'"'
    return (
        opening_tag + b' t="inlineStr">'
        + b"<" + prefix + b"is><" + prefix + b"t" + space + b">"
        + encoded_value
        + b"</" + prefix + b"t></" + prefix + b"is></" + prefix + b"c>"
    )


def _patch_row(row_xml: bytes, row_number: int, changes: dict[int, str]) -> bytes:
    row_prefix_match = re.match(rb"<(?P<prefix>[A-Za-z_][A-Za-z0-9_.-]*:)?row\b", row_xml)
    row_prefix = row_prefix_match.group("prefix") if row_prefix_match else b""
    for column, value in sorted(changes.items()):
        ref = f"{column_letters(column)}{row_number}"
        cell_pattern = _element_pattern(b"c", b"r", ref)
        match = cell_pattern.search(row_xml)
        replacement = _inline_cell(match.group(0) if match else None, ref, value, row_prefix)
        if match:
            row_xml = row_xml[:match.start()] + replacement + row_xml[match.end():]
            continue

        insert_at = None
        for candidate in re.finditer(rb"<" + XML_PREFIX + rb"c\b[^>]*\br=(?:\"([A-Z]+)\d+\"|'([A-Z]+)\d+')[^>]*", row_xml):
            letters = (candidate.group(1) or candidate.group(2)).decode("ascii")
            if column_number(letters) > column:
                insert_at = candidate.start()
                break
        if insert_at is None:
            closing = re.search(rb"</" + XML_PREFIX + rb"row\s*>", row_xml)
            if not closing:
                raise ValueError(f"无法定位第 {row_number} 行结束标签")
            insert_at = closing.start()
        row_xml = row_xml[:insert_at] + replacement + row_xml[insert_at:]
    return row_xml


def _patch_sheet_xml(data: bytes, sheet_changes: dict[tuple[int, int], str], sheet_path: str) -> bytes:
    by_row: dict[int, dict[int, str]] = {}
    for (row_number, column), value in sheet_changes.items():
        by_row.setdefault(row_number, {})[column] = value
    for row_number, row_changes in sorted(by_row.items()):
        pattern = _element_pattern(b"row", b"r", str(row_number))
        match = pattern.search(data)
        if not match:
            raise ValueError(f"worksheet {sheet_path} 缺少已索引的第 {row_number} 行")
        replacement = _patch_row(match.group(0), row_number, row_changes)
        data = data[:match.start()] + replacement + data[match.end():]
    return data


def patch_workbook(input_path: str | Path, output_path: str | Path, changes: dict[str, dict[tuple[int, int], str]]) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(input_path, "r") as source:
        available_sheets = set(_sheet_paths(source))
    missing_sheets = sorted(set(changes) - available_sheets)
    if missing_sheets:
        raise ValueError("输入工作簿缺少待回写 sheet: " + ", ".join(missing_sheets))
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    if temporary_path.exists():
        temporary_path.unlink()
    try:
        with ZipFile(input_path, "r") as source, ZipFile(temporary_path, "w", ZIP_DEFLATED) as target:
            sheet_paths = _sheet_paths(source)
            changes_by_path = {sheet_paths[name]: values for name, values in changes.items()}
            for info in source.infolist():
                data = source.read(info.filename)
                sheet_changes = changes_by_path.get(info.filename)
                if sheet_changes:
                    data = _patch_sheet_xml(data, sheet_changes, info.filename)
                target.writestr(copy(info), data)
        with ZipFile(temporary_path, "r") as written:
            damaged_member = written.testzip()
            if damaged_member:
                raise ValueError(f"回写后的 XLSX ZIP 成员损坏: {damaged_member}")
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
