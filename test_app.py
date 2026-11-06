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
        rows = [{'day': (anchor - dt.timedelta(days=i)).isoformat(), 'type': 'long_sleep', 'total_sleep_duration': 8*3600,
                 'average_hrv': 50, 'lowest_heart_rate': 55} for i in range(1, 8)]
        rows += [{'day': anchor.isoformat(), 'type': 'long_sleep', 'total_sleep_duration': 6*3600},
                 {'day': anchor.isoformat(), 'type': 'long_sleep', 'total_sleep_duration': 20*60},
                 {'day': (anchor+dt.timedelta(days=1)).isoformat(), 'type': 'long_sleep', 'total_sleep_duration': 12*3600}]
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

    def test_pending_sleep_fragment_is_not_main_sleep_or_recovery_input(self):
        app.save(app.DATA/'oura/sleep.json',{'data':[{'day':'2026-11-06','type':'sleep',
            'total_sleep_duration':3810,'average_hrv':32,'lowest_heart_rate':66}]})
        r=app.report('2026-11-06')
        self.assertEqual(r['recovery']['sleep_status'],'pending_main')
        self.assertIsNone(r['recovery']['sleep_hours'])
        self.assertIsNone(r['recovery']['hrv'])
        self.assertIsNone(r['recovery']['rhr'])
        self.assertEqual(r['trends']['sleep_hours']['recent']['n'],0)
        self.assertEqual(app.report('2026-11-07')['baseline']['sleep_hours']['n'],0)
        self.assertTrue(any('片段' in n for n in r['observations']))

    def test_main_sleep_can_be_short_and_does_not_select_a_longer_ordinary_fragment(self):
        app.save(app.DATA/'oura/sleep.json',{'data':[
            {'day':'2026-11-06','type':'long_sleep','total_sleep_duration':3600,'average_hrv':40},
            {'day':'2026-11-06','type':'sleep','total_sleep_duration':7200,'average_hrv':20}]})
        r=app.recovery_data()['2026-11-06']
        self.assertEqual(r['sleep_status'],'main_record')
        self.assertEqual(r['sleep_hours'],1)
        self.assertEqual(r['hrv'],40)

    def test_fragment_then_complete_record_updates_without_stale_values(self):
        p=app.DATA/'oura/sleep.json'
        app.save(p,{'data':[{'day':'2026-11-06','type':'sleep','total_sleep_duration':3810}]})
        self.assertIsNone(app.recovery_data()['2026-11-06']['sleep_hours'])
        app.save(p,{'data':[{'day':'2026-11-06','type':'long_sleep','total_sleep_duration':27540}]})
        r=app.recovery_data()['2026-11-06']
        self.assertEqual(r['sleep_hours'],7.65)
        self.assertNotIn('partial_sleep_hours',r)

    def test_day_modes_distinguish_plan_record_and_missing_sync(self):
        d = '2026-11-05'
        self.assertEqual(app.day_context(d, [], [], {})['mode'], 'unknown')
        self.assertEqual(app.day_context(d, [], [d], {})['mode'], 'recovery')
        planned = app.day_context(d, [], [], {'plan': 'train'})
        self.assertEqual(planned['mode'], 'training')
        self.assertFalse(planned['has_record'])
        self.assertIn('不代表已经完成', planned['reason'])
        self.assertEqual(app.day_context(d, [], [], {'plan': 'rest'})['mode'], 'recovery')
        actual = app.day_context(d, [{'date': d}], [d], {'plan': 'rest'})
        self.assertEqual(actual['mode'], 'training')
        self.assertIn('核对', actual['reason'])

    def test_checkin_plan_is_persisted_per_date_without_erasing_old_fields(self):
        app.save(app.DATA/'checkins.json', {'2026-11-04': {'note': 'yesterday'},
                                          '2026-11-05': {'legacy': 'keep'}})
        app.save_checkin({'date': '2026-11-05', 'energy': 4, 'soreness': 1, 'plan': 'rest', 'note': 'today'})
        stored = app.load(app.DATA/'checkins.json')
        self.assertEqual(stored['2026-11-04']['note'], 'yesterday')
        self.assertEqual(stored['2026-11-05']['plan'], 'rest')
        self.assertEqual(stored['2026-11-05']['legacy'], 'keep')
        with self.assertRaises(app.AppError):
            app.save_checkin({'date': '2026-11-05', 'energy': 3, 'soreness': 0, 'plan': 'invalid'})
        self.assertEqual(app.load(app.DATA/'checkins.json')['2026-11-05']['plan'], 'rest')

    def test_recovery_trends_have_separate_windows_and_ignore_future(self):
        anchor = dt.date(2026, 11, 5)
        data = {(anchor-dt.timedelta(days=i)).isoformat(): {'hrv': 40 if i<7 else 60} for i in range(14)}
        data['2026-11-06'] = {'hrv': 999}
        trend = app.recovery_trends(data, anchor)['hrv']
        self.assertEqual(trend['recent'], {'n': 7, 'value': 40})
        self.assertEqual(trend['previous'], {'n': 7, 'value': 60})
        del data['2026-11-05'];del data['2026-11-04'];del data['2026-11-03']
        del data['2026-11-02'];del data['2026-11-01']
        self.assertIsNone(app.recovery_trends(data, anchor)['hrv']['recent']['value'])

    def test_recovery_report_and_export_respect_plan_without_claiming_full_recovery(self):
        app.save(app.DATA/'xunji/2026-11-05.json', {'data': {'res': {'trains': []}}})
        app.save(app.DATA/'oura/sleep.json', {'data': [{'day': '2026-11-05', 'type': 'long_sleep', 'total_sleep_duration': 28800}]})
        app.update_settings({'oura_tokens': {'access_token': 'test'}})
        app.save_checkin({'date': '2026-11-05', 'energy': 3, 'soreness': 0, 'plan': 'rest'})
        r = app.report('2026-11-05')
        self.assertEqual(r['day_context']['mode'], 'recovery')
        self.assertIn('连续变化', r['focus'])
        self.assertIn('当日计划：休息', app.markdown(r))
        app.save_checkin({'date': '2026-11-05', 'energy': 3, 'soreness': 0, 'plan': 'train'})
        self.assertEqual(app.report('2026-11-05')['day_context']['mode'], 'training')

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
        app.save(app.DATA/'oura/sleep.json', {'data': [{'day': '2026-11-05', 'type': 'long_sleep', 'total_sleep_duration': 3600*8}]})
        with patch.object(app, 'request_json', return_value={'output': [{'content': [{'type': 'output_text', 'text': '测试报告'}]}]}) as req:
            result = app.ai_report('2026-11-05')
        payload = req.call_args.args[1]
        self.assertFalse(payload['store'])
        self.assertNotIn('PRIVATE NOTE', payload['input'])
        self.assertNotIn('private-xunji-key', payload['input'])
        self.assertEqual(result['text'], '测试报告')


if __name__ == '__main__':
    unittest.main()
