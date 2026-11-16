/* Run node test_push_ui.js. Synthetic browser; no network or permission prompts. */
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/push.js'),'utf8');
function setup({subscription=true,failKey=false,standalone=true,permission='granted'}={}){
  const elements={},calls=[],events={};let permissionRequests=0;
  const get=id=>elements[id]||(elements[id]={disabled:true,hidden:false,textContent:''});
  const sub=subscription?{endpoint:'https://web.push.apple.com/synthetic-test',toJSON:()=>({})}:null;
  const registration={pushManager:{getSubscription:async()=>sub}};
  const scope={console,setTimeout,clearTimeout,Uint8Array,TextEncoder:require('node:util').TextEncoder,
    document:{getElementById:get,addEventListener:(name,handler)=>events[name]=handler,hidden:false},
    navigator:{userAgent:'iPhone',platform:'iPhone',maxTouchPoints:5,standalone,serviceWorker:{register:async()=>registration,ready:Promise.resolve(registration)}},
    matchMedia:()=>({matches:standalone}),isSecureContext:true,PushManager:function(){},
    Notification:{permission,requestPermission:async()=>{permissionRequests++;return 'granted';}},
    crypto:{subtle:{digest:async()=>new Uint8Array([1,2,3]).buffer}},
    api:async(url)=>{calls.push(url);if(url==='/api/status')return {timezone:'America/New_York',automation:{enabled:true,mode:'wake',poll_minutes:15,today:{status:'complete',finished_at:'2026-11-16T10:55:58-05:00',analyzed_sleep_end:'2026-11-16T10:34:53-05:00'}},push:{available:true}};if(url==='/api/push/key'){if(failKey)throw new Error('PRIVATE ENDPOINT');return {public_key:'synthetic'};}if(url.startsWith('/api/push/status'))return {registered:true};throw new Error('Unexpected request');}};
  scope.window=scope;vm.createContext(scope);vm.runInContext(source,scope);
  return {scope,elements,calls,events,recover:()=>{failKey=false;},permissionRequests:()=>permissionRequests,done:()=>vm.runInContext('pushPreparation',scope)};
}
module.exports=(async()=>{
  const ready=setup();assert.equal(ready.scope.preparePush(),ready.scope.preparePush());await ready.done();
  // Intentionally no global `state`: the push flow must initialize independently.
  assert.equal(ready.elements['push-test'].disabled,false);assert.equal(ready.elements['push-recheck'].disabled,false);
  assert.match(ready.elements['push-status'].textContent,/此设备已启用/);assert.equal(ready.permissionRequests(),0);
  const failed=setup({failKey:true});await failed.done();
  assert.equal(failed.elements['push-test'].disabled,true);assert.equal(failed.elements['push-recheck'].disabled,false);
  assert.match(failed.elements['push-status'].textContent,/服务器通知密钥/);assert.doesNotMatch(failed.elements['push-status'].textContent,/PRIVATE/);
  failed.recover();await failed.scope.preparePush();assert.equal(failed.elements['push-test'].disabled,false);
  const denied=setup({permission:'denied'});await denied.done();assert.equal(denied.elements['push-test'].disabled,true);assert.match(denied.elements['push-status'].textContent,/权限已关闭/);
  const noSub=setup({subscription:false});await noSub.done();assert.equal(noSub.elements['push-enable'].disabled,false);assert.equal(noSub.elements['push-test'].disabled,true);assert.equal(noSub.permissionRequests(),0);
  const safari=setup({standalone:false});await safari.done();assert.match(safari.elements['push-status'].textContent,/主屏幕/);assert.equal(safari.permissionRequests(),0);
  console.log('Push UI tests passed: startup race, recoverable errors, existing subscription, missing subscription, iPhone Home Screen gate, no automatic permission prompt');
})();
