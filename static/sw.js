// No fetch handler: private reports, credentials and API responses are not cached.
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data={};try{data=event.data?.json()||{};}catch(_){}
  // Fixed text keeps health indicators off the lock screen, even for malformed payloads.
  const test=data.tag==='iron-test';
  event.waitUntil(self.registration.showNotification(test?'通知测试':'训练晨报已更新',{
    body:test?'手机通知连接成功，点击打开网页。':'登录后查看今天的分析与训练安排。',
    icon:'/icon-192.png',badge:'/icon-192.png',tag:test?'iron-test':'iron-report',
    data:{url: typeof data.url==='string'&&/^\/\?date=\d{4}-\d{2}-\d{2}$/.test(data.url)?data.url:'/'}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url=new URL(event.notification.data?.url||'/',self.location.origin).href;
  event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async clients=>{
    for(const client of clients){if(new URL(client.url).origin===self.location.origin){await client.navigate(url);return client.focus();}}
    return self.clients.openWindow(url);
  }));
});
