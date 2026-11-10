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


def run_due(app, now=None):
    """One attempt per local date, persisted before work. No cross-process runner."""
    now = now or dt.datetime.now(app.TZ)
    hour = int(os.environ.get('IRON_SCHEDULE_HOUR', '11'))
    if not 0 <= hour <= 23:
        raise ValueError('IRON_SCHEDULE_HOUR 须为 0–23。')
    if now.hour < hour:
        return False
    d = now.date().isoformat()
    path = app.DATA / 'cloud-runs.json'
    with app.LOCK:
        state = app.load(path, {})
        if d in state or app.JOB['running']:
            return False
        state[d] = {'status': 'running', 'started_at': now.isoformat()}
        app.save(path, state)
        # Reserve sync before releasing the lock, just as the web endpoint does.
        app.JOB['running'] = True
    status, reason = 'complete', ''
    try:
        app.sync(7, claimed=True)
        report = app.report(d)
        ready = (not app.JOB.get('errors') and report['day_context']['synced']
                 and report['recovery'].get('sleep_hours') is not None
                 and bool(app.settings().get('oura_tokens')))
        if not ready:
            status, reason = 'incomplete', '数据未齐或同步失败；未请求 AI，等待手动同步后复核。'
        elif os.environ.get('IRON_SCHEDULE_AI') == '1':
            # Separate, explicit deployment opt-in authorizes this provider each day.
            selected = app.providers.config(app)['provider']
            if os.environ.get('IRON_SCHEDULE_AI_PROVIDER') != selected:
                status, reason = 'incomplete', '定时 AI 提供商未确认；未发送数据。'
            else:
                app.ai_report(d)
        else:
            reason = '仅生成数据报告；定时 AI 未启用。'
    except Exception:
        status, reason = 'failed', '定时任务未完成；请在受保护面板检查连接与配置。'
    finally:
        # A failed AI call must not suppress the cached report.
        try:
            import morning_report
            morning_report.generate(cached=False, synchronize=False, runtime=app)
        except Exception:
            status, reason = 'failed', '报告未能完整保存；请在受保护面板检查。'
        with app.LOCK:
            state = app.load(path, {})
            state[d] = {**state.get(d, {}), 'status': status, 'reason': reason,
                        'finished_at': dt.datetime.now(app.TZ).isoformat()}
            app.save(path, state)
    return True


def start(app):
    if os.environ.get('IRON_SCHEDULE_ENABLED') != '1':
        return
    def loop():
        while True:
            try:
                run_due(app)
            except Exception:
                pass  # Never log provider errors, records, or credentials.
            threading.Event().wait(30)
    threading.Thread(target=loop, name='daily-report', daemon=True).start()
