let sourceProgramState={};
window.renderSourceProgram=function(value,date){
  sourceProgramState=value;
  const active=value.active,draft=value.draft,shown=draft||active;
  $('program-source').textContent=active?`${active.name} · 现行计划副本 · 来源：你确认的训记资料 · 本地版本 ${active.version}。训记后续改动不会自动同步。`:'尚未启用现行计划；网页草案不能代替你的训记日程。';
  $('program-confirm-box').hidden=!draft;$('program-shift-box').hidden=!active;
  const preview=$('program-preview');preview.replaceChildren();
  if(!shown)return;
  preview.append(text('p',(draft?'待核对导入：':'已导入：')+shown.name));
  preview.append(text('p',`周期起点 ${shown.anchor_date} · `+shown.cycle.map((id,i)=>`${i+1}. ${id?shown.templates[id].name:'休息'}`).join(' → '),'footnote'));
  preview.append(text('p','规则：'+(shown.shift_rule==='shift_all'?'确认训练未完成后，后续训练与休息整体顺延一天。':'顺延方式待确认。')+' 不会自动写回 SynFit。','footnote'));
  for(const pending of value.pending_followup||[])preview.append(text('p',pending.date+'：训练完成情况待核对。先补同步或确认完成；确实没练时再整体顺延。','footnote'));
  for(const template of Object.values(shown.templates)){
    const detail=text('details','');detail.append(text('summary',template.name+' · 查看逐组安排'));
    const list=text('ul','');for(const move of template.movements)list.append(text('li',formatPrescribedMove(move)));detail.append(list);preview.append(detail);
  }
  if(document.activeElement?.id!=='program-shift-date')$('program-shift-date').value=value.pending_followup?.[0]?.date||date;
  $('program-shift-date').max=state.today;
};
$('program-file').onchange=async event=>{
  const file=event.target.files?.[0];if(!file)return;
  try{if(file.size>90000)throw new Error('计划文件过大。');const value=JSON.parse(await file.text());await api('/api/program',{action:'preview',program:value});$('program-confirm').checked=false;await refreshReport();$('program-status').textContent='已生成导入预览，请逐项核对后确认。';}catch(error){$('program-status').textContent=error.message;}
};
$('program-activate').onclick=async()=>{
  try{if(!$('program-confirm').checked)throw new Error('请先核对导入内容并勾选确认。');await api('/api/program',{action:'activate',id:sourceProgramState.draft?.id,confirmed:true});$('program-confirm').checked=false;await refreshReport();$('program-status').textContent='已启用现行计划副本；旧分析需要以新计划重新评估。';}catch(error){$('program-status').textContent=error.message;}
};
$('program-shift').onclick=async()=>{
  try{if(!$('program-unfinished').checked)throw new Error('请先确认该日训练未完成。');await api('/api/program',{action:'shift',date:$('program-shift-date').value,version:sourceProgramState.active?.version,confirmed:true});$('program-unfinished').checked=false;await refreshReport();$('program-status').textContent='已整体顺延一天，训记内的安排未被修改。';}catch(error){$('program-status').textContent=error.message;}
};

if(typeof coachData!=='undefined'&&coachData)window.renderSourceProgram(coachData.source_program||{},selected());
