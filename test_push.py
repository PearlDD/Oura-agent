import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import app
import push


def encoded(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def subscription():
    return {'endpoint': 'https://web.push.apple.com/Q/test-private-device',
            'keys': {'auth': encoded(b'a'*16), 'p256dh': encoded(b'\x04'+b'b'*64)}}


class PushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = patch.object(app, 'DATA', Path(self.tmp.name))
        self.data.start()

    def tearDown(self):
        self.data.stop()
        self.tmp.cleanup()

    def test_rejects_non_push_hosts_private_urls_and_invalid_keys(self):
        self.assertEqual(push.validate_subscription(app, subscription()), subscription())
        for url in ['http://web.push.apple.com/a', 'https://127.0.0.1/private',
                    'https://web.push.apple.com.evil.example/a',
                    'https://user:password@web.push.apple.com/a',
                    'https://web.push.apple.com:444/a']:
            with self.assertRaises(app.AppError):
                push.validate_subscription(app, {**subscription(), 'endpoint': url})
        bad = subscription();bad['keys']['auth'] = encoded(b'a')
        with self.assertRaises(app.AppError):push.validate_subscription(app, bad)

    def test_subscription_requires_opt_in_and_revocation_removes_recipient(self):
        with self.assertRaises(app.AppError):push.subscribe(app, {'subscription': subscription()})
        with patch.object(push, 'public_key', return_value='public'):
            result = push.subscribe(app, {'subscription': subscription(), 'consent': True})
        path = app.DATA/'push-subscriptions.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        push.unsubscribe(app, result)
        with patch.object(push, 'send') as send:
            self.assertEqual(push.deliver(app, '2026-11-10')['accepted'], 0)
            send.assert_not_called()

    def test_daily_delivery_claim_prevents_repeat_after_restart(self):
        key = push.endpoint_id(subscription()['endpoint'])
        app.save(app.DATA/'push-subscriptions.json', {'devices': {key: {'subscription': subscription()}}})
        with patch.object(push, 'send') as send:
            self.assertEqual(push.deliver(app, '2026-11-10')['accepted'], 1)
            self.assertEqual(push.deliver(app, '2026-11-10')['accepted'], 0)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(push.deliver(app, '2026-11-11')['accepted'], 1)

    def test_expired_subscription_is_removed_without_recording_error_body(self):
        key = push.endpoint_id(subscription()['endpoint'])
        path = app.DATA/'push-subscriptions.json'
        app.save(path, {'devices': {key: {'subscription': subscription()}}})
        class Gone(Exception):status_code = 410
        with patch.object(push, 'send', side_effect=Gone('SECRET-ENDPOINT')):
            self.assertEqual(push.deliver(app, '2026-11-10')['failed'], 1)
        self.assertEqual(app.load(path)['devices'], {})
        self.assertNotIn('SECRET-ENDPOINT', path.read_text())

    @unittest.skipUnless(push.available(), 'Cloud-only Web Push package not installed')
    def test_real_encryption_and_vapid_without_network_or_health_payload(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        import http_ece
        import requests
        receiver = ec.generate_private_key(ec.SECP256R1())
        receiver_public = receiver.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        info = {'endpoint': 'https://fcm.googleapis.com/fcm/send/test-device',
                'keys': {'auth': encoded(b'c'*16), 'p256dh': encoded(receiver_public)}}
        with patch.object(app, 'PUBLIC_URL', 'https://oura.example.com'):
            first = push.public_key(app)
            self.assertEqual(first, push.public_key(app))
            self.assertEqual((app.DATA/'push-vapid.pem').stat().st_mode & 0o777, 0o600)
            calls = []
            def capture(session, method, url, **kwargs):
                calls.append(kwargs)
                plain = http_ece.decrypt(kwargs['data'], private_key=receiver, auth_secret=b'c'*16, version='aes128gcm')
                payload = json.loads(plain)
                self.assertEqual(set(payload), {'title', 'body', 'url', 'tag'})
                self.assertEqual(payload['title'], '训练晨报已更新')
                self.assertEqual(payload['url'], '/?date=2026-11-10')
                self.assertFalse(kwargs['allow_redirects'])
                self.assertIn('Authorization', kwargs['headers'])
                response=requests.Response();response.status_code=201
                return response
            with patch.object(requests.Session, 'request', capture):
                push.send(app, info, '2026-11-10')
            self.assertEqual(len(calls), 1)

class FailureNoticeTests(unittest.TestCase):
    def test_failed_and_successful_notices_are_separately_deduplicated(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DATA',Path(folder)),patch('push.send') as send:
            app.save(app.DATA/'push-subscriptions.json',{'devices':{'test-device':{'subscription':{'endpoint':'not-used'}}}})
            first=push.deliver(app,'2026-11-13',failure=True)
            again=push.deliver(app,'2026-11-13',failure=True)
            success=push.deliver(app,'2026-11-13')
            self.assertEqual((first['accepted'],again['accepted'],success['accepted']),(1,0,1))
            revision=push.deliver(app,'2026-11-13',revision=True)
            self.assertEqual(revision['accepted'],1)
            self.assertEqual(push.deliver(app,'2026-11-13',revision=True)['accepted'],0)
            self.assertEqual(push.deliver(app,'2026-11-13',revision=2)['accepted'],1)
            self.assertEqual(push.deliver(app,'2026-11-13',revision=2)['accepted'],0)
            self.assertEqual(send.call_count,4)
            record=app.load(app.DATA/'push-subscriptions.json')['devices']['test-device']['deliveries']
            self.assertEqual(set(record),{'2026-11-13:failure','2026-11-13','2026-11-13:revision','2026-11-13:revision2'})
