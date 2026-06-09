#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse,re
from common import iter_jsonl,read_json,write_jsonl,make_net_name
def load_candidates(path): return {r['line_id']:r for r in iter_jsonl(path)}
def load_groups(path):
    data=read_json(path,{'groups':[]}); out={}
    for g in data.get('groups',[]):
        for line_id in g.get('line_ids',[]): out[line_id]=g
    return out
def template_matches(t,g,c):
    reasons=[]
    if t.get('group_id') and t.get('group_id')!=g.get('group_id'): reasons.append('group_id_not_match')
    app=t.get('applicability',{})
    if app.get('source_port_regex') and not re.search(app['source_port_regex'],c.get('source_port','')): reasons.append('source_port_regex_not_match')
    if app.get('target_port_regex') and not re.search(app['target_port_regex'],c.get('target_port','')): reasons.append('target_port_regex_not_match')
    if app.get('required_direction') and app['required_direction']!=c.get('direction'): reasons.append('direction_not_match')
    return len(reasons)==0,reasons
def choose_by_template(t,c):
    cands=c.get('candidates',[]); prefer=t.get('candidate_rule',{}).get('prefer_pin_regex','')
    if prefer:
        for x in cands:
            if re.search(prefer,x.get('pin','')): return x['pin'],'template_prefer_pin_regex'
    if cands and cands[0].get('score',0)>=.80: return cands[0]['pin'],'top_candidate_score'
    return '','no_unique_candidate'
def apply_templates(normalized_path,candidate_path,group_path,template_path,decisions_out,needs_model_out):
    rows=list(iter_jsonl(normalized_path)); cands=load_candidates(candidate_path); groups=load_groups(group_path); templates=read_json(template_path,{'templates':[]}).get('templates',[])
    decisions=[]; needs=[]
    for row in rows:
        line=row['line_id']; cand=cands.get(line,{'candidates':[]}); group=groups.get(line,{}); matched=False
        for t in templates:
            ok,_=template_matches(t,group,cand)
            if not ok: continue
            matched=True; pin,basis=choose_by_template(t,cand)
            if pin: decisions.append({'line_id':line,'selected_pin':pin,'decision_type':'template_applied','confidence':'High' if basis!='top_candidate_score' else 'Medium','analysis':f"运行时模板 {t.get('template_id')} 通过 Gate 检查，依据 {basis} 选择 Pin。",'net_name':make_net_name(row.get('source_port',''),'TO',pin),'needs_human_review':False,'template_id':t.get('template_id','')})
            else: needs.append({'line_id':line,'reason':basis,'normalized_connection':row,'candidate_mapping':cand,'group':group,'template':t})
            break
        if not matched:
            cc=cand.get('candidates',[])
            if cc and cc[0].get('score',0)>=.92 and (len(cc)==1 or cc[0]['score']-cc[1].get('score',0)>=.20):
                pin=cc[0]['pin']; decisions.append({'line_id':line,'selected_pin':pin,'decision_type':'template_applied','confidence':'Medium','analysis':'无运行时模板，但候选分数高且明显领先，作为自动候选结果输出，建议抽查。','net_name':make_net_name(row.get('source_port',''),'TO',pin),'needs_human_review':False,'template_id':''})
            else: needs.append({'line_id':line,'reason':'no_template_or_ambiguous_candidates','normalized_connection':row,'candidate_mapping':cand,'group':group,'template':{}})
    write_jsonl(decisions_out,decisions); write_jsonl(needs_model_out,needs)
def main():
    p=argparse.ArgumentParser(); p.add_argument('--normalized',required=True); p.add_argument('--candidates',required=True); p.add_argument('--groups',required=True); p.add_argument('--templates',required=True); p.add_argument('--decisions-out',required=True); p.add_argument('--needs-model-out',required=True); a=p.parse_args(); apply_templates(a.normalized,a.candidates,a.groups,a.templates,a.decisions_out,a.needs_model_out); print('[OK] template application finished')
if __name__=='__main__': main()
