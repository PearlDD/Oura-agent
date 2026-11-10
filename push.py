"""Opt-in Web Push. Generic notices only; subscriptions and VAPID stay private."""
import base64
import hashlib
import importlib.util
import json
import os
import time
import urllib.parse


def available():
    return importlib.util.find_spec('pywebpush') is not None


def public_key(app):
    if not available():
        raise app.AppError('此运行环境尚未安装手机通知组件。')
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    path = app.DATA / 'push-vapid.pem'
    with app.LOCK:
        if not path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            raw = key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption())
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    raw = key.public_key().public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def endpoint_id(endpoint):
    return hashlib.sha256(endpoint.encode()).hexdigest()


def validate_subscription(app, value):
    if not isinstance(value, dict):
        raise app.AppError('通知订阅格式无效。')
    endpoint = value.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        raise app.AppError('通知地址无效。')
    try:
        p = urllib.parse.urlsplit(endpoint)
        host = (p.hostname or '').lower()
        allowed = host in ('fcm.googleapis.com', 'updates.push.services.mozilla.com',
                           'push.services.mozilla.com', 'web.push.apple.com')
        allowed = allowed or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
        if not (p.scheme == 'https' and allowed and not p.username and not p.password
                and p.port in (None, 443) and not p.fragment and p.path not in ('', '/')):
            raise ValueError()
        keys = value.get('keys', {})
        decoded = {}
        for name, size in (('auth', 16), ('p256dh', 65)):
            text = keys[name]
            if not isinstance(text, str) or len(text) > 200:
                raise ValueError()
            raw = base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)
            if len(raw) != size or name == 'p256dh' and raw[0] != 4:
                raise ValueError()
            decoded[name] = text
    except (ValueError, TypeError, KeyError):
        raise app.AppError('通知订阅无效或不是受支持的浏览器推送服务。') from None
    return {'endpoint': endpoint, 'keys': decoded}


def view(app):
    state = app.load(app.DATA / 'push-subscriptions.json', {})
    return {'available': bool(app.PUBLIC_URL) and available(),
            'device_count': len(state.get('devices', {})),
            'notice': '通知只显示晨报已更新，不包含健康指标或训练结论。'}


def subscribe(app, body):
    if body.get('consent') is not True:
        raise app.AppError('请先确认启用此设备的手机网页通知。')
    subscription = validate_subscription(app, body.get('subscription'))
    public_key(app)
    device_id = endpoint_id(subscription['endpoint'])
    with app.LOCK:
        state = app.load(app.DATA / 'push-subscriptions.json', {'devices': {}})
        devices = state.setdefault('devices', {})
        if device_id not in devices and len(devices) >= 8:
            raise app.AppError('最多启用 8 台设备，请先关闭其他设备的通知。')
        old = devices.get(device_id, {})
        devices[device_id] = {**old, 'subscription': subscription, 'updated_at': time.time()}
        app.save(app.DATA / 'push-subscriptions.json', state)
    return {'ok': True, 'device_id': device_id}


def unsubscribe(app, body):
    with app.LOCK:
        state = app.load(app.DATA / 'push-subscriptions.json', {'devices': {}})
        state.setdefault('devices', {}).pop(str(body.get('device_id', '')), None)
        app.save(app.DATA / 'push-subscriptions.json', state)
    return {'ok': True}


def send(app, subscription, date, test=False):
    from pywebpush import webpush
    import requests
    class NoRedirectSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs['allow_redirects'] = False
            return super().request(method, url, **kwargs)
    subscription = validate_subscription(app, subscription)
    payload = {'title': '通知测试' if test else '训练晨报已更新',
               'body': '手机通知连接成功，点击打开网页。' if test else '登录后查看今天的分析与训练安排。',
               'url': '/' if test else '/?date=' + app.day(date),
               'tag': 'iron-test' if test else 'iron-report-' + app.day(date)}
    with NoRedirectSession() as session:
        response = webpush(subscription_info=subscription, data=json.dumps(payload, ensure_ascii=False),
                           vapid_private_key=str(app.DATA / 'push-vapid.pem'),
                           vapid_claims={'sub': app.PUBLIC_URL},
                           requests_session=session, timeout=12, ttl=86400,
                           headers={'Urgency': 'normal'})
    if not 200 <= response.status_code < 300:
        raise app.AppError('推送服务未接受通知。')


def deliver(app, date, device_id=None, test=False):
    path = app.DATA / 'push-subscriptions.json'
    with app.LOCK:
        state = app.load(path, {'devices': {}})
        selected = [(key, dict(value)) for key, value in state.get('devices', {}).items()
                    if device_id is None or key == device_id]
    if test and not selected:
        raise app.AppError('请先在此设备启用通知。')
    sent, failed = 0, 0
    for key, device in selected:
        with app.LOCK:
            state = app.load(path, {'devices': {}})
            current = state['devices'].get(key)
            if not current:
                continue
            if test:
                if time.time() - current.get('test_at', 0) < 30:
                    raise app.AppError('测试通知每 30 秒可发送一次。')
                current['test_at'] = time.time()
            else:
                deliveries = current.setdefault('deliveries', {})
                if date in deliveries:
                    continue
                deliveries[date] = {'status': 'sending', 'at': time.time()}
            app.save(path, state)
        status, expired = 'accepted', False
        try:
            send(app, device['subscription'], date, test)
            sent += 1
        except Exception as error:
            # Exceptions may contain private endpoint URLs; never serialize or log them.
            status = 'failed'
            expired = getattr(error, 'status_code', None) in (404, 410)
            failed += 1
        with app.LOCK:
            state = app.load(path, {'devices': {}})
            current = state['devices'].get(key)
            if current and expired:
                del state['devices'][key]
            elif current:
                if test:
                    current['test_status'] = status
                else:
                    current.setdefault('deliveries', {})[date] = {'status': status, 'at': time.time()}
            app.save(path, state)
    return {'accepted': sent, 'failed': failed, 'device_count': len(selected)}
