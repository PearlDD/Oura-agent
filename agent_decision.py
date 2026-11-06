#!/usr/bin/env python3
"""Persist a real Agent-authored JSON decision after freshness/schema validation.
Input files must remain in the private local data directory. Never prints health data.
"""
import argparse
import json
import app


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--date',required=True)
    p.add_argument('--input',required=True)
    p.add_argument('--hash',required=True)
    args=p.parse_args()
    from pathlib import Path
    path=Path(args.input).resolve()
    if not path.is_relative_to(app.DATA.resolve()):p.error('决策输入必须保存在本机私有数据目录。')
    if path.stat().st_size>100000:p.error('决策文件过大。')
    value=json.loads(path.read_text())
    app.store_decision(app.day(args.date),value,args.hash,'Codex Agent')
    print(json.dumps({'saved':True,'date':args.date},ensure_ascii=False))


if __name__=='__main__':main()
