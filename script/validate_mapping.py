#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from common import iter_jsonl,write_json,VALID_CONFIDENCE,load_pin_catalog,pins_for_part
def selected_pins(decision):
    pins=decision.get('selected_pins')
    if isinstance(pins,list) and pins: return [str(p).strip() for p in pins if str(p).strip()]
    pin=str(decision.get('selected_pin','') or '').strip()
    return [pin] if pin else []
def physical_instance_key(row):
    return f"SHEET:{row.get('source_sheet_name') or row.get('output_sheet_name') or 'UNKNOWN_SHEET'}|PART:{row.get('source_part_id') or 'UNKNOWN_PART'}"
def source_endpoint_key(row):
    return '|'.join([str(row.get('source_sheet_name') or row.get('output_sheet_name') or ''),str(row.get('source_block_id') or row.get('source_block_name') or ''),str(row.get('source_port') or '')])
def shared_signal_key(row):
    name=str(row.get('connection_name','') or '').strip()
    if name: return f"NET:{name}"
    base=str(row.get('base_connection_id','') or '').strip()
    if base: return f"CONNECTION:{base}"
    return ''
def validate_mapping(normalized_path,decisions_path,pins_path,report_path):
    normalized=list(iter_jsonl(normalized_path)); decisions=list(iter_jsonl(decisions_path)); catalog=load_pin_catalog(pins_path)
    normalized_by_id={r['line_id']:r for r in normalized}
    nids={r['line_id'] for r in normalized}; dids=[d['line_id'] for d in decisions]; dset=set(dids)
    errors=[]; warnings=[]; pin_usage={}
    for x in sorted(nids-dset): errors.append({'severity':'ERROR','line_id':x,'message':'missing mapping decision'})
    for x in sorted(dset-nids): errors.append({'severity':'ERROR','line_id':x,'message':'decision line_id not in normalized connections'})
    for x in sorted({x for x in dids if dids.count(x)>1}): errors.append({'severity':'ERROR','line_id':x,'message':'duplicate mapping decision'})
    for d in decisions:
        line=d.get('line_id',''); conf=d.get('confidence',''); pins=selected_pins(d); net=d.get('net_name','')
        if conf not in VALID_CONFIDENCE: errors.append({'severity':'ERROR','line_id':line,'message':f'invalid confidence: {conf}'})
        row=normalized_by_id.get(line,{})
        source_part_id=row.get('source_part_id','')
        source_pins=set(pins_for_part(catalog,source_part_id))
        for pin in pins:
            if pin and pin not in source_pins:
                errors.append({'severity':'ERROR','line_id':line,'message':f'selected_pin must come from input pin_info for source_part_id={source_part_id}: {pin}'})
            if pin:
                key=(physical_instance_key(row),pin)
                pin_usage.setdefault(key,[]).append({'line_id':line,'shared_signal_key':shared_signal_key(row),'source_endpoint_key':source_endpoint_key(row)})
        if not pins and conf=='High': errors.append({'severity':'ERROR','line_id':line,'message':'empty selected_pin cannot be High confidence'})
    for (instance_key,pin),uses in sorted(pin_usage.items()):
        line_ids=sorted({u['line_id'] for u in uses})
        if len(line_ids)<=1: continue
        all_shared_keys=[u.get('shared_signal_key','') for u in uses]
        if all(all_shared_keys) and len(set(all_shared_keys))==1:
            continue
        all_source_endpoints=[u.get('source_endpoint_key','') for u in uses]
        if all(all_source_endpoints) and len(set(all_source_endpoints))==1:
            continue
        warnings.append({'severity':'WARNING','line_id':','.join(line_ids),'message':f'selected_pin reused within same physical device instance {instance_key}: {pin}. Reuse is allowed only for same source endpoint fanout, same net/base_connection, or explicit multi-port alias rule.'})
    report={'status':'PASS' if not errors else 'ERROR','summary':{'normalized_count':len(normalized),'decision_count':len(decisions),'error_count':len(errors),'warning_count':len(warnings)},'errors':errors,'warnings':warnings}
    write_json(report_path,report); return report
def main():
    p=argparse.ArgumentParser(); p.add_argument('--normalized',required=True); p.add_argument('--decisions',required=True); p.add_argument('--pins',required=True); p.add_argument('--report',required=True); a=p.parse_args(); r=validate_mapping(a.normalized,a.decisions,a.pins,a.report); print(f"[{r['status']}] errors={r['summary']['error_count']} warnings={r['summary']['warning_count']}")
if __name__=='__main__': main()
