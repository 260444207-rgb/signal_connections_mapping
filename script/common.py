#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import csv,json,re,hashlib
from pathlib import Path
from typing import Any,Dict,Iterable,List,Optional

FINAL_HEADERS=["源Block标识","源Block名称","源Port","目的Block标识","目的Block名称","目的Port","连线ID","连线名称","连线方向","原理图Pin脚","分析说明","映射置信度","网络命名"]
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
def normalize_direction(v):
    s=normalize_text(v).upper()
    if s in {'IN','INPUT'}: return 'INPUT'
    if s in {'OUT','OUTPUT'}: return 'OUTPUT'
    return s if s in VALID_DIRECTIONS else ''
def extract_index(text):
    m=re.findall(r'(\d+)',text or '')
    return int(m[-1]) if m else None
def tokenize_signal_name(name): return [x for x in re.split(r'[^A-Z0-9]+',normalize_text(name).upper()) if x]
def simple_similarity(a,b):
    ta,tb=set(tokenize_signal_name(a)),set(tokenize_signal_name(b))
    return 0.0 if not ta or not tb else len(ta&tb)/len(ta|tb)
def make_net_name(*parts):
    raw='_'.join([p for p in parts if p]).upper(); raw=re.sub(r'[^A-Z0-9_]+','_',raw); return re.sub(r'_+','_',raw).strip('_')

def _read_xlsx_rows(path: Path) -> List[Dict[str, Any]]:
    """读取输入框图 Excel：保留分页信息。默认跳过 BLOCK_INFO 等非器件页。"""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    rows: List[Dict[str, Any]] = []
    for ws in wb.worksheets:
        if ws.title.strip().upper() in {x.upper() for x in EXCLUDED_INPUT_SHEETS}:
            continue
        values = list(ws.iter_rows(values_only=True))
        if not values:
            continue
        header_idx = None
        headers = None
        for i, row in enumerate(values[:20]):
            cells=[normalize_text(c) for c in row]
            if any(c in {"源Port","source_port","目的Port","目标Port","target_port","连线ID","连线标识","connection_id"} for c in cells):
                header_idx=i; headers=cells; break
        if header_idx is None or not headers:
            continue
        for raw in values[header_idx+1:]:
            if raw is None:
                continue
            row_dict={headers[i]: raw[i] if i < len(raw) else '' for i in range(len(headers)) if headers[i]}
            if not any(normalize_text(v) for v in row_dict.values()):
                continue
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

def load_pin_catalog(path):
    """Return pin_info as the native {part_number: [pin_name]} catalog."""
    p=Path(path); suf=p.suffix.lower()
    if suf=='.json':
        data=json.loads(p.read_text(encoding='utf-8'))
        if isinstance(data,dict) and all(isinstance(v,list) for v in data.values()):
            return {normalize_text(k):[normalize_text(x) for x in v if normalize_text(x)] for k,v in data.items()}
        if isinstance(data,dict) and isinstance(data.get('pins'),dict):
            return {normalize_text(k):[normalize_text(x) for x in v if normalize_text(x)] for k,v in data['pins'].items()}
    catalog={}
    for row in read_table(p):
        part=normalize_text(row.get('device_part_id') or row.get('part_number') or row.get('器件信息') or row.get('device_id') or row.get('block_id') or row.get('source_block_id') or row.get('器件标识'))
        pin=normalize_text(row.get('pin') or row.get('pin_name') or row.get('Pin') or row.get('name'))
        if part and pin: catalog.setdefault(part,[]).append(pin)
    return catalog

def resolve_catalog_key(catalog, part_id):
    part=normalize_text(part_id)
    if part in catalog: return part
    stripped=part.lstrip('0')
    for key in catalog:
        if key.lstrip('0')==stripped:
            return key
    return part

def pins_for_part(catalog, part_id):
    return catalog.get(resolve_catalog_key(catalog, part_id), [])

def find_pin(pins, pattern):
    rx=re.compile(pattern, re.I)
    for pin in pins:
        if rx.search(pin):
            return pin
    return ""
