/* Plans are views of saved state. Chat prose never becomes a revision. */
let coachSelectedDate='';
function planPrescription(e){
  if(!e)return '—';
  if(e.prescribed_sets){
    const work=e.prescribed_sets.filter(s=>!s.warmup),warm=e.prescribed_sets.filter(s=>s.warmup);
    const target=s=>s.seconds!=null?s.seconds+'秒':s.reps!=null?s.reps+'次':s.distance_note||'距离 / 时长待记录';
    const values=work.map(target);
    const main=values.length?(new Set(values).size===1?values.length+'组 × '+values[0]:values.length+'组 · '+values.join(' / ')):'无正式组';
    return main+(warm.length?'；另 '+warm.length+'组热身':'')+(e.target_rir!=null?' · RIR '+e.target_rir:'');
  }
  return e.sets+'组'+(e.reps!=null?' × '+e.reps+'次':'')+(e.target_rir!=null?' · RIR '+e.target_rir:'');
}
function planKey(e){return JSON.stringify(e?[e.sets,e.reps,e.target_rir,e.prescribed_sets?.map(s=>[s.reps,s.seconds,s.warmup,s.distance_note])]:null);}
function planDiff(base,current){
  const names=[...new Set([...(base?.exercises||[]),...(current?.exercises||[])].map(e=>e.name))];
  return names.map(name=>({name,before:base?.exercises?.find(e=>e.name===name),after:current?.exercises?.find(e=>e.name===name)}))
    .map(r=>({...r,changed:planKey(r.before)!==planKey(r.after)}));
}
function renderPlanWorkspace(c,d){
  const host=$('coach-plans');host.className='plan-workspace';host.replaceChildren();
  const plans=Object.values(c.plans).filter(p=>p.date>=d).sort((a,b)=>a.date.localeCompare(b.date));
  if(!plans.length){host.append(text('p','点击「更新计划与跟进」生成安排。'));return;}
  if(!plans.some(p=>p.date===coachSelectedDate))coachSelectedDate=plans[0].date;
  const strip=text('nav','','week-strip');strip.setAttribute('aria-label','选择训练日期');
  for(const p of plans){
    const b=text('button','','week-day'+(p.date===coachSelectedDate?' is-selected':''));
    b.type='button';b.setAttribute('aria-pressed',String(p.date===coachSelectedDate));
    b.append(text('small',p.date.slice(5).replace('-','/')+' · '+['日','一','二','三','四','五','六'][new Date(p.date+'T12:00:00').getDay()]),
      text('strong',p.template_name||(p.kind==='rest'?'休息日':'训练')),
      text('small',p.revision_proposal?'有待确认调整':p.status==='completed'?'已标记完成':p.kind==='rest'?'计划休息':'训练安排'));
    b.onclick=()=>{coachSelectedDate=p.date;renderPlanWorkspace(c,d);};strip.append(b);
  }
  host.append(strip);
  const p=plans.find(p=>p.date===coachSelectedDate),base=c.plan_baselines?.[p.date],proposal=p.revision_proposal;
  const changed=base?planDiff(base,p).filter(r=>r.changed):[];
  const kindChanged=base&&base.kind!==p.kind;
  const panel=text('section','','day-workspace');panel.append(text('small',p.date+' · '+({draft:'待确认安排',accepted:'已接受',completed:'已手动标记完成',skipped:'已跳过'}[p.status]||'待核对')),
    text('h3',p.template_name||(p.kind==='rest'?'休息日':'训练安排')));
  const summary=text('div','','plan-change-summary'+(proposal?' has-change':''));
  summary.append(text('strong',proposal?'有调整建议 · 尚未应用':base?(changed.length||kindChanged?'当前安排已偏离原计划':'原计划未变'):'Agent 草案 · 尚无导入原计划对照'));
  summary.append(text('p',proposal?'下面对照当前安排和待确认草案；接受修订后才会更新当前安排。':'聊天里的建议不会自动修改计划。下表展示已保存的安排。'));
  panel.append(summary);
  const before=proposal?p:base,after=proposal||p,rows=planDiff(before,after);
  if(p.kind==='rest'&&!proposal)panel.append(text('p','按计划休息 / 自由安排。休息安排不代表已完成训练。','rest-note'));
  if(proposal&&proposal.kind!==p.kind)panel.append(text('p',(p.kind==='train'?'训练':'休息')+' → '+(proposal.kind==='rest'?'改为休息':'改为训练')+'（待确认）','change-label'));
  function group(title,filter,collapsed){
    const selected=rows.filter(filter);if(!selected.length)return;
    const section=text(collapsed?'details':'section','','exercise-group');
    section.append(text(collapsed?'summary':'h4',title+' · '+selected.length+'个动作'));
    const table=text('table','','plan-table'),head=text('tr','');
    for(const name of ['动作',before?(proposal?'当前安排':'原计划'):'安排',proposal?'建议调整（待确认）':'当前安排'])head.append(text('th',name));
    const thead=text('thead','');thead.append(head);table.append(thead);
    const body=text('tbody','');
    for(const r of selected){
      const tr=text('tr','',r.changed&&before?'changed-row':'');
      const name=text('td','');name.append(text('strong',r.name));
      if(before&&r.changed)name.append(text('small',!r.after?'移除':!r.before?'新增':proposal?'待确认调整':'已变更','change-label'));
      tr.append(name,text('td',before?planPrescription(r.before):'—'),text('td',planPrescription(r.after)));
      body.append(tr);
    }
    table.append(body);section.append(table);panel.append(section);
  }
  const role=r=>(r.after||r.before).role||'strength';
  group('力量动作',r=>role(r)==='strength',false);
  group('准备 / 活动度',r=>role(r)==='preparation',true);
  group('待归类动作',r=>role(r)==='unclassified',false);
  panel.append(text('p','组数按动作分别列出，准备动作不计为力量正式组。未提供的 RIR 不补默认值；重量仅作历史参考。','footnote'));
  const refs=text('details','','plan-reference');refs.append(text('summary','历史重量参考 / 调整依据'));
  for(const e of p.exercises||[]){
    const loads=[...new Set((e.prescribed_sets||[]).map(s=>s.reference_load).filter(Boolean))];
    if(loads.length||e.reference_kg!=null)refs.append(text('p',e.name+'：'+(loads.join(' / ')||e.reference_kg+' kg')+'（历史记录，非本次要求）'));
  }
  for(const reason of [...(p.reasons||[]),...(proposal?.reasons||[])])refs.append(text('p',reason));
  refs.append(text('small','安排版本 '+p.version+' · '+(p.program_id?'来自你确认的现行计划副本':'Agent 起草')));
  panel.append(refs);if(p.tracking)panel.append(text('p',p.tracking.message,'footnote'));
  const actions=text('div','','plan-actions');
  for(const [action,label] of [['accepted','确认当前安排'],['completed','标记已完成'],['skipped','标记跳过'],['accept_revision','接受上述修订']]){
    if(action==='accepted'&&(p.status!=='draft'||p.kind==='review'))continue;
    if(action==='completed'&&(p.date>state.today||p.kind!=='train'||p.status==='completed'))continue;
    if(action==='accept_revision'&&(!proposal||proposal.kind==='review'))continue;
    if(action==='skipped'&&p.status==='skipped')continue;
    const b=text('button',label,action==='accept_revision'?'':'ghost');b.type='button';
    b.onclick=async()=>{b.disabled=true;try{await api('/api/coach',{action:'plan_status',date:p.date,version:p.version,status:action});await refreshReport();status('计划状态已保存。');}catch(e){status(e.message,true);}finally{b.disabled=false;}};
    actions.append(b);
  }
  panel.append(actions);host.append(panel);
}

