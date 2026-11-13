/* Refresh a rejected CSRF token once; never retry ambiguous/failed operations. */
let csrf = document.querySelector('meta[name="iron-token"]').content;
async function api(path, body) {
  for(let attempt=0;attempt<2;attempt++){
    const res=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Iron-Token':csrf},body:JSON.stringify(body)});
    const data=await res.json();
    if(res.status===401&&data.login_required){window.location.assign('/login');throw new Error('请重新登录。');}
    if(body!==undefined&&attempt===0&&res.status===403&&data.code==='csrf_expired'){
      const fresh=await fetch('/api/csrf',{cache:'no-store'}),value=await fresh.json();
      if(!fresh.ok||typeof value.token!=='string'||value.token.length<30)throw new Error('校验更新未完成，请稍后重试；输入内容仍保留。');
      csrf=value.token;document.querySelector('meta[name="iron-token"]').content=csrf;
      continue;
    }
    if(!res.ok)throw new Error(data.error||'操作失败');
    return data;
  }
}
