import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,chat,providers
from test_decision import sample

class ProvidersTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(app,'DATA',Path(self.tmp.name));self.p.start()
        app.update_settings({'ai_provider':'gemini','gemini_key':'GOOGLE TEST SECRET','gemini_model':'models/test-gemini','gemini_paid_confirmed':True,'openai_key':'OPENAI TEST SECRET','openai_model':'test-openai'})
    def tearDown(self):self.p.stop();self.tmp.cleanup();chat.BUSY.clear()
    def response(self,text):return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'hidden reasoning','thought':True},{'text':text}]}}]}
    def test_gemini_chat_recipient_auth_and_history(self):
        with patch.object(app,'request_json',return_value=self.response('这是规则草案。')) as req:
            result=chat.send(app,{'date':'2026-11-06','message':'为什么两组？','revision':0,'provider':'gemini','consent':True})
            self.assertEqual(result['messages'][-1]['text'],'这是规则草案。')
            url,payload=req.call_args.args
            self.assertTrue(url.endswith('/test-gemini:generateContent'));self.assertNotIn('SECRET',url)
            self.assertEqual(req.call_args.kwargs['extra_headers'],{'x-goog-api-key':'GOOGLE TEST SECRET'})
            self.assertNotIn('OPENAI TEST SECRET',json.dumps(payload));self.assertEqual(payload['contents'][-1]['role'],'user')
            result=chat.send(app,{'date':'2026-11-06','message':'预留是什么？','revision':1,'provider':'gemini','consent':True})
            self.assertEqual([m['role'] for m in req.call_args.args[1]['contents']],['user','model','user'])
    def test_paid_confirmation_and_recipient_mismatch_block_send(self):
        body={'date':'2026-11-06','message':'你好','revision':0,'provider':'openai','consent':True}
        with patch.object(app,'request_json') as req:
            with self.assertRaises(app.AppError):chat.send(app,body)
            app.update_settings({'gemini_paid_confirmed':False})
            with self.assertRaises(app.AppError):chat.send(app,{**body,'provider':'gemini'})
            self.assertFalse(providers.ready(app));req.assert_not_called()
    def test_structured_decision_and_provider_specific_status(self):
        app.save(app.DATA/'oura/sleep.json',{'data':[{'day':'2026-11-06','type':'long_sleep','total_sleep_duration':28000}]})
        app.save(app.DATA/'ai-status.json',{'ok':False,'message':'old OpenAI quota problem'})
        with patch.object(app,'request_json',return_value=self.response(json.dumps(sample()))) as req:
            app.ai_report('2026-11-06')
            cfg=req.call_args.args[1]['generationConfig'];self.assertEqual(cfg['responseMimeType'],'application/json');self.assertIn('responseJsonSchema',cfg)
        self.assertIn('Gemini',app.current_decision('2026-11-06')['source'])
        self.assertEqual(chat.view(app,'2026-11-06')['provider_notice'],'')
    def test_incomplete_and_invalid_models_do_not_fallback(self):
        c=providers.require(app)
        with patch.object(app,'request_json',return_value={'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'partial'}]}}]}) as req:
            with self.assertRaises(app.AppError):providers.complete(app,c,'instructions',[{'role':'user','content':'test'}])
            self.assertEqual(req.call_count,1)
        app.update_settings({'gemini_model':'https://bad.invalid/key'})
        with self.assertRaises(app.AppError):providers.require(app)
