#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path
from .common import ensure_dir,write_json
def init_task(task_dir):
    task=Path(task_dir)
    ensure_dir(task/'intermediate')
    write_json(task/'intermediate'/'pipeline_state.json',{"status":"initialized","stages":[]})
def main():
    p=argparse.ArgumentParser(); p.add_argument('--task-dir',required=True); a=p.parse_args(); init_task(a.task_dir); print(f'[OK] initialized: {a.task_dir}')
if __name__=='__main__': main()
