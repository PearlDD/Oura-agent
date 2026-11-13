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
            'poll': {k: poll.get(k) for k in ('checked_at', 'message', 'date')},
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
    phase = 'sync'
    analyzed_sleep = None
    try:
        app.sync(7, claimed=True)
        report = app.report(d)
        analyzed_sleep = sleep_candidate(report, now)
        ready = (not app.JOB.get('errors') and report['day_context']['synced']
                 and report['recovery'].get('sleep_hours') is not None
                 and bool(app.settings().get('oura_tokens')))
        if not ready:
            status, reason = 'incomplete', '数据未齐或同步失败；未请求 AI，等待手动同步后复核。'
        elif os.environ.get('IRON_SCHEDULE_AI') == '1':
            phase = 'analysis'
            configured = app.providers.config(app)
            if os.environ.get('IRON_SCHEDULE_AI_PROVIDER') != configured['provider']:
                status, reason = 'incomplete', '定时 AI 提供商未确认；未发送数据。'
            else:
                record = report.get('decision') or {}
                source = configured['label'] + ' / ' + configured['model']
                reused = bool(record and not record.get('stale') and record.get('source') == source)
                if not reused:
                    phase = 'analysis'
                    app.ai_report(d)
                latest = app.report(d).get('decision') or {}
                analysis_ready = bool(latest and not latest.get('stale') and latest.get('source') == source)
                if not analysis_ready:
                    status, reason = 'incomplete', '数据或配置发生变化，请复核并重新生成分析。'
                else:
                    reason = '复用今日已生成的有效 AI 分析。' if reused else '今日 AI 分析已生成。'
        else:
            reason = '仅生成数据报告；定时 AI 未启用。'
    except Exception as error:
        status = 'failed'
        reason = failure_reason(error, phase)
    finally:
        try:
            import morning_report
            morning_report.generate(cached=False, synchronize=False, runtime=app)
        except Exception:
            status, reason, phase = 'failed', '报告未能完整保存；请在受保护面板检查。', 'export'
        if status == 'complete' and analysis_ready:
            try:
                import push
                if _load_state(app).get(d, {}).get('sleep_refreshes', 0):
                    notification = push.deliver(app, d, revision=True)
                else:
                    notification = push.deliver(app, d)
            except Exception:
                notification = {'accepted': 0, 'failed': 1, 'device_count': 0}
        if status in ('failed', 'incomplete') and os.environ.get('IRON_SCHEDULE_AI') == '1':
            try:
                import push
                notification = push.deliver(app, d, failure=True)
            except Exception:
                notification = {'accepted': 0, 'failed': 1, 'device_count': 0}
        with app.LOCK:
            app.JOB['running'] = False
            state = _load_state(app)
            state[d] = {**state.get(d, {}), 'status': status, 'reason': reason,
                        'notification': notification, 'analyzed_sleep': analyzed_sleep,
                        'failure_stage': phase if status == 'failed' else None,
                        'finished_at': dt.datetime.now(app.TZ).isoformat()}
            app.save(path, state)
    return True


def failure_reason(error, phase):
    # Never persist raw exceptions: network/provider errors can contain secrets.
    if phase == 'sync':
        return '数据同步阶段失败；未完成今日分析，请核对数据连接。'
    if isinstance(error, ValueError):
        return 'AI 回复未通过证据或计划安全校验，未保存为建议；可手动重试。'
    message = str(error) if type(error).__name__ == 'AppError' else ''
    if '额度不足' in message:
        return 'OpenAI API 额度不足，今日分析未完成；请检查账单后重试。'
    if '数据或计划已变化' in message:
        return '分析期间数据或计划发生变化，结果未保存；请重新分析。'
    if '无法连接服务' in message:
        return 'AI 请求连接失败或超时，结果未保存；请稍后重试。'
    return 'AI 分析或保存阶段失败；未保存有效建议，可在面板重试。'


def reconcile(app, now):
    """Reuse a successful manual analysis without another model request."""
    d = now.date().isoformat()
    with app.LOCK:
        state = _load_state(app)
        previous = state.get(d, {})
        if previous.get('status') not in ('failed', 'incomplete') or app.JOB['running']:
            return False
        configured = app.providers.config(app)
        if (os.environ.get('IRON_SCHEDULE_AI') != '1'
                or os.environ.get('IRON_SCHEDULE_AI_PROVIDER') != configured['provider']):
            return False
        report = app.report(d)
        record = report.get('decision') or {}
        source = configured['label'] + ' / ' + configured['model']
        if not record or record.get('stale') or record.get('source') != source:
            return False
        app.JOB['running'] = True
        state[d] = {**previous, 'status': 'running', 'reason': '正在保存已生成的有效分析…'}
        app.save(app.DATA / 'cloud-runs.json', state)
    try:
        import morning_report
        import push
        morning_report.generate(cached=False, synchronize=False, runtime=app)
        try:
            if previous.get('sleep_refreshes', 0):
                notification = push.deliver(app, d, revision=True)
            else:
                notification = push.deliver(app, d)
        except Exception:
            notification = {'accepted': 0, 'failed': 1, 'device_count': 0}
        with app.LOCK:
            state = _load_state(app)
            state[d] = {**state.get(d, {}), 'status': 'complete',
                        'reason': '已核对并保存今日有效 AI 分析；未再次调用模型。',
                        'failure_stage': None, 'notification': notification,
                        'analyzed_sleep': sleep_candidate(report, now),
                        'finished_at': dt.datetime.now(app.TZ).isoformat()}
            app.save(app.DATA / 'cloud-runs.json', state)
        return True
    except Exception:
        with app.LOCK:
            state = _load_state(app)
            state[d] = {**state.get(d, {}), 'status': 'failed', 'failure_stage': 'export',
                        'reason': 'AI 分析已生成，但报告导出未完成；稍后重新核对。'}
            app.save(app.DATA / 'cloud-runs.json', state)
        return False
    finally:
        app.JOB['running'] = False


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
    if reconcile(app, now):
        return True
    with app.LOCK:
        daily = _load_state(app).get(d, {})
        if daily.get('status') == 'running' or app.JOB['running']:
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
            existing = state.get(d, {})
            if existing.get('status') not in TERMINAL:
                state[d] = {**existing, 'status': 'waiting_for_sleep', 'reason': message}
            elif existing.get('status') == 'complete':
                analyzed = existing.get('analyzed_sleep') or (previous.get('candidate') if previous.get('date') == d else None)
                if analyzed and candidate and candidate != analyzed:
                    state[d] = {**existing, 'update_available': True,
                                'reason': ('Oura 数据再次更新；已达今日自动修订上限，请在面板重新分析。'
                                           if existing.get('sleep_refreshes', 0) >= 1 else
                                           'Oura 睡眠/恢复数据已更新，等待稳定后更新分析。')}
                    if ready and existing.get('sleep_refreshes', 0) < 1:
                        state[d] = {**state[d], 'status': 'waiting_for_sleep',
                                    'sleep_refreshes': existing.get('sleep_refreshes', 0) + 1,
                                    'update_available': False}
                elif not existing.get('analyzed_sleep') and analyzed:
                    state[d] = {**existing, 'analyzed_sleep': analyzed}
            app.save(app.DATA / 'cloud-runs.json', state)
            app.JOB['message'] = message
    except Exception:
        with app.LOCK:
            app.save(path, {**previous, 'date': d, 'checked_at': stamp,
                            'message': 'Oura 检查未完成，稍后重试；不会请求 AI。'})
            app.JOB['message'] = 'Oura 检查未完成，稍后重试；不会请求 AI。'
    finally:
        app.JOB['running'] = False
    if ready and _load_state(app).get(d, {}).get('status') not in TERMINAL:
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
