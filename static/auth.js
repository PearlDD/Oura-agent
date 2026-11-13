async function loadDevices(){
  const result=await api('/api/auth/sessions');
  const container=document.getElementById('login-devices');container.replaceChildren();
  for(const device of result.devices){
    const row=document.createElement('li'),name=document.createElement('span'),button=document.createElement('button');
    name.textContent=device.label+(device.current?' · 当前设备':'')+' · 有效至 '+new Date(device.expires_at*1000).toLocaleDateString('zh-CN');
    button.type='button';button.className='ghost';button.textContent=device.current?'退出此设备':'撤销登录';
    button.onclick=async()=>{try{const r=await api('/api/auth/revoke',{session_id:device.id});if(r.logged_out)window.location.replace('/login');else await loadDevices();}catch(error){document.getElementById('login-device-status').textContent=error.message;}};
    row.append(name,button);container.append(row);
  }
}
document.getElementById('show-login-devices').onclick=()=>loadDevices().catch(error=>{document.getElementById('login-device-status').textContent=error.message;});
document.getElementById('logout-device').onclick=async()=>{try{await api('/api/auth/logout',{});window.location.replace('/login');}catch(error){document.getElementById('login-device-status').textContent=error.message;}};
document.getElementById('logout-others').onclick=async()=>{try{await api('/api/auth/revoke',{others:true});await loadDevices();document.getElementById('login-device-status').textContent='已退出其他设备，当前设备继续保持登录。';}catch(error){document.getElementById('login-device-status').textContent=error.message;}};
