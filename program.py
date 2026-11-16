"""User-confirmed imported programs. Private state; no SynFit writes or model calls."""
import copy
import datetime as dt
import hashlib
import json


def validate(value):
    if not isinstance(value,dict):raise ValueError('计划文件格式无效。')
    allowed={'name','anchor_date','cycle','templates','shift_rule','source','version','shifts','id','confirmed','source_confirmed_at'}
    if set(value)-allowed:raise ValueError('计划包含不支持的字段。')
    result=copy.deepcopy(value)
    if not isinstance(result.get('name'),str) or not 1<=len(result['name'])<=100:raise ValueError('计划名称无效。')
    dt.date.fromisoformat(result['anchor_date'])
    if not isinstance(result.get('source',''),str) or len(result.get('source',''))>500:raise ValueError('来源说明无效。')
    templates=result.get('templates',{});cycle=result.get('cycle',[])
    if not isinstance(templates,dict) or not 1<=len(templates)<=14:raise ValueError('计划须有 1–14 个训练模板。')
    if not isinstance(cycle,list) or not 1<=len(cycle)<=31 or any(x is not None and x not in templates for x in cycle):raise ValueError('周期引用的模板无效。')
    if not any(x is not None for x in cycle):raise ValueError('周期不能全为空。')
    for key,t in templates.items():
        if not isinstance(key,str) or not isinstance(t,dict) or set(t)-{'name','source_date','movements'}:raise ValueError('模板字段无效。')
        if not isinstance(t.get('name'),str) or len(t['name'])>150:raise ValueError('模板名称无效。')
        dt.date.fromisoformat(t['source_date'])
        if not isinstance(t.get('movements'),list) or not 1<=len(t['movements'])<=40:raise ValueError('模板动作数无效。')
        seen=set()
        for m in t['movements']:
            if not isinstance(m,dict) or set(m)-{'name','role','prescribed_sets'}:raise ValueError('动作字段无效。')
            if not isinstance(m.get('name'),str) or not 1<=len(m['name'])<=200 or m['name'] in seen:raise ValueError('动作名无效或重复。')
            seen.add(m['name'])
            if m.get('role') not in ('strength','preparation','unclassified'):raise ValueError('动作类别无效。')
            if not isinstance(m.get('prescribed_sets'),list) or not 1<=len(m['prescribed_sets'])<=20:raise ValueError('逐组数据无效。')
            for row in m['prescribed_sets']:
                if not isinstance(row,dict) or set(row)-{'reps','seconds','warmup','reference_load','distance_note'}:raise ValueError('组数据字段无效。')
                if type(row.get('warmup')) is not bool:raise ValueError('热身标记无效。')
                for k in ('reps','seconds'):
                    if row.get(k) is not None and (type(row[k]) not in (int,float) or not 0<row[k]<=3600):raise ValueError('次数或时间无效。')
                if not isinstance(row.get('distance_note',''),str) or len(row.get('distance_note',''))>200:raise ValueError('距离说明无效。')
                if not isinstance(row.get('reference_load',''),str) or len(row.get('reference_load',''))>100:raise ValueError('历史负重参考无效。')
    if result.get('shift_rule') not in ('shift_all','unknown'):raise ValueError('顺延规则无效。')
    result['version']=1;result['shifts']=[];result['confirmed']=False
    result['id']=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
    return result


def scheduled(value,date):
    if not value or not value.get('confirmed'):return None
    offset=(dt.date.fromisoformat(date)-dt.date.fromisoformat(value['anchor_date'])).days
    if offset<0:return None
    shifts=[s for s in value.get('shifts',[]) if s['from_date']<=date]
    if any(s['from_date']==date for s in shifts):return {'rest':True,'shifted':True}
    offset-=sum(s['days'] for s in shifts)
    key=value['cycle'][offset%len(value['cycle'])]
    return {'rest':key is None,'template':value['templates'].get(key),'template_id':key,'shifted':False}


def make_day(value,date):
    entry=scheduled(value,date)
    if entry is None:return None
    base={'date':date,'kind':'rest' if entry['rest'] else 'train','original_kind':'rest' if entry['rest'] else 'train',
          'status':'draft','profile_confirmed':True,'origin':'synfit_import','program_id':value['id'],
          'program_version':value['version'],'focus':value['name'],'exercises':[],'version':1,
          'reasons':['来自你确认的训记现行计划副本；不是网页重新挑选的动作。','重量仅为历史参考；未提供 RIR 的动作保持未填写，不假设已充分恢复。']}
    if entry['rest']:
        base['template_name']='已确认顺延' if entry['shifted'] else '休息日'
        return base
    base['template_name']=entry['template']['name']
    for m in entry['template']['movements']:
        work=[s for s in m['prescribed_sets'] if not s['warmup']]
        reps=[s['reps'] for s in work if s.get('reps') is not None]
        base['exercises'].append({'name':m['name'],'sets':len(work),'reps':int(min(reps)) if reps else None,
            'target_rir':None,'reference_kg':None,'role':m['role'],'prescribed_sets':copy.deepcopy(m['prescribed_sets'])})
    return base


def shift(value,date,expected_version):
    if not value or not value.get('confirmed') or value['shift_rule']!='shift_all':raise ValueError('请先确认现行计划和整体顺延规则。')
    if type(expected_version) is not int or value['version']!=expected_version:raise ValueError('计划已更新，请刷新后再操作。')
    if date<value['anchor_date']:raise ValueError('不能顺延计划开始前的日期。')
    if any(s['from_date']==date for s in value.get('shifts',[])):raise ValueError('该日已顺延，不会重复移动。')
    entry=scheduled(value,date)
    if not entry or entry['rest']:raise ValueError('只能将未完成的训练日顺延。')
    result=copy.deepcopy(value);result['shifts'].append({'from_date':date,'days':1,'source':'user_confirmed_unfinished'})
    result['version']+=1
    return result
