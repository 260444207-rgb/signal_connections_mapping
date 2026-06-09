#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from collections import defaultdict
from common import iter_jsonl,read_table,write_json,stable_hash,tokenize_signal_name
def load_pins_by_block(pin_path):
    by=defaultdict(list)
    for p in read_table(pin_path): by[str(p.get('block_id') or p.get('source_block_id') or p.get('器件标识') or p.get('device_id') or '')].append(p)
    return dict(by)
def group_units(normalized_path,pin_path,output_path):
    rows=list(iter_jsonl(normalized_path)); pins_by=load_pins_by_block(pin_path); groups={}
    for row in rows:
        bid=row['source_block_id']; pin_names=sorted([str(p.get('pin') or p.get('pin_name') or p.get('Pin') or p.get('name') or '') for p in pins_by.get(bid,[])])
        sig=stable_hash({'source_name_tokens':tokenize_signal_name(row.get('source_block_name','')),'target_name_tokens':tokenize_signal_name(row.get('target_block_name','')),'pin_names':pin_names})
        gid=f'GROUP_{sig}'
        groups.setdefault(gid,{'group_id':gid,'source_block_ids':set(),'target_block_names':set(),'line_ids':[],'pin_signature':stable_hash(pin_names),'topology_signature':sig})
        groups[gid]['source_block_ids'].add(bid); groups[gid]['target_block_names'].add(row.get('target_block_name','')); groups[gid]['line_ids'].append(row['line_id'])
    result={'groups':[]}
    for g in groups.values(): g['source_block_ids']=sorted(g['source_block_ids']); g['target_block_names']=sorted(g['target_block_names']); result['groups'].append(g)
    write_json(output_path,result); return result
def main():
    p=argparse.ArgumentParser(); p.add_argument('--normalized',required=True); p.add_argument('--pins',required=True); p.add_argument('--output',required=True); a=p.parse_args(); r=group_units(a.normalized,a.pins,a.output); print(f"[OK] groups: {len(r['groups'])} -> {a.output}")
if __name__=='__main__': main()
