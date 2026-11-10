/* Browser opt-in only. Never asks for permission on page load. */
let pushRegistration=null,pushKey=null,pushDevice=null,pushSubscription=null;
function pushMessage(message){document.getElementById('push-status').textContent=message;}
function pushBytes(value){const raw=atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));}
async function pushDeviceId(endpoint){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(endpoint));return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');}
function pushButtons(enabled){
  document.getElementById('push-enable').disabled=enabled||!pushRegistration||!pushKey;
  document.getElementById('push-enable').textContent=enabled?'此设备通知已启用':'启用手机通知';
  document.getElementById('push-test').disabled=!enabled;
  document.getElementById('push-disable').hidden=!enabled;
}
window.renderAutomation=function(automation,notice){
  if(!automation)return;
  const run=automation.today||{},names={running:'正在生成',complete:'今日已完成',failed:'分析未完成',incomplete:'信息待补齐',waiting_for_sleep:'等待睡眠数据'};
  document.getElementById('automation-badge').textContent=automation.enabled?(names[run.status]||'自动检查中'):'尚未启用';
  const mode=automation.mode==='wake'?`Oura 数据就绪后自动分析 · 每 ${automation.poll_minutes} 分钟检查`:'固定时间运行';
  document.getElementById('automation-status').textContent=automation.enabled?mode+'。'+(run.reason||automation.poll?.message||'等待今天的数据。'):'自动任务尚未启用，历史报告仍可查看。';
  if(run.notification?.failed)document.getElementById('automation-status').textContent+=' 报告已保留，但通知发送失败，请测试手机通知。';
  document.getElementById('automation-retry').hidden=!automation.enabled||!['failed','incomplete'].includes(run.status);
};
(async function preparePush(){
  try{
    const status=await api('/api/status');window.renderAutomation(status.automation,status.push);
    const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
    if(ios&&!matchMedia('(display-mode: standalone)').matches&&!navigator.standalone){pushMessage('请先添加到 iPhone 主屏幕，再从图标打开并启用通知。');return;}
    if(!window.isSecureContext||!('serviceWorker'in navigator)||!('PushManager'in window)||!('Notification'in window)){pushMessage('当前浏览器不支持通知；请使用支持 Web Push 的手机浏览器或主屏幕网页。');return;}
    if(!status.push?.available){pushMessage('通知服务尚未就绪，请稍后刷新。');return;}
    pushRegistration=await navigator.serviceWorker.register('/sw.js',{scope:'/'});
    pushRegistration=await navigator.serviceWorker.ready;
    pushKey=(await api('/api/push/key')).public_key;
    pushSubscription=await pushRegistration.pushManager.getSubscription();
    if(pushSubscription){pushDevice=await pushDeviceId(pushSubscription.endpoint);const saved=await api('/api/push/status?device_id='+pushDevice);pushButtons(saved.registered);pushMessage(saved.registered?'此设备已启用；可以发送测试通知。':'此设备需要重新保存通知订阅。');}
    else{pushButtons(false);pushMessage(Notification.permission==='denied'?'通知被浏览器阻止；请在系统/网站设置中允许后重试。':'启用后，只推送“晨报已更新”，不在锁屏显示健康数据。');}
  }catch(_){pushMessage('通知初始化未完成，请刷新后重试。');}
})();
document.getElementById('push-enable').onclick=async()=>{
  if(!pushRegistration||!pushKey)return;
  try{
    // Request directly from the user gesture; Safari rejects delayed permission prompts.
    const permission=Notification.permission==='granted'?'granted':await Notification.requestPermission();
    if(permission!=='granted'){pushMessage('未获得通知权限，晨报仍可在网页查看。');return;}
    pushSubscription=await pushRegistration.pushManager.getSubscription()||await pushRegistration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:pushBytes(pushKey)});
    const saved=await api('/api/push/subscribe',{consent:true,subscription:pushSubscription.toJSON()});
    pushDevice=saved.device_id;pushButtons(true);pushMessage('通知订阅已保存。请点“发送测试通知”确认手机能收到。');
  }catch(_){pushMessage('通知未能启用，请确认从主屏幕打开并允许通知。');pushButtons(false);}
};
document.getElementById('push-test').onclick=async()=>{
  try{const result=await api('/api/push/test',{device_id:pushDevice});pushMessage(result.accepted?'推送服务已接收测试通知，请在手机确认是否收到。':'通知未发送成功，请重新启用此设备后再试。');}catch(error){pushMessage(error.message);}
};
document.getElementById('push-disable').onclick=async()=>{
  try{await api('/api/push/unsubscribe',{device_id:pushDevice});if(pushSubscription)await pushSubscription.unsubscribe();pushDevice=null;pushSubscription=null;pushButtons(false);pushMessage('已关闭此设备通知。');}catch(error){pushMessage(error.message);}
};
document.getElementById('automation-retry').onclick=async()=>{
  const button=document.getElementById('automation-retry');button.disabled=true;
  try{await api('/api/automation/retry',{});document.getElementById('automation-status').textContent='已请求重试；将先核对睡眠数据，再使用当前已启用的 AI 提供商分析（API 可能计费）。';button.hidden=true;}
  catch(error){pushMessage(error.message);}finally{button.disabled=false;}
};
