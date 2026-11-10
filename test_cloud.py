import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import cloud


class BoundaryTests(unittest.TestCase):
    def test_fail_closed_and_exact_proxy_boundary(self):
        for value in ['http://example.com', 'https://u:p@example.com',
                      'https://example.com/path', 'https://example.com/?token=x']:
            with self.assertRaises(ValueError):
                cloud.public_origin(value)
        with self.assertRaises(ValueError):
            cloud.validate('0.0.0.0', '', '')
        with self.assertRaises(ValueError):
            cloud.validate('0.0.0.0', 'https://example.com', 'short')
        token = 'a' * 40
        origin = cloud.public_origin('https://example.com/')
        cloud.validate('0.0.0.0', origin, token)
        good = {'Host': 'example.com', 'X-Iron-Proxy-Token': token}
        self.assertTrue(cloud.allowed(good, 8765, origin, token))
        for headers in [{'Host': 'example.com'}, {**good, 'Host': 'evil.com'},
                        {**good, 'X-Iron-Proxy-Token': 'wrong'}]:
            self.assertFalse(cloud.allowed(headers, 8765, origin, token))
        self.assertTrue(cloud.allowed({'Host': 'localhost:8765'}, 8765, '', ''))

    def test_callback_uses_same_origin_as_access_boundary(self):
        with patch.object(app, 'PUBLIC_URL', 'https://oura.example.com'):
            self.assertEqual(app.redirect_uri(), 'https://oura.example.com/oauth/callback')

    def test_daily_claim_survives_restart_and_missing_data_never_calls_ai(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(app, 'DATA', Path(folder)), \
             patch.object(app, 'JOB', {'running': False, 'errors': []}), \
             patch.object(app, 'sync') as sync, \
             patch.object(app, 'report', return_value={'day_context': {'synced': True},
                                                       'recovery': {'sleep_hours': None}}), \
             patch.object(app, 'ai_report') as ai, \
             patch('morning_report.generate'), \
             patch.dict('os.environ', {'IRON_SCHEDULE_AI': '1', 'IRON_SCHEDULE_HOUR': '11'}):
            morning = dt.datetime(2026, 11, 10, 10, tzinfo=app.TZ)
            self.assertFalse(cloud.run_due(app, morning))
            self.assertTrue(cloud.run_due(app, morning.replace(hour=11)))
            self.assertFalse(cloud.run_due(app, morning.replace(hour=12)))
            sync.assert_called_once_with(7, claimed=True)
            ai.assert_not_called()
            self.assertEqual(app.load(Path(folder)/'cloud-runs.json')['2026-11-10']['status'], 'incomplete')

    def test_failed_task_is_not_retried_or_logged_with_exception_text(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(app, 'DATA', Path(folder)), \
             patch.object(app, 'JOB', {'running': False}), \
             patch.object(app, 'sync', side_effect=RuntimeError('SECRET')), \
             patch('morning_report.generate'), \
             patch.dict('os.environ', {'IRON_SCHEDULE_HOUR': '11'}):
            now = dt.datetime(2026, 11, 10, 12, tzinfo=app.TZ)
            self.assertTrue(cloud.run_due(app, now))
            self.assertFalse(cloud.run_due(app, now))
            saved = (Path(folder)/'cloud-runs.json').read_text()
            self.assertNotIn('SECRET', saved)
            self.assertIn('failed', saved)
