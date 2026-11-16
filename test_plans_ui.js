const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const nodes={};function node(tag='',value='',cls=''){return{tag,textContent:value,className:cls,children:[],attrs:{},append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},setAttribute(k,v){this.attrs[k]=v}}}
const scope={text:node,$:id=>nodes[id]||(nodes[id]=node()),state:{today:'2030-01-01'},console,Date};vm.createContext(scope);
vm.runInContext(fs.readFileSync(__dirname+'/static/plans.js','utf8'),scope);
const ex={name:'Lift',role:'strength',sets:3,reps:10,target_rir:null,prescribed_sets:[{reps:10},{reps:8},{reps:8},{warmup:true,reps:5}]};
assert.match(scope.planPrescription(ex),/10.*8.*8/);assert.doesNotMatch(scope.planPrescription(ex),/null|undefined/);
assert.match(scope.planPrescription({prescribed_sets:[{seconds:45},{seconds:44}]}),/45.*44/);
assert.match(scope.planPrescription({prescribed_sets:[{distance_note:'unmeasured'}]}),/unmeasured/);
const p={date:'2030-01-01',version:1,kind:'train',status:'draft',template_name:'Pull',exercises:[ex],reasons:[]},b=JSON.parse(JSON.stringify(p));
assert.equal(scope.planDiff(b,p).filter(r=>r.changed).length,0);
const revised={...p,exercises:[{...ex,sets:2,prescribed_sets:[{reps:10},{reps:8}]}]};
assert.equal(scope.planDiff(p,revised).filter(r=>r.changed).length,1);
const flatten=n=>[n.textContent,...n.children.map(flatten)].join(' ');
scope.renderPlanWorkspace({plans:{[p.date]:p},plan_baselines:{[p.date]:b}},p.date);
assert.match(flatten(nodes['coach-plans']),/原计划未变/);
scope.renderPlanWorkspace({plans:{[p.date]:{...p,revision_proposal:revised}},plan_baselines:{[p.date]:b}},p.date);
assert.match(flatten(nodes['coach-plans']),/尚未应用/);assert.match(flatten(nodes['coach-plans']),/接受上述修订/);
assert.equal(p.exercises[0].sets,3);
scope.renderPlanWorkspace({plans:{[p.date]:{...p,revision_proposal:{kind:'rest',exercises:[]}}},plan_baselines:{[p.date]:b}},p.date);
assert.match(flatten(nodes['coach-plans']),/改为休息/);assert.match(flatten(nodes['coach-plans']),/移除/);
console.log('Plan workspace tests passed');

