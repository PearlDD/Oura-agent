import io
import json
import os
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
try:
    import bcrypt
except ImportError:
    bcrypt = None
import app
import auth


@unittest.skipUnless(bcrypt, "Install requirements-cloud.txt to test cloud login")
class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data=patch.object(app,'DATA',Path(self.temp.name));self.data.start()
        self.origin=patch.object(app,'PUBLIC_URL','https://unit.example');self.origin.start()
        self.proxy=patch.object(app,'PROXY_TOKEN','q'*40);self.proxy.start()
        self.env=patch.dict(os.environ,{'IRON_LOGIN_USER':'testuser','IRON_LOGIN_HASH':bcrypt.hashpw(b'test-only-pass',bcrypt.gensalt(rounds=4)).decode()});self.env.start()
        self.headers={'Host':'unit.example','X-Iron-Proxy-Token':'q'*40,'X-Iron-Client-IP':'192.0.2.1','User-Agent':'iPhone'}
        auth.ATTEMPTS.clear()

    def tearDown(self):
        self.env.stop();self.proxy.stop();self.origin.stop();self.data.stop();self.temp.cleanup();auth.ATTEMPTS.clear()

    def login(self,remember=True):
        return auth.login(app,{'username':'testuser','password':'test-only-pass','remember':remember},self.headers)

    def cookie_headers(self,value):
        parsed=SimpleCookie();parsed.load(value)
        return {**self.headers,'Cookie':auth.COOKIE+'='+parsed[auth.COOKIE].value}

    def handler(self,path,body=None,headers=None):
        handler=object.__new__(app.Handler)
        handler.path=path;handler.headers={**self.headers,**(headers or {})};handler.wfile=io.BytesIO();handler.rfile=io.BytesIO()
        handler.captured_status=None;handler.captured_headers={}
        handler.send_response=lambda status:setattr(handler,'captured_status',status)
        handler.send_header=lambda name,value:handler.captured_headers.__setitem__(name,value)
        handler.end_headers=lambda:None
        if body is not None:
            raw=json.dumps(body).encode();handler.rfile=io.BytesIO(raw);handler.headers['Content-Length']=str(len(raw));handler.headers['X-Iron-Token']=app.NONCE
        return handler

    def test_remember_cookie_is_secure_private_and_session_hash_survives_reload(self):
        cookie=self.login();headers=self.cookie_headers(cookie)
        for value in ['Secure','HttpOnly','SameSite=Lax','Path=/','Max-Age=7776000']:self.assertIn(value,cookie)
        self.assertNotIn('Domain=',cookie)
        record=auth.current(app,headers);self.assertEqual(record['label'],'iPhone / iPad')
        stored=(app.DATA/'login-sessions.json').read_text()
        self.assertNotIn(auth.token(headers),stored);self.assertNotIn('test-only-pass',stored)
        self.assertEqual((app.DATA/'login-sessions.json').stat().st_mode & 0o777,0o600)
        auth.ATTEMPTS.clear() # A restart does not erase persisted login state.
        self.assertEqual(auth.current(app,headers)['id'],record['id'])

    def test_expiry_and_password_rotation_invalidate_existing_session(self):
        headers=self.cookie_headers(self.login());record=auth.current(app,headers)
        with patch('auth.time.time',return_value=record['expires_at']+1):self.assertIsNone(auth.current(app,headers))
        with patch.dict(os.environ,{'IRON_LOGIN_HASH':bcrypt.hashpw(b'another-test-pass',bcrypt.gensalt(rounds=4)).decode()}):self.assertIsNone(auth.current(app,headers))

    def test_short_session_is_not_a_persistent_cookie(self):
        cookie=self.login(False);self.assertNotIn('Max-Age=',cookie)
        record=auth.current(app,self.cookie_headers(cookie))
        self.assertEqual(record['expires_at']-record['created_at'],86400)

    def test_wrong_password_and_forged_cookie_cannot_read_private_routes(self):
        with self.assertRaises(app.AppError):auth.login(app,{'username':'testuser','password':'wrong'},self.headers)
        with self.assertRaises(app.AppError):auth.login(app,{'username':'another','password':'test-only-pass'},self.headers)
        headers={**self.headers,'Cookie':auth.COOKIE+'='+'x'*43}
        self.assertIsNone(auth.current(app,headers))
        for route in ['/api/status','/api/export?date=2026-11-13','/api/chat?date=2026-11-13']:
            handler=self.handler(route,headers=headers);handler.do_GET();self.assertEqual(handler.captured_status,401)
        handler=self.handler('/',headers=headers);handler.do_GET();self.assertEqual(handler.captured_headers['Location'],'/login')

    def test_failed_attempts_are_limited_before_password_work(self):
        for _ in range(10):
            with self.assertRaises(app.AppError):auth.login(app,{'username':'testuser','password':'wrong'},self.headers)
        with patch('bcrypt.checkpw') as check:
            with self.assertRaisesRegex(app.AppError,'15 分钟'):self.login()
            check.assert_not_called()

    def test_public_assets_do_not_expose_health_and_login_requires_csrf_origin(self):
        handler=self.handler('/login');handler.do_GET();self.assertEqual(handler.captured_status,200)
        self.assertIn('记住此设备 90 天',handler.wfile.getvalue().decode())
        handler=self.handler('/api/auth/login',{'username':'testuser','password':'test-only-pass'})
        handler.headers.pop('X-Iron-Token');handler.do_POST();self.assertEqual(handler.captured_status,403)
        handler=self.handler('/api/auth/login',{'username':'testuser','password':'test-only-pass'},headers={'Origin':'https://untrusted.example'})
        handler.do_POST();self.assertEqual(handler.captured_status,403)
        handler=self.handler('/api/auth/login',{'username':'testuser','password':'test-only-pass','remember':True},headers={'Origin':'https://unit.example'})
        handler.do_POST();self.assertEqual(handler.captured_status,200);self.assertIn('Set-Cookie',handler.captured_headers)

    def test_revoke_other_devices_and_logout_clear_access(self):
        first=self.cookie_headers(self.login());second=self.cookie_headers(self.login())
        result=auth.sessions(app,first)
        self.assertEqual(len(result['devices']),2);self.assertNotIn('credential_tag',str(result))
        self.assertFalse(auth.revoke(app,first,others=True)['logged_out'])
        self.assertIsNone(auth.current(app,second));self.assertIsNotNone(auth.current(app,first))
        handler=self.handler('/api/auth/logout',{},headers=first);handler.do_POST()
        self.assertEqual(handler.captured_status,200);self.assertIn('Max-Age=0',handler.captured_headers['Set-Cookie'])
        self.assertIsNone(auth.current(app,first))

    def test_api_mutations_need_both_session_and_csrf(self):
        handler=self.handler('/api/settings',{'xunji_key':'never-store-this'});handler.do_POST()
        self.assertEqual(handler.captured_status,401);self.assertFalse((app.DATA/'settings.json').exists())

    def test_oauth_callback_requires_same_site_login(self):
        handler=self.handler('/oauth/callback?code=test&state=test');handler.do_GET()
        self.assertEqual(handler.captured_headers['Location'],'/login')

    def test_misconfigured_cloud_auth_fails_closed(self):
        with patch.dict(os.environ,{'IRON_LOGIN_HASH':''}):
            with self.assertRaises(ValueError):auth.validate(app)


    def test_expired_csrf_is_rejected_before_action_and_can_be_refreshed(self):
        session=self.cookie_headers(self.login())
        handler=self.handler('/api/auth/logout',{},headers=session)
        handler.headers['X-Iron-Token']='old-process-token'
        handler.do_POST()
        self.assertEqual(handler.captured_status,403)
        self.assertEqual(json.loads(handler.wfile.getvalue())['code'],'csrf_expired')
        self.assertIsNotNone(auth.current(app,session))
        refresh=self.handler('/api/csrf');refresh.do_GET()
        self.assertEqual(refresh.captured_status,200)
        self.assertEqual(json.loads(refresh.wfile.getvalue()),{'token':app.NONCE})
        handler=self.handler('/api/auth/logout',{},headers=session);handler.do_POST()
        self.assertEqual(handler.captured_status,200);self.assertIsNone(auth.current(app,session))

    def test_csrf_refresh_still_requires_trusted_host_proxy_and_does_not_allow_cross_origin_post(self):
        handler=self.handler('/api/csrf',headers={'Host':'untrusted.example'});handler.do_GET()
        self.assertEqual(handler.captured_status,403)
        session=self.cookie_headers(self.login())
        handler=self.handler('/api/auth/logout',{},headers={**session,'Origin':'https://untrusted.example'})
        handler.do_POST();self.assertEqual(handler.captured_status,403)
        self.assertIsNotNone(auth.current(app,session))
