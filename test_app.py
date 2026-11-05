import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = patch.object(app, 'DATA', Path(self.temp.name))
        self.path.start()

    def tearDown(self):
        self.path.stop()
        self.temp.cleanup()

    def test_working_sets_warmups_units_and_missing_values(self):
        raw = {'res': {'trains': [{'movements': [{'name': '卧推', 'sets': [
            {'done': True, 'weight': 20, 'unit': 'kg', 'reps': 10, 'setType': '热'},
            {'done': True, 'weight': 100, 'unit': 'lb', 'reps': 5, 'rpe': '8'},
            {'done': False, 'weight': 100, 'reps': 8},
            {'done': 'false', 'weight': 100, 'reps': 8},
            {'done': True, 'reps': 10},
        ]}]}]}}
        result = app.totals(app.normalize_training(raw, '2026-11-05'))
        self.assertEqual(result['sets'], 2)
        self.assertAlmostEqual(result['volume_kg'], 226.8)
        self.assertEqual(result['rpe'], 8)
        self.assertEqual(result['rpe_count'], 1)

    def test_super_and_drop_sets(self):
        raw = {'res': [{'movements': [{'name': '超级组', 'sets': [{'done': True, 'items': [
            {'name': '引体', 'set': {'done': True, 'reps': 8}},
            {'name': '划船', 'set': {'done': True, 'weight': 20, 'reps': 10,
                                   'dropSets': [{'weight': 10, 'reps': 5}]}}]}]}]}]}
        result = app.totals(app.normalize_training(raw, '2026-11-05'))
        self.assertEqual(result['sets'], 3)
        self.assertEqual(result['volume_kg'], 250)

    def test_exercise_comparison_matches_name_load_and_completed_sets(self):
        def session(d, name, weight, reps):
            return app.normalize_training({'res': [{'movements': [{'name': name, 'sets': [
                {'done': True, 'weight': weight, 'unit': 'kg', 'reps': reps}]}]}]}, d)[0]
        old = session('2026-10-20', '卧推', 60, 8)
        other = session('2026-10-25', '深蹲', 60, 12)
        current = session('2026-10-29', '卧推', 60, 10)
        rows = app.exercise_comparisons([old, other, current], current['date'], [current])
        self.assertEqual(rows[0]['previous_date'], old['date'])
        self.assertEqual(rows[0]['same_load']['previous_reps'], 8)
        self.assertEqual(rows[0]['same_load']['current_reps'], 10)

    def test_baseline_excludes_current_and_future_and_requires_seven_nights(self):
        anchor = dt.date(2026, 11, 5)
        rows = [{'day': (anchor - dt.timedelta(days=i)).isoformat(), 'total_sleep_duration': 8*3600,
                 'average_hrv': 50, 'lowest_heart_rate': 55} for i in range(1, 8)]
        rows += [{'day': anchor.isoformat(), 'total_sleep_duration': 6*3600},
                 {'day': anchor.isoformat(), 'total_sleep_duration': 20*60},
                 {'day': (anchor+dt.timedelta(days=1)).isoformat(), 'total_sleep_duration': 12*3600}]
        app.save(app.DATA/'oura/sleep.json', {'data': rows})
        r = app.report(anchor.isoformat())
        self.assertEqual(r['baseline']['sleep_hours'], {'n': 7, 'value': 8})
        self.assertEqual(r['recovery']['sleep_hours'], 6)
        self.assertIsNone(r['recovery'].get('hrv'))
        rows.pop(0)
        app.save(app.DATA/'oura/sleep.json', {'data': rows})
        self.assertIsNone(app.report(anchor.isoformat())['baseline']['sleep_hours']['value'])

    def test_missing_days_are_not_rest_days(self):
        r = app.report('2026-11-05')
        self.assertEqual(r['coverage'], 0)
        self.assertTrue(any('未读取日期不能视为休息日' in x for x in r['observations']))
        self.assertIsNone(r['recovery'].get('hrv'))

    def test_empty_records_cache_and_no_duplicate_requests(self):
        app.update_settings({'xunji_key': 'test-not-a-real-key'})
        with patch.object(app, 'request_json', return_value={'res': {'trains': []}}) as req:
            app.xunji('2026-11-05')
            app.xunji('2026-11-05')
        self.assertEqual(req.call_count, 1)
        self.assertEqual((app.DATA/'settings.json').stat().st_mode & 0o777, 0o600)

    def test_error_response_is_not_cached(self):
        app.update_settings({'xunji_key': 'test-not-a-real-key'})
        with patch.object(app, 'request_json', return_value={'success': False, 'res': []}):
            with self.assertRaises(app.AppError):
                app.xunji('2026-11-05')
        self.assertFalse((app.DATA/'xunji/2026-11-05.json').exists())

    def test_refresh_token_rotation_is_saved(self):
        app.update_settings({'oura_client_id': 'test', 'oura_client_secret': 'test',
                             'oura_tokens': {'access_token': 'old', 'refresh_token': 'old-refresh', 'expires_at': 0}})
        with patch.object(app, 'request_json', return_value={'access_token': 'new', 'refresh_token': 'new-refresh', 'expires_in': 3600}) as req:
            self.assertEqual(app.oura_token(), 'new')
            self.assertEqual(app.oura_token(), 'new')
        self.assertEqual(req.call_count, 1)
        self.assertEqual(app.settings()['oura_tokens']['refresh_token'], 'new-refresh')

    def test_oura_pagination(self):
        with patch.object(app, 'oura_token', return_value='test'), patch.object(app, 'request_json', side_effect=[
            {'data': [{'day': '2026-11-04'}], 'next_token': 'page2'},
            {'data': [{'day': '2026-11-05'}], 'next_token': None},
            {'data': [], 'next_token': None}, {'data': [], 'next_token': None}]):
            app.fetch_oura('2026-11-04', '2026-11-06')
        self.assertEqual(len(app.load(app.DATA/'oura/sleep.json')['data']), 2)

    def test_ai_sends_summary_not_secret_or_freeform_note(self):
        app.update_settings({'xunji_key': 'private-xunji-key', 'openai_key': 'test-openai-key', 'openai_model': 'test-model'})
        app.save(app.DATA/'checkins.json', {'2026-11-05': {'energy': 3, 'note': 'PRIVATE NOTE'}})
        app.save(app.DATA/'oura/sleep.json', {'data': [{'day': '2026-11-05', 'total_sleep_duration': 3600*8}]})
        with patch.object(app, 'request_json', return_value={'output': [{'content': [{'type': 'output_text', 'text': '测试报告'}]}]}) as req:
            result = app.ai_report('2026-11-05')
        payload = req.call_args.args[1]
        self.assertFalse(payload['store'])
        self.assertNotIn('PRIVATE NOTE', payload['input'])
        self.assertNotIn('private-xunji-key', payload['input'])
        self.assertEqual(result['text'], '测试报告')


if __name__ == '__main__':
    unittest.main()
