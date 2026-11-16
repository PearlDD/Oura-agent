import copy,datetime as dt,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,program,coach,decision
from test_decision import sample


def source():
    def template(name,reps=10):return {'name':name,'source_date':'2026-09-28','movements':[{'name':'Synthetic lift','role':'strength','prescribed_sets':[{'reps':reps,'seconds':None,'warmup':False,'reference_load':'40 lb'},{'reps':8,'seconds':None,'warmup':False,'reference_load':'45 lb'}]},{'name':'Timed preparation','role':'preparation','prescribed_sets':[{'reps':None,'seconds':45,'warmup':False,'reference_load':''}]}]}
    return {'name':'Synthetic cycle','anchor_date':'2026-11-16','cycle':['pull',None,'posterior','shoulder',None,'lower',None],'templates':{k:template(k) for k in ('pull','posterior','shoulder','lower')},'shift_rule':'shift_all','source':'Synthetic test fixture'}


class ProgramTests(unittest.TestCase):
    def active(self):return {**program.validate(source()),'confirmed':True}
    def test_exact_cycle_and_variable_sets_preserved_without_invented_rir(self):
        active=self.active()
        days=[program.make_day(active,(dt.date(2026,11,16)+dt.timedelta(days=i)).isoformat()) for i in range(8)]
        self.assertEqual([d['template_name'] for d in days],['pull','休息日','posterior','shoulder','休息日','lower','休息日','pull'])
        e=days[0]['exercises'][0];self.assertEqual([s['reps'] for s in e['prescribed_sets']],[10,8]);self.assertIsNone(e['target_rir']);self.assertIsNone(e['reference_kg'])
        self.assertEqual(days[0]['exercises'][1]['prescribed_sets'][0]['seconds'],45)
        self.assertIsNone(program.make_day(active,'2026-11-15'))
        self.assertIsNone(program.make_day(program.validate(source()),'2026-11-16'))

    def test_entire_cycle_shifts_only_after_confirmation_and_is_deduplicated(self):
        active=self.active();shifted=program.shift(active,'2026-11-16',1)
        self.assertTrue(program.scheduled(shifted,'2026-11-16')['rest'])
        self.assertEqual(program.make_day(shifted,'2026-11-17')['template_name'],'pull')
        self.assertEqual(program.make_day(shifted,'2026-11-18')['kind'],'rest')
        self.assertEqual(program.make_day(shifted,'2026-11-19')['template_name'],'posterior')
        with self.assertRaises(ValueError):program.shift(shifted,'2026-11-16',2)
        with self.assertRaises(ValueError):program.shift(active,'2026-11-17',1)
        with self.assertRaises(ValueError):program.shift(active,'2026-11-16',True)
        self.assertEqual(active['shifts'],[])

    def test_imported_cycle_overrides_weekdays_and_no_missing_log_auto_shift(self):
        active=self.active();state=coach.run('2026-11-16',[],[],{},coach.DEFAULT_PROFILE,[],{},None,active)
        self.assertEqual(state['plans']['2026-11-18']['template_name'],'posterior')
        self.assertEqual(state['plans']['2026-11-16']['tracking']['status'],'unknown')
        self.assertEqual(active['shifts'],[])
        again=coach.run('2026-11-16',[],[],{},coach.DEFAULT_PROFILE,[],{},state,active)
        self.assertEqual(state,again)

    def test_invalid_or_oversized_program_does_not_validate(self):
        for mutate in (lambda x:x.update(cycle=['missing']),lambda x:x.update(templates={}),lambda x:x['templates']['pull']['movements'][0]['prescribed_sets'][0].update(reps=-1),lambda x:x.update(api_key='SECRET')):
            value=source();mutate(value)
            with self.assertRaises((ValueError,KeyError)):program.validate(value)

    def test_activation_archives_old_plan_and_requires_exact_preview_confirmation(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DATA',Path(folder)):
            app.program_action({'action':'preview','program':source()})
            draft=app.load(app.DATA/'source-program.json')['draft']
            with self.assertRaises(app.AppError):app.program_action({'action':'activate','id':draft['id']})
            app.save(app.DATA/'coach-state.json',{'plans':{'2026-11-16':{'date':'2026-11-16','kind':'train','status':'accepted','exercises':[],'version':7}}})
            with patch.object(app,'today',return_value=dt.date(2026,11,16)):
                app.program_action({'action':'activate','id':draft['id'],'confirmed':True})
            state=app.load(app.DATA/'coach-state.json');p=state['plans']['2026-11-16']
            self.assertEqual(p['template_name'],'pull');self.assertGreater(p['version'],7)
            self.assertTrue(list((app.DATA/'program-plan-archive').glob('*.json')))
            with patch.object(app,'today',return_value=dt.date(2026,11,16)):
                with self.assertRaises(app.AppError):app.program_action({'action':'shift','date':'2026-11-16','version':1})
                app.program_action({'action':'shift','date':'2026-11-16','version':1,'confirmed':True})
            self.assertEqual(app.load(app.DATA/'coach-state.json')['plans']['2026-11-17']['template_name'],'pull')

    def test_unknown_rir_import_cannot_receive_automatic_exercise_replacement(self):
        p=program.make_day(self.active(),'2026-11-16');ctx={'date':'2026-11-16','plans':{'2026-11-16':p},'checkin':{},'feedback':[],'recovery':{}}
        v=sample();v['adjustment']={'date':'2026-11-16','version':1,'kind':'train','exercises':[{'name':'Synthetic lift','sets':1,'reps':8,'target_rir':3}]}
        with self.assertRaises(ValueError):decision.validate(v,ctx)
        v['adjustment']['kind']='rest';v['adjustment']['exercises']=[]
        self.assertEqual(decision.validate(v,ctx)['adjustment']['kind'],'rest')

    def test_overdue_unverified_training_is_followup_not_an_assumed_missed_day(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DATA',Path(folder)):
            app.save(app.DATA/'source-program.json',{'active':self.active()})
            app.run_coach('2026-11-16');app.run_coach('2026-11-17')
            view=app.coach_view('2026-11-17')
            self.assertEqual(view['source_program']['pending_followup'][0]['date'],'2026-11-16')
            self.assertEqual(view['source_program']['active']['shifts'],[])
            state=app.load(app.DATA/'coach-state.json');state['plans']['2026-11-16']['status']='completed';app.save(app.DATA/'coach-state.json',state)
            self.assertEqual(app.coach_view('2026-11-17')['source_program']['pending_followup'],[])
            self.assertEqual(app.report('2026-11-17')['week']['sets'],0)
