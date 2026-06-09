#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from common import iter_jsonl,write_jsonl,simple_similarity,extract_index,normalize_text,load_pin_catalog,pins_for_part,resolve_catalog_key
def score_candidate(row,pin_name):
    pin_name=normalize_text(pin_name); pin_desc=''; sp=row.get('source_port',''); tp=row.get('target_port',''); tb=row.get('target_block_name','')
    score=0.0; basis=[]; ns=max(simple_similarity(sp,pin_name),simple_similarity(sp,pin_desc))
    if ns>0: score+=ns*.45; basis.append('name_or_description_similarity')
    si,pi=extract_index(sp),extract_index(pin_name)
    if si is not None and pi is not None and si==pi: score+=.25; basis.append('index_match')
    if simple_similarity(tp,pin_name)>0: score+=.15; basis.append('target_port_similarity')
    if simple_similarity(tb,pin_desc)>0: score+=.10; basis.append('target_block_semantic_similarity')
    if row.get('direction') in {'INPUT','OUTPUT'}: score+=.05; basis.append('direction_available')
    return {'pin':pin_name,'score':round(min(score,1.0),4),'basis':basis,'pin_description':pin_desc}
def generate_candidates(normalized_path,pin_path,output_path,top_k=5):
    catalog=load_pin_catalog(pin_path); out=[]
    for row in iter_jsonl(normalized_path):
        part=row.get('source_part_id') or row.get('source_block_id')
        resolved=resolve_catalog_key(catalog,part)
        available_pins=pins_for_part(catalog,part)
        c=[score_candidate(row,p) for p in available_pins]
        c.sort(key=lambda x:x['score'],reverse=True)
        out.append({'line_id':row['line_id'],'source_part_id':part,'resolved_part_id':resolved,'source_block_id':row['source_block_id'],'source_port':row['source_port'],'target_block_name':row['target_block_name'],'target_port':row['target_port'],'direction':row['direction'],'expansion_index':row.get('expansion_index',1),'expansion_count':row.get('expansion_count',1),'available_pins':available_pins,'candidates':c[:top_k]})
    write_jsonl(output_path,out); return out
def main():
    p=argparse.ArgumentParser(); p.add_argument('--normalized',required=True); p.add_argument('--pins',required=True); p.add_argument('--output',required=True); p.add_argument('--top-k',type=int,default=5); a=p.parse_args(); rows=generate_candidates(a.normalized,a.pins,a.output,a.top_k); print(f'[OK] candidate mappings: {len(rows)} -> {a.output}')
if __name__=='__main__': main()
