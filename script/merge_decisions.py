#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path
from common import iter_jsonl,write_jsonl
def merge_decisions(output,inputs):
    merged={}
    for path in inputs:
        if not Path(path).exists(): continue
        for row in iter_jsonl(path): merged[row['line_id']]=row
    write_jsonl(output,merged.values())
def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True); p.add_argument('--inputs',nargs='+',required=True); a=p.parse_args(); merge_decisions(a.output,a.inputs); print(f'[OK] merged decisions -> {a.output}')
if __name__=='__main__': main()
