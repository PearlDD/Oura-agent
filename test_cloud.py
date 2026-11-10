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


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.data=patch.object(app,'DATA',Path(self.tmp.name));self.data.start()
        self.job=patch.object(app,'JOB',{'running':False,'errors':[]});self.job.start()
        self.env=patch.dict('os.environ',{'IRON_SCHEDULE_MODE':'wake','IRON_WAKE_POLL_SECONDS':'900','IRON_WAKE_STABLE_SECONDS':'900'});self.env.start()
        self.now=dt.datetime(2026,11,10,10,0,tzinfo=app.TZ)
        self.recovery={'sleep_status':'main_record','sleep_hours':8,'sleep_score':80,'readiness':75,
                       'bedtime_start':'2026-11-10T01:00:00-05:00','bedtime_end':'2026-11-10T09:00:00-05:00'}

    def tearDown(self):
        self.env.stop();self.job.stop();self.data.stop();self.tmp.cleanup()

    def test_stable_main_sleep_triggers_before_old_eleven_o_clock(self):
        with patch.object(app,'settings',return_value={'oura_tokens':{'configured':True}}), \
             patch.object(app,'recovery_data',return_value={}), \
             patch.object(app,'fetch_oura') as fetch, \
             patch.object(app,'report',return_value={'recovery':self.recovery}), \
             patch.object(cloud,'_run_daily',return_value=True) as run:
            self.assertFalse(cloud.run_due(app,self.now))
            self.assertFalse(cloud.run_due(app,self.now+dt.timedelta(minutes=14)))
            self.assertTrue(cloud.run_due(app,self.now+dt.timedelta(minutes=15)))
            run.assert_called_once_with(app,self.now+dt.timedelta(minutes=15),enforce_hour=False)
            self.assertEqual(fetch.call_count,2)

    def test_changes_reset_stability_and_persist_across_restart(self):
        with patch.object(app,'settings',return_value={'oura_tokens':{'configured':True}}), \
             patch.object(app,'recovery_data',return_value={}),patch.object(app,'fetch_oura'), \
             patch.object(app,'report',side_effect=lambda _: {'recovery':dict(self.recovery)}), \
             patch.object(cloud,'_run_daily',return_value=True) as run:
            self.assertFalse(cloud.run_due(app,self.now))
            self.recovery['sleep_hours']=8.1
            self.assertFalse(cloud.run_due(app,self.now+dt.timedelta(minutes=15)))
            self.assertTrue(cloud.run_due(app,self.now+dt.timedelta(minutes=30)))
            self.assertEqual(run.call_count,1)

    def test_fragments_stale_dates_missing_scores_and_future_end_do_not_trigger(self):
        for changes in [{'sleep_status':'pending_main'}, {'readiness':None}, {'sleep_score':None},
                        {'bedtime_end':'2026-11-09T09:00:00-05:00'},
                        {'bedtime_end':'2026-11-10T11:00:00-05:00'},
                        {'bedtime_end':'2026-11-10T09:00:00'}]:
            with self.subTest(changes=changes):
                self.assertIsNone(cloud.sleep_candidate({'recovery':{**self.recovery,**changes}},self.now))

    def test_completed_or_failed_day_is_not_automatically_billed_again(self):
        for status in ['complete','failed','running','incomplete']:
            app.save(app.DATA/'cloud-runs.json',{'2026-11-10':{'status':status}})
            with patch.object(app,'fetch_oura') as fetch:
                self.assertFalse(cloud.run_due(app,self.now));fetch.assert_not_called()

    def test_poll_network_failure_retries_only_after_interval_and_never_calls_ai(self):
        with patch.object(app,'settings',return_value={'oura_tokens':{'configured':True}}), \
             patch.object(app,'recovery_data',return_value={}), \
             patch.object(app,'fetch_oura',side_effect=app.AppError('SECRET')) as fetch, \
             patch.object(app,'ai_report') as ai:
            self.assertFalse(cloud.run_due(app,self.now))
            self.assertFalse(cloud.run_due(app,self.now+dt.timedelta(minutes=1)))
            self.assertFalse(cloud.run_due(app,self.now+dt.timedelta(minutes=15)))
            self.assertEqual(fetch.call_count,2);ai.assert_not_called()
            self.assertNotIn('SECRET',(app.DATA/'wake-poll.json').read_text())
            self.assertFalse(app.JOB['running'])

    def test_explicit_retry_keeps_attempt_history_and_cannot_double_click(self):
        app.save(app.DATA/'cloud-runs.json',{'2026-11-10':{'status':'failed','attempts':1}})
        with patch.object(app,'today',return_value=self.now.date()):
            self.assertTrue(cloud.retry(app)['ok'])
            with self.assertRaises(app.AppError):cloud.retry(app)
        record=app.load(app.DATA/'cloud-runs.json')['2026-11-10']
        self.assertEqual(record['attempts'],1);self.assertEqual(record['manual_retries'],1)

    def test_manual_fresh_report_is_reused_and_notification_failure_does_not_destroy_it(self):
        record={'stale':False,'source':'OpenAI / chosen-model'}
        report={'day_context':{'synced':True},'recovery':{'sleep_hours':8},'decision':record}
        with patch.dict('os.environ',{'IRON_SCHEDULE_AI':'1','IRON_SCHEDULE_AI_PROVIDER':'openai'}), \
             patch.object(app,'settings',return_value={'oura_tokens':{'configured':True}}), \
             patch.object(app.providers,'config',return_value={'provider':'openai','label':'OpenAI','model':'chosen-model'}), \
             patch.object(app,'sync'),patch.object(app,'report',return_value=report), \
             patch.object(app,'ai_report') as ai,patch('morning_report.generate'), \
             patch('push.deliver',side_effect=RuntimeError('SECRET')):
            self.assertTrue(cloud._run_daily(app,self.now,enforce_hour=False))
            self.assertFalse(cloud._run_daily(app,self.now,enforce_hour=False))
            ai.assert_not_called()
        saved=app.load(app.DATA/'cloud-runs.json')['2026-11-10']
        self.assertEqual(saved['status'],'complete')
        self.assertEqual(saved['notification']['failed'],1)
        self.assertNotIn('SECRET',str(saved))
