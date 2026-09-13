"""Bounded verbatim-English repair: positive cases and adversarial no-ops."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
P=Path(__file__).resolve().parents[1]/'addons/service.subtitles.kodipovilai/resources/lib/english_residual.py'
spec=importlib.util.spec_from_file_location('residual',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def block(text, ident=1):return '{}\r\n00:00:01,000 --> 00:00:02,000\r\n{}'.format(ident,text)
class ResidualRepair(unittest.TestCase):
    def run_case(self, text='♪ We know the way ♪', answer='♪ אנחנו יודעים את הדרך ♪', **kw):
        before=[block(text)]
        req=Mock(return_value=json.dumps([{'id':'0:0','text':answer}]))
        out,counts=m.repair(before,before,'en',req,**kw)
        return before,out,counts,req
    def test_authored_english_chorus_translates_one_call(self):
        before,out,c,req=self.run_case()
        self.assertEqual(out,[block('♪ אנחנו יודעים את הדרך ♪')]);self.assertEqual(c['repaired'],1)
        req.assert_called_once();self.assertIn('source_context',req.call_args.args[0])
    def test_mixed_cue_preserves_hebrew_neighbor_and_headers(self):
        src=[block('We know the way\r\nWe sail together')]
        cur=[block('We know the way\r\nאנחנו מפליגים יחד')]
        req=lambda p:json.dumps([{'id':'0:0','text':'אנחנו יודעים את הדרך'}])
        out,c=m.repair(src,cur,'en',req)
        self.assertEqual(out,[block('אנחנו יודעים את הדרך\r\nאנחנו מפליגים יחד')])
    def test_unknown_lyrics_names_literals_and_locations_never_requested(self):
        for value in ('Aue aue te fenua','Moana Maui Te Fiti','The Lord Of The Rings',
                      'WE KNOW THE WAY','"We know the way"',"'We know the way'",
                      'Visit the www.example.com site','we use /the/path now','we mail the a@b.test'):
            req=Mock();before=[block(value)]
            with self.subTest(value=value):
                self.assertEqual(m.repair(before,before,'en',req)[0],before);req.assert_not_called()
    def test_source_exact_same_cue_and_language_required(self):
        req=Mock();cur=[block('We know the way')]
        for source,lang in (([block('We know another way')],'en'),(cur,'sm'),([block('We know the way',2)],'en')):
            self.assertEqual(m.repair(source,cur,lang,req)[0],cur)
        req.assert_not_called()
    def test_negation_and_structure_guards(self):
        for answer in ('אנחנו יודעים את הדרך','אנחנו לא יודעים\nאת הדרך','אנחנו לא יודעים 2 את הדרך'):
            before,out,c,req=self.run_case('We do not know the way',answer)
            self.assertEqual(out,before)
        self.assertEqual(self.run_case('We do not know the way','אנחנו לא יודעים את הדרך')[2]['repaired'],1)
    def test_music_tags_numbers_are_preserved(self):
        text='<i>♪ We have the 2 keys ♪</i>'
        for answer in ('יש לנו 2 מפתחות','<i>יש לנו 3 מפתחות</i>','<i>♪ יש לנו 2 מפתחות ♪</i>'):
            before,out,c,req=self.run_case(text,answer)
            self.assertEqual(c['repaired'],int(answer=='<i>♪ יש לנו 2 מפתחות ♪</i>'))
    def test_malformed_duplicate_and_unrequested_json_noop(self):
        before=[block('We know the way')]
        for response in ('oops','{}','[{"id":"9:0","text":"שלום"}]',
                         '[{"id":"0:0","text":"שלום"},{"id":"0:0","text":"שלום"}]'):
            req=Mock(return_value=response)
            self.assertEqual(m.repair(before,before,'en',req)[0],before);req.assert_called_once()
    def test_cancel_and_exception_never_retry(self):
        before=[block('We know the way')];req=Mock(side_effect=RuntimeError('quota'))
        self.assertEqual(m.repair(before,before,'en',req)[0],before);req.assert_called_once()
        req=Mock();self.assertEqual(m.repair(before,before,'en',req,cancelled=lambda:True)[0],before);req.assert_not_called()
        state={'cancel':False}
        def call(prompt):state['cancel']=True;return '[{"id":"0:0","text":"אנחנו יודעים"}]'
        self.assertEqual(m.repair(before,before,'en',call,cancelled=lambda:state['cancel'])[0],before)
    def test_cap_and_context(self):
        before=[block('We know the way',i+1) for i in range(30)]
        req=Mock(return_value='[]');out,c=m.repair(before,before,'en',req)
        self.assertEqual(c['selected'],16);req.assert_called_once();self.assertLess(len(req.call_args.args[0]),21000)
        self.assertEqual(out,before)
    def test_proper_latin_name_allowed_in_hebrew_result(self):
        before,out,c,req=self.run_case('We will follow Maui','אנחנו נלך בעקבות Maui')
        self.assertEqual(c['repaired'],1)
    def test_additional_reviewer_guards(self):
        for answer in ('אנחנו יודעים את הדרך\n', 'אל תלכו בדרך'):
            self.assertEqual(self.run_case(answer=answer)[2]['repaired'], 0)
        self.assertEqual(self.run_case('<i>We know the way</i>', '</i>אנחנו יודעים את הדרך<i>')[2]['repaired'], 0)
        before=[block('The lord of the rings')];req=Mock()
        self.assertEqual(m.repair(before,before,'en',req)[0],before);req.assert_not_called()

    def test_actual_production_integration_pairs_ids_and_checks_cancel_after_gate(self):
        import ast
        import sys
        import types
        from unittest.mock import patch
        production=P.with_name('translate.py')
        tree=ast.parse(production.read_text(encoding='utf-8'))
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.Try)
                  and any(isinstance(x,ast.ImportFrom) and any(a.name=='english_residual' for a in x.names)
                          for x in n.body))
        source=block('An annotation',1)+'\n\n'+block('We know the way',2)
        current=[block('We know the way',2)]
        for mode in ('success','quota','cancel-at-gate'):
            state={'cancel':False}
            api=Mock(return_value='[{"id":"0:0","text":"אנחנו יודעים את הדרך"}]')
            if mode=='quota':api.side_effect=RuntimeError('quota')
            def gate(interval):
                if mode=='cancel-at-gate':state['cancel']=True
            pkg=types.ModuleType('resources');lib=types.ModuleType('resources.lib');lib.english_residual=m
            xbmc=types.SimpleNamespace(Monitor=lambda:types.SimpleNamespace(abortRequested=lambda:state['cancel']))
            env=dict(srt=types.SimpleNamespace(parse_blocks=lambda text:text.split('\n\n')),
                     src_text=source,out_blocks=list(current),source_lang='en',progressive_cb=None,
                     _gemini_rate_gate=gate,_rpm_interval=2,api_key='synthetic',model='test',
                     max_output_tokens=8192,top_p=None,thinking_budget=None,thinking_level='medium',
                     gemini_timeout=90,gemini=types.SimpleNamespace(generate=api,REQUEST_TIMEOUT=90),
                     kodi_utils=types.SimpleNamespace(log=Mock()))
            with patch.dict(sys.modules,{'resources':pkg,'resources.lib':lib,'xbmc':xbmc}):
                exec(compile(ast.Module(body=[node],type_ignores=[]),'production-residual','exec'),env)
            if mode=='success':
                self.assertEqual(env['out_blocks'],[block('אנחנו יודעים את הדרך',2)])
                api.assert_called_once();self.assertEqual(api.call_args.kwargs['max_output_tokens'],4096)
            else:
                self.assertEqual(env['out_blocks'],current)
                self.assertEqual(api.call_count,0 if mode=='cancel-at-gate' else 1)

    def test_single_anchored_json_fence_and_keep(self):
        before=[block('We know the way')]
        data=json.dumps([{'id':'0:0','text':'אנחנו יודעים את הדרך'}])
        for response in ('```json\n'+data+'\n```', ' \n```\n'+data+'\n```\n '):
            out,c=m.repair(before,before,'en',lambda p:response)
            self.assertEqual(c['repaired'],1)
        for response in ('Here is JSON:\n```json\n'+data+'\n```',
                         '```json\n'+data+'\n```\nDone',
                         '```json\n'+data+'\n```\n```json\n[]\n```'):
            out,c=m.repair(before,before,'en',lambda p:response)
            self.assertEqual(out,before);self.assertEqual(c['repaired'],0)
        keep=json.dumps([{'id':'0:0','text':'We know the way'}])
        out,c=m.repair(before,before,'en',lambda p:keep)
        self.assertEqual(out,before);self.assertEqual(c['repaired'],0);self.assertEqual(c['rejected'],0)

if __name__=='__main__':unittest.main()
