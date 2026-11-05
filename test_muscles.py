import datetime as dt
import unittest
import muscles
import test_app
import app


def session(d='2026-11-05', name='杠铃卧推', rpe=8, done=True, warmup=False):
    return {'date': d, 'movements': [{'name': name, 'sets': [
        {'done': done, 'warmup': warmup, 'rpe': rpe, 'weight_kg': None, 'reps': 8}]}]}


def row(m, key):
    return next(x for x in m['muscles'] if x['key'] == key)


class MuscleTests(unittest.TestCase):
    def test_direct_and_indirect_sets_do_not_depend_on_tonnage(self):
        value = muscles.model([session()], ['2026-11-05'], '2026-11-05')
        self.assertEqual(row(value, 'chest')['direct_sets'], 1)
        self.assertEqual(row(value, 'triceps')['indirect_sets'], .5)
        self.assertEqual(row(value, 'chest')['residual_low'], .8)
        self.assertEqual(value['counts']['strength'], 1)

    def test_mobility_support_unknown_and_unfinished_sets_are_not_strength(self):
        sessions = [session(name='猫式伸展'), session(name='外旋阻力带'),
                    session(name='未识别动作'), session(done=False), session(warmup=True)]
        value = muscles.model(sessions, [], '2026-11-05')
        self.assertEqual(value['counts'], {'strength': 0, 'support': 1, 'mobility': 1, 'unmapped': 1, 'with_rpe': 0})
        self.assertEqual(value['unknown'][0]['name'], '未识别动作')
        self.assertEqual(value['muscles'], [])

    def test_missing_rpe_is_an_interval_and_fatigue_decays(self):
        sessions = [session(d='2026-11-03', rpe=None)]
        value = muscles.model(sessions, [], '2026-11-05')
        chest = row(value, 'chest')
        self.assertEqual(chest['residual_low'], .3)
        self.assertEqual(chest['residual_high'], .5)
        slower = muscles.model(sessions, [], '2026-11-05', {'half_life_days': 4})
        self.assertGreater(row(slower, 'chest')['residual_high'], chest['residual_high'])
        self.assertIsNone(chest['soreness'])

    def test_future_records_and_window_boundary_are_excluded(self):
        value = muscles.model([session(d='2026-11-06'), session(d='2026-10-08'), session(d='2026-11-05')], [], '2026-11-05')
        self.assertEqual(value['counts']['strength'], 1)

    def test_custom_mapping_and_explicit_zero_soreness(self):
        config = {'exercises': {'外旋阻力带': {'kind': 'strength', 'weights': {'rotator_cuff': 1}}}}
        value = muscles.model([session(name='外旋阻力带')], [], '2026-11-05', config, {'rotator_cuff': 0})
        self.assertEqual(value['counts']['strength'], 1)
        self.assertEqual(row(value, 'rotator_cuff')['soreness'], 0)
        self.assertEqual(value['exercises'][0]['source'], 'user')

    def test_local_soreness_does_not_change_physical_load_estimate(self):
        a = muscles.model([session()], [], '2026-11-05')
        b = muscles.model([session()], [], '2026-11-05', soreness={'chest': 4})
        self.assertEqual(row(a, 'chest')['residual_high'], row(b, 'chest')['residual_high'])
        self.assertIn('胸', b['focus'])
        self.assertIn('酸痛', b['focus'])

    def test_complete_weeks_required_for_reference_and_week_change(self):
        date = dt.date(2026, 11, 5)
        days = [(date-dt.timedelta(days=i)).isoformat() for i in range(28)]
        sessions = [session(d=days[i]) for i in (0, 7, 14, 21)]
        value = muscles.model(sessions, days, date.isoformat())
        chest = row(value, 'chest')
        self.assertEqual(chest['usual_week'], 1)
        self.assertEqual(chest['reference_weeks'], 3)
        self.assertEqual(chest['week_change'], 0)
        sparse = muscles.model(sessions, days[:7], date.isoformat())
        self.assertIsNone(row(sparse, 'chest')['usual_week'])
        self.assertIsNone(row(sparse, 'chest')['week_change'])

    def test_mapping_validation_and_unicode_alias(self):
        self.assertEqual(muscles.mapping('引体向上(辅助)_背部训练', {})['weights']['lats'], 1)
        for bad in ({'kind': 'strength', 'weights': {}}, {'kind': 'strength', 'weights': {'chest': 2}},
                    {'kind': 'strength', 'weights': {'chest': True}}, {'kind': 'bad'}):
            with self.assertRaises(ValueError):
                muscles.validate_mapping(bad)


class MusclePersistenceTests(unittest.TestCase):
    setUp = test_app.AppTests.setUp
    tearDown = test_app.AppTests.tearDown
    def test_muscle_settings_preserve_other_mappings_and_reset(self):
        app.save_muscle_config({'half_life_days': 3})
        app.save_muscle_config({'name': '自定义动作', 'kind': 'strength', 'weights': {'chest': 1}})
        config = app.load(app.DATA/'muscles.json')
        self.assertEqual(config['half_life_days'], 3)
        self.assertEqual(config['exercises']['自定义动作']['weights'], {'chest': 1})
        app.save_muscle_config({'name': '自定义动作', 'reset': True})
        self.assertEqual(app.load(app.DATA/'muscles.json')['exercises'], {})
        with self.assertRaises(app.AppError):
            app.save_muscle_config({'half_life_days': 0})

    def test_soreness_validation_and_old_clients_preserve_muscle_entries(self):
        body = {'date': '2026-11-05', 'energy': 3, 'soreness': 0, 'muscle_soreness': {'chest': 0, 'quads': 4}}
        app.save_checkin(body)
        del body['muscle_soreness']
        app.save_checkin(body)
        self.assertEqual(app.load(app.DATA/'checkins.json')['2026-11-05']['muscle_soreness']['quads'], 4)
        for bad in ({'quads': 6}, {'quads': True}, {'unknown': 2}):
            with self.assertRaises(app.AppError):
                app.save_checkin({**body, 'muscle_soreness': bad})


if __name__ == '__main__':
    unittest.main()
