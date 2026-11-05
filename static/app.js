const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="iron-token"]').content;
let state, loadedDate, wasRunning = false, polling, dirtyCheckin = false, muscleData, coachData, feedbackDirty=false;
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Iron-Token':csrf},body:JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || '操作失败');
  return data;
}
function status(text, error=false) { $('status').textContent=text; $('status').classList.toggle('error',error); }
function text(tag, value, className) {const el=document.createElement(tag);el.textContent=value;if(className)el.className=className;return el;}
function fmt(v, digits=0) {return v == null ? '—' : Number(v).toFixed(digits);}
function selected() {return $('report-date').value || state.today;}
async function refreshStatus() {
  state = await api('/api/status');
  if (!$('report-date').value) {$('report-date').value=state.today; $('report-date').max=state.today;}
  $('timezone').textContent=state.timezone;
  for (const [name,label] of [['xunji','已配置'],['oura','已授权']]) {
    $(name+'-dot').classList.toggle('on',state[name]);
    $(name+'-state').textContent=state[name] ? label : '待连接';
  }
  $('ai-state').textContent=state.ai?'已配置':'可选 · 待配置';
  $('redirect-uri').value=state.redirect_uri;
  $('sync').disabled=state.job.running;
  const errors=state.job.errors || [];
  if(state.job.running)status(state.job.message);
  else if(errors.length)status(errors.join('；'),true);
  else status(state.dates.length ? `已缓存 ${state.dates.length} 个日期 · ${state.job.message}`:'连接已就绪，点击「同步数据」读取真实训练记录。');
  if (wasRunning && !state.job.running) await refreshReport();
  wasRunning=state.job.running;
}
async function refreshReport() {
  const d=selected();
  const r=await api('/api/report?date='+d);
  if(selected()!==d)return;
  const fields={sleep:'sleep_hours',hrv:'hrv',rhr:'rhr'};
  for(const [id,key] of Object.entries(fields)) {
    $(id).textContent=fmt(r.recovery[key], id==='sleep'?1:0);
    const b=r.baseline[key];
    $(id+'-baseline').textContent=b.value==null?`基线样本 ${b.n}/7 晚`:`28 天中位数 ${fmt(b.value,id==='sleep'?1:0)} · ${b.n} 晚`;
  }
  $('sets').textContent=r.week.sets;
  $('week-meta').textContent=`${r.week.sessions} 次记录 · 已读取 ${r.coverage}/7 天`;
  $('observations').replaceChildren(...r.observations.map(n=>text('li',n)));
  $('focus').textContent=r.focus;
  $('limits').textContent=r.limits;
  muscleData=r.muscle_load;
  renderMuscles(muscleData);
  coachData=r.coach_agent;renderCoach(coachData,d);
  $('report-mode').textContent=r.day_context.label;
  $('plan-context').textContent=r.day_context.reason;
  $('training-heading').textContent=r.day_context.mode==='training'?'训练表现回顾':'最近训练回顾';
  $('recovery-trends').replaceChildren();
  for(const [key,label,unit] of [['sleep_hours','主睡眠','小时'],['hrv','HRV','ms'],['rhr','夜间最低心率','bpm']]){
    const {recent,previous}=r.trends[key];
    const detail=recent.value==null||previous.value==null?`样本不足 · 最近 ${recent.n}/3 晚，此前 ${previous.n}/3 晚`:`${fmt(previous.value,1)} → ${fmt(recent.value,1)} ${unit} · 最近 ${recent.n} 晚 / 此前 ${previous.n} 晚`;
    const row=text('div','','trend-row');row.append(text('strong',label),text('span',detail));$('recovery-trends').append(row);
  }
  $('last-date').textContent=r.last_date||'暂无记录';
  const container=$('training');container.replaceChildren();
  if(!r.last_sessions.length)container.append(text('div','同步训记后，这里会显示最近一次训练的动作、正式组和 RPE。','empty'));
  for(const session of r.last_sessions) {
    const box=text('div','','session');box.append(text('h3',session.title));
    for(const m of session.movements) {
      const el=text('div','','movement');const head=text('div','','movement-header');
      const work=m.sets.filter(s=>s.done&&!s.warmup);
      head.append(text('span',m.name),text('small',work.length+' 正式组'));el.append(head);
      if(work.length)el.append(text('div',work.map(s=>`${s.weight_kg==null?'自重/未填负重':fmt(s.weight_kg,1)+' kg'} × ${s.reps==null?'未填次数':fmt(s.reps)}${s.rpe==null?'':' · RPE '+s.rpe}`).join('  /  '),'set-row'));
      else el.append(text('div','无已完成正式组；可能是有氧、未完成或未填写组数据。','set-row'));
      box.append(el);
    }
    container.append(box);
  }
  $('comparisons').replaceChildren();
  for(const c of r.comparisons){
    const s=c.same_load;
    const detail=s?`同负重 ${fmt(s.weight_kg,1)} kg 最佳次数 ${fmt(s.previous_reps)} → ${fmt(s.current_reps)}`:'暂无相同负重的次数对比';
    $('comparisons').append(text('p',`${c.name} · 对比 ${c.previous_date}\n正式组 ${c.previous_sets} → ${c.current_sets}；${detail}`));
  }
  if(!r.comparisons.length)$('comparisons').append(text('p','需要至少两次包含相同动作的训练记录。'));
  if(loadedDate!==d||!dirtyCheckin){
    $('energy').value=r.checkin.energy??3;$('soreness').value=r.checkin.soreness??0;$('note').value=r.checkin.note??'';
    $('daily-plan').value=r.day_context.plan;
    renderSoreness(muscleData.groups,r.checkin.muscle_soreness||{});
    updateRanges();dirtyCheckin=false;
  }
  loadedDate=d;
  $('export').href='/api/export?date='+d;$('export').download='训练日报-'+d+'.md';
  const ai=await api('/api/ai?date='+d);
  if(selected()!==d)return;
  $('ai-result').textContent=ai.text||'';
  $('ai-meta').textContent=ai.generated_at?`已保存的解读 · ${ai.model} · ${new Date(ai.generated_at*1000).toLocaleString('zh-CN')}（同步后可重新生成）`:'';
}
function renderCoach(c,d){
  $('coach-profile-state').textContent=c.profile.confirmed?'偏好已确认':'偏好待确认';
  const labels={draft:'草案',accepted:'已接受',completed:'已手动标记完成',skipped:'已跳过'};
  const box=$('coach-plans');box.replaceChildren();
  const upcoming=Object.values(c.plans).filter(p=>p.date>=d).sort((a,b)=>a.date.localeCompare(b.date));
  for(const p of upcoming){
    const card=text('article','','plan-card');card.append(text('h3',p.date+' · '+({train:'训练',rest:'休息',review:'待核对'}[p.kind])),text('small',`${labels[p.status]} · 版本 ${p.version}`));
    const list=text('ul','');for(const e of p.exercises){list.append(text('li',`${e.name}：${e.sets} × ${e.reps}，预留约 ${e.target_rir} 次；${e.reference_kg==null?'负重未填':'历史参考 '+fmt(e.reference_kg,1)+' kg'}`));}card.append(list);for(const e of p.exercises)if(e.adaptation)card.append(text('small',e.name+'：'+e.adaptation));
    const why=text('details','');why.append(text('summary','依据与调整说明'));for(const r of p.reasons)why.append(text('p',r));card.append(why);
    if(p.tracking)card.append(text('p',p.tracking.message));
    if(p.revision_proposal){const rev=text('div','','plan-revision');rev.append(text('strong','有新的修订草案，当前计划保留'));for(const e of p.revision_proposal.exercises)rev.append(text('p',`${e.name}：${e.sets} × ${e.reps}，预留 ${e.target_rir} 次`));for(const r of p.revision_proposal.reasons)rev.append(text('small',r));card.append(rev);}
    const actions=text('div','','plan-actions');
    for(const [action,label] of [['accepted','接受计划'],['completed','标记已完成'],['skipped','跳过'],['accept_revision','接受修订']]){
      if(action==='accepted'&&(p.status!=='draft'||p.kind==='review'))continue;
      if(action==='completed'&&(p.date>state.today||p.kind!=='train'||p.status==='completed'))continue;
      if(action==='accept_revision'&&(!p.revision_proposal||p.revision_proposal.kind==='review'))continue;
      if(action==='skipped'&&p.status==='skipped')continue;
      const b=text('button',label,'ghost');b.type='button';b.onclick=async()=>{try{await api('/api/coach',{action:'plan_status',date:p.date,version:p.version,status:action});await refreshReport();status('计划状态已保存。');}catch(e){status(e.message,true);}};actions.append(b);
    }
    card.append(actions);box.append(card);
  }
  if(!upcoming.length)box.append(text('div','点击「更新计划与跟进」生成未来 7 天草案，再确认训练偏好。','empty'));
  $('coach-calibration').replaceChildren();
  const calibration=Object.values(c.calibration_status).filter(m=>m.samples);
  for(const m of calibration)$('coach-calibration').append(text('p',`${m.name}：${m.samples} 天反馈 / ${m.episodes} 次相关训练 / RPE 覆盖 ${fmt(m.rpe_coverage*100)}%。${m.reason}${m.baseline_mae==null?'':` 留出 MAE ${m.baseline_mae} → ${m.candidate_mae}。`}${m.status==='accepted'?' 参数将于 '+m.effective_from+' 生效。':''}`,'calibration-row'));
  if(!calibration.length)$('coach-calibration').append(text('p','尚无局部疲劳反馈，当前保留初始模型；新版本会持续收集反馈后验证是否更新。'));
  $('coach-followup').replaceChildren();
  for(const p of Object.values(c.plans).filter(p=>p.date<d&&p.kind==='train').sort((a,b)=>b.date.localeCompare(a.date)).slice(0,4))$('coach-followup').append(text('p',`${p.date} · ${labels[p.status]} · ${p.tracking?.message||'待同步核对'} · ${(c.feedback_dates||[]).includes(p.date)?'反馈已记录':'实际完成后请补当日反馈。'}`));
  $('coach-events').replaceChildren(...c.events.slice(-5).map(e=>text('p',`${e.date} · ${e.message}`)));
  if(loadedDate!==d||!feedbackDirty){fillFeedback(c);feedbackDirty=false;}
}
function fillFeedback(c){
  const record=c.feedback_day.find(f=>f.phase===$('feedback-phase').value)||{};
  const box=$('feedback-fatigue');box.replaceChildren();
  for(const [key,label] of Object.entries(muscleData.groups)){
    const row=text('div','','soreness-row'),sel=text('select','');sel.id='fatigue-'+key;sel.dataset.muscle=key;
    sel.append(option('','未填'),...Array.from({length:6},(_,i)=>option(String(i),String(i))));sel.value=record.fatigue?.[key]??'';sel.onchange=()=>{feedbackDirty=true;};
    const lab=text('label',label+'疲劳');lab.htmlFor=sel.id;row.append(lab,sel);box.append(row);
  }
  $('feedback-performance').value=record.performance||'unknown';$('feedback-discomfort').checked=record.discomfort||false;
}
$('feedback-phase').onchange=()=>{fillFeedback(coachData);feedbackDirty=false;};
$('feedback-performance').onchange=$('feedback-discomfort').onchange=()=>{feedbackDirty=true;};
$('feedback-form').onsubmit=async e=>{e.preventDefault();try{const fatigue={};for(const sel of $('feedback-fatigue').querySelectorAll('select'))if(sel.value!=='')fatigue[sel.dataset.muscle]=Number(sel.value);
  await api('/api/coach',{action:'feedback',date:selected(),phase:$('feedback-phase').value,fatigue,performance:$('feedback-performance').value,discomfort:$('feedback-discomfort').checked});feedbackDirty=false;await refreshReport();status('反馈已保存，校准与计划已重新评估。');
}catch(e){status(e.message,true);}};
$('coach-run').onclick=async()=>{const b=$('coach-run');b.disabled=true;try{await api('/api/coach',{action:'run'});await refreshReport();status('已更新校准、计划草案与执行跟进。');}catch(e){status(e.message,true);}finally{b.disabled=false;}};
$('coach-profile-open').onclick=()=>{
  const p=coachData.profile;$('coach-goal').value=p.goal;$('coach-minutes').value=p.minutes;$('coach-exercises').value=p.excluded_exercises.join('\n');
  for(const [id,entries,chosen] of [['coach-weekdays',['周一','周二','周三','周四','周五','周六','周日'].map((n,i)=>[String(i),n]),p.weekdays.map(String)],['coach-exclusions',Object.entries(muscleData.groups),p.excluded_muscles]]){
    const box=$(id);box.replaceChildren();for(const [key,label] of entries){const lab=text('label','','choice'),input=document.createElement('input');input.type='checkbox';input.value=key;input.checked=chosen.includes(key);lab.append(input,document.createTextNode(label));box.append(lab);}
  }
  $('coach-profile-message').textContent='';$('coach-profile-dialog').showModal();
};
$('coach-profile-close').onclick=()=>$('coach-profile-dialog').close();
$('coach-profile-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/coach',{action:'profile',profile:{goal:$('coach-goal').value,minutes:Number($('coach-minutes').value),weekdays:[...$('coach-weekdays').querySelectorAll('input:checked')].map(e=>Number(e.value)),excluded_muscles:[...$('coach-exclusions').querySelectorAll('input:checked')].map(e=>e.value),excluded_exercises:$('coach-exercises').value.split('\n').map(s=>s.trim()).filter(Boolean)}});await refreshReport();$('coach-profile-dialog').close();status('训练偏好已保存，未来草案已更新。');}catch(e){$('coach-profile-message').textContent=e.message;}};
function updateRanges(){for(const key of ['energy','soreness'])$(key+'-value').textContent=$(key).value+' / 5';}
function option(value,label){const o=text('option',label);o.value=value;return o;}
function renderMuscles(m){
  $('half-life').value=String(m.half_life_days);
  const body=$('muscle-rows');body.replaceChildren();
  for(const row of m.muscles){
    const el=text('tr','');
    const values=[row.name,fmt(row.direct_sets,1),fmt(row.indirect_sets,1),`${fmt(row.previous_sets,1)} → ${fmt(row.week_sets,1)}${row.week_change==null?'（读取未齐）':''}`,row.usual_week==null?'样本不足':`${fmt(row.usual_week,1)}（${row.reference_weeks}周）`,`${fmt(row.residual_low,2)}–${fmt(row.residual_high,2)}`,row.last_trained||'暂无',row.soreness==null?'未填':String(row.soreness),row.personalized?`拟合 ${row.half_life_days}天 / 预期疲劳 ${fmt(row.fatigue_estimate,1)}`:`初始 ${row.half_life_days}天`];
    for(const v of values)el.append(text('td',v));body.append(el);
  }
  if(!m.muscles.length){const row=text('tr',''),cell=text('td','暂无已归类的力量组；先同步记录或校准动作归属。');cell.colSpan=9;row.append(cell);body.append(row);}
  $('muscle-alerts').replaceChildren(...m.alerts.map(a=>text('li',a)));
  $('muscle-focus').textContent=m.focus;
  $('muscle-method').textContent=m.method;
  $('muscle-counts').textContent=`过去 28 天：力量 ${m.counts.strength} 组 · 辅助 ${m.counts.support} 组 · 活动度 ${m.counts.mobility} 组 · 待归类 ${m.counts.unmapped} 组。`;
}
function renderSoreness(groups,saved){
  const box=$('muscle-soreness');box.replaceChildren();
  for(const [key,label] of Object.entries(groups)){
    const row=text('div','','soreness-row'),select=text('select','');select.id='soreness-'+key;select.dataset.muscle=key;
    select.append(option('','未填'),...Array.from({length:6},(_,i)=>option(String(i),String(i))));select.value=saved[key]??'';
    select.onchange=()=>{dirtyCheckin=true;};const lab=text('label',label);lab.htmlFor=select.id;row.append(lab,select);box.append(row);
  }
}
function localSoreness(){const values={};for(const el of $('muscle-soreness').querySelectorAll('select'))if(el.value!=='')values[el.dataset.muscle]=Number(el.value);return values;}
function renderMapping(){
  const e=muscleData.exercises.find(e=>e.name===$('mapping-exercise').value);if(!e)return;
  $('mapping-kind').value=e.kind;$('mapping-source').textContent=e.source==='user'?'使用你保存的归属':'默认归属，请按实际动作核对';
  const box=$('mapping-weights');box.replaceChildren();
  for(const [key,label] of Object.entries(muscleData.groups)){
    const row=text('div','','mapping-row'),select=text('select','');select.id='weight-'+key;select.dataset.muscle=key;
    select.append(option('0','不计入'),option('1','主练 × 1'),option('0.5','间接 × 0.5'));select.value=String(e.weights[key]||0);
    const lab=text('label',label);lab.htmlFor=select.id;row.append(lab,select);box.append(row);
  }
}
$('muscle-edit').onclick=()=>{
  if(!muscleData?.exercises.length){status('先同步训练记录，再校准动作归属。',true);return;}
  $('mapping-exercise').replaceChildren(...muscleData.exercises.map(e=>option(e.name,`${e.name} · ${muscleData.kinds[e.kind]}`)));
  $('mapping-status').textContent='';renderMapping();$('muscle-dialog').showModal();
};
$('mapping-exercise').onchange=()=>{renderMapping();$('mapping-status').textContent='';};
$('muscle-close').onclick=()=>$('muscle-dialog').close();
$('muscle-form').onsubmit=async e=>{e.preventDefault();try{
  const name=$('mapping-exercise').value,weights={};for(const select of $('mapping-weights').querySelectorAll('select'))if(Number(select.value))weights[select.dataset.muscle]=Number(select.value);
  await api('/api/muscles',{name,kind:$('mapping-kind').value,weights});await refreshReport();renderMapping();$('mapping-status').textContent='已保存，负荷与日报已重算。';
}catch(e){$('mapping-status').textContent=e.message;}};
$('mapping-reset').onclick=async()=>{try{await api('/api/muscles',{name:$('mapping-exercise').value,reset:true});await refreshReport();renderMapping();$('mapping-status').textContent='已恢复默认归属。';}catch(e){$('mapping-status').textContent=e.message;}};
$('save-half-life').onclick=async()=>{try{await api('/api/muscles',{half_life_days:Number($('half-life').value)});await refreshReport();status('衰减假设已保存并重算；它不是实际恢复时间。');}catch(e){status(e.message,true);}};
async function saveSettings(){
  const fields={'xunji_key':'xunji-key','oura_client_id':'oura-client','oura_client_secret':'oura-secret','openai_key':'openai-key','openai_model':'openai-model'};
  const body={};for(const [k,id] of Object.entries(fields))if($(id).value.trim())body[k]=$(id).value.trim();
  await api('/api/settings',body);
  for(const id of ['xunji-key','oura-secret','openai-key'])$(id).value='';
  $('settings-status').textContent='设置已保存在本机。';
  await refreshStatus();
}
$('settings-button').onclick=()=>{$('openai-model').value=state?.model||'';$('settings-dialog').showModal();};
$('settings-close').onclick=()=>$('settings-dialog').close();
$('settings-form').onsubmit=async e=>{e.preventDefault();try{await saveSettings();}catch(e){$('settings-status').textContent=e.message;}};
$('connect-oura').onclick=async()=>{const b=$('connect-oura');b.disabled=true;try{await saveSettings();const r=await api('/api/oura/connect',{});window.location.assign(r.url);}catch(e){$('settings-status').textContent=e.message;b.disabled=false;}};
$('sync').onclick=async()=>{try{$('sync').disabled=true;await api('/api/sync',{days:Number($('sync-days').value)});wasRunning=true;status('开始同步…');await refreshStatus();}catch(e){status(e.message,true);$('sync').disabled=false;}};
$('report-date').onchange=()=>{dirtyCheckin=false;refreshReport().catch(e=>status(e.message,true));};
for(const key of ['energy','soreness'])$(key).oninput=()=>{dirtyCheckin=true;updateRanges();};
$('note').oninput=()=>{dirtyCheckin=true;};
$('daily-plan').onchange=()=>{dirtyCheckin=true;};
$('checkin-form').onsubmit=async e=>{e.preventDefault();const d=selected();try{await api('/api/checkin',{date:d,energy:Number($('energy').value),soreness:Number($('soreness').value),note:$('note').value,plan:$('daily-plan').value,muscle_soreness:localSoreness()});if(d===selected()){dirtyCheckin=false;await refreshReport();}status('当日计划与感受已保存，日报已更新。');}catch(e){status(e.message,true);}};
$('ai-generate').onclick=async()=>{
  if(!state.ai){$('settings-dialog').showModal();$('settings-status').textContent='请先填写 OpenAI API Key 和模型 ID。';return;}
  if(!$('ai-consent').checked){status('请先勾选 AI 摘要发送授权。',true);return;}
  const b=$('ai-generate'),d=selected();b.disabled=true;b.textContent='正在生成…';
  try{const r=await api('/api/ai',{date:d,consent:true});if(d===selected()){$('ai-result').textContent=r.text;$('ai-meta').textContent='刚刚生成 · '+r.model;}status('AI 日报已保存。');}
  catch(e){status(e.message,true);}finally{b.disabled=false;b.textContent='生成 AI 日报 ↗';}
};
(async()=>{try{await refreshStatus();await refreshReport();polling=setInterval(()=>{if(wasRunning)refreshStatus().catch(e=>status(e.message,true));},1800);}catch(e){status('本地服务连接失败：'+e.message,true);}})();
