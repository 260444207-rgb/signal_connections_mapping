#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import csv,json,re,hashlib
from pathlib import Path
from typing import Any,Callable,Dict,Iterable,List,Optional

FINAL_HEADERS=["源Block标识","源Block名称","源Port","目的Block标识","目的Block名称","目的Port","连线ID","连线名称","连线方向","连线属性","原理图Pin脚","分析说明","映射置信度","网络命名"]
VALID_DIRECTIONS={"INPUT","OUTPUT",""}; VALID_CONFIDENCE={"High","Medium","Low",""}
EXCLUDED_INPUT_SHEETS={"BLOCK_INFO","目录","说明","README","INDEX"}

def ensure_dir(path): p=Path(path); p.mkdir(parents=True,exist_ok=True); return p

def read_json(path,default=None):
    p=Path(path); return default if not p.exists() else json.loads(p.read_text(encoding='utf-8'))

def write_json(path,obj): p=Path(path); ensure_dir(p.parent); p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def iter_jsonl(path):
    p=Path(path)
    if not p.exists(): return
    with p.open('r',encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if line: yield json.loads(line)

def write_jsonl(path,rows):
    p=Path(path); ensure_dir(p.parent)
    with p.open('w',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+'\n')

def stable_hash(obj): return hashlib.md5(json.dumps(obj,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:12]
def normalize_text(v): return '' if v is None else str(v).strip()

def normalize_header_name(value: Any) -> str:
    return normalize_text(value).casefold()

def find_header_alias(header_map: Dict[str, int], aliases: Iterable[str]) -> str:
    """Return the actual worksheet header matching aliases case-insensitively."""
    actual_by_normalized = {
        normalize_header_name(header): header
        for header in header_map
    }
    for alias in aliases:
        actual = actual_by_normalized.get(normalize_header_name(alias))
        if actual:
            return actual
    return ""

def worksheet_header_map(ws, header_row: int) -> Dict[str, int]:
    """Return non-empty worksheet headers mapped to their actual column numbers."""
    header_map: Dict[str, int] = {}
    for cell in ws[header_row]:
        name = normalize_text(cell.value)
        if name and name not in header_map:
            header_map[name] = cell.column
    return header_map

def find_worksheet_header(
    ws,
    matcher: Callable[[List[str]], bool],
    max_scan_rows: Optional[int] = None,
) -> tuple[Optional[int], Dict[str, int]]:
    """Find a header row by its names, never by a fixed row or column position."""
    last_row = min(ws.max_row, max_scan_rows) if max_scan_rows else ws.max_row
    for row_number in range(1, last_row + 1):
        header_map = worksheet_header_map(ws, row_number)
        if header_map and matcher(list(header_map)):
            return row_number, header_map
    return None, {}

def iter_worksheet_records_with_row_numbers(ws, header_row: int, header_map: Dict[str, int]):
    """Yield worksheet row numbers and records addressed only through header names."""
    for row_number in range(header_row + 1, ws.max_row + 1):
        record = {
            header: ws.cell(row=row_number, column=column_number).value
            for header, column_number in header_map.items()
        }
        if any(normalize_text(value) for value in record.values()):
            yield row_number, record

def iter_worksheet_records(ws, header_row: int, header_map: Dict[str, int]):
    """Yield worksheet records whose values are addressed only through header names."""
    for _, record in iter_worksheet_records_with_row_numbers(ws, header_row, header_map):
        yield record

def write_worksheet_records(ws, headers: List[str], rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Rebuild a worksheet and write every field via its header-to-column mapping."""
    if ws.max_row:
        ws.delete_rows(1, ws.max_row)
    for column_number, header in enumerate(headers, start=1):
        ws.cell(row=1, column=column_number, value=header)
    header_map = worksheet_header_map(ws, 1)
    for row_number, record in enumerate(rows, start=2):
        for header in headers:
            ws.cell(row=row_number, column=header_map[header], value=record.get(header, ""))
    return header_map

def device_identity_tokens(value):
    """Return strict code/name tokens used to match a ### RULE title."""
    text=normalize_text(value).upper()
    if not text: return set()
    tokens=set()
    generic={'DEV','DEVICE','PART','SOURCE','TARGET','SRC','DST','BLOCK','RULE'}
    compact=re.sub(r'[^A-Z0-9\u4e00-\u9fff]+','',text)
    if len(compact)>=3 and compact not in generic: tokens.add(compact)
    for segment in re.split(r'[\s/,，;；、]+',text):
        segment_compact=re.sub(r'[^A-Z0-9\u4e00-\u9fff]+','',segment)
        if len(segment_compact)>=3 and segment_compact not in generic:
            tokens.add(segment_compact)
    for token in re.findall(r'[A-Z0-9]+(?:-[A-Z0-9]+)*|[\u4e00-\u9fff]{2,}',text):
        if len(token)>=3 and token not in generic:
            tokens.add(token)
            if token.isdigit(): tokens.add(token.lstrip('0') or '0')
    return tokens

def rule_title_device_matches(title, device_values):
    """Require a device-scoped rule title to name an actual endpoint device."""
    title_tokens=device_identity_tokens(title)
    if not title_tokens: return False
    return any(title_tokens.intersection(device_identity_tokens(value)) for value in device_values)

COMPONENT_UUID_KEYS={"componentuuid","component_uuid","component-uuid"}
PIN_COLLECTION_KEYS=("pins","pin_info","pinInfo","pin_list","pinList","pinNames","pin_names")
PIN_NAME_KEYS=("pin","pin_name","pinName","Pin","name")
COMPONENT_CONTAINER_KEYS={"components","componentpins","component_pin_infos","devices","items","data","records"}

def _clean_component_uuid(value):
    text=normalize_text(value).strip('\\').strip().strip('"\'').strip()
    if len(text)>=2 and text[0]=='{' and text[-1]=='}': text=text[1:-1].strip()
    return text

def _component_uuid_from_object(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if normalize_text(key).lower() in COMPONENT_UUID_KEYS:
                found=_clean_component_uuid(item)
                if found: return found
        for item in value.values():
            found=_component_uuid_from_object(item)
            if found: return found
    elif isinstance(value,list):
        for item in value:
            found=_component_uuid_from_object(item)
            if found: return found
    return ''

def extract_component_uuid(value):
    """Extract componentUuid from JSON-like block_info device metadata."""
    if isinstance(value,(dict,list)):
        return _component_uuid_from_object(value)
    text=normalize_text(value)
    if not text or 'componentuuid' not in text.lower().replace('_','').replace('-',''):
        return ''
    decoded=text
    for _ in range(2):
        try:
            parsed=json.loads(decoded)
        except (json.JSONDecodeError,TypeError):
            break
        found=_component_uuid_from_object(parsed)
        if found: return found
        if not isinstance(parsed,str): break
        decoded=parsed
    quoted=re.search(r'''(?ix)
        [\\"']*component[_-]?uuid[\\"']*\s*[:=]\s*
        (?:\\?["'])(?P<value>[^"'\\]+)(?:\\?["'])
    ''',text)
    if quoted:
        return _clean_component_uuid(quoted.group('value'))
    bare=re.search(r'''(?ix)
        \bcomponent[_-]?uuid\b\s*[:=]\s*
        (?P<value>\{?[a-z0-9][a-z0-9._:/-]*\}?)
    ''',text)
    return _clean_component_uuid(bare.group('value')) if bare else ''

def normalize_component_reference(value):
    return extract_component_uuid(value) or normalize_text(value)
def normalize_direction(v):
    s=normalize_text(v).upper()
    if s in {'IN','INPUT'}: return 'INPUT'
    if s in {'OUT','OUTPUT'}: return 'OUTPUT'
    return s if s in VALID_DIRECTIONS else ''

def _read_xlsx_rows(path: Path) -> List[Dict[str, Any]]:
    """读取输入框图 Excel：保留分页信息。默认跳过 BLOCK_INFO 等非器件页。"""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    rows: List[Dict[str, Any]] = []
    supported_table_headers = {
        "源Port", "source_port", "目的Port", "目标Port", "target_port",
        "连线ID", "连线标识", "connection_id", "器件信息", "器件标识",
        "device_part_id", "part_number", "device_id", "block_id", "source_block_id",
        *COMPONENT_UUID_KEYS, *PIN_NAME_KEYS,
    }
    for ws in wb.worksheets:
        if ws.title.strip().upper() in {x.upper() for x in EXCLUDED_INPUT_SHEETS}:
            continue
        header_row, header_map = find_worksheet_header(
            ws,
            lambda headers: any(
                header in supported_table_headers or header.lower() in supported_table_headers
                for header in headers
            ),
            max_scan_rows=20,
        )
        if header_row is None:
            continue
        for row_dict in iter_worksheet_records(ws, header_row, header_map):
            row_dict['__sheet_name']=ws.title
            row_dict.setdefault('source_sheet_name', ws.title)
            row_dict.setdefault('output_sheet_name', ws.title)
            rows.append(row_dict)
    wb.close()
    return rows

def read_table(path):
    p=Path(path); suf=p.suffix.lower()
    if suf=='.json':
        data=json.loads(p.read_text(encoding='utf-8'))
        if isinstance(data,list): return data
        if isinstance(data,dict):
            for k in ('rows','connections','pins'):
                if isinstance(data.get(k),list): return data[k]
        raise ValueError(f'Unsupported JSON shape: {p}')
    if suf=='.jsonl': return list(iter_jsonl(p))
    if suf=='.csv':
        with p.open('r',encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
    if suf in {'.xlsx','.xlsm'}:
        return _read_xlsx_rows(p)
    raise ValueError(f'Unsupported file type: {p.suffix}; use json/jsonl/csv/xlsx.')

def _pin_names_from_value(value):
    if isinstance(value,list):
        result=[]
        for item in value:
            if isinstance(item,dict):
                pin=next((normalize_text(item.get(key)) for key in PIN_NAME_KEYS if normalize_text(item.get(key))), '')
                if pin: result.append(pin)
            else:
                pin=normalize_text(item)
                if pin: result.append(pin)
        return result
    if isinstance(value,dict):
        direct=next((normalize_text(value.get(key)) for key in PIN_NAME_KEYS if normalize_text(value.get(key))), '')
        if direct: return [direct]
        for key in PIN_COLLECTION_KEYS:
            if key in value:
                nested=_pin_names_from_value(value.get(key))
                if nested: return nested
    return []

def _collect_component_pin_records(value,catalog):
    if isinstance(value,list):
        for item in value: _collect_component_pin_records(item,catalog)
        return
    if not isinstance(value,dict): return
    component_id=''
    for key,item in value.items():
        if normalize_text(key).lower() in COMPONENT_UUID_KEYS:
            component_id=_clean_component_uuid(item)
            break
    pin_values=[]
    for key in PIN_COLLECTION_KEYS:
        if key in value:
            pin_values=_pin_names_from_value(value.get(key))
            if pin_values: break
    if not pin_values:
        direct_pin=next((normalize_text(value.get(key)) for key in PIN_NAME_KEYS if normalize_text(value.get(key))), '')
        if direct_pin: pin_values=[direct_pin]
    if component_id and pin_values:
        catalog.setdefault(component_id,[]).extend(pin_values)
    for item in value.values():
        if isinstance(item,(dict,list)): _collect_component_pin_records(item,catalog)

def load_pin_catalog(path):
    """Return pin_info as the native {part_number: [pin_name]} catalog."""
    p=Path(path); suf=p.suffix.lower()
    if suf=='.json':
        data=json.loads(p.read_text(encoding='utf-8'))
        if (
            isinstance(data,dict)
            and not any(normalize_text(key).lower() in COMPONENT_CONTAINER_KEYS for key in data)
            and all(isinstance(v,list) and all(not isinstance(item,(dict,list)) for item in v) for v in data.values())
        ):
            return {normalize_component_reference(k):[normalize_text(x) for x in v if normalize_text(x)] for k,v in data.items()}
        if isinstance(data,dict) and isinstance(data.get('pins'),dict):
            return {normalize_component_reference(k):[normalize_text(x) for x in v if normalize_text(x)] for k,v in data['pins'].items()}
        catalog={}
        _collect_component_pin_records(data,catalog)
        if catalog: return catalog
    catalog={}
    for row in read_table(p):
        part=normalize_component_reference(row.get('componentUuid') or row.get('component_uuid') or row.get('device_part_id') or row.get('part_number') or row.get('器件信息') or row.get('device_id') or row.get('block_id') or row.get('source_block_id') or row.get('器件标识'))
        pin=normalize_text(row.get('pin') or row.get('pin_name') or row.get('pinName') or row.get('Pin') or row.get('name'))
        if part and pin: catalog.setdefault(part,[]).append(pin)
    return catalog

def resolve_catalog_key(catalog, part_id):
    part=normalize_component_reference(part_id)
    if part in catalog: return part
    part_lower=part.lower()
    for key in catalog:
        if normalize_text(key).lower()==part_lower: return key
    stripped=part.lstrip('0')
    for key in catalog:
        if key.lstrip('0')==stripped:
            return key
    return part

def pins_for_part(catalog, part_id):
    return catalog.get(resolve_catalog_key(catalog, part_id), [])
