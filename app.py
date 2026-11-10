#!/usr/bin/env python3
"""Local, single-user lifting/recovery journal. Python 3.10+, no dependencies."""
import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo
import muscles
import coach
import decision
import chat
import providers
import cloud

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('IRON_DATA_DIR', str(ROOT.parents[1] / 'work' / 'iron-oura-data')))
TZ = ZoneInfo(os.environ.get('IRON_TIMEZONE', 'America/New_York'))
PORT = int(os.environ.get('IRON_PORT', '8765'))
BIND = os.environ.get('IRON_BIND', '127.0.0.1')
PUBLIC_URL = cloud.public_origin(os.environ.get('IRON_PUBLIC_URL', ''))
PROXY_TOKEN = os.environ.get('IRON_PROXY_TOKEN', '')
REPORT_DIR = Path(os.environ.get('IRON_REPORT_DIR', str(ROOT.parents[1] / 'outputs' / '晨报')))
cloud.validate(BIND, PUBLIC_URL, PROXY_TOKEN)
LOCK = threading.RLock()
NONCE = secrets.token_urlsafe(32)
OAUTH = {}
JOB = {'running': False, 'message': '尚未同步', 'errors': []}


class AppError(Exception):
    pass


def redirect_uri():
    return (PUBLIC_URL or f'http://localhost:{PORT}') + '/oauth/callback'


def today():
    return dt.datetime.now(TZ).date()


def day(value):
    return dt.date.fromisoformat(str(value)).isoformat()


def load(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text())


def save(path, value):
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = path.with_suffix('.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False)
        os.chmod(temp, 0o600)
        os.replace(temp, path)


def settings():
    return load(DATA / 'settings.json')


def update_settings(values):
    with LOCK:
        s = settings()
        s.update(values)
        save(DATA / 'settings.json', s)


def request_json(url, payload=None, token=None, form=False, extra_headers=None):
    provider='gemini' if url.startswith('https://generativelanguage.googleapis.com/') else 'openai'
    is_ai=url.startswith(('https://api.openai.com/','https://generativelanguage.googleapis.com/'))
    ai_status=DATA/('ai-status-gemini.json' if provider=='gemini' else 'ai-status.json')
    headers = {'User-Agent': 'IronOuraMVP/0.1', 'Accept-Encoding': 'gzip'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if extra_headers:headers.update(extra_headers)
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        body = (urllib.parse.urlencode(payload) if form else json.dumps(payload)).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=60) as r:
            raw = r.read(15_000_001)
        if len(raw) > 15_000_000:
            raise AppError('接口响应过大，请缩小同步范围。')
        if raw[:2] == b'\x1f\x8b':
            raw = gzip.decompress(raw)
        result=json.loads(raw)
        if is_ai:
            save(ai_status,{'ok':True,'checked_at':time.time()})
        return result
    except urllib.error.HTTPError as e:
        labels = {401: '授权无效或已过期，请重新连接', 403: '无访问权限，请检查会员或授权范围',
                  429: '请求过于频繁，请稍后再试'}
        if provider=='gemini':
            labels.update({400:'Gemini 请求无效，请核对模型 ID 和参数',403:'Gemini 无访问权限，请检查 API Key、项目和地区',404:'Gemini 模型不存在或当前 Key 不可用',429:'Gemini 额度或速率受限，请检查项目配额后重试'})
        if e.code == 429 and url.startswith('https://api.openai.com/'):
            try:
                error=json.loads(e.read(16384)).get('error',{})
                if error.get('code')=='insufficient_quota' or error.get('type')=='insufficient_quota':
                    labels[429]='OpenAI API 额度不足，请检查账户余额和账单设置'
            except (ValueError,AttributeError):pass
        if is_ai:
            save(ai_status,{'ok':False,'checked_at':time.time(),'message':labels.get(e.code,'模型请求失败，请检查设置或稍后重试')})
        raise AppError(f'接口 HTTP {e.code}：{labels.get(e.code, "请求失败，请稍后重试")}。') from None
    except (urllib.error.URLError, TimeoutError):
        raise AppError('无法连接服务，请检查网络后重试。') from None
    except (ValueError, gzip.BadGzipFile):
        raise AppError('接口未返回有效 JSON 数据。') from None


def xunji(d):
    path = DATA / 'xunji' / (d + '.json')
    cached = load(path)
    age = time.time() - cached.get('fetched_at', 0)
    # Old dates remain cached for 24h; recent dates refresh after 5 minutes.
    ttl = 300 if d >= (today() - dt.timedelta(days=2)).isoformat() else 86400
    if cached and age < ttl:
        return cached['data']
    key = settings().get('xunji_key')
    if not key:
        raise AppError('请先配置训记 API Key。')
    result = request_json('https://trains.xunjiapp.cn/api_trains_for_llm_v2',
                          {'schema_version': 'train_open_api_v2', 'datestr': d,
                           'include_full_data': True}, key)
    res = result.get('res') if isinstance(result, dict) else None
    if result.get('success') is False or not isinstance(res, (dict, list)):
        raise AppError('训记读取失败：请检查 API Key、会员权限或稍后重试。')
    if isinstance(res, list) and any(not isinstance(t, dict) for t in res):
        raise AppError('训记返回了旧版记录格式，请更新 App 并重新导出接入说明。')
    if isinstance(res, dict) and not isinstance(res.get('trains'), list):
        raise AppError('训记记录结构不符合 v2 格式，尚未覆盖现有缓存。')
    save(path, {'fetched_at': time.time(), 'data': result})
    return result


def oura_token():
    with LOCK:
        s = settings()
        tokens = s.get('oura_tokens', {})
        if not tokens.get('access_token'):
            raise AppError('请先连接 Oura。')
        if tokens.get('expires_at', 0) > time.time() + 120:
            return tokens['access_token']
        result = request_json('https://api.ouraring.com/oauth/token', {
            'grant_type': 'refresh_token', 'refresh_token': tokens.get('refresh_token', ''),
            'client_id': s.get('oura_client_id', ''), 'client_secret': s.get('oura_client_secret', '')}, form=True)
        store_tokens(result)
        return result['access_token']


def store_tokens(tokens):
    if not tokens.get('access_token') or not tokens.get('refresh_token'):
        raise AppError('Oura 授权没有返回完整令牌，请重新连接。')
    tokens['expires_at'] = time.time() + int(tokens.get('expires_in', 3600))
    update_settings({'oura_tokens': tokens})


def fetch_oura(start, end):
    token = oura_token()
    for collection in ('sleep', 'daily_sleep', 'daily_readiness', 'daily_activity'):
        records, cursor, seen = [], None, set()
        for _ in range(100):
            params = {'start_date': start, 'end_date': end}
            if cursor:
                params['next_token'] = cursor
            result = request_json('https://api.ouraring.com/v2/usercollection/' + collection + '?' +
                                  urllib.parse.urlencode(params), token=token)
            if not isinstance(result.get('data'), list):
                raise AppError('Oura 返回了无法识别的数据格式。')
            records.extend(result['data'])
            cursor = result.get('next_token')
            if not cursor:
                break
            if cursor in seen:
                raise AppError('Oura 分页游标重复，请稍后重试。')
            seen.add(cursor)
        else:
            raise AppError('Oura 分页超出限制。')
        old = load(DATA / 'oura' / (collection + '.json'), {'data': []})
        retained = [r for r in old['data'] if not start <= r.get('day', '') < end]
        save(DATA / 'oura' / (collection + '.json'),
             {'fetched_at': time.time(), 'data': retained + records})


def sync(days=7, claimed=False):
    global JOB
    days = int(days)
    if not 1 <= days <= 28:
        raise AppError('同步范围须为 1–28 天。')
    with LOCK:
        if JOB['running'] and not claimed:
            raise AppError('已有同步任务正在运行。')
        JOB = {'running': True, 'message': '开始同步…', 'errors': [], 'completed': 0, 'total': days}
    try:
        for offset in range(days):
            d = (today() - dt.timedelta(days=offset)).isoformat()
            JOB['message'] = f'读取训记 {d}（{offset + 1}/{days}）'
            try:
                xunji(d)
            except AppError as e:
                JOB['errors'].append(f'{d}：{e}')
                # Avoid repeating authentication/network failures for every date.
                break
            JOB['completed'] = offset + 1
        if settings().get('oura_tokens'):
            JOB['message'] = '读取 Oura 睡眠与恢复…'
            try:
                fetch_oura((today() - dt.timedelta(days=days - 1)).isoformat(),
                           (today() + dt.timedelta(days=1)).isoformat())
            except AppError as e:
                JOB['errors'].append(str(e))
        JOB['message'] = '同步完成' if not JOB['errors'] else '同步结束，部分来源未成功'
    except Exception:
        JOB['errors'].append('同步意外中断，请重试。')
    finally:
        JOB['running'] = False
        try:
            run_coach()
        except Exception:
            JOB['errors'].append('数据同步已结束，但教练评估更新失败，请在面板重试。')
        save(DATA / 'last-sync.json', {**JOB, 'at': dt.datetime.now(TZ).isoformat()})


def number(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def completed(v):
    return v is True or v == 1 or isinstance(v, str) and v.lower() in ('true', '1')


def normalize_training(raw, d):
    res = raw.get('res', {})
    trains = res.get('trains', []) if isinstance(res, dict) else res
    sessions = []
    for t in trains:
        moves = []
        for m in t.get('movements', []):
            flattened = {}
            for s in m.get('sets', []):
                if s.get('items'):
                    children = [(i.get('name', '未命名动作'), i.get('set', {})) for i in s['items']]
                else:
                    children = [(m.get('name', '未命名动作'), s)]
                for name, item in children:
                    target = flattened.setdefault(name, [])
                    target.append(item)
                    for drop in item.get('dropSets', []):
                        target.append({**drop, 'done': drop.get('done', item.get('done')),
                                       'unit': drop.get('unit', item.get('unit', 'kg'))})
            if not flattened:
                flattened[m.get('name', '未命名动作')] = []
            for name, rows in flattened.items():
                sets = []
                for s in rows:
                    unit = str(s.get('unit', 'kg')).lower()
                    w = number(s.get('weight_kg', s.get('weight')))
                    if w is not None and 'weight_kg' not in s:
                        w = w * 0.45359237 if unit in ('lb', 'lbs', '磅') else w if unit in ('kg', '公斤', '千克') else None
                    rpe = number(s.get('rpe'))
                    sets.append({'done': completed(s.get('done')), 'warmup': s.get('setType') in ('热', 'warmup'),
                                 'weight_kg': w, 'reps': number(s.get('reps')),
                                 'rpe': rpe if rpe is not None and 6 <= rpe <= 10 else None})
                moves.append({'name': name, 'sets': sets})
        sessions.append({'date': d, 'title': t.get('title') or '训练记录', 'movements': moves})
    return sessions


def training_data():
    result, dates = [], []
    for p in sorted((DATA / 'xunji').glob('*.json')):
        cached = load(p)
        result.extend(normalize_training(cached['data'], p.stem))
        dates.append(p.stem)
    return result, dates


def totals(sessions):
    working = [s for t in sessions for m in t['movements'] for s in m['sets'] if s['done'] and not s['warmup']]
    rpes = [s['rpe'] for s in working if s['rpe'] is not None]
    volume = sum(s['weight_kg'] * s['reps'] for s in working
                 if s['weight_kg'] is not None and s['reps'] is not None)
    return {'sessions': len(sessions), 'sets': len(working), 'volume_kg': round(volume, 1),
            'rpe': round(statistics.mean(rpes), 1) if rpes else None, 'rpe_count': len(rpes)}


def recovery_data():
    merged = {}
    for collection in ('daily_sleep', 'daily_readiness', 'daily_activity', 'sleep'):
        cached = load(DATA / 'oura' / (collection + '.json'), {'data': []})
        data = cached['data']
        if collection == 'sleep':
            grouped = {}
            for r in data:
                d = r.get('day')
                if d:grouped.setdefault(d, []).append(r)
            selected=[]
            for d, rows in grouped.items():
                # An unfinished ordinary sleep record must never stand in for the main night.
                main=[r for r in rows if r.get('type')=='long_sleep']
                # Legacy/imported rows without type are usable only with a daily sleep summary.
                if not main and merged.get(d,{}).get('sleep_score') is not None:
                    main=[r for r in rows if not r.get('type')]
                dest=merged.setdefault(d,{'date':d})
                dest['sleep_status']='main_record' if main else 'pending_main'
                dest['sleep_synced_at']=cached.get('fetched_at')
                if main:
                    selected.append(max(main,key=lambda r:number(r.get('total_sleep_duration')) or 0))
                else:
                    partial=max((number(r.get('total_sleep_duration')) or 0 for r in rows),default=0)
                    dest.update(sleep_hours=None,hrv=None,rhr=None,partial_sleep_hours=round(partial/3600,2))
            data=selected
        for r in data:
            d = r.get('day')
            if not d:
                continue
            dest = merged.setdefault(d, {'date': d})
            if collection == 'daily_sleep':
                dest['sleep_score'] = number(r.get('score'))
                dest['sleep_contributors'] = r.get('contributors', {})
            elif collection == 'daily_readiness':
                dest['readiness'] = number(r.get('score'))
                dest['readiness_contributors'] = r.get('contributors', {})
                dest['temperature_deviation'] = number(r.get('temperature_deviation'))
                dest['temperature_trend_deviation'] = number(r.get('temperature_trend_deviation'))
            elif collection == 'daily_activity':
                dest['activity'] = {k:r.get(k) for k in ('score','steps','sedentary_time','low_activity_time','medium_activity_time','high_activity_time','contributors')}
            else:
                duration = number(r.get('total_sleep_duration'))
                dest.update({'sleep_hours': round(duration / 3600, 2) if duration is not None else None,
                             'hrv': number(r.get('average_hrv')),
                             'average_heart_rate': number(r.get('average_heart_rate')),
                             'respiratory_rate': number(r.get('average_breath')),
                             'sleep_efficiency': number(r.get('efficiency')),
                             'rhr': number(r.get('lowest_heart_rate')),
                             'bedtime_start':r.get('bedtime_start'),'bedtime_end':r.get('bedtime_end')})
    return merged


def exercise_comparisons(sessions, last_date, last_sessions):
    comparisons = []
    for t in last_sessions:
        for m in t['movements']:
            work = [s for s in m['sets'] if s['done'] and not s['warmup']]
            if not work:
                continue
            previous = [(other['date'], move) for other in sessions if other['date'] < last_date
                        for move in other['movements'] if move['name'] == m['name']]
            if not previous:
                continue
            old_date, old = max(previous, key=lambda x: x[0])
            old_work = [s for s in old['sets'] if s['done'] and not s['warmup']]
            measured = [s for s in work if s['weight_kg'] is not None and s['reps'] is not None]
            row = {'name': m['name'], 'previous_date': old_date,
                   'current_sets': len(work), 'previous_sets': len(old_work), 'same_load': None}
            if measured:
                top = max(measured, key=lambda s: (s['weight_kg'], s['reps']))
                same = [s for s in old_work if s['weight_kg'] is not None and s['reps'] is not None
                        and abs(s['weight_kg'] - top['weight_kg']) < 0.01]
                if same:
                    old_best = max(s['reps'] for s in same)
                    row['same_load'] = {'weight_kg': round(top['weight_kg'], 1),
                                        'current_reps': top['reps'], 'previous_reps': old_best}
            comparisons.append(row)
    return comparisons


def day_context(d, sessions, fetched, check):
    plan = check.get('plan', 'undecided')
    recorded = any(t['date'] == d for t in sessions)
    synced = d in fetched
    mode = 'training' if recorded or plan == 'train' else 'recovery' if synced or plan == 'rest' else 'unknown'
    labels = {'training': '训练日', 'recovery': '休息／停练观察', 'unknown': '数据待补齐'}
    if recorded:
        reason = '本日已有训练记录，以记录回顾动作表现与训练量。'
        if plan == 'rest':
            reason += '你选择了休息，但本日有训练记录，请核对计划与实际安排。'
    elif plan == 'train':
        reason = '你计划训练；本日尚无训练记录，计划不代表已经完成训练。'
    elif plan == 'rest':
        reason = '你计划休息，重点回顾睡眠与恢复趋势。'
    elif synced:
        reason = '本日已读取，暂无训练记录；今日计划未决定，先查看恢复趋势。'
    else:
        reason = '本日训练数据未读取，不能据此判断是否休息。'
    return {'mode': mode, 'label': labels[mode], 'plan': plan, 'has_record': recorded,
            'synced': synced, 'reason': reason}


def recovery_trends(recovery, date):
    result = {}
    for key in ('sleep_hours', 'hrv', 'rhr'):
        windows = []
        for start, end in ((6, 0), (13, 7)):
            low, high = (date - dt.timedelta(days=start)).isoformat(), (date - dt.timedelta(days=end)).isoformat()
            vals = [v[key] for d, v in recovery.items() if low <= d <= high and v.get(key) is not None]
            windows.append({'n': len(vals), 'value': round(statistics.median(vals), 2) if len(vals) >= 3 else None})
        result[key] = {'recent': windows[0], 'previous': windows[1]}
    return result


def save_checkin(body):
    d = day(body.get('date'))
    energy, soreness = int(body.get('energy')), int(body.get('soreness'))
    if not (1 <= energy <= 5 and 0 <= soreness <= 5):
        raise AppError('评分超出范围。')
    plan = body.get('plan', 'undecided')
    if plan not in ('train', 'rest', 'undecided'):
        raise AppError('今日计划无效。')
    local_soreness = body.get('muscle_soreness')
    if local_soreness is not None:
        if not isinstance(local_soreness, dict) or any(k not in muscles.GROUPS or isinstance(v, bool)
            or not isinstance(v, int) or not 0 <= v <= 5 for k, v in local_soreness.items()):
            raise AppError('肌群酸痛必须为 0–5 的整数，未填的肌群请留空。')
    with LOCK:
        checks = load(DATA / 'checkins.json')
        # Preserve any existing diary fields as the format evolves.
        checks[d] = {**checks.get(d, {}), 'energy': energy, 'soreness': soreness,
                     'note': str(body.get('note', ''))[:1000], 'plan': plan}
        if local_soreness is not None:
            checks[d]['muscle_soreness'] = local_soreness
        save(DATA / 'checkins.json', checks)


def save_muscle_config(body):
    with LOCK:
        config = load(DATA / 'muscles.json')
        if 'half_life_days' in body:
            days = body['half_life_days']
            if isinstance(days, bool) or days not in (1, 2, 3, 4):
                raise AppError('半衰期假设请选择 1–4 天。')
            config['half_life_days'] = int(days)
        if 'name' in body:
            name = str(body['name']).strip()
            if not name or len(name) > 200:
                raise AppError('动作名称无效。')
            mappings = dict(config.get('exercises', {}))
            if body.get('reset') is True:
                mappings.pop(name, None)
            else:
                try:
                    mappings[name] = muscles.validate_mapping(body)
                except ValueError as e:
                    raise AppError(str(e)) from None
            config['exercises'] = mappings
        save(DATA / 'muscles.json', config)


def run_coach(d=None):
    d = day(d or today().isoformat())
    with LOCK:
        sessions, fetched = training_data()
        state = coach.run(d, sessions, fetched, load(DATA/'muscles.json'),
                          load(DATA/'coach-profile.json'), load(DATA/'feedback.json', []),
                          load(DATA/'checkins.json'), load(DATA/'coach-state.json'))
        save(DATA/'coach-state.json', state)
        return state


def coach_view(d):
    state = load(DATA/'coach-state.json')
    limit = (dt.date.fromisoformat(d)+dt.timedelta(days=6)).isoformat()
    plans = {k:v for k,v in state.get('plans',{}).items()
             if (dt.date.fromisoformat(d)-dt.timedelta(days=7)).isoformat()<=k<=limit
             and v.get('revised_on',v.get('created_on',d))<=d}
    return {'profile':coach.profile(load(DATA/'coach-profile.json')), 'plans':plans,
            'calibration_status':state.get('calibration_status',{}) if state.get('last_run','')<=d else {},
            'events':[e for e in state.get('events',[]) if e['date']<=d][-12:],
            'feedback_dates':sorted({f['date'] for f in load(DATA/'feedback.json',[]) if f['date']<=d}),
            'last_run':state.get('last_run'),
            'feedback_day':[f for f in load(DATA/'feedback.json',[]) if f['date']==d]}


def coach_action(body):
    action=body.get('action')
    with LOCK:
        if action=='profile':
            p=coach.profile({**load(DATA/'coach-profile.json'),**body.get('profile',{}),'confirmed':True})
            save(DATA/'coach-profile.json',p)
        elif action=='feedback':
            f=coach.validate_feedback(body)
            if f['date']>today().isoformat():
                raise AppError('不能保存未来日期的实际训练反馈。')
            rows=load(DATA/'feedback.json',[])
            rows=[r for r in rows if (r['date'],r['phase'])!=(f['date'],f['phase'])]+[f]
            save(DATA/'feedback.json',rows)
        elif action=='plan_status':
            state=load(DATA/'coach-state.json')
            d=day(body.get('date'))
            p=state.get('plans',{}).get(d)
            if not p:raise AppError('该日期还没有计划。')
            if body.get('version')!=p['version']:raise AppError('计划已更新，请刷新后再操作。')
            status=body.get('status')
            if status not in ('accepted','completed','skipped','accept_revision'):
                raise AppError('计划状态无效。')
            if status=='completed' and d>today().isoformat():raise AppError('未来计划不能标记已完成。')
            if status=='accept_revision':
                if not p.get('revision_proposal'):raise AppError('暂无修订草案。')
                if p['revision_proposal'].get('origin')=='agent_analysis':
                    record=current_decision(p['revision_proposal']['analysis_date'])
                    if not record or record['stale'] or record['data_hash']!=p['revision_proposal']['analysis_hash']:
                        raise AppError('AI 修订所依据的数据已变化，请重新分析。')
                if p['revision_proposal']['kind']=='review':raise AppError('修订仍待核对，暂不能接受为训练计划。')
                p={**p['revision_proposal'],'status':'accepted','version':p['version']+1,
                   'created_on':p.get('created_on',today().isoformat()),'revised_on':today().isoformat()}
            else:
                if status=='accepted' and p['kind']=='review':raise AppError('请先核对限制或动作归属，再生成可执行草案。')
                p={**p,'status':status,'version':p['version']+1}
            state['plans'][d]=p
            state.setdefault('events',[]).append({'date':today().isoformat(),'type':'user','message':d+' 计划状态：'+p['status']})
            save(DATA/'coach-state.json',state)
        elif action!='run':
            raise AppError('教练操作无效。')
        run_coach()


def report(d):
    date = dt.date.fromisoformat(d)
    sessions, fetched = training_data()
    recent = [t for t in sessions if (date - dt.timedelta(days=6)).isoformat() <= t['date'] <= d]
    last = [t for t in sessions if t['date'] <= d]
    last_date = max((t['date'] for t in last), default=None)
    last_sessions = [t for t in last if t['date'] == last_date]
    recovery = recovery_data()
    current = recovery.get(d, {'date': d})
    baseline = [v for k, v in recovery.items() if (date - dt.timedelta(days=28)).isoformat() <= k < d]
    baselines = {}
    for metric in ('sleep_hours', 'hrv', 'rhr', 'average_heart_rate', 'respiratory_rate', 'temperature_deviation'):
        vals = [v[metric] for v in baseline if v.get(metric) is not None]
        baselines[metric] = {'value': round(statistics.median(vals), 2) if len(vals) >= 7 else None,
                             'n': len(vals)}
    week = totals(recent)
    notes = []
    if last_date:
        last_total = totals(last_sessions)
        notes.append(f'最近一次训练为 {last_date}，记录了 {last_total["sets"]} 个已完成正式组。')
    else:
        notes.append('尚无所选日期及之前的训练记录，请先同步训记。')
    if current.get('sleep_hours') is not None:
        b = baselines['sleep_hours']['value']
        notes.append(f'本日主睡眠 {current["sleep_hours"]:.1f} 小时。' +
                     (f'相对过去 28 天中位数变化 {(current["sleep_hours"]-b)*60:+.0f} 分钟。' if b is not None else '历史样本不足 7 晚，暂不比较个人基线。'))
    else:
        notes.append('本日 Oura 仅有未识别为主睡眠的片段，等待完整主睡眠；片段时长和心率不用于整晚恢复分析。' if current.get('sleep_status')=='pending_main' else '本日 Oura 主睡眠数据尚未同步，暂不能给出联合恢复分析。')
    for metric, label, unit in (('hrv', 'HRV', 'ms'), ('rhr', '夜间最低静息心率', 'bpm')):
        v, b = current.get(metric), baselines[metric]['value']
        if v is not None:
            notes.append(f'{label} {v:g} {unit}；' + (f'个人基线 {b:g} {unit}。' if b is not None else '基线样本不足。'))
    coverage = sum((date - dt.timedelta(days=i)).isoformat() in fetched for i in range(7))
    if coverage < 7:
        notes.append(f'近 7 天仅有 {coverage} 天成功读取，未读取日期不能视为休息日。')
    for p in (DATA / 'xunji').glob('*.json'):
        if not (date - dt.timedelta(days=27)).isoformat() <= p.stem <= d:
            continue
        res = load(p)['data'].get('res', {})
        rows = res.get('trains', []) if isinstance(res, dict) else res
        if any(t.get('truncated') or any(m.get('truncated') for m in t.get('movements', [])) for t in rows):
            notes.append('部分训记记录被接口截断，组数统计可能不完整。')
            break
    check = load(DATA / 'checkins.json').get(d, {})
    context = day_context(d, sessions, fetched, check)
    notes.insert(0, context['reason'])
    gap = (date - dt.date.fromisoformat(last_date)).days if last_date else None
    if gap is not None and gap > 0:
        notes.append(f'距最近一次训练记录 {gap} 天；间隔天数不代表已经充分恢复。')
    if context['mode'] == 'training':
        focus = '结合今日计划，记录精神、酸痛与第一组的实际表现；训练后核对本次与上次同动作的差异。'
    elif context['mode'] == 'recovery':
        focus = '记录今天的精神与酸痛，观察睡眠、HRV 和夜间心率的连续变化；准备回归训练时，再结合你的计划与实际感受。'
    else:
        focus = '先补齐本日训练数据或选择今日计划，再结合主观感受回顾恢复趋势。'
    if not settings().get('oura_tokens'):
        focus = '先连接 Oura 并同步数据，建立训练与睡眠恢复的共同记录。'
    result = {'date': d, 'generated_at': dt.datetime.now(TZ).isoformat(), 'timezone': str(TZ),
              'week': week, 'coverage': coverage, 'recovery': current, 'baseline': baselines,
              'last_date': last_date, 'last_sessions': last_sessions, 'checkin': check,
              'day_context': context, 'days_since_training': gap,
              'trends': recovery_trends(recovery, date),
              'muscle_load': muscles.model(sessions, fetched, d,
                  coach.personalized_config(load(DATA/'muscles.json'),load(DATA/'coach-state.json').get('calibrations',[]),d), check.get('muscle_soreness', {})),
              'coach_agent':coach_view(d),
              'comparisons': exercise_comparisons(sessions, last_date, last_sessions),
              'observations': notes, 'focus': focus,
              'limits': '基线使用所选日期之前 28 天的中位数，至少需 7 个有效夜晚。正式组只计已完成且非热身组；递减组子组单独计数。负重总量仅供日志核对，不代表肌肉刺激或不同动作间的可比训练负荷。恢复指标不能判断某块肌肉是否恢复。教练自动生成草案，已接受计划的变化另列修订提案。'}
    result['health_observations'] = health_context(d)
    result['decision'] = current_decision(d, result)
    return result


def markdown(r):
    plans = {'train': '训练', 'rest': '休息', 'undecided': '未决定'}
    lines = [f'# 训练与恢复日报 · {r["date"]}', '', f'生成时间：{r["generated_at"]}',
             f'日报模式：{r["day_context"]["label"]}；当日计划：{plans[r["day_context"]["plan"]]}', '', '## 观察', '']
    lines.extend('- ' + n for n in r['observations'])
    lines += ['', '## 近 7 天训练', '', f'训练记录 {r["week"]["sessions"]} 次；正式组 {r["week"]["sets"]} 组；成功读取 {r["coverage"]}/7 天。',
              '', '## 今日关注', '', r['focus'], '', '## 数据口径', '', r['limits']]
    lines += ['', '## 恢复趋势', '', '最近 7 天与此前 7 天分别取中位数，每段至少需 3 个有效夜晚。', '']
    for key, label, unit in (('sleep_hours', '主睡眠', '小时'), ('hrv', 'HRV', 'ms'), ('rhr', '夜间最低心率', 'bpm')):
        recent, previous = r['trends'][key]['recent'], r['trends'][key]['previous']
        if recent['value'] is not None and previous['value'] is not None:
            lines.append(f'- {label}：{previous["value"]:g} → {recent["value"]:g} {unit}（此前 {previous["n"]} 晚，最近 {recent["n"]} 晚）。')
        else:
            lines.append(f'- {label}：样本不足（最近 {recent["n"]} 晚，此前 {previous["n"]} 晚）。')
    if r['checkin']:
        lines += ['', '## 主观记录', '', f'精神：{r["checkin"].get("energy", "未填")} / 5；酸痛：{r["checkin"].get("soreness", "未填")} / 5。', r['checkin'].get('note', '')]
    if r['comparisons']:
        lines += ['', '## 与上次同动作比较', '']
        for c in r['comparisons']:
            s = c['same_load']
            detail = (f'同负重 {s["weight_kg"]:g} kg 的最佳次数 {s["previous_reps"]:g} → {s["current_reps"]:g}。' if s else '无相同负重的次数可比记录。')
            lines.append(f'- {c["name"]}：对比 {c["previous_date"]}，正式组 {c["previous_sets"]} → {c["current_sets"]}；{detail}')
    return decision.markdown(r.get('decision')) + '\n\n' + '\n'.join(lines) + muscles.markdown(r['muscle_load']) + coach.plan_markdown(r['coach_agent'],r['date'])


def health_context(d):
    low=(dt.date.fromisoformat(d)-dt.timedelta(days=27)).isoformat()
    return {'history':[v for date,v in sorted(load(DATA/'health-context.json').items()) if low<=date<=d],
            'availability':{'cycle':'当前同步接口未提供周期阶段；用户确认的信息独立保存，不从体温推算。',
                            'strain':'Symptom Radar 等级来自用户在 Oura 界面的报告，未由当前接口验证。'}}


def save_health(body):
    d=day(body.get('date'))
    if d>today().isoformat():raise AppError('不能记录未来的实际身体状态。')
    strain=body.get('strain','unknown');cycle=body.get('cycle','unknown')
    if strain not in ('unknown','none','minor','major') or cycle not in ('unknown','menstrual','recently_ended','premenstrual','other'):
        raise AppError('身体状态选项无效。')
    symptoms=body.get('symptoms','')
    if not isinstance(symptoms,str) or len(symptoms)>1000:raise AppError('症状说明过长。')
    rows=load(DATA/'health-context.json')
    rows[d]={'date':d,'strain':strain,'cycle':cycle,'symptoms':symptoms,'source':'user_report','updated_at':dt.datetime.now(TZ).isoformat()}
    save(DATA/'health-context.json',rows)


def analysis_context(d, r=None):
    sessions,fetched=training_data()
    return decision.context(r or report(d),recovery_data(),sessions,fetched,load(DATA/'feedback.json',[]))


def current_decision(d, r=None):
    record=load(DATA/'decisions'/(d+'.json'))
    if not record:return None
    # Pass the report under construction to avoid report/context recursion.
    record['stale']=record['data_hash']!=decision.fingerprint(analysis_context(d,r))
    return record


def store_decision(d, value, expected_hash, source='Codex chat'):
    with LOCK:
        ctx=analysis_context(d)
        if decision.fingerprint(ctx)!=expected_hash:raise AppError('分析期间数据或计划已变化，请重新分析。')
        decision.validate(value,ctx)
        record={'date':d,'analysis':value,'data_hash':expected_hash,'source':source,'created_at':dt.datetime.now(TZ).isoformat(),'stale':False}
        save(DATA/'decisions'/(d+'.json'),record)
        return record


def propose_decision(d):
    with LOCK:
        record=current_decision(d)
        if not record or record['stale']:raise AppError('AI 分析缺失或已过期，请先重新生成。')
        change=record['analysis']['adjustment']
        if not change:raise AppError('本次分析没有可提交的动作修订。')
        state=load(DATA/'coach-state.json');old=state['plans'][change['date']]
        if old['version']!=change['version']:raise AppError('计划版本已变化。')
        proposed={**old,'kind':change['kind'],'origin':'agent_analysis','analysis_date':d,'analysis_hash':record['data_hash'],
                  'reasons':[record['analysis']['headline']],'status':'draft'}
        proposed.pop('revision_proposal',None)
        previous={e['name']:e for e in old['exercises']}
        proposed['exercises']=[{**previous[e['name']],**e} for e in change['exercises']]
        old['revision_proposal']=proposed
        save(DATA/'coach-state.json',state)


def ai_report(d):
    c=providers.require(sys.modules[__name__])
    r = report(d)
    if not r['last_sessions'] and all(r['recovery'].get(k) is None for k in ('sleep_hours','hrv','rhr','sleep_score','readiness')):
        raise AppError('请先同步训练或 Oura 数据，再生成 AI 解读。')
    ctx = analysis_context(d, r)
    output=providers.complete(sys.modules[__name__],c,decision.PROMPT,json.dumps(ctx,ensure_ascii=False),decision.SCHEMA)
    try:value=json.loads(output)
    except (ValueError,TypeError):raise AppError('模型未返回有效决策，原计划未修改。') from None
    record=store_decision(d,value,decision.fingerprint(ctx),c['label']+' / '+c['model'])
    result={'date':d,'text':decision.markdown(record),'generated_at':time.time(),'model':c['model']}
    save(DATA/'reports'/(d+'.json'),result)
    return result



class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # OAuth query strings and health data never enter request logs.

    def reply(self, value, status=200, mime='application/json; charset=utf-8'):
        body = json.dumps(value, ensure_ascii=False).encode() if mime.startswith('application/json') else value.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, url):
        self.send_response(303)
        self.send_header('Location', url)
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def allowed(self):
        return cloud.allowed(self.headers, PORT, PUBLIC_URL, PROXY_TOKEN)

    def do_GET(self):
        if not self.allowed():
            return self.reply({'error': '不允许的主机'}, 403)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        p = parsed.path
        try:
            if p == '/':
                self.reply((ROOT / 'static/index.html').read_text().replace('__NONCE__', NONCE), mime='text/html; charset=utf-8')
            elif p in ('/app.js', '/style.css'):
                self.reply((ROOT / 'static' / p[1:]).read_text(), mime='text/javascript' if p.endswith('.js') else 'text/css')
            elif p == '/api/status':
                s = settings()
                _, dates = training_data()
                self.reply({'today': today().isoformat(), 'timezone': str(TZ), 'xunji': bool(s.get('xunji_key')),
                            'oura': bool(s.get('oura_tokens')), 'oura_configured': bool(s.get('oura_client_id') and s.get('oura_client_secret')),
                            'ai':providers.ready(sys.modules[__name__]),'model':providers.config(sys.modules[__name__])['model'],
                            'ai_provider':s.get('ai_provider','openai'),'ai_models':{k:s.get(k+'_model','') for k in ('openai','gemini')},
                            'gemini_paid_confirmed':s.get('gemini_paid_confirmed') is True,
                            'dates': dates, 'job': JOB if JOB['running'] or JOB['message'] != '尚未同步' else load(DATA / 'last-sync.json', {'running': False, 'message': '本地缓存已就绪', 'errors': []}), 'redirect_uri': redirect_uri()})
            elif p in ('/api/report', '/api/export', '/api/ai', '/api/coach', '/api/chat'):
                d = day(params.get('date', [today().isoformat()])[0])
                if p == '/api/report':
                    self.reply(report(d))
                elif p == '/api/chat':
                    self.reply(chat.view(sys.modules[__name__],d))
                elif p == '/api/coach':
                    self.reply(coach_view(d))
                elif p == '/api/ai':
                    self.reply(load(DATA / 'reports' / (d + '.json'), {'text': ''}))
                else:
                    self.reply(markdown(report(d)), mime='text/markdown; charset=utf-8')
            elif p == '/oauth/callback':
                state = params.get('state', [''])[0]
                entry = OAUTH.pop(state, None)
                if not entry or time.time() - entry['time'] > 600:
                    raise AppError('授权校验失败或已超时，请重新连接。')
                if params.get('error'):
                    raise AppError('你取消了 Oura 授权，可稍后重新连接。')
                code = params.get('code', [''])[0]
                if not code:
                    raise AppError('缺少授权码。')
                s = settings()
                tokens = request_json('https://api.ouraring.com/oauth/token', {
                    'grant_type': 'authorization_code', 'code': code, 'client_id': s['oura_client_id'],
                    'client_secret': s['oura_client_secret'], 'redirect_uri': redirect_uri(),
                    'code_verifier': entry['verifier']}, form=True)
                store_tokens(tokens)
                self.redirect('/?connected=oura')
            else:
                self.reply({'error': '页面不存在'}, 404)
        except (AppError, ValueError) as e:
            self.reply({'error': str(e)}, 400)
        except Exception:
            self.reply({'error': '操作失败，请检查本地数据或重试。'}, 500)

    def do_POST(self):
        global JOB
        if not self.allowed() or not secrets.compare_digest(self.headers.get('X-Iron-Token', ''), NONCE):
            return self.reply({'error': '请求校验失败，请刷新页面'}, 403)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 100_000:
                raise AppError('请求大小无效。')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise AppError('请求格式无效。')
            p = urllib.parse.urlparse(self.path).path
            if p == '/api/settings':
                if JOB['running']:
                    raise AppError('请等同步完成后再更改连接设置。')
                values = {k: str(body[k]).strip() for k in ('xunji_key', 'oura_client_id', 'oura_client_secret', 'openai_key', 'openai_model','gemini_key','gemini_model','ai_provider') if body.get(k)}
                if 'ai_provider' in values and values['ai_provider'] not in providers.LABELS:raise AppError('AI 提供商无效。')
                if 'gemini_paid_confirmed' in body:values['gemini_paid_confirmed']=body['gemini_paid_confirmed'] is True
                s = settings()
                if values.get('gemini_key') and values['gemini_key']!=s.get('gemini_key'):
                    values['gemini_paid_confirmed']=body.get('gemini_paid_confirmed') is True
                if any(k in values and values[k] != s.get(k) for k in ('oura_client_id', 'oura_client_secret')):
                    values['oura_tokens'] = {}
                update_settings(values)
                self.reply({'ok': True})
            elif p == '/api/sync':
                count = int(body.get('days', 7))
                if not 1 <= count <= 28:
                    raise AppError('同步范围须为 1–28 天。')
                with LOCK:
                    if JOB['running']:
                        raise AppError('已有同步任务正在运行。')
                    JOB = {'running': True, 'message': '开始同步…', 'errors': []}
                    threading.Thread(target=sync, args=(count, True), daemon=True).start()
                self.reply({'ok': True})
            elif p == '/api/health':
                save_health(body)
                self.reply({'ok':True})
            elif p == '/api/decision/apply':
                propose_decision(day(body.get('date')))
                self.reply({'ok':True})
            elif p == '/api/checkin':
                save_checkin(body)
                run_coach()
                self.reply({'ok': True})
            elif p == '/api/muscles':
                save_muscle_config(body)
                run_coach()
                self.reply({'ok': True})
            elif p == '/api/coach':
                coach_action(body)
                self.reply({'ok':True})
            elif p == '/api/oura/connect':
                s = settings()
                if not s.get('oura_client_id') or not s.get('oura_client_secret'):
                    raise AppError('请先填写 Oura Client ID 和 Client Secret。')
                state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
                OAUTH.clear()
                OAUTH[state] = {'time': time.time(), 'verifier': verifier}
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                self.reply({'url': 'https://cloud.ouraring.com/oauth/authorize?' + urllib.parse.urlencode({
                    'response_type': 'code', 'client_id': s['oura_client_id'],
                    'redirect_uri': redirect_uri(), 'scope': 'daily',
                    'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})})
            elif p == '/api/chat':
                self.reply(chat.send(sys.modules[__name__],body))
            elif p == '/api/chat/new':
                self.reply(chat.new_conversation(sys.modules[__name__],body))
            elif p == '/api/ai':
                if body.get('consent') is not True:
                    raise AppError('请先确认将摘要发送至当前 AI 提供商。')
                if body.get('provider')!=providers.config(sys.modules[__name__])['provider']:raise AppError('AI 提供商已变化，请刷新并重新授权。')
                self.reply(ai_report(day(body.get('date'))))
            else:
                self.reply({'error': '接口不存在'}, 404)
        except (AppError, ValueError, TypeError) as e:
            self.reply({'error': str(e)}, 400)
        except Exception:
            self.reply({'error': '操作失败，请重试。'}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sync', type=int, metavar='DAYS', help='同步最近 1–28 天并退出')
    parser.add_argument('--report', metavar='YYYY-MM-DD', help='打印缓存数据的 Markdown 日报')
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.sync is not None:
        sync(args.sync)
        print(json.dumps(JOB, ensure_ascii=False))
        raise SystemExit(1 if JOB['errors'] else 0)
    if args.report:
        print(markdown(report(day(args.report))))
        return
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    cloud.start(sys.modules[__name__])
    print('Iron / Oura 已启动：' + (PUBLIC_URL or f'http://127.0.0.1:{PORT}'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
