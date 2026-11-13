"""Single-user persistent sessions. Cloud only; opaque tokens never enter storage."""
import hashlib
import os
import secrets
import time
from http.cookies import SimpleCookie

COOKIE = '__Host-iron-session'
REMEMBER_SECONDS = 90 * 86400
SHORT_SECONDS = 86400
PUBLIC_PATHS = {'/login', '/login.js', '/api.js', '/api/csrf', '/style.css', '/manifest.webmanifest',
                '/icon-192.png', '/icon-512.png', '/sw.js'}
ATTEMPTS = {}


def enabled(app):
    return bool(app.PUBLIC_URL)


def config():
    return os.environ.get('IRON_LOGIN_USER', ''), os.environ.get('IRON_LOGIN_HASH', '')


def validate(app):
    if not enabled(app):
        return
    import bcrypt
    user, hashed = config()
    if not user or len(user) > 100 or not hashed.startswith(('$2a$', '$2b$', '$2y$')):
        raise ValueError('云端登录用户名和 bcrypt 密码散列未配置。')
    try:
        bcrypt.checkpw(b'configuration-check', hashed.encode())
    except ValueError:
        raise ValueError('云端登录密码散列格式无效。') from None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def credential_tag():
    user, hashed = config()
    return digest(user + ':' + hashed)


def token(headers):
    try:
        cookie = SimpleCookie()
        cookie.load(headers.get('Cookie', ''))
        value = cookie[COOKIE].value
        return value if 30 <= len(value) <= 100 else ''
    except Exception:
        return ''


def current(app, headers):
    value = token(headers)
    if not value:
        return None
    with app.LOCK:
        record = app.load(app.DATA / 'login-sessions.json', {}).get(digest(value))
    if (not record or record.get('expires_at', 0) <= time.time()
            or not secrets.compare_digest(record.get('credential_tag', ''), credential_tag())):
        return None
    return {'id': digest(value), **record}


def label(headers):
    agent = headers.get('User-Agent', '')[:400]
    if 'iPhone' in agent or 'iPad' in agent:
        return 'iPhone / iPad'
    if 'Android' in agent:
        return 'Android 手机'
    if 'Macintosh' in agent:
        return 'Mac 浏览器'
    if 'Windows' in agent:
        return 'Windows 浏览器'
    return '其他设备'


def cookie(value, remember=False, clear=False):
    result = COOKIE + '=' + value + '; Path=/; Secure; HttpOnly; SameSite=Lax'
    if clear:
        result += '; Max-Age=0'
    elif remember:
        result += '; Max-Age=' + str(REMEMBER_SECONDS)
    return result


def login(app, body, headers):
    import bcrypt
    user, hashed = config()
    username, password = body.get('username'), body.get('password')
    if (not isinstance(username, str) or not isinstance(password, str)
            or len(username) > 100 or not 0 < len(password.encode()) <= 72):
        raise app.AppError('用户名或密码不正确。')
    # This header is overwritten by the trusted proxy, never accepted directly.
    address = headers.get('X-Iron-Client-IP', 'unknown')[:100]
    now = time.time()
    with app.LOCK:
        for key in list(ATTEMPTS):
            if now - ATTEMPTS[key]['at'] > 900:
                del ATTEMPTS[key]
        attempt = ATTEMPTS.setdefault(address, {'at': now, 'count': 0})
        if attempt['count'] >= 10:
            raise app.AppError('登录尝试过多，请 15 分钟后再试。')
        attempt['count'] += 1
        if len(ATTEMPTS) > 1000:
            oldest = min(ATTEMPTS, key=lambda key: ATTEMPTS[key]['at'])
            del ATTEMPTS[oldest]
    try:
        valid = bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        raise app.AppError('服务器登录配置无效，请联系维护者。') from None
    if not valid or not secrets.compare_digest(username.encode(), user.encode()):
        raise app.AppError('用户名或密码不正确。')
    remember = body.get('remember') is True
    value = secrets.token_urlsafe(32)
    record = {'created_at': now, 'expires_at': now + (REMEMBER_SECONDS if remember else SHORT_SECONDS),
              'label': label(headers), 'credential_tag': credential_tag(), 'remembered': remember}
    with app.LOCK:
        ATTEMPTS.pop(address, None)
        sessions = app.load(app.DATA / 'login-sessions.json', {})
        sessions = {key: item for key, item in sessions.items()
                    if item.get('expires_at', 0) > now and item.get('credential_tag') == credential_tag()}
        if len(sessions) >= 20:
            del sessions[min(sessions, key=lambda key: sessions[key]['created_at'])]
        sessions[digest(value)] = record
        app.save(app.DATA / 'login-sessions.json', sessions)
    return cookie(value, remember)


def sessions(app, headers):
    active = current(app, headers)
    now = time.time()
    with app.LOCK:
        records = app.load(app.DATA / 'login-sessions.json', {})
    return {'devices': [{'id': key, 'label': row.get('label', '设备'),
                         'created_at': row['created_at'], 'expires_at': row['expires_at'],
                         'current': bool(active and active['id'] == key)}
                        for key, row in records.items()
                        if row.get('expires_at', 0) > now and row.get('credential_tag') == credential_tag()]}


def revoke(app, headers, target=None, others=False):
    active = current(app, headers)
    if not active:
        raise app.AppError('登录已失效，请重新登录。')
    with app.LOCK:
        records = app.load(app.DATA / 'login-sessions.json', {})
        if others:
            records = {active['id']: records[active['id']]} if active['id'] in records else {}
        else:
            records.pop(target or active['id'], None)
        app.save(app.DATA / 'login-sessions.json', records)
    return {'ok': True, 'logged_out': not others and (target is None or target == active['id'])}
