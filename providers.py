"""Provider routing; credentials stay server-side and recipients are explicit."""
import re

LABELS={'openai':'OpenAI','gemini':'Google / Gemini'}


def config(app,settings=None):
    s=app.settings() if settings is None else settings
    provider=s.get('ai_provider','openai')
    if provider not in LABELS:raise app.AppError('请选择 OpenAI 或 Gemini。')
    prefix='gemini' if provider=='gemini' else 'openai'
    return {'provider':provider,'label':LABELS[provider],'key':s.get(prefix+'_key',''),'model':s.get(prefix+'_model','').removeprefix('models/'),
            'paid_confirmed':s.get('gemini_paid_confirmed') is True}


def require(app):
    c=config(app)
    if not c['key'] or not c['model']:raise app.AppError('请在连接与设置中填写 '+c['label']+' API Key 和模型 ID。')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,120}',c['model']):raise app.AppError('模型 ID 格式无效，请填写模型名称，不要填写网址。')
    if c['provider']=='gemini' and not c['paid_confirmed']:
        raise app.AppError('报告含个人健康信息，请先在设置确认 Gemini 项目使用付费服务；免费服务条款要求不要提交敏感个人信息。')
    return c


def ready(app):
    try:require(app);return True
    except app.AppError:return False


def complete(app,c,instructions,inputs,schema=None):
    if c['provider']=='openai':
        payload={'model':c['model'],'store':False,'instructions':instructions,'input':inputs}
        if schema is not None:payload['text']={'format':{'type':'json_schema','name':'training_decision','strict':True,'schema':schema}}
        else:payload['max_output_tokens']=3000
        data=app.request_json('https://api.openai.com/v1/responses',payload,c['key'])
        if data.get('status')=='incomplete':raise app.AppError('模型回复未完成，本次未保存；请缩小问题后重试。')
        output='\n'.join(p.get('text','') for i in data.get('output',[]) for p in i.get('content',[]) if p.get('type')=='output_text').strip()
    else:
        system=[{'text':instructions}];contents=[]
        if isinstance(inputs,str):inputs=[{'role':'user','content':inputs}]
        for item in inputs:
            if item['role']=='developer':system.append({'text':item['content']})
            else:contents.append({'role':'model' if item['role']=='assistant' else 'user','parts':[{'text':item['content']}]})
        generation={'maxOutputTokens':8192 if schema else 4096}
        if schema is not None:generation.update(responseMimeType='application/json',responseJsonSchema=schema)
        data=app.request_json('https://generativelanguage.googleapis.com/v1beta/models/'+c['model']+':generateContent',
              {'systemInstruction':{'parts':system},'contents':contents,'generationConfig':generation},
              extra_headers={'x-goog-api-key':c['key']})
        candidates=data.get('candidates',[])
        if not candidates or candidates[0].get('finishReason')!='STOP':raise app.AppError('Gemini 未返回完整回复，可能被拦截或超过长度限制；本次未保存。')
        output='\n'.join(p.get('text','') for p in candidates[0].get('content',{}).get('parts',[]) if not p.get('thought')).strip()
    if not output:raise app.AppError('模型未返回有效文字，本次未保存，请重试。')
    return output
