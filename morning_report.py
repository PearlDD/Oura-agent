#!/usr/bin/env python3
"""Refresh recent records and save a dated morning report without an AI API call."""
import argparse
import json
from pathlib import Path
import app


def generate(cached=False, synchronize=True, runtime=None):
    app = runtime or globals()['app']
    if synchronize and not cached:
        app.sync(7)
    d = app.today().isoformat()
    app.run_coach(d)
    result = app.report(d)
    ctx=app.analysis_context(d,result)
    context_path=app.DATA/'agent-context'/(d+'.json')
    app.save(context_path,{'data_hash':app.decision.fingerprint(ctx),'context':ctx})
    failures = [] if cached else list(app.JOB.get('errors', []))
    missing = []
    if not result['day_context']['synced']:
        missing.append('本日训记记录未成功读取，不能据此判断是否休息。')
    if result['recovery'].get('sleep_hours') is None:
        missing.append('本日 Oura 只有睡眠片段，完整主睡眠待同步；不会将片段当作整晚睡眠。' if result['recovery'].get('sleep_status')=='pending_main' else '本日 Oura 主睡眠尚未上传或同步，请先在 Oura App 同步戒指。')
    warnings = failures + missing
    content = app.markdown(result)
    if warnings:
        content = '# 数据状态提醒\n\n' + '\n'.join('- ' + x for x in warnings) + '\n\n' + content
    folder = app.REPORT_DIR
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / (d + '.md')
    target.write_text(content)
    target.chmod(0o600)
    return {'date': d, 'report_path': str(target), 'mode': result['day_context']['label'],
            'analysis_context_path':str(context_path),'data_hash':app.decision.fingerprint(ctx),
            'warnings': warnings, 'cached_only': cached, 'sync_failed': bool(failures)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cached', action='store_true', help='仅使用缓存生成，用于检查输出')
    args = parser.parse_args()
    result = generate(cached=args.cached)
    print(json.dumps(result, ensure_ascii=False))
    if result['sync_failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
