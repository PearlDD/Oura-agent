/* Run node test_decision_ui.js; evaluates the actual presentation rule. */
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/app.js'),'utf8');
const start=source.indexOf('function decisionSignal('),end=source.indexOf('function renderDecision(',start);
assert.ok(start>=0&&end>start);const scope={};vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);
function signal(verdict,kind,extra={}){return scope.decisionSignal({analysis:{verdict},stale:false},{kind,...extra});}
assert.equal(signal('rest','rest').tone,'neutral');assert.equal(signal('rest','rest').label,'按计划休息');
assert.equal(signal('rest','train').tone,'red');assert.equal(signal('rest','train').label,'今天改为休息');
assert.equal(signal('rest','rest',{original_kind:'train'}).tone,'red');
assert.equal(signal('rest','review').tone,'neutral');assert.equal(signal('rest',undefined).tone,'neutral');
assert.equal(signal('keep','rest').tone,'neutral');assert.equal(signal('keep','train').tone,'green');
assert.equal(signal('reduce','train').tone,'amber');assert.equal(signal('light','train').tone,'amber');
assert.equal(scope.decisionSignal({analysis:{verdict:'rest'},stale:true},{kind:'train'}).tone,'neutral');
assert.equal(scope.decisionSignal(null,{kind:'rest'}).tone,'neutral');
console.log('Decision colors passed: red only for replacing a planned training day with rest; planned rest stays neutral');

assert.equal(scope.decisionSignal({analysis:{verdict:'rest'}},{kind:'train'},'rest').tone,'neutral');
assert.equal(scope.decisionSignal({analysis:{verdict:'rest'}},{kind:'rest'},'train').tone,'red');

const clues={};
function element(tag,value=''){return {tag,textContent:value,children:[],append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x}}}
scope.$=id=>clues[id]||(clues[id]=element('div'));scope.text=element;scope.fmt=x=>String(x);
vm.runInContext(source.slice(source.indexOf('function renderClues('),source.indexOf('function renderHealth(')),scope);
const report={date:'2030-01-01',recovery:{hrv:50,rhr:55},baseline:{hrv:{value:52},rhr:{value:55}},health_observations:{history:[]}};
scope.renderClues(report);assert.equal(clues['decision-clues'].children.length,2);
report.health_observations.history=[{date:report.date,strain:'none'}];
scope.renderClues(report);assert.equal(clues['decision-clues'].children[2].children[1].textContent,'无提示');
console.log('Missing optional strain is omitted; explicit no-sign report stays visible');
