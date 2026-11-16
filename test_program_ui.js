const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const root=__dirname,source=fs.readFileSync(path.join(root,'static/app.js'),'utf8');
const start=source.indexOf('function formatPrescribedMove('),end=source.indexOf('function fmt(',start);
const nodes={};function node(){return {children:[],value:'',hidden:false,textContent:'',append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}};}
const scope={$:id=>nodes[id]||(nodes[id]=node()),text:(tag,value)=>({...node(),tag,textContent:value}),window:{},document:{activeElement:null},state:{today:'2026-11-16'},console};
vm.createContext(scope);vm.runInContext(source.slice(start,end),scope);vm.runInContext(fs.readFileSync(path.join(root,'static/program.js'),'utf8'),scope);
const move={name:'Synthetic lift',role:'strength',prescribed_sets:[{reps:10,warmup:false,reference_load:'40 lb'},{reps:8,warmup:false,reference_load:'45 lb'}]};
const formatted=scope.formatPrescribedMove(move);assert.match(formatted,/10/);assert.match(formatted,/8/);assert.match(formatted,/RIR/);assert.doesNotMatch(formatted,/3 次/);
const active={id:'test',name:'Synthetic plan',version:1,anchor_date:'2026-11-16',cycle:['pull',null],shift_rule:'shift_all',templates:{pull:{name:'Pull',movements:[move]}}};
scope.window.renderSourceProgram({active},'2026-11-16');assert.equal(nodes['program-shift-box'].hidden,false);assert.equal(nodes['program-confirm-box'].hidden,true);assert.equal(nodes['program-shift-date'].value,'2026-11-16');assert.match(nodes['program-source'].textContent,/Synthetic plan/);
scope.window.renderSourceProgram({draft:active},'2026-11-16');assert.equal(nodes['program-confirm-box'].hidden,false);assert.equal(nodes['program-shift-box'].hidden,true);
console.log('Imported program UI passed: exact set rows, unknown RIR, source labels, activation and shift controls');
