/* Run with node test_api.js; only synthetic fetch responses, no network. */
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/api.js'),'utf8');
function setup(responses){
  const calls=[],redirects=[],meta={content:'old-token'},scope={document:{querySelector:()=>meta},window:{location:{assign:value=>redirects.push(value)}},fetch:async(url,options)=>{calls.push({url,options});const value=responses.shift();if(value instanceof Error)throw value;assert.ok(value,'unexpected retry');return {status:value.status,ok:value.status>=200&&value.status<300,json:async()=>value.data};}};
  vm.createContext(scope);vm.runInContext(source,scope);return {scope,calls,redirects,meta};
}
module.exports=(async()=>{
  const good=setup([{status:403,data:{code:'csrf_expired'}},{status:200,data:{token:'n'.repeat(43)}},{status:200,data:{ok:true}}]);
  assert.equal((await good.scope.api('/api/example',{value:2})).ok,true);
  assert.equal(good.calls.length,3);assert.equal(good.calls[1].url,'/api/csrf');
  assert.equal(good.calls[0].options.body,good.calls[2].options.body);assert.equal(good.calls[2].options.headers['X-Iron-Token'],'n'.repeat(43));
  for(const failure of [{status:403,data:{error:'origin rejected'}},{status:500,data:{error:'failed'}},new Error('connection lost')]){
    const test=setup([failure]);await assert.rejects(test.scope.api('/api/example',{}));assert.equal(test.calls.length,1);
  }
  const twice=setup([{status:403,data:{code:'csrf_expired'}},{status:200,data:{token:'n'.repeat(43)}},{status:403,data:{code:'csrf_expired',error:'rejected'}}]);
  await assert.rejects(twice.scope.api('/api/example',{}));assert.equal(twice.calls.length,3);
  const expired=setup([{status:401,data:{login_required:true}}]);await assert.rejects(expired.scope.api('/api/example',{}));assert.deepEqual(expired.redirects,['/login']);
  const readonly=setup([{status:403,data:{code:'csrf_expired'}}]);await assert.rejects(readonly.scope.api('/api/status'));assert.equal(readonly.calls.length,1);
  console.log('API recovery tests passed: safe one-time refresh; no network/5xx/origin retries; login expiry retained');
})();
