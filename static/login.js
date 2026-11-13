const loginForm=document.getElementById('login-form');
loginForm.onsubmit=async event=>{
  event.preventDefault();
  const button=document.getElementById('login-submit'),message=document.getElementById('login-message');
  button.disabled=true;message.textContent='正在登录…';
  try{
    const response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-Iron-Token':document.querySelector('meta[name="iron-token"]').content},body:JSON.stringify({username:document.getElementById('username').value.trim(),password:document.getElementById('password').value,remember:document.getElementById('remember').checked})});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'登录失败，请重试。');
    document.getElementById('password').value='';
    window.location.replace('/');
  }catch(error){message.textContent=error.message;button.disabled=false;}
};
