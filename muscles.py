"""Transparent, configurable workload heuristics; not a validated fatigue measure."""
import datetime as dt
import math
import statistics
import unicodedata

GROUPS = {'chest': '胸', 'lats': '背阔肌', 'upper_back': '上背',
          'front_delts': '肩前束', 'side_delts': '肩中束', 'rear_delts': '肩后束',
          'biceps': '肱二头肌', 'triceps': '肱三头肌', 'quads': '股四头肌',
          'hamstrings': '腘绳肌', 'glutes': '臀', 'calves': '小腿',
          'core': '核心', 'rotator_cuff': '肩袖', 'serratus': '前锯肌', 'forearms': '前臂'}
KINDS = {'strength': '力量', 'support': '辅助／控制', 'mobility': '拉伸／活动度', 'unmapped': '待归类'}
CATALOG = {}


def canonical(name):
    return unicodedata.normalize('NFKC', str(name)).split('_')[0].replace(' ', '').casefold()


def add(names, primary=(), secondary=(), kind='strength'):
    for name in names:
        CATALOG[canonical(name)] = {'kind': kind, 'weights': {**{k: 1 for k in primary}, **{k: .5 for k in secondary}}}


add(['卧推', '杠铃卧推', '哑铃卧推', '地板哑铃卧推（锤式）', '上斜俯卧撑', '俯卧撑', '上斜哑铃卧推', '上斜杠铃卧推'], ['chest'], ['front_delts', 'triceps'])
add(['哑铃飞鸟', '夹胸', '蝴蝶机夹胸', '绳索夹胸'], ['chest'])
add(['引体向上', '引体向上（辅助）', '高位下拉', '单手下拉'], ['lats'], ['upper_back', 'biceps'])
add(['器械划船2', '器械划船', '绳索坐姿划船（单手）', '坐姿划船', '杠铃划船', '哑铃划船'], ['upper_back'], ['lats', 'biceps', 'rear_delts'])
add(['面拉'], ['rear_delts'], ['upper_back'])
add(['绳索侧平举（单边）', '平板上斜侧平举', '侧平举', '哑铃侧平举'], ['side_delts'])
add(['前平举', '哑铃前平举'], ['front_delts'])
add(['器械坐姿推举', '哑铃推肩', '杠铃推举', '半跪地雷杆推肩'], ['front_delts'], ['side_delts', 'triceps'])
add(['俯身飞鸟', '蝴蝶机反向飞鸟', '绳索交叉后束飞鸟'], ['rear_delts'], ['upper_back'])
add(['弯举', '哑铃弯举', '杠铃弯举', '绳索弯举'], ['biceps'])
add(['绳索下压', '肱三头肌下压', '仰卧臂屈伸', '哑铃臂屈伸'], ['triceps'])
add(['杠铃罗马尼亚硬拉', '罗马尼亚硬拉', '哑铃罗马尼亚硬拉'], ['hamstrings', 'glutes'])
add(['器械臀冲', '臀冲', '杠铃臀冲', '自重臀冲'], ['glutes'])
add(['哑铃保加利亚蹲', '保加利亚蹲', '哑铃酒杯深蹲', '杠铃深蹲', '深蹲', '腿举'], ['quads', 'glutes'])
add(['腿弯举', '坐姿腿弯举', '俯卧腿弯举'], ['hamstrings'])
add(['腿屈伸', '器械腿屈伸'], ['quads'])
add(['坐姿髋外展'], ['glutes'])
add(['站姿提踵', '坐姿提踵', '提踵'], ['calves'])
add(['哑铃农夫行走'], ['forearms'], ['upper_back', 'core'])
# Low-load control and mobility records remain visible but do not enter the strength-load proxy.
add(['外旋阻力带', '弹力带肩内旋'], ['rotator_cuff'], kind='support')
add(['站姿绳索髋外旋', '弹力带蚌式开合'], ['glutes'], kind='support')
add(['肩胛墙角撑', '仰卧弹力带前锯推'], ['serratus'], kind='support')
add(['靠墙滑行', '墙天使', '俯卧W字', '哑铃Y字上抬'], ['upper_back'], kind='support')
add(['死虫', '猎鸟狗', '绳索Pallof推'], ['core'], kind='support')
add(['弹力带末端膝盖伸展', '西班牙蹲'], ['quads'], kind='support')
add(['仰卧胸腰椎泡沫轴放松', '胸椎四足位旋转', '猫式伸展', '9090旋转',
     '单腿跨步后压', '单腿跨步侧压', '下犬式', '跪姿膝盖画圈', '平躺曲腿旋转'], kind='mobility')
# Ambiguous names (e.g. 抬腿, 青蛙趴抬腿) are intentionally left for the user to classify.

METHOD = ('实验性负荷模型，尚未按你的实际疲劳校准。主练肌群每组计 1，间接参与计 0.5；'
          '辅助／控制、拉伸不计力量组当量，未知动作单列。RPE 系数 = RPE/10；缺失时用 0.6–1.0 假设区间（不是统计置信区间）。'
          '残余负荷 = 过去 28 天各组当量 × RPE 系数 × 2^(-距记录日期天数/半衰期)。'
          '默认半衰期 2 天，可选 1–4 天；是软件假设，不是肌肉生理恢复时间。按日期估算，不使用小时精度。'
          '历史周量参考使用此前 3 个七天窗口中至少 2 个完整读取窗口的中位数，不是训练目标。低残余负荷不代表已经恢复；未同步日期、动作误分类及窗口前的训练会影响结果。'
          '单侧动作沿用日志组数，不自动除以二或翻倍；递减组子组沿用单独计数。'
          '周量比较不代表推荐目标；不以组数推断肌肉增长，也不根据 Oura 数值计算局部肌肉疲劳。')


def validate_mapping(value):
    kind = value.get('kind')
    weights = value.get('weights', {})
    if kind not in KINDS or not isinstance(weights, dict):
        raise ValueError('动作类型或肌群格式无效。')
    if any(k not in GROUPS or isinstance(v, bool) or v not in (.5, 1) for k, v in weights.items()):
        raise ValueError('肌群权重只能是主练 1 或间接 0.5。')
    if kind in ('strength', 'support') and not weights:
        raise ValueError('力量或辅助动作至少需要选择一个肌群。')
    return {'kind': kind, 'weights': weights if kind in ('strength', 'support') else {}}


def mapping(name, overrides):
    value = overrides.get(name)
    if value is not None:
        return {**validate_mapping(value), 'source': 'user'}
    default = CATALOG.get(canonical(name), {'kind': 'unmapped', 'weights': {}})
    return {**default, 'source': 'default'}


def model(sessions, fetched, d, config=None, soreness=None):
    config, soreness = config or {}, soreness or {}
    half_life = int(config.get('half_life_days', 2))
    if half_life not in (1, 2, 3, 4):
        half_life = 2
    overrides = config.get('exercises', {})
    date = dt.date.fromisoformat(d)
    rows = {k: {'key': k, 'name': v, 'direct_sets': 0., 'indirect_sets': 0.,
                'week_sets': 0., 'previous_sets': 0., 'residual_low': 0., 'residual_high': 0.,
                'last_trained': None, 'soreness': soreness.get(k)} for k, v in GROUPS.items()}
    daily = {}
    exercises = {}
    counts = {'strength': 0, 'support': 0, 'mobility': 0, 'unmapped': 0, 'with_rpe': 0}
    for session in sessions:
        age = (date-dt.date.fromisoformat(session['date'])).days
        if not 0 <= age < 28:
            continue
        by_day = daily.setdefault(session['date'], {k: 0. for k in GROUPS})
        for move in session['movements']:
            name = move['name']
            mapped = mapping(name, overrides)
            entry = exercises.setdefault(name, {'name': name, **mapped, 'sets_28d': 0, 'sets_7d': 0})
            work = [s for s in move['sets'] if s['done'] and not s['warmup']]
            entry['sets_28d'] += len(work)
            if age < 7:
                entry['sets_7d'] += len(work)
            counts[mapped['kind']] += len(work)
            if mapped['kind'] != 'strength':
                continue
            for s in work:
                rpe = s.get('rpe')
                counts['with_rpe'] += rpe is not None
                low = rpe/10 if rpe is not None else .6
                high = rpe/10 if rpe is not None else 1.
                decay = math.pow(2, -age/half_life)
                for muscle, weight in mapped['weights'].items():
                    row = rows[muscle]
                    by_day[muscle] += weight
                    if age < 7:
                        row['direct_sets' if weight == 1 else 'indirect_sets'] += weight
                        row['week_sets'] += weight
                    elif age < 14:
                        row['previous_sets'] += weight
                    row['residual_low'] += weight*low*decay
                    row['residual_high'] += weight*high*decay
                    row['last_trained'] = max(row['last_trained'] or '', session['date'])
    fetched = set(fetched)
    coverage = [sum((date-dt.timedelta(days=i)).isoformat() in fetched for i in range(start, start+7)) for start in (0, 7, 14, 21)]
    for muscle, row in rows.items():
        reference_weeks = []
        for start, cov in zip((7, 14, 21), coverage[1:]):
            if cov == 7:
                reference_weeks.append(sum(daily.get((date-dt.timedelta(days=i)).isoformat(), {}).get(muscle, 0) for i in range(start, start+7)))
        row['usual_week'] = statistics.median(reference_weeks) if len(reference_weeks) >= 2 else None
        row['reference_weeks'] = len(reference_weeks)
        row['week_change'] = round(row['week_sets']-row['previous_sets'], 1) if coverage[:2] == [7, 7] else None
        for key in ('direct_sets', 'indirect_sets', 'week_sets', 'previous_sets', 'residual_low', 'residual_high'):
            row[key] = round(row[key], 2)
    unknown = [e for e in exercises.values() if e['kind'] == 'unmapped' and e['sets_28d']]
    active = [r for r in rows.values() if r['last_trained'] or r['soreness'] is not None]
    active.sort(key=lambda r: (-r['residual_high'], -r['week_sets'], r['key']))
    alerts = []
    if unknown:
        alerts.append(f'{len(unknown)} 个动作共 {sum(e["sets_28d"] for e in unknown)} 个已完成组待归类，尚未计入肌群负荷。')
    if coverage[0] < 7:
        alerts.append(f'本周仅 {coverage[0]}/7 天有读取结果，未同步日期不视为零负荷。')
    if counts['strength'] > counts['with_rpe']:
        alerts.append(f'{counts["strength"]-counts["with_rpe"]}/{counts["strength"]} 个力量正式组缺少 RPE，残余负荷使用假设区间。')
    alerts.append(f'过去 28 天 {counts["support"]} 组辅助／控制与 {counts["mobility"]} 组活动度记录单列，不计入力量组当量。')
    local = [r['name'] for r in active if r['soreness'] is not None and r['soreness'] >= 3]
    focus = ('你记录了' + '、'.join(local) + '较明显的酸痛，先结合实际感受和动作表现核对安排；模型不会自动判定恢复或增加训练量。') if local else '先核对动作归属，并记录本次主练肌群的酸痛与 RPE，逐步校准负荷估计；未填酸痛不视为无酸痛。'
    return {'version': 'experimental-v1', 'half_life_days': half_life, 'muscles': active,
            'groups': GROUPS, 'kinds': KINDS, 'exercises': sorted(exercises.values(), key=lambda e: (e['kind'] != 'unmapped', e['name'])),
            'counts': counts, 'coverage': coverage, 'unknown': unknown, 'alerts': alerts,
            'focus': focus, 'method': METHOD,
            'references': [{'title': 'Resistance Training Dose Response (2026)', 'url': 'https://pubmed.ncbi.nlm.nih.gov/41343037/'},
                           {'title': 'HRV Applications in Strength and Conditioning (2024)', 'url': 'https://pubmed.ncbi.nlm.nih.gov/38921629/'}]}


def markdown(value):
    lines = ['', '## 肌群负荷与疲劳估计（实验版）', '',
             '| 肌群 | 近7天主练 | 间接当量 | 前7天当量 | 残余负荷区间 | 酸痛0–5 |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in value['muscles']:
        soreness = '未填' if r['soreness'] is None else str(r['soreness'])
        lines.append(f'| {r["name"]} | {r["direct_sets"]:g} | {r["indirect_sets"]:g} | {r["previous_sets"]:g} | {r["residual_low"]:.2f}–{r["residual_high"]:.2f} | {soreness} |')
    lines += ['', *('- '+a for a in value['alerts']), '', value['focus'], '', value['method'], '', '### 动作归属（近28天）', '']
    for e in value['exercises']:
        allocation = '、'.join(f'{GROUPS[k]} × {v:g}' for k, v in e['weights'].items()) or '无'
        lines.append(f'- {e["name"]}：{KINDS[e["kind"]]}，{allocation}；{e["sets_28d"]} 个完成组。')
    lines += ['', '研究参考支持记录和解释训练量的思路；上述 RPE 系数、衰减天数及动作权重是可调软件假设，并非由研究验证的疲劳公式。']
    lines.extend(f'- [{r["title"]}]({r["url"]})' for r in value['references'])
    return '\n'.join(lines)
