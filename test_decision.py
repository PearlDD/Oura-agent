import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import decision


def sample():
    return {'verdict':'rest','headline':'保持今天的休息安排','rationale':'综合症状和恢复背景，等待重新评估。',
            'evidence':[{'statement':'本日有可用记录','refs':['/date']}],
            'options':[{'mode':'rest','when':'仍有不适','details':'保留休息安排'}],
            'muscle_review':[],'short_term':[],'long_term':[],'questions':['今天是否仍有不适？'],
            'confidence':'low','adjustment':None}


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(app,'DATA',Path(self.tmp.name));self.p.start()
        app.run_coach('2026-11-06')
    def tearDown(self):self.p.stop();self.tmp.cleanup()
    def test_provenance_stale_on_health_update_and_export(self):
        ctx=app.analysis_context('2026-11-06');h=decision.fingerprint(ctx)
        app.store_decision('2026-11-06',sample(),h)
        self.assertFalse(app.report('2026-11-06')['decision']['stale'])
        app.save_health({'date':'2026-11-06','strain':'minor','cycle':'recently_ended','symptoms':'今天未知'})
        r=app.report('2026-11-06')
        self.assertTrue(r['decision']['stale']);self.assertIn('历史分析',app.markdown(r))
        with self.assertRaises(app.AppError):app.store_decision('2026-11-06',sample(),h)
        self.assertEqual(r['health_observations']['history'][0]['source'],'user_report')
        self.assertNotIn('cycle',r['recovery'])
    def test_evidence_and_confidence_guard(self):
        ctx=app.analysis_context('2026-11-06');v=sample();v['evidence'][0]['refs']=['/invented']
        with self.assertRaises(ValueError):decision.validate(v,ctx)
        v=sample();v['confidence']='high'
        with self.assertRaises(ValueError):decision.validate(v,ctx)
    def test_adjustment_conservative_version_and_accept_stale(self):
        d='2026-11-06';p={'date':d,'version':1,'status':'accepted','kind':'train','exercises':[{'name':'划船','sets':3,'reps':10,'target_rir':3}],'reasons':[]}
        app.save(app.DATA/'coach-state.json',{'plans':{d:p}})
        v=sample();v['adjustment']={'date':d,'version':1,'kind':'train','exercises':[{'name':'划船','sets':2,'reps':8,'target_rir':4}]}
        c=app.analysis_context(d);app.store_decision(d,v,decision.fingerprint(c));app.propose_decision(d)
        self.assertEqual(app.load(app.DATA/'coach-state.json')['plans'][d]['exercises'][0]['sets'],3)
        self.assertFalse(app.current_decision(d)['stale'])
        v2=copy.deepcopy(v);v2['adjustment']['exercises'][0]['sets']=4
        with self.assertRaises(ValueError):decision.validate(v2,c)
        app.save_health({'date':d,'strain':'major'})
        with self.assertRaises(app.AppError):app.coach_action({'action':'plan_status','date':d,'version':1,'status':'accept_revision'})
    def test_contributors_preserved_and_no_phase_inference(self):
        app.save(app.DATA/'oura/daily_readiness.json',{'data':[{'day':'2026-11-06','contributors':{'recovery_index':95},'temperature_deviation':0.03}]})
        r=app.recovery_data()['2026-11-06'];self.assertEqual(r['readiness_contributors']['recovery_index'],95)
        self.assertNotIn('cycle',r);self.assertEqual(app.health_context('2026-11-06')['history'],[])

class SnapshotFingerprintTests(unittest.TestCase):
    def context(self):
        return {'date':'2026-11-13','recovery':{'sleep_hours':8,'hrv':50,'activity':{'steps':100,'sedentary_time':90}},'recovery_history':[{'date':'2026-11-12','activity':{'steps':8000}},{'date':'2026-11-13','activity':{'steps':100}}],'plans':{'version':1},'training_history':[],'checkin':{},'health_observations':{}}

    def test_intraday_counters_do_not_invalidate_or_modify_context(self):
        old=self.context();new=copy.deepcopy(old)
        new['recovery']['activity']['steps']=150;new['recovery_history'][1]['activity']['steps']=150
        self.assertEqual(decision.fingerprint(old),decision.fingerprint(new))
        self.assertEqual(old['recovery']['activity']['steps'],100)

    def test_sleep_recovery_training_feedback_plan_and_completed_activity_still_invalidate(self):
        old=self.context()
        for change in (lambda x:x['recovery'].update(sleep_hours=9),lambda x:x['recovery'].update(hrv=45),lambda x:x['plans'].update(version=2),lambda x:x['training_history'].append({'sets':3}),lambda x:x['checkin'].update(energy=2),lambda x:x['health_observations'].update(symptoms='changed'),lambda x:x['recovery_history'][0]['activity'].update(steps=9000)):
            new=copy.deepcopy(old);change(new)
            self.assertNotEqual(decision.fingerprint(old),decision.fingerprint(new))

    def test_legacy_hash_is_compatible_only_with_verified_original_snapshot(self):
        old=self.context();stored=decision.legacy_fingerprint(old);snapshot={'data_hash':stored,'context':old}
        new=copy.deepcopy(old);new['recovery']['activity']['steps']=200
        self.assertEqual(decision.compatible_hash(stored,new,snapshot),decision.fingerprint(new))
        self.assertEqual(decision.compatible_hash(stored,new,{}),stored)
        bad=copy.deepcopy(snapshot);bad['context']['plans']['version']=4
        self.assertEqual(decision.compatible_hash(stored,new,bad),stored)
        new['recovery']['sleep_hours']=9
        self.assertEqual(decision.compatible_hash(stored,new,snapshot),stored)

    def test_saved_legacy_analysis_recovers_without_model_call_and_keeps_original_audit(self):
        old=self.context();stored=decision.legacy_fingerprint(old);new=copy.deepcopy(old);new['recovery']['activity']['steps']=300
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DATA',Path(folder)),patch.object(app,'analysis_context',return_value=new),patch.object(app,'ai_report') as ai:
            app.save(app.DATA/'decisions'/'2026-11-13.json',{'data_hash':stored,'analysis':sample()})
            app.save(app.DATA/'agent-context'/'2026-11-13.json',{'data_hash':stored,'context':old})
            self.assertFalse(app.current_decision('2026-11-13')['stale'])
            migrated=app.load(app.DATA/'decisions'/'2026-11-13.json')
            self.assertEqual(migrated['original_data_hash'],stored)
            self.assertEqual(migrated['data_hash'],decision.fingerprint(new))
            app.save(app.DATA/'agent-context'/'2026-11-13.json',{'data_hash':decision.fingerprint(new),'context':new})
            self.assertFalse(app.current_decision('2026-11-13')['stale'])
            new['recovery']['sleep_hours']=9
            self.assertTrue(app.current_decision('2026-11-13')['stale']);ai.assert_not_called()
