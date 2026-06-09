#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from common import iter_jsonl,write_json,VALID_CONFIDENCE,load_pin_catalog
def validate_mapping(normalized_path,decisions_path,pins_path,report_path):
    normalized=list(iter_jsonl(normalized_path)); decisions=list(iter_jsonl(decisions_path)); catalog=load_pin_catalog(pins_path)
    nids={r['line_id'] for r in normalized}; dids=[d['line_id'] for d in decisions]; dset=set(dids); pin_names={p for pins in catalog.values() for p in pins}
    errors=[]; warnings=[]
    for x in sorted(nids-dset): errors.append({'severity':'ERROR','line_id':x,'message':'missing mapping decision'})
    for x in sorted(dset-nids): errors.append({'severity':'ERROR','line_id':x,'message':'decision line_id not in normalized connections'})
    for x in sorted({x for x in dids if dids.count(x)>1}): errors.append({'severity':'ERROR','line_id':x,'message':'duplicate mapping decision'})
    for d in decisions:
        line=d.get('line_id',''); conf=d.get('confidence',''); pin=d.get('selected_pin',''); net=d.get('net_name','')
        if conf not in VALID_CONFIDENCE: errors.append({'severity':'ERROR','line_id':line,'message':f'invalid confidence: {conf}'})
        if pin and pin not in pin_names: warnings.append({'severity':'WARNING','line_id':line,'message':f'selected_pin not found in pins: {pin}'})
        if pin and not net: errors.append({'severity':'ERROR','line_id':line,'message':'selected_pin exists but net_name is empty'})
        if not pin and conf=='High': errors.append({'severity':'ERROR','line_id':line,'message':'empty selected_pin cannot be High confidence'})
    report={'status':'PASS' if not errors else 'ERROR','summary':{'normalized_count':len(normalized),'decision_count':len(decisions),'error_count':len(errors),'warning_count':len(warnings)},'errors':errors,'warnings':warnings}
    write_json(report_path,report); return report
def main():
    p=argparse.ArgumentParser(); p.add_argument('--normalized',required=True); p.add_argument('--decisions',required=True); p.add_argument('--pins',required=True); p.add_argument('--report',required=True); a=p.parse_args(); r=validate_mapping(a.normalized,a.decisions,a.pins,a.report); print(f"[{r['status']}] errors={r['summary']['error_count']} warnings={r['summary']['warning_count']}")
if __name__=='__main__': main()
