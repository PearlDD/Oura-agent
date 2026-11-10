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
  const previousProvider=state?.ai_provider;
  state = await api('/api/status');
  if(previousProvider&&previousProvider!==state.ai_provider){$('chat-consent').checked=false;$('ai-consent').checked=false;}
  const recipient=state.ai_provider==='gemini'?'Google / Gemini':'OpenAI';
  $('ai-consent-copy').textContent=`允许将近28天训练、恢复、活动、肌群估计、偏好、计划、疲劳、症状、strain及周期背景发送至 ${recipient}。`;
  $('chat-consent-copy').textContent=`同意将本次问题、近期对话及所选报告背景（含训练、恢复、症状和周期）发送至 ${recipient}。`;
  $('chat-data-note').textContent=state.ai_provider==='gemini'?'对话保存在应用服务器，聊天不自动改计划。Gemini API 可能收费，数据处理适用 Google 付费服务条款。':'对话保存在应用服务器，聊天不自动改计划。API 可能收费，store:false 不等于零数据保留。';
  if (!$('report-date').value) {$('report-date').value=state.today; $('report-date').max=state.today;}
  $('timezone').textContent=state.timezone;
  for (const [name,label] of [['xunji','已配置'],['oura','已授权']]) {
    $(name+'-dot').classList.toggle('on',state[name]);
    $(name+'-state').textContent=state[name] ? label : '待连接';
  }
  $('ai-state').textContent=state.ai?'已配置':'可选 · 待配置';
  $('redirect-uri').value=state.redirect_uri;
  if(typeof window.renderAutomation==='function')window.renderAutomation(state.automation,state.push);
  $('sync').disabled=state.job.running;
  const errors=state.job.errors || [];
  if(state.job.running)status(state.job.message);
  else if(errors.length)status('上次同步：'+errors.join('；')+(state.xunji&&errors.some(e=>e.includes('请先配置训记 API Key'))?' 当前训记密钥已保存，请重新同步验证。':''),true);
  else status(state.dates.length ? `已缓存 ${state.dates.length} 个日期 · ${state.job.message}`:'连接已就绪，点击「同步数据」读取真实训练记录。');
  if (wasRunning && !state.job.running) await refreshReport();
  wasRunning=state.job.running;
}
async function refreshReport() {
  const d=selected();
  const r=await api('/api/report?date='+d);
  if(selected()!==d)return;
  renderDecision(r.decision,r.coach_agent.plans[r.date]);renderClues(r);
  renderHealth(r.health_observations,d);
  const fields={sleep:'sleep_hours',hrv:'hrv',rhr:'rhr'};
  for(const [id,key] of Object.entries(fields)) {
    $(id).textContent=fmt(r.recovery[key], id==='sleep'?1:0);
    const b=r.baseline[key];
    $(id+'-baseline').textContent=r.recovery.sleep_status==='pending_main'?'完整主睡眠待同步 · 片段不参与分析':b.value==null?`基线样本 ${b.n}/7 晚`:`28 天中位数 ${fmt(b.value,id==='sleep'?1:0)} · ${b.n} 晚`;
  }
  $('sets').textContent=r.week.sets;
  $('week-meta').textContent=`${r.week.sessions} 次记录 · 已读取 ${r.coverage}/7 天`;
  $('observations').replaceChildren(...r.observations.map(n=>text('li',n)));
  $('focus').textContent=r.focus;
  $('limits').textContent=r.limits;
  coachData=r.coach_agent;
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
    const row=text('div','','trend-row');row.append(text('strong',label),text('span',detail));
    if(recent.value!=null&&previous.value!=null){const max=Math.max(recent.value,previous.value,1)*1.12;for(const [v,cls,name] of [[previous.value,'trend-previous','此前'],[recent.value,'trend-current','最近']]){const bar=text('div','','trend-bar');bar.append(text('small',name));const rail=text('div',''),fill=text('i','',cls);fill.style.width=(v/max*100)+'%';rail.append(fill);bar.append(rail);row.append(bar);}}$('recovery-trends').append(row);
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
function brief(value,max=82){
  if(!value)return '';
  const first=value.split(/(?<=[。！？])/u)[0];
  return first.length>max?first.slice(0,max-1)+'…':first;
}
function decisionSignal(record,plan){
  if(!record||record.stale)return {tone:'neutral',label:record?.stale?'分析已过期':'等待生成分析',english:record?.stale?'REGENERATE ANALYSIS':'WAIT FOR INSIGHT'};
  const v=record.analysis.verdict;
  if(v==='rest')return {tone:'red',label:'今天先休息',english:'REST & RESET'};
  if(v==='reduce'||v==='light')return {tone:'amber',label:v==='light'?'轻轻动一动':'放慢一点',english:'GO EASY'};
  if(v==='clarify')return {tone:'neutral',label:'先听听身体怎么说',english:'CHECK IN FIRST'};
  if(plan?.kind!=='train')return {tone:'neutral',label:plan?.kind==='rest'?'按计划休息':'先核对今天的安排',english:plan?.kind==='rest'?'PLANNED REST':'CHECK YOUR PLAN'};
  return {tone:'green',label:'按计划练，稳稳来',english:'READY FOR YOUR PLAN'};
}
function renderDecision(record,plan){
  const labels={keep:'保持原安排',reduce:'减量',rest:'休息',light:'轻量活动',clarify:'先补信息'};
  const a=record?.analysis,signal=decisionSignal(record,plan);
  $('decision-panel').dataset.tone=signal.tone;
  $('decision-panel').querySelector('.eyebrow').textContent=record?.stale?'AI 历史分析 · 等待更新':'TODAY’S CALL · AI 今日建议';
  $('decision-signal').textContent=signal.label;$('decision-english').textContent=signal.english;
  $('decision-verdict').textContent=record?.stale?'待重新生成':a?labels[a.verdict]:'尚无结论';
  $('decision-headline').textContent=record?.stale?'数据已变化，请重新生成今日分析。':a?.headline||'同步数据后，让 Agent 看看今天适合怎么练。';
  $('decision-rationale').textContent=record?.stale?'下方保留的是上次分析记录，不作为今天训练安排的依据。':a?brief(a.rationale.split(/(?<=[。！？])/u).find(v=>!v.includes('不存在的训练'))||a.rationale,105):'已有规则草案，等待实际 AI 分析。';
  $('decision-full-rationale').textContent=a?.rationale||'';
  $('decision-meta').textContent=record?`${record.source} · ${new Date(record.created_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} · ${record.stale?'数据已变化，以下为历史分析':{low:'仍需主观反馈',medium:'部分信息待核对',high:'信息较完整'}[a.confidence]}`:'';
  $('decision-evidence').replaceChildren(...(a?.evidence||[]).map(e=>text('li',e.statement)));
  $('decision-options').replaceChildren(...(a?.options||[]).map(o=>text('p',`${labels[o.mode]} · ${o.when}：${o.details}`)));
  const box=$('decision-details');box.replaceChildren();
  for(const [label,key] of [['肌群负荷复核','muscle_review'],['短期调整','short_term'],['长期计划','long_term'],['待确认','questions']]){
    if(a?.[key]?.length){const ul=text('ul','');ul.append(...a[key].map(v=>text('li',v)));box.append(text('h3',label),ul);}
  }
  $('decision-next').textContent=record?.stale?'先完成数据同步，再确认 AI 数据发送授权并点击生成解读。':a?brief(a.questions?.[0]||a.short_term?.[0]||a.headline,85):'先同步 Oura 和训记，再生成当日分析。';
  $('decision-apply').hidden=!a?.adjustment||record.stale;
}
function renderClues(r){
  const rows=[],cur=r.recovery;
  for(const [key,label,unit] of [['hrv','HRV','ms'],['rhr','夜间最低心率','bpm']]){
    const b=r.baseline[key].value,v=cur[key];
    rows.push([label,v==null?'待同步':`${fmt(v)} ${unit}`,b==null?'基线不足':`平时 ${fmt(b)} ${unit}`]);
  }
  const h=r.health_observations.history.find(v=>v.date===r.date);
  const level={major:'Major',minor:'Minor',none:'No signs',unknown:'未填写'}[h?.strain]||'未填写';
  rows.push(['Strain',level,h?'用户报告':'待核对']);
  $('decision-clues').replaceChildren(...rows.map(([label,value,sub])=>{const row=text('div','','decision-clue');row.append(text('span',label),text('strong',value),text('small',sub));return row;}));
}
function renderHealth(h,d){
  const row=h.history.find(v=>v.date===d)||{};
  if(document.activeElement?.closest('#health-form'))return;
  $('health-strain').value=row.strain||'unknown';$('health-cycle').value=row.cycle||'unknown';$('health-symptoms').value=row.symptoms||'';
  $('health-history').textContent=h.history.map(v=>`${v.date} · strain ${v.strain} · ${v.symptoms||'症状未填'}`).join('；');
}
$('health-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/health',{date:selected(),strain:$('health-strain').value,cycle:$('health-cycle').value,symptoms:$('health-symptoms').value});await refreshReport();status('身体背景已保存；需要重新生成 AI 分析。');}catch(e){status(e.message,true);}};
$('decision-apply').onclick=async()=>{try{await api('/api/decision/apply',{date:selected()});await refreshReport();status('已提交修订提案，请在计划卡片核对后决定是否接受。');}catch(e){status(e.message,true);}};
function renderCoach(c,d){
  $('coach-profile-state').textContent=c.profile.confirmed?(c.profile.schedule_provisional||c.profile.minutes_provisional?'安排待确认':'偏好已确认'):'偏好待确认';
  const labels={draft:'草案',accepted:'已接受',completed:'已手动标记完成',skipped:'已跳过'};
  const box=$('coach-plans');box.replaceChildren();
  const upcoming=Object.values(c.plans).filter(p=>p.date>=d).sort((a,b)=>a.date.localeCompare(b.date));
  for(const p of upcoming){
    const card=text('article','','plan-card');card.append(text('h3',p.date+' · '+({train:'训练',rest:'休息',review:'待核对'}[p.kind])),text('small',`${labels[p.status]} · 版本 ${p.version}`));
    const drill=text('details','','plan-drill');drill.append(text('summary','查看安排 ↗'));card.append(text('p',p.kind==='train'?`${p.exercises.length} 个动作 · ${p.exercises.reduce((n,e)=>n+e.sets,0)} 组`:p.kind==='rest'?'恢复 / 自由安排':'先核对限制','plan-preview'));
    const list=text('ul','');for(const e of p.exercises){list.append(text('li',`${e.name}：${e.sets} × ${e.reps}，预留约 ${e.target_rir} 次；${e.reference_kg==null?'负重未填':'历史参考 '+fmt(e.reference_kg,1)+' kg'}`));}drill.append(list);for(const e of p.exercises)if(e.adaptation)drill.append(text('small',e.name+'：'+e.adaptation));
    const why=text('details','');why.append(text('summary','依据与调整说明'));for(const r of p.reasons)why.append(text('p',r));drill.append(why);
    if(p.tracking)drill.append(text('p',p.tracking.message));
    if(p.revision_proposal){const rev=text('div','','plan-revision');rev.append(text('strong','有新的修订草案，当前计划保留'));for(const e of p.revision_proposal.exercises)rev.append(text('p',`${e.name}：${e.sets} × ${e.reps}，预留 ${e.target_rir} 次`));for(const r of p.revision_proposal.reasons)rev.append(text('small',r));drill.append(rev);}
    const actions=text('div','','plan-actions');
    for(const [action,label] of [['accepted','接受计划'],['completed','标记已完成'],['skipped','跳过'],['accept_revision','接受修订']]){
      if(action==='accepted'&&(p.status!=='draft'||p.kind==='review'))continue;
      if(action==='completed'&&(p.date>state.today||p.kind!=='train'||p.status==='completed'))continue;
      if(action==='accept_revision'&&(!p.revision_proposal||p.revision_proposal.kind==='review'))continue;
      if(action==='skipped'&&p.status==='skipped')continue;
      const b=text('button',label,'ghost');b.type='button';b.onclick=async()=>{try{await api('/api/coach',{action:'plan_status',date:p.date,version:p.version,status:action});await refreshReport();status('计划状态已保存。');}catch(e){status(e.message,true);}};actions.append(b);
    }
    drill.append(actions);card.append(drill);box.append(card);
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
  const p=coachData.profile;$('coach-goal').value=p.goal;$('coach-minutes').value=p.minutes;$('coach-split').value=p.split||'history';$('coach-shoulder-caution').checked=!!p.shoulder_caution;$('coach-shoulder-review').checked=!!p.shoulder_review_required;$('coach-exercises').value=p.excluded_exercises.join('\n');
  for(const [id,entries,chosen] of [['coach-weekdays',['周一','周二','周三','周四','周五','周六','周日'].map((n,i)=>[String(i),n]),p.weekdays.map(String)],['coach-exclusions',Object.entries(muscleData.groups),p.excluded_muscles],['coach-priorities',Object.entries(muscleData.groups),p.priority_muscles||[]],['coach-depriorities',Object.entries(muscleData.groups),p.deprioritized_muscles||[]]]){
    const box=$(id);box.replaceChildren();for(const [key,label] of entries){const lab=text('label','','choice'),input=document.createElement('input');input.type='checkbox';input.value=key;input.checked=chosen.includes(key);lab.append(input,document.createTextNode(label));box.append(lab);}
  }
  $('coach-profile-message').textContent='';$('coach-profile-dialog').showModal();
};
$('coach-profile-close').onclick=()=>$('coach-profile-dialog').close();
$('coach-profile-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/coach',{action:'profile',profile:{goal:$('coach-goal').value,split:$('coach-split').value,shoulder_caution:$('coach-shoulder-caution').checked,shoulder_review_required:$('coach-shoulder-review').checked,schedule_provisional:false,minutes_provisional:false,priority_muscles:[...$('coach-priorities').querySelectorAll('input:checked')].map(e=>e.value),deprioritized_muscles:[...$('coach-depriorities').querySelectorAll('input:checked')].map(e=>e.value),minutes:Number($('coach-minutes').value),weekdays:[...$('coach-weekdays').querySelectorAll('input:checked')].map(e=>Number(e.value)),excluded_muscles:[...$('coach-exclusions').querySelectorAll('input:checked')].map(e=>e.value),excluded_exercises:$('coach-exercises').value.split('\n').map(s=>s.trim()).filter(Boolean)}});await refreshReport();$('coach-profile-dialog').close();status('训练偏好已保存，未来草案已更新。');}catch(e){$('coach-profile-message').textContent=e.message;}};
function updateRanges(){for(const key of ['energy','soreness'])$(key+'-value').textContent=$(key).value+' / 5';}
function option(value,label){const o=text('option',label);o.value=value;return o;}
function renderLoadChart(m){
  const priority=new Set(coachData?.profile?.priority_muscles||['glutes','lats','upper_back','side_delts']);
  const rows=m.muscles.filter(v=>priority.has(v.key)||['rear_delts','hamstrings'].includes(v.key));
  const max=Math.max(1,...rows.flatMap(v=>[v.week_sets,v.previous_sets,v.usual_week||0]));
  const cap=Math.max(5,Math.ceil(max/5)*5),box=$('load-chart');box.replaceChildren();
  const cover=m.coverage||[];
  $('load-coverage').textContent=`读取 ${cover[0]??0}/7 天 · 前周 ${cover[1]??0}/7 天 · 0–${cap} 当量`;
  for(const r of rows){
    const row=text('div','','load-row'),head=text('div','','load-label');
    head.append(text('strong',r.name),text('span',`${fmt(r.week_sets,1)} 组${cover[0]<7?' · 未齐':''}`));row.append(head);
    const plot=text('div','','load-plot');plot.title=`近7天 ${r.week_sets}（主练 ${r.direct_sets} / 间接 ${r.indirect_sets}）；前7天 ${r.previous_sets}；历史 ${r.usual_week??'不足'} 组当量`;
    const now=text('div','','load-track load-now');now.setAttribute('role','img');
    now.setAttribute('aria-label',`${r.name}近七天主练 ${r.direct_sets} 组，间接 ${r.indirect_sets} 当量，前七天 ${r.previous_sets}，历史周量 ${r.usual_week??'不足'}`);
    for(const [value,cls] of [[r.direct_sets,'bar-direct'],[r.indirect_sets,'bar-indirect']]){const fill=text('i','',cls);fill.style.width=(Math.max(0,value)/cap*100)+'%';now.append(fill);}
    if(r.week_sets===0&&cover[0]===7)now.append(text('i','','bar-zero'));
    const previous=text('div','','load-track load-before'),fill=text('i','','bar-previous');fill.style.width=(Math.max(0,r.previous_sets)/cap*100)+'%';previous.append(fill);
    plot.append(now,previous);
    if(r.usual_week!=null){const marker=text('i','','bar-marker');marker.style.left=(Math.max(0,r.usual_week)/cap*100)+'%';marker.title=`历史周量 ${r.usual_week} 当量`;plot.append(marker);}
    row.append(plot);box.append(row);
  }
  if(!rows.length)box.append(text('p','暂无可归类的肌群数据，先同步或核对动作归属。','muted'));
  $('load-summary').textContent=cover[0]<7||cover[1]<7?'读取尚未齐全：条形只表示已同步的记录，缺失日期不能当作零负荷。':rows.every(r=>r.week_sets===0)?'近 7 天未记录这些肌群的正式组；浅色条保留前 7 天的训练分布。低负荷不等于已经恢复。':'实色＋浅绿为本周主练与间接参与；灰条对照前周，虚线标记个人历史。';
}
function renderMuscles(m){
  renderLoadChart(m);
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
  const fields={'xunji_key':'xunji-key','oura_client_id':'oura-client','oura_client_secret':'oura-secret','openai_key':'openai-key','openai_model':'openai-model','gemini_key':'gemini-key','gemini_model':'gemini-model'};
  const body={};for(const [k,id] of Object.entries(fields))if($(id).value.trim())body[k]=$(id).value.trim();
  body.ai_provider=$('ai-provider').value;body.gemini_paid_confirmed=$('gemini-paid').checked;
  await api('/api/settings',body);
  for(const id of ['xunji-key','oura-secret','openai-key','gemini-key'])$(id).value='';
  $('settings-status').textContent='设置已保存在应用服务器。';
  $('chat-consent').checked=false;$('ai-consent').checked=false;
  await refreshStatus();if(!$('chat-drawer').hidden)await loadChat();
}
function renderProviderSettings(){const g=$('ai-provider').value==='gemini';$('gemini-fields').hidden=!g;$('openai-fields').hidden=g;}
$('ai-provider').onchange=renderProviderSettings;
function openSettings(){
  $('ai-provider').value=state?.ai_provider||'gemini';$('openai-model').value=state?.ai_models?.openai||'';$('gemini-model').value=state?.ai_models?.gemini||'';$('gemini-paid').checked=!!state?.gemini_paid_confirmed;renderProviderSettings();$('settings-dialog').showModal();
}
$('settings-button').onclick=openSettings;
$('settings-close').onclick=()=>$('settings-dialog').close();
$('settings-form').onsubmit=async e=>{e.preventDefault();try{await saveSettings();}catch(e){$('settings-status').textContent=e.message;}};
$('connect-oura').onclick=async()=>{const b=$('connect-oura');b.disabled=true;try{await saveSettings();const r=await api('/api/oura/connect',{});window.location.assign(r.url);}catch(e){$('settings-status').textContent=e.message;b.disabled=false;}};
$('sync').onclick=async()=>{try{$('sync').disabled=true;await api('/api/sync',{days:Number($('sync-days').value)});wasRunning=true;status('开始同步…');await refreshStatus();}catch(e){status(e.message,true);$('sync').disabled=false;}};
$('report-date').onchange=()=>{dirtyCheckin=false;$('chat-consent').checked=false;refreshReport().catch(e=>status(e.message,true));if(!$('chat-drawer').hidden)loadChat();};
for(const key of ['energy','soreness'])$(key).oninput=()=>{dirtyCheckin=true;updateRanges();};
$('note').oninput=()=>{dirtyCheckin=true;};
$('daily-plan').onchange=()=>{dirtyCheckin=true;};
$('checkin-form').onsubmit=async e=>{e.preventDefault();const d=selected();try{await api('/api/checkin',{date:d,energy:Number($('energy').value),soreness:Number($('soreness').value),note:$('note').value,plan:$('daily-plan').value,muscle_soreness:localSoreness()});if(d===selected()){dirtyCheckin=false;await refreshReport();}status('当日计划与感受已保存，日报已更新。');}catch(e){status(e.message,true);}};
$('ai-generate').onclick=async()=>{
  if(!state.ai){openSettings();$('settings-status').textContent='请先配置所选 AI 提供商的密钥、模型与必要确认。';return;}
  if(!$('ai-consent').checked){status('请先勾选 AI 摘要发送授权。',true);return;}
  const b=$('ai-generate'),d=selected();b.disabled=true;b.textContent='正在生成…';
  try{const r=await api('/api/ai',{date:d,consent:true,provider:state.ai_provider});if(d===selected()){$('ai-result').textContent=r.text;$('ai-meta').textContent='刚刚生成 · '+r.model;}await refreshReport();status('AI 决策已保存。');}
  catch(e){status(e.message,true);}finally{b.disabled=false;b.textContent='生成 AI 日报 ↗';}
};
let chatState=null,chatDate=null,chatLoading=false,chatSending=false;
const chatDrafts={};
function chatStatus(message,error=false){$('chat-status').textContent=message;$('chat-status').classList.toggle('error',error);}
function renderChat(c){
  chatState=c;$('chat-context-date').textContent='正在讨论 '+c.date+' 的报告';
  $('chat-model').textContent=c.ready?`${c.provider_label} · ${c.model} · 最近6轮对话`:c.configuration_error||'请先在连接与设置配置模型和 API Key';
  const box=$('chat-messages');box.replaceChildren();
  if(!c.messages.length){const empty=text('div','','chat-welcome');empty.append(text('strong','看不懂哪一处？直接问。'),text('p','我会结合这份报告和当前计划解释。你的问题可以继续追问；这里的对话与 Codex 聊天分别保存。'));box.append(empty);}
  for(const m of c.messages){const bubble=text('article','',m.role==='user'?'chat-bubble chat-user':'chat-bubble chat-agent');bubble.append(text('small',m.role==='user'?'你':'训练 Agent'),text('p',m.text));if(m.role==='assistant'&&m.context_changed)bubble.append(text('small','回答后数据已变化，以新提问时的背景为准。','chat-old'));box.append(bubble);}
  $('chat-new').disabled=chatSending||c.busy;
  $('chat-send').disabled=chatSending||c.busy||!c.ready;
  const examples=['这些组数是减载还是基础安排？','今天为什么建议休息？','预留 3 次是什么意思？'];
  $('chat-suggestions').replaceChildren(...(c.messages.length?[]:examples.map(q=>{const b=text('button',q,'ghost');b.type='button';b.onclick=()=>{$('chat-input').value=q;chatDrafts[chatDate]=q;$('chat-input').focus();};return b;})));
  box.scrollTop=box.scrollHeight;
}
async function loadChat(){
  const d=selected();
  if(chatDate&&chatDate!==d)chatDrafts[chatDate]=$('chat-input').value;
  chatDate=d;chatLoading=true;chatStatus('正在读取这份报告的对话…');$('chat-send').disabled=true;
  try{const c=await api('/api/chat?date='+d);if(chatDate!==d)return;renderChat(c);$('chat-input').value=chatDrafts[d]||'';chatStatus(c.busy?'Agent 正在回复，请稍后刷新对话。':c.provider_notice?'上次连接检查：'+c.provider_notice:'',!!c.provider_notice);}
  catch(e){if(chatDate===d){chatState=null;$('chat-messages').replaceChildren();chatStatus(e.message,true);}}
  finally{if(chatDate===d)chatLoading=false;}
}
async function openChat(){
  $('chat-drawer').hidden=false;$('chat-toggle').setAttribute('aria-expanded','true');
  await loadChat();$('chat-input').focus();
}
function closeChat(){if(chatDate)chatDrafts[chatDate]=$('chat-input').value;$('chat-drawer').hidden=true;$('chat-toggle').setAttribute('aria-expanded','false');$('chat-toggle').focus();}
$('chat-toggle').onclick=()=>{$('chat-drawer').hidden?openChat():closeChat();};
$('chat-open-inline').onclick=openChat;$('chat-close').onclick=closeChat;
$('chat-input').oninput=()=>{if(chatDate)chatDrafts[chatDate]=$('chat-input').value;};
$('chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chat-form').requestSubmit();}};
$('chat-drawer').onkeydown=e=>{if(e.key==='Escape')closeChat();};
$('chat-new').onclick=async()=>{if(chatSending||!chatState||chatLoading)return;try{const d=chatDate;const c=await api('/api/chat/new',{date:d,revision:chatState.revision});if(d===chatDate){chatDrafts[d]='';$('chat-input').value='';$('chat-consent').checked=false;renderChat(c);chatStatus('已开始新对话，旧对话仍保存在应用服务器归档。');}}catch(e){chatStatus(e.message,true);}};
$('chat-form').onsubmit=async e=>{
  e.preventDefault();if(chatSending||chatLoading||!chatState||chatState.date!==chatDate)return;
  const d=chatDate,message=$('chat-input').value.trim();
  if(!message){chatStatus('先输入一个问题。',true);return;}
  if(!$('chat-consent').checked){chatStatus('请先勾选本次聊天的数据发送授权。',true);return;}
  chatSending=true;$('chat-send').disabled=true;$('chat-new').disabled=true;chatStatus('Agent 正在结合报告思考…');
  try{const c=await api('/api/chat',{date:d,message,revision:chatState.revision,consent:true,provider:chatState.provider});chatDrafts[d]='';if(chatDate===d){$('chat-input').value='';renderChat(c);chatStatus('已回复；回答基于发送时的报告。');}}
  catch(e){if(chatDate===d)chatStatus(e.message+' 问题仍保留，可重试。',true);}
  finally{chatSending=false;$('chat-send').disabled=!chatState?.ready||chatState?.busy;$('chat-new').disabled=!!chatState?.busy;}
};
(async()=>{try{await refreshStatus();await refreshReport();polling=setInterval(()=>{if(wasRunning)refreshStatus().catch(e=>status(e.message,true));},1800);}catch(e){status('服务连接失败：'+e.message,true);}})();
