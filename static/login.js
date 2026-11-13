const loginForm=document.getElementById('login-form');
loginForm.onsubmit=async event=>{
  event.preventDefault();
  const button=document.getElementById('login-submit'),message=document.getElementById('login-message');
  button.disabled=true;message.textContent='正在登录…';
  try{
    await api('/api/auth/login',{username:document.getElementById('username').value.trim(),password:document.getElementById('password').value,remember:document.getElementById('remember').checked});
    document.getElementById('password').value='';
    window.location.replace('/');
  }catch(error){message.textContent=error.message;button.disabled=false;}
};
