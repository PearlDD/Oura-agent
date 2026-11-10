"""Opt-in cloud boundary and same-process daily runner; local defaults stay local."""
import datetime as dt
import os
import secrets
import threading
import urllib.parse


def public_origin(value):
    if not value:
        return ''
    p = urllib.parse.urlsplit(value)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.path not in ('', '/') or p.query or p.fragment):
        raise ValueError('IRON_PUBLIC_URL 必须是无路径的 HTTPS 域名地址。')
    # Accessing port validates malformed ports too.
    _ = p.port
    return urllib.parse.urlunsplit(('https', p.netloc.lower(), '', '', ''))


def validate(bind, origin, token):
    if origin and len(token) < 32:
        raise ValueError('云端模式需要至少 32 字符的 IRON_PROXY_TOKEN。')
    if bind not in ('127.0.0.1', 'localhost', '::1') and not origin:
        raise ValueError('对外监听必须设置 HTTPS IRON_PUBLIC_URL 和代理密钥。')


def allowed(headers, port, origin, token):
    if origin:
        return (headers.get('Host', '').lower() == urllib.parse.urlsplit(origin).netloc
                and secrets.compare_digest(headers.get('X-Iron-Proxy-Token', ''), token))
    return headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')


TERMINAL = {'running', 'complete', 'failed', 'incomplete'}


def _load_state(app):
    return app.load(app.DATA / 'cloud-runs.json', {})


def view(app):
    now = dt.datetime.now(app.TZ)
    poll = app.load(app.DATA / 'wake-poll.json', {})
    return {'enabled': os.environ.get('IRON_SCHEDULE_ENABLED') == '1',
            'mode': os.environ.get('IRON_SCHEDULE_MODE', 'fixed'),
            'ai_enabled': os.environ.get('IRON_SCHEDULE_AI') == '1',
            'provider': os.environ.get('IRON_SCHEDULE_AI_PROVIDER', ''),
            'today': _load_state(app).get(now.date().isoformat(), {}),
            'poll': {k: poll.get(k) for k in ('checked_at', 'message')},
            'poll_minutes': int(os.environ.get('IRON_WAKE_POLL_SECONDS', '900')) // 60}


def _run_daily(app, now, enforce_hour=True):
    hour = int(os.environ.get('IRON_SCHEDULE_HOUR', '11'))
    if not 0 <= hour <= 23:
        raise ValueError('IRON_SCHEDULE_HOUR 须为 0–23。')
    if enforce_hour and now.hour < hour:
        return False
    d = now.date().isoformat()
    path = app.DATA / 'cloud-runs.json'
    with app.LOCK:
        state = _load_state(app)
        previous = state.get(d, {})
        if previous.get('status') in TERMINAL or app.JOB['running']:
            return False
        state[d] = {**previous, 'status': 'running', 'started_at': now.isoformat(),
                    'attempts': previous.get('attempts', 0) + 1}
        app.save(path, state)
        app.JOB['running'] = True
    status, reason, analysis_ready = 'complete', '', False
    notification = None
    try:
        app.sync(7, claimed=True)
        report = app.report(d)
        ready = (not app.JOB.get('errors') and report['day_context']['synced']
                 and report['recovery'].get('sleep_hours') is not None
                 and bool(app.settings().get('oura_tokens')))
        if not ready:
            status, reason = 'incomplete', '数据未齐或同步失败；未请求 AI，等待手动同步后复核。'
        elif os.environ.get('IRON_SCHEDULE_AI') == '1':
            configured = app.providers.config(app)
            if os.environ.get('IRON_SCHEDULE_AI_PROVIDER') != configured['provider']:
                status, reason = 'incomplete', '定时 AI 提供商未确认；未发送数据。'
            else:
                record = report.get('decision') or {}
                source = configured['label'] + ' / ' + configured['model']
                reused = bool(record and not record.get('stale') and record.get('source') == source)
                if not reused:
                    app.ai_report(d)
                latest = app.report(d).get('decision') or {}
                analysis_ready = bool(latest and not latest.get('stale') and latest.get('source') == source)
                if not analysis_ready:
                    status, reason = 'incomplete', '数据或配置发生变化，请复核并重新生成分析。'
                else:
                    reason = '复用今日已生成的有效 AI 分析。' if reused else '今日 AI 分析已生成。'
        else:
            reason = '仅生成数据报告；定时 AI 未启用。'
    except Exception:
        status, reason = 'failed', '自动分析未完成；请检查模型额度、数据连接或在面板手动重试。'
    finally:
        try:
            import morning_report
            morning_report.generate(cached=False, synchronize=False, runtime=app)
        except Exception:
            status, reason = 'failed', '报告未能完整保存；请在受保护面板检查。'
        if status == 'complete' and analysis_ready:
            try:
                import push
                notification = push.deliver(app, d)
            except Exception:
                notification = {'accepted': 0, 'failed': 1, 'device_count': 0}
        with app.LOCK:
            app.JOB['running'] = False
            state = _load_state(app)
            state[d] = {**state.get(d, {}), 'status': status, 'reason': reason,
                        'notification': notification,
                        'finished_at': dt.datetime.now(app.TZ).isoformat()}
            app.save(path, state)
    return True


def sleep_candidate(report, now):
    """Data readiness proxy, never a physiological awake detector."""
    r = report.get('recovery', {})
    if (r.get('sleep_status') != 'main_record' or r.get('sleep_hours') is None
            or r.get('sleep_score') is None or r.get('readiness') is None):
        return None
    try:
        end = dt.datetime.fromisoformat(r['bedtime_end'])
        if end.tzinfo is None or end.astimezone(now.tzinfo).date() != now.date() or end > now:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    import hashlib
    import json
    keys = ('sleep_hours', 'bedtime_start', 'bedtime_end', 'sleep_score', 'readiness',
            'hrv', 'rhr', 'temperature_deviation', 'respiratory_rate')
    return hashlib.sha256(json.dumps({key: r.get(key) for key in keys}, sort_keys=True).encode()).hexdigest()


def run_wake_due(app, now):
    d, stamp = now.date().isoformat(), now.timestamp()
    interval = max(60, int(os.environ.get('IRON_WAKE_POLL_SECONDS', '900')))
    stable = max(60, int(os.environ.get('IRON_WAKE_STABLE_SECONDS', '900')))
    path = app.DATA / 'wake-poll.json'
    with app.LOCK:
        if _load_state(app).get(d, {}).get('status') in TERMINAL or app.JOB['running']:
            return False
        previous = app.load(path, {})
        if stamp - previous.get('checked_at', 0) < interval:
            return False
        app.save(path, {**previous, 'checked_at': stamp, 'date': d, 'message': '检查 Oura 今日睡眠同步…'})
        app.JOB = {'running': True, 'message': '检查 Oura 今日睡眠同步…', 'errors': []}
    ready = False
    try:
        if not app.settings().get('oura_tokens'):
            raise app.AppError('Oura 尚未授权。')
        # Capture the old identity so a previously fetched, unchanged complete night
        # can establish stability even after a process restart.
        old = app.recovery_data().get(d, {})
        old_candidate = sleep_candidate({'recovery': old}, now)
        app.fetch_oura((now.date() - dt.timedelta(days=1)).isoformat(),
                       (now.date() + dt.timedelta(days=1)).isoformat())
        report = app.report(d)
        candidate = sleep_candidate(report, now)
        first_seen = stamp
        if candidate and candidate == previous.get('candidate') and previous.get('date') == d:
            first_seen = previous.get('first_seen_at', stamp)
        elif candidate and candidate == old_candidate:
            # The existing snapshot was already complete; use its fetch timestamp.
            first_seen = min(stamp, old.get('sleep_synced_at') or stamp)
        ready = bool(candidate and stamp - first_seen >= stable)
        message = ('完整主睡眠与恢复数据已就绪。' if ready else
                   '主睡眠已上传，等待下一次检查确认数据稳定。' if candidate else
                   '等待今天已结束的主睡眠及睡眠/准备度数据；可先打开 Oura App 同步戒指。')
        with app.LOCK:
            app.save(path, {'date': d, 'checked_at': stamp, 'candidate': candidate,
                            'first_seen_at': first_seen, 'message': message})
            state = _load_state(app)
            state[d] = {**state.get(d, {}), 'status': 'waiting_for_sleep', 'reason': message}
            app.save(app.DATA / 'cloud-runs.json', state)
            app.JOB['message'] = message
    except Exception:
        with app.LOCK:
            app.save(path, {**previous, 'date': d, 'checked_at': stamp,
                            'message': 'Oura 检查未完成，稍后重试；不会请求 AI。'})
            app.JOB['message'] = 'Oura 检查未完成，稍后重试；不会请求 AI。'
    finally:
        app.JOB['running'] = False
    if ready:
        return _run_daily(app, now, enforce_hour=False)
    return False


def retry(app):
    d = app.today().isoformat()
    with app.LOCK:
        state = _load_state(app)
        record = state.get(d, {})
        if app.JOB['running'] or record.get('status') not in ('failed', 'incomplete'):
            raise app.AppError('只有失败或未完成的自动分析可以手动重试。')
        record = {**record, 'status': 'waiting_for_sleep',
                  'manual_retries': record.get('manual_retries', 0) + 1,
                  'reason': '已请求重试，将先确认 Oura 数据就绪。'}
        state[d] = record
        app.save(app.DATA / 'cloud-runs.json', state)
        poll = app.load(app.DATA / 'wake-poll.json', {})
        app.save(app.DATA / 'wake-poll.json', {**poll, 'checked_at': 0})
    return {'ok': True}


def run_due(app, now=None):
    now = now or dt.datetime.now(app.TZ)
    if os.environ.get('IRON_SCHEDULE_MODE', 'fixed') == 'wake':
        return run_wake_due(app, now)
    return _run_daily(app, now)


def start(app):
    if os.environ.get('IRON_SCHEDULE_ENABLED') != '1':
        return
    def loop():
        while True:
            try:
                run_due(app)
            except Exception:
                pass
            threading.Event().wait(30)
    threading.Thread(target=loop, name='daily-report', daemon=True).start()
