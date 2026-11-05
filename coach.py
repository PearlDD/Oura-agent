"""Local feedback, out-of-sample calibration, planning and follow-up primitives.

Forecasts perceived fatigue, not physiological recovery. No provider writes or LLM calls.
"""
import datetime as dt
import hashlib
import json
import math
import statistics
import muscles

DEFAULT_PROFILE = {'goal': 'balanced', 'weekdays': [0, 2, 4], 'minutes': 45,
                   'excluded_muscles': [], 'excluded_exercises': [], 'confirmed': False}


def profile(value):
    result = {**DEFAULT_PROFILE, **value}
    if result['goal'] not in ('hypertrophy', 'strength', 'balanced'):
        raise ValueError('训练目标无效。')
    days = result['weekdays']
    if not isinstance(days, list) or not 1 <= len(days) <= 5 or any(type(d) is not int or d not in range(7) for d in days) or len(set(days)) != len(days):
        raise ValueError('请选择每周 1–5 个不重复训练日。')
    if type(result['minutes']) is not int or not 20 <= result['minutes'] <= 120:
        raise ValueError('每次训练时间须为 20–120 分钟。')
    if not isinstance(result['excluded_muscles'], list) or any(k not in muscles.GROUPS for k in result['excluded_muscles']):
        raise ValueError('需避开的肌群无效。')
    if not isinstance(result['excluded_exercises'], list) or any(not isinstance(x, str) or len(x)>200 for x in result['excluded_exercises']):
        raise ValueError('需避开的动作无效。')
    return {k: result[k] for k in DEFAULT_PROFILE}


def validate_feedback(value):
    date = dt.date.fromisoformat(str(value.get('date'))).isoformat()
    phase = value.get('phase', 'pre')
    fatigue = value.get('fatigue', {})
    if phase not in ('pre', 'post') or not isinstance(fatigue, dict) or not fatigue:
        raise ValueError('请选择训练前或训练后，并至少填写一个肌群疲劳评分。')
    if any(k not in muscles.GROUPS or type(v) is not int or not 0 <= v <= 5 for k,v in fatigue.items()):
        raise ValueError('肌群疲劳评分须为 0–5 的整数。')
    performance = value.get('performance', 'unknown')
    if performance not in ('below', 'expected', 'above', 'unknown'):
        raise ValueError('表现反馈无效。')
    return {'date': date, 'phase': phase, 'fatigue': fatigue, 'performance': performance,
            'discomfort': value.get('discomfort') is True}


def exposures(sessions, config):
    rows = []
    for t in sessions:
        amounts, known, total, muscle_known, muscle_total = {}, 0, 0, {}, {}
        for move in t['movements']:
            mapped = muscles.mapping(move['name'], config.get('exercises', {}))
            if mapped['kind'] != 'strength':
                continue
            for s in move['sets']:
                if not s['done'] or s['warmup']:
                    continue
                total += 1
                known += s.get('rpe') is not None
                effort = s['rpe']/10 if s.get('rpe') is not None else .8
                for k,w in mapped['weights'].items():
                    amounts[k] = amounts.get(k, 0) + w*effort
                    muscle_total[k]=muscle_total.get(k,0)+1
                    muscle_known[k]=muscle_known.get(k,0)+(s.get('rpe') is not None)
        if amounts:
            rows.append({'date': t['date'], 'amounts': amounts, 'rpe_known': known, 'sets': total,
                         'muscle_known':muscle_known,'muscle_total':muscle_total})
    return rows


def residual(rows, key, date, tau, phase='pre'):
    anchor = dt.date.fromisoformat(date)
    return sum(t['amounts'].get(key,0)*2**(-(anchor-dt.date.fromisoformat(t['date'])).days/tau)
               for t in rows if 0 <= (anchor-dt.date.fromisoformat(t['date'])).days < 28
               and (phase == 'post' or t['date'] < date))


def predict(rows, key, observation, tau, gain):
    return 5*(1-math.exp(-gain*residual(rows,key,observation['date'],tau,observation['phase'])))


def fit(sessions, feedback, config, asof, previous=None):
    previous = previous or {}
    rows = exposures([t for t in sessions if t['date']<=asof],config)
    results = {}
    for key in muscles.GROUPS:
        # At most one observation per day: prefer pre-training feedback.
        daily = {}
        for f in sorted(feedback, key=lambda f:(f['date'],f['phase']=='pre')):
            if f['date']<=asof and key in f['fatigue']:
                daily[f['date']]=f
        obs = [daily[d] for d in sorted(daily)]
        relevant = [t for t in rows if t['amounts'].get(key,0)>0 and any(0<=(dt.date.fromisoformat(f['date'])-dt.date.fromisoformat(t['date'])).days<=7 for f in obs)]
        known = sum(t['muscle_known'].get(key,0) for t in relevant)
        sets = sum(t['muscle_total'].get(key,0) for t in relevant)
        episodes = len({t['date'] for t in relevant})
        old = previous.get(key, {})
        tau, gain = old.get('tau',config.get('half_life_days',2)), old.get('gain',.15)
        base = {'key':key,'name':muscles.GROUPS[key],'samples':len(obs),'episodes':episodes,
                'rpe_coverage':round(known/sets,2) if sets else 0,'tau':tau,'gain':gain,
                'status':'collecting','reason':'需至少 10 个不同日期的局部疲劳反馈、3 次相关训练，且相关训练至少一半正式组有 RPE。'}
        if len(obs)<10 or episodes<3 or not sets or known/sets<.5:
            results[key]=base
            continue
        holdout=max(2,len(obs)//5)
        train,valid=obs[:-holdout],obs[-holdout:]
        def mae(points,t,g):
            return statistics.mean(abs(predict(rows,key,f,t,g)-f['fatigue'][key]) for f in points)
        # Regularization favors modest change from the existing estimate.
        candidates=[(t,g) for t in (1.,1.5,2.,2.5,3.,4.) for g in (.05,.1,.15,.2,.3,.5)]
        candidate=min(candidates,key=lambda x:mae(train,*x)+.03*abs(x[0]-tau)+.05*abs(x[1]-gain))
        old_error,new_error=mae(valid,tau,gain),mae(valid,*candidate)
        accepted = new_error+.1<old_error and new_error<=old_error*.9
        base.update({'status':'accepted' if accepted else 'retained','validation_samples':holdout,
                     'baseline_mae':round(old_error,3),'candidate_mae':round(new_error,3),
                     'reason':'候选在按时间留出的反馈中改善，通过软件验证门槛。' if accepted else '候选未在留出反馈中稳定改善，保留现有参数。',
                     'trained_through':obs[-1]['date'],
                     'effective_from':(dt.date.fromisoformat(obs[-1]['date'])+dt.timedelta(days=1)).isoformat()})
        if accepted:
            # Bounded change per accepted update; gain does not enter the workload index.
            base['tau']=round(max(tau-.5,min(tau+.5,candidate[0])),2)
            base['gain']=candidate[1]
            bounded_error=mae(valid,base['tau'],base['gain'])
            if not (bounded_error+.1<old_error and bounded_error<=old_error*.9):
                base.update(status='retained',tau=tau,gain=gain,reason='限制参数步长后改善不足，保留现有参数。')
            base['candidate_mae']=round(bounded_error,3)
        results[key]=base
    return results


def active_models(history, asof):
    result = {}
    for version in history:
        if version.get('invalidated'):continue
        for key,m in version.get('models',{}).items():
            if m['status']=='accepted' and m['effective_from']<=asof:
                result[key]=m
    return result


def personalized_config(config, history, asof):
    active=active_models(history,asof)
    return {**config,'half_life_by_muscle':{k:v['tau'] for k,v in active.items()},'calibration_by_muscle':active}


def tracking(plan,sessions,fetched):
    if plan['kind']=='rest':
        return {'status':'rest','message':'计划休息；实际训练仍以日志为准。'}
    if plan['kind']=='review':
        return {'status':'review','message':'动作草案待核对，尚未作为训练安排跟进。'}
    if plan['date'] not in fetched:
        return {'status':'unknown','message':'该日数据尚未读取，不能判定未执行。'}
    actual={}
    for t in sessions:
        if t['date']==plan['date']:
            for m in t['movements']:
                actual[m['name']]=actual.get(m['name'],0)+sum(s['done'] and not s['warmup'] for s in m['sets'])
    targets=plan.get('exercises',[])
    done=sum(min(actual.get(e['name'],0),e['sets']) for e in targets)
    total=sum(e['sets'] for e in targets)
    status='observed_complete' if total and done>=total else 'partial' if done else 'not_observed'
    return {'status':status,'matched_sets':done,'target_sets':total,
            'message':f'日志匹配 {done}/{total} 个计划正式组；匹配只核对动作名与组数。'}


def candidates(sessions,config,p):
    templates=[]
    excluded=set(p['excluded_exercises'])
    for t in sorted(sessions,key=lambda t:t['date'],reverse=True):
        selected=[]
        for m in t['movements']:
            mapped=muscles.mapping(m['name'],config.get('exercises',{}))
            work=[s for s in m['sets'] if s['done'] and not s['warmup']]
            if mapped['kind']!='strength' or not work or m['name'] in excluded or set(mapped['weights'])&set(p['excluded_muscles']):
                continue
            reps=[s['reps'] for s in work if s.get('reps') is not None and 3<=s['reps']<=30]
            weights=[s['weight_kg'] for s in work if s.get('weight_kg') is not None and s['weight_kg']>=0]
            selected.append({'name':m['name'],'sets':min(2,len(work)),
                             'reps':int(statistics.median(reps)) if reps else 8,
                             'reference_kg':round(statistics.median(weights),1) if weights else None,
                             'target_rir':3,'muscles':mapped['weights'],'source_date':t['date']})
        if selected:
            # Time budget is a rough planning bound, not measured workout duration.
            budget=max(1,(p['minutes']-10)//5)
            trimmed=[]
            for e in selected:
                if budget<=0:break
                item={**e,'sets':min(e['sets'],budget)};trimmed.append(item);budget-=item['sets']
            sig=tuple(e['name'] for e in trimmed)
            if not any(tuple(e['name'] for e in x)==sig for x in templates):
                templates.append(trimmed)
    return templates


def make_plan(d,sessions,fetched,config,p,feedback,checks,history,forecast=None):
    p=profile(p)
    date=dt.date.fromisoformat(d)
    observations=[f for f in feedback if f['date']==d and f['phase']=='pre']
    fatigue={k:v for f in observations for k,v in f['fatigue'].items()}
    discomfort=any(f.get('discomfort',False) for f in observations)
    current=checks.get(d,{})
    scheduled=date.weekday() in p['weekdays']
    if current.get('plan')=='rest':scheduled=False
    if current.get('plan')=='train':scheduled=True
    base={'date':d,'kind':'train' if scheduled else 'rest','status':'draft','profile_confirmed':p['confirmed'],
          'exercises':[],'reasons':[],'version':1}
    if not p['confirmed']:base['reasons'].append('训练偏好尚未确认：暂按每周一/三/五、45 分钟、两者兼顾起草。')
    if not scheduled:
        base['reasons'].append('按可训练日或你保存的当日计划安排休息。');return base
    if discomfort:
        base.update(kind='review');base['reasons'].append('本日反馈存在不适，暂停自动生成动作，先核对需避开的动作和肌群。');return base
    templates=candidates([t for t in sessions if t['date']<d],config,p)
    if not templates:
        base.update(kind='review');base['reasons'].append('没有符合限制且已归类的历史力量动作，请先校准动作归属。');return base
    local=muscles.model(sessions+(forecast or []),fetched,d,personalized_config(config,history,d))
    load={m['key']:m['residual_high']+(m.get('fatigue_estimate') or 0) for m in local['muscles']}
    def score(template):
        return sum(w*(load.get(k,0)+2*fatigue.get(k,0)+current.get('muscle_soreness',{}).get(k,0)) for e in template for k,w in e['muscles'].items())/max(1,len(template))
    chosen=min(templates,key=score)
    selected=[]
    for original in chosen:
        e=dict(original)
        rep_low,rep_high={'strength':(3,6),'hypertrophy':(6,15),'balanced':(6,12)}[p['goal']]
        e['reps']=max(rep_low,min(rep_high,e['reps']))
        e['adaptation']='按目标范围起草；保留历史负重参考。'
        involved=list(e['muscles'])
        high=max([fatigue.get(k,0) for k in involved]+[current.get('muscle_soreness',{}).get(k,0) for k in involved])
        if high>=4:continue
        if high>=3 or current.get('energy',3)<=2:
            e['sets']=max(1,e['sets']-1);e['target_rir']=4
            e['adaptation']='根据明确的局部/精神反馈减少组数并增加预留次数。'
        else:
            past=[]
            for t in sorted(sessions,key=lambda t:t['date'],reverse=True):
                moves=[m for m in t['movements'] if m['name']==e['name']]
                work=[s for m in moves for s in m['sets'] if s['done'] and not s['warmup']]
                if work:
                    f=next((f for f in feedback if f['date']==t['date'] and f['phase']=='post'),{})
                    past.append((work,f))
                if len(past)==2:break
            if past and past[0][1].get('performance')=='below':
                e['sets']=max(1,e['sets']-1);e['target_rir']=4
                e['adaptation']='上次同动作对应的训练后表现低于预期，先减少一组并跟进。'
            elif len(past)==2 and all(f.get('performance')=='above' and not f.get('discomfort')
                 and all(s.get('rpe') is not None and s['rpe']<=8 for s in work) for work,f in past):
                e['reps']=min(rep_high,e['reps']+1)
                e['adaptation']='两次相关训练均反馈高于预期且完成组 RPE ≤ 8，草案增加一次目标次数，不自动加重量。'
        selected.append(e)
    if not selected:
        base.update(kind='review');base['reasons'].append('候选动作涉及你反馈明显疲劳/酸痛的肌群，先核对安排，不自动补满训练量。');return base
    base['exercises']=selected
    base['reasons'] += ['优先使用你做过的动作，按局部负荷与明确反馈排序。',
                        '起步每动作最多 2 个正式组；负重列只提供历史参考，不要求达到或加重。目标预留约 3 次，结合热身调整。',
                        'Oura 作为整体背景，不因单次 HRV 自动停练或判定某块肌肉已恢复。']
    if any(e['target_rir']==4 for e in selected):base['reasons'].append('结合你填写的精神/局部疲劳反馈减少一组并增加预留次数。')
    return base


def run(d,sessions,fetched,config,p,feedback,checks,state):
    """Idempotent, date-bounded update; return new state without doing IO."""
    state=json.loads(json.dumps(state or {'plans':{},'calibrations':[],'events':[]}))
    for key,default in (('plans',{}),('calibrations',[]),('events',[])):state.setdefault(key,default)
    asof=dt.date.fromisoformat(d)
    sessions=[t for t in sessions if t['date']<=d]
    feedback=[f for f in feedback if f['date']<=d]
    def evidence(cutoff):
        return hashlib.sha256(json.dumps([[t for t in sessions if t['date']<=cutoff],
                 [f for f in feedback if f['date']<=cutoff],config],sort_keys=True).encode()).hexdigest()
    for version in state['calibrations']:
        if not version.get('invalidated') and version.get('evidence_hash') and evidence(version['cutoff'])!=version['evidence_hash']:
            version['invalidated']=True
            state['events'].append({'date':d,'type':'calibration','message':'历史记录、反馈或模型归属已修改，旧拟合停用并重新验证。'})
    fingerprint=hashlib.sha256(json.dumps([sessions,feedback,config],sort_keys=True).encode()).hexdigest()
    if state.get('fit_fingerprint')!=fingerprint:
        previous=active_models(state['calibrations'],d)
        results=fit(sessions,feedback,config,d,previous)
        state['calibration_status']=results
        if any(m['status']=='accepted' for m in results.values()):
            cutoff=max(m['trained_through'] for m in results.values() if m['status']=='accepted')
            state['calibrations'].append({'asof':d,'fingerprint':fingerprint,'models':results,
                                         'cutoff':cutoff,'evidence_hash':evidence(cutoff)})
            state['events'].append({'date':d,'type':'calibration','message':'反馈留出验证通过，拟合参数次日起生效。'})
        state['fit_fingerprint']=fingerprint
    # Track all retained prior plans as well as the new seven-day horizon.
    for plan in state['plans'].values():
        if plan['date']<=d:plan['tracking']=tracking(plan,sessions,fetched)
    forecast=[]
    def project(plan):
        if plan['kind']=='train' and not any(t['date']==plan['date'] for t in sessions):
            forecast.append({'date':plan['date'],'movements':[{'name':e['name'],'sets':[
                {'done':True,'warmup':False,'rpe':10-e['target_rir'],'weight_kg':e['reference_kg'],'reps':e['reps']}
                for _ in range(e['sets'])]} for e in plan['exercises']]})
    for offset in range(7):
        target=(asof+dt.timedelta(days=offset)).isoformat()
        draft=make_plan(target,sessions,fetched,config,p,feedback,checks,state['calibrations'],forecast)
        old=state['plans'].get(target)
        if old and old['status']!='draft':
            # Preserve accepted plans. New information is a separate proposal.
            if old['exercises']!=draft['exercises'] or old['kind']!=draft['kind']:
                old['revision_proposal']=draft
            project(old)
            continue
        if old and all(old.get(k)==draft.get(k) for k in ('kind','exercises','reasons','profile_confirmed')):
            project(old)
            continue
        draft['version']=old.get('version',0)+1 if old else 1
        draft['created_on']=old.get('created_on',d) if old else d
        draft['revised_on']=d
        if target<=d:draft['tracking']=tracking(draft,sessions,fetched)
        state['plans'][target]=draft
        project(draft)
        state['events'].append({'date':d,'type':'plan','message':target+' 的计划草案已生成/更新。'})
    state['events']=state['events'][-200:]
    state['last_run']=d
    return state


def plan_markdown(state,d):
    lines=['','## 教练 Agent：计划与跟进','']
    for date,p in sorted(state.get('plans',{}).items()):
        if not d<=date<=(dt.date.fromisoformat(d)+dt.timedelta(days=6)).isoformat():continue
        label={'train':'训练草案','rest':'休息','review':'待核对'}[p['kind']]
        lines.append(f'### {date} · {label} · {p["status"]}')
        lines.extend('- '+r for r in p['reasons'])
        for e in p['exercises']:
            ref='未填负重' if e['reference_kg'] is None else f'历史负重参考 {e["reference_kg"]:g} kg'
            lines.append(f'- {e["name"]}：{e["sets"]} 组 × {e["reps"]} 次；预留约 {e["target_rir"]} 次；{ref}。')
            if e.get('adaptation'):lines.append('  - '+e['adaptation'])
        if p.get('tracking'):lines.append('- '+p['tracking']['message'])
        if p.get('revision_proposal'):lines.append('- 存在新的修订草案，原已接受计划仍保留，请在面板核对修订。')
    lines+=['','### 执行后跟进','']
    prior=[p for date,p in sorted(state.get('plans',{}).items()) if date<d and p['kind']=='train']
    for p in prior[-4:]:
        message=p.get('tracking',{}).get('message','待同步核对')
        pending='反馈已记录。' if p['date'] in state.get('feedback_dates',[]) else '实际训练后请补当日局部疲劳和表现反馈。'
        lines.append(f'- {p["date"]}：{message} {pending}')
    if not prior:lines.append('- 尚无过去的计划可跟进，后续会对照日志和反馈持续核对。')
    lines+=['','### 校准与待反馈','']
    for m in state.get('calibration_status',{}).values():
        if m['samples']:lines.append(f'- {m["name"]}：{m["samples"]} 天反馈，{m["episodes"]} 次相关训练；{m["reason"]}')
    if not any(m['samples'] for m in state.get('calibration_status',{}).values()):
        lines.append('- 尚无局部疲劳反馈。当前保留初始参数，未声称已经学会个人恢复速度。')
    return '\n'.join(lines)
