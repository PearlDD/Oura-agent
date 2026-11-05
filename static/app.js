const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="iron-token"]').content;
let state, loadedDate, wasRunning = false, polling, dirtyCheckin = false;
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
    updateRanges();dirtyCheckin=false;
  }
  loadedDate=d;
  $('export').href='/api/export?date='+d;$('export').download='训练日报-'+d+'.md';
  const ai=await api('/api/ai?date='+d);
  if(selected()!==d)return;
  $('ai-result').textContent=ai.text||'';
  $('ai-meta').textContent=ai.generated_at?`已保存的解读 · ${ai.model} · ${new Date(ai.generated_at*1000).toLocaleString('zh-CN')}（同步后可重新生成）`:'';
}
function updateRanges(){for(const key of ['energy','soreness'])$(key+'-value').textContent=$(key).value+' / 5';}
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
$('checkin-form').onsubmit=async e=>{e.preventDefault();const d=selected();try{await api('/api/checkin',{date:d,energy:Number($('energy').value),soreness:Number($('soreness').value),note:$('note').value,plan:$('daily-plan').value});if(d===selected()){dirtyCheckin=false;await refreshReport();}status('当日计划与感受已保存，日报已更新。');}catch(e){status(e.message,true);}};
$('ai-generate').onclick=async()=>{
  if(!state.ai){$('settings-dialog').showModal();$('settings-status').textContent='请先填写 OpenAI API Key 和模型 ID。';return;}
  if(!$('ai-consent').checked){status('请先勾选 AI 摘要发送授权。',true);return;}
  const b=$('ai-generate'),d=selected();b.disabled=true;b.textContent='正在生成…';
  try{const r=await api('/api/ai',{date:d,consent:true});if(d===selected()){$('ai-result').textContent=r.text;$('ai-meta').textContent='刚刚生成 · '+r.model;}status('AI 日报已保存。');}
  catch(e){status(e.message,true);}finally{b.disabled=false;b.textContent='生成 AI 日报 ↗';}
};
(async()=>{try{await refreshStatus();await refreshReport();polling=setInterval(()=>{if(wasRunning)refreshStatus().catch(e=>status(e.message,true));},1800);}catch(e){status('本地服务连接失败：'+e.message,true);}})();
