"""Transport behavior with synthetic failures only; never calls an API."""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
import app
import cloud


class TransportTests(unittest.TestCase):
    def test_generation_gets_longer_wait_without_retrying_ambiguous_timeout(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'DATA', Path(folder)), \
                patch.object(app.urllib.request, 'urlopen', side_effect=TimeoutError('SENSITIVE')) as request:
            with self.assertRaises(app.AppError) as caught:
                app.request_json('https://api.openai.com/v1/responses', {'synthetic': True}, 'TEST-SECRET')
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.kwargs['timeout'], 180)
            status = app.load(Path(folder)/'ai-status.json')
            self.assertEqual(status['error_code'], 'timeout')
            self.assertEqual(status['timeout_seconds'], 180)
            self.assertNotIn('SENSITIVE', json.dumps(status))
            self.assertNotIn('TEST-SECRET', str(caught.exception))
            self.assertIn('超时', cloud.failure_reason(caught.exception, 'analysis'))

    def test_data_sync_keeps_shorter_timeout_and_no_retry(self):
        with patch.object(app.urllib.request, 'urlopen', side_effect=urllib.error.URLError('SENSITIVE')) as request:
            with self.assertRaises(app.AppError):
                app.request_json('https://api.ouraring.com/v2/usercollection/sleep', token='TEST-SECRET')
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.kwargs['timeout'], 60)

    def test_connection_failure_is_distinct_and_sanitized(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'DATA', Path(folder)), \
                patch.object(app.urllib.request, 'urlopen', side_effect=urllib.error.URLError('SENSITIVE')):
            with self.assertRaises(app.AppError):
                app.request_json('https://api.openai.com/v1/responses', {}, 'TEST-SECRET')
            status = app.load(Path(folder)/'ai-status.json')
            self.assertEqual(status['error_code'], 'connection_error')
            self.assertNotIn('SENSITIVE', json.dumps(status))

