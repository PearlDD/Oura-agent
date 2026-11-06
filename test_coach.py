import datetime as dt
import unittest
import app
import coach
import test_app


def session(date, name='杠铃卧推', rpe=8, reps=8, sets=4):
    return {'date':date,'movements':[{'name':name,'sets':[
        {'done':True,'warmup':False,'rpe':rpe,'reps':reps,'weight_kg':40} for _ in range(sets)]}]}


class CoachTests(unittest.TestCase):
    def test_upper_lower_split_and_low_priority_quads(self):
        p={**coach.DEFAULT_PROFILE,'goal':'hypertrophy','weekdays':[0,2,3,5],
           'minutes':60,'split':'upper_lower','deprioritized_muscles':['quads'],
           'priority_muscles':['glutes','lats'],'confirmed':True}
        sessions=[session('2026-11-01','杠铃深蹲'),session('2026-11-02','器械臀冲'),session('2026-11-03','高位下拉')]
        lower=coach.make_plan('2026-11-09',sessions,[],{},p,[],{},[])
        self.assertEqual(lower['focus'],'lower')
        self.assertTrue(all('quads' not in e['muscles'] for e in lower['exercises']))
        self.assertTrue(any('glutes' in e['muscles'] for e in lower['exercises']))
        upper=coach.make_plan('2026-11-11',sessions,[],{},p,[],{},[])
        self.assertEqual(upper['focus'],'upper')
        self.assertTrue(all('glutes' not in e['muscles'] for e in upper['exercises']))

    def test_shoulder_history_caution_differs_from_pending_review(self):
        p={**coach.DEFAULT_PROFILE,'weekdays':[0,2,3,5],'split':'upper_lower','shoulder_caution':True}
        sessions=[session('2026-11-01','高位下拉')]
        allowed=coach.make_plan('2026-11-11',sessions,[],{},p,[],{},[])
        self.assertEqual(allowed['kind'],'train')
        self.assertEqual(allowed['exercises'][0]['target_rir'],4)
        pending=coach.make_plan('2026-11-11',sessions,[],{}, {**p,'shoulder_review_required':True},[],{},[])
        self.assertEqual(pending['kind'],'review')

    def test_muscle_priority_cannot_contradict_itself(self):
        with self.assertRaises(ValueError):coach.profile({'priority_muscles':['quads'],'deprioritized_muscles':['quads']})

    def test_feedback_is_explicit_and_validated(self):
        f=coach.validate_feedback({'date':'2026-11-05','phase':'pre','fatigue':{'chest':0}})
        self.assertEqual(f['fatigue']['chest'],0)
        for bad in ({},{'chest':True},{'chest':6},{'unknown':2}):
            with self.assertRaises(ValueError):coach.validate_feedback({'date':'2026-11-05','fatigue':bad})

    def test_pre_training_feedback_excludes_same_day_work(self):
        rows=coach.exposures([session('2026-11-05')],{})
        self.assertEqual(coach.residual(rows,'chest','2026-11-05',2,'pre'),0)
        self.assertGreater(coach.residual(rows,'chest','2026-11-05',2,'post'),0)

    def test_sparse_feedback_and_missing_rpe_never_claim_personalized_model(self):
        sessions=[session('2026-10-01',rpe=None)]
        feedback=[{'date':'2026-10-02','phase':'pre','fatigue':{'chest':3}}]
        result=coach.fit(sessions,feedback,{},'2026-11-05')
        self.assertEqual(result['chest']['status'],'collecting')
        self.assertEqual(result['chest']['samples'],1)
        self.assertEqual(coach.active_models([], '2026-11-05'),{})

    def test_calibration_fits_real_labels_with_temporal_holdout(self):
        start=dt.date(2026,9,1)
        sessions=[session((start+dt.timedelta(days=i)).isoformat()) for i in range(0,36,3)]
        rows=coach.exposures(sessions,{})
        feedback=[]
        for i in range(2,36):
            f={'date':(start+dt.timedelta(days=i)).isoformat(),'phase':'pre'}
            f['fatigue']={'chest':round(coach.predict(rows,'chest',f,2.5,.3))}
            feedback.append(f)
        result=coach.fit(sessions,feedback,{},'2026-10-06')['chest']
        self.assertEqual(result['status'],'accepted')
        self.assertLess(result['candidate_mae'],result['baseline_mae'])
        self.assertGreaterEqual(result['validation_samples'],2)
        self.assertLessEqual(abs(result['tau']-2),.5)
        history=[{'models':{'chest':result}}]
        self.assertNotIn('chest',coach.active_models(history,result['trained_through']))
        self.assertIn('chest',coach.active_models(history,result['effective_from']))

    def test_future_feedback_not_used_in_fit(self):
        f={'date':'2026-11-06','phase':'pre','fatigue':{'chest':5}}
        self.assertEqual(coach.fit([], [f], {}, '2026-11-05')['chest']['samples'],0)

    def test_correcting_evidence_invalidates_prior_fit(self):
        start=dt.date(2026,9,1)
        sessions=[session((start+dt.timedelta(days=i)).isoformat()) for i in range(0,36,3)]
        rows=coach.exposures(sessions,{})
        feedback=[]
        for i in range(2,36):
            f={'date':(start+dt.timedelta(days=i)).isoformat(),'phase':'pre'}
            f['fatigue']={'chest':round(coach.predict(rows,'chest',f,2.5,.3))};feedback.append(f)
        state=coach.run('2026-10-06',sessions,[],{}, {},feedback,{}, {})
        self.assertTrue(state['calibrations'])
        feedback[0]['fatigue']['chest']=5-feedback[0]['fatigue']['chest']
        corrected=coach.run('2026-10-06',sessions,[],{}, {},feedback,{},state)
        self.assertTrue(corrected['calibrations'][0]['invalidated'])
        self.assertTrue(any('停用' in e['message'] for e in corrected['events']))

    def test_profile_goal_changes_rep_draft_and_does_not_force_heavier_weight(self):
        sessions=[session('2026-11-02',reps=12)]
        p={**coach.DEFAULT_PROFILE,'weekdays':[3]}
        strength=coach.make_plan('2026-11-05',sessions,[],{}, {**p,'goal':'strength'},[],{},[])
        hypertrophy=coach.make_plan('2026-11-05',sessions,[],{}, {**p,'goal':'hypertrophy'},[],{},[])
        self.assertEqual(strength['exercises'][0]['reps'],6)
        self.assertEqual(hypertrophy['exercises'][0]['reps'],12)
        self.assertEqual(strength['exercises'][0]['reference_kg'],hypertrophy['exercises'][0]['reference_kg'])

    def test_daily_run_is_idempotent_and_accepted_plan_is_preserved(self):
        p={**coach.DEFAULT_PROFILE,'confirmed':True,'weekdays':[3]}
        sessions=[session('2026-11-02')]
        first=coach.run('2026-11-05',sessions,[],{},p,[],{}, {})
        again=coach.run('2026-11-05',sessions,[],{},p,[],{},first)
        self.assertEqual(first,again)
        accepted=again['plans']['2026-11-05'];accepted['status']='accepted'
        old=list(accepted['exercises'])
        changed=coach.run('2026-11-05',sessions,[],{}, {**p,'excluded_muscles':['chest']},[],{},again)
        plan=changed['plans']['2026-11-05']
        self.assertEqual(plan['exercises'],old)
        self.assertEqual(plan['revision_proposal']['kind'],'review')

    def test_tracking_distinguishes_unknown_partial_and_logged_completion(self):
        p={'date':'2026-11-05','kind':'train','exercises':[{'name':'杠铃卧推','sets':2}]}
        self.assertEqual(coach.tracking(p,[],[])['status'],'unknown')
        self.assertEqual(coach.tracking(p,[],['2026-11-05'])['status'],'not_observed')
        self.assertEqual(coach.tracking(p,[session('2026-11-05',sets=1)],['2026-11-05'])['status'],'partial')
        self.assertEqual(coach.tracking(p,[session('2026-11-05',sets=2)],['2026-11-05'])['status'],'observed_complete')

    def test_limits_and_local_discomfort_are_respected(self):
        p={**coach.DEFAULT_PROFILE,'weekdays':[3],'excluded_muscles':['chest']}
        plan=coach.make_plan('2026-11-05',[session('2026-11-02')],[],{},p,[],{},[])
        self.assertEqual(plan['kind'],'review')
        f={'date':'2026-11-05','phase':'pre','fatigue':{'chest':2},'discomfort':True}
        plan=coach.make_plan('2026-11-05',[session('2026-11-02')],[],{}, {**p,'excluded_muscles':[]},[f],{},[])
        self.assertEqual(plan['kind'],'review')

    def test_performance_feedback_changes_draft_without_increasing_weight(self):
        p={**coach.DEFAULT_PROFILE,'weekdays':[3],'confirmed':True}
        sessions=[session('2026-11-01'),session('2026-11-03')]
        feedback=[{'date':d,'phase':'post','performance':'above','fatigue':{'chest':1},'discomfort':False} for d in ('2026-11-01','2026-11-03')]
        plan=coach.make_plan('2026-11-05',sessions,[],{},p,feedback,{},[])
        self.assertEqual(plan['exercises'][0]['reps'],9)
        self.assertEqual(plan['exercises'][0]['reference_kg'],40)
        feedback[-1]['performance']='below'
        plan=coach.make_plan('2026-11-05',sessions,[],{},p,feedback,{},[])
        self.assertEqual(plan['exercises'][0]['sets'],1)
        self.assertEqual(plan['exercises'][0]['target_rir'],4)


class CoachStorageTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown

    def test_feedback_updates_in_place_and_does_not_touch_checkins(self):
        app.save(app.DATA/'checkins.json',{'2026-11-05':{'note':'keep'}})
        date=app.today().isoformat()
        app.coach_action({'action':'feedback','date':date,'fatigue':{'chest':3}})
        app.coach_action({'action':'feedback','date':date,'fatigue':{'chest':2}})
        rows=app.load(app.DATA/'feedback.json')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['fatigue']['chest'],2)
        self.assertEqual(app.load(app.DATA/'checkins.json')['2026-11-05']['note'],'keep')

    def test_future_feedback_and_stale_plan_version_rejected(self):
        with self.assertRaises(app.AppError):app.coach_action({'action':'feedback','date':(app.today()+dt.timedelta(days=1)).isoformat(),'fatigue':{'chest':2}})
        app.run_coach()
        date=app.today().isoformat()
        with self.assertRaises(app.AppError):app.coach_action({'action':'plan_status','date':date,'version':999,'status':'accepted'})


if __name__=='__main__':unittest.main()
