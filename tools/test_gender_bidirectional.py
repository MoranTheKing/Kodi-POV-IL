"""Real extracted repair code: mixed targets, abstention, shape and wiring."""
import ast,importlib.util,sys,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'addons/service.subtitles.kodipovilai/resources/lib'
def module(name):
    spec=importlib.util.spec_from_file_location(name,BASE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
ag=module('arabic_gender');srt=module('srt')
TREE=ast.parse((BASE/'translate.py').read_text(encoding='utf-8'))
def block(n,text):return '%s\n00:00:%02d,000 --> 00:00:%02d,900\n%s'%(n,n,n,text)
def repair(source,refs,reply):
    calls=[]
    def generate(**kw):calls.append(kw);return reply
    ns=dict(gemini=types.SimpleNamespace(REQUEST_TIMEOUT=60,generate=generate),srt=srt,arabic_gender=ag,
            kodi_utils=types.SimpleNamespace(log=lambda *a,**kw:None),api_key='fixture',model='fixture',max_output_tokens=8192,
            top_p=1.0,thinking_budget=None,thinking_level=None,gemini_timeout=None,_rpm_interval=0,
            _gemini_rate_gate=lambda x:None,src_text='\n\n'.join(source),_ar_map=refs,_ref_lang='he')
    for node in ast.walk(TREE):
        if isinstance(node,ast.FunctionDef) and node.name in ('_regender_blocks','_regender_unguarded'):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-repair>','exec'),ns)
    return ns['_regender_blocks'],calls

class Bidirectional(unittest.TestCase):
    def test_walking_requires_reviewed_verbal_continuation(self):
        for line in ['את הולכת בלי המפתח.', 'את הולכת איתי?', 'אמרתי שאת הולכת בלי מים.']:
            self.assertTrue(ag.addresses_female(line),line)
        for line in ['את הולכת הרגל ראיתי.', 'את הולכת הרגליים ראיתי.', 'את הילדה ראיתי.', 'את הולכת.', 'ראיתי את הולכת הרגל.', 'אני הולכת בלי המפתח.']:
            self.assertFalse(ag.addresses_female(line),line)
        original=[block(1,'את הולכת בלי המפתח, דניאל.')]
        self.assertEqual(ag.wrong_gender_entries(original,{1:'אתה הולך בלי המפתח, דניאל.'},'he',both_directions=True),[1])

    def test_attached_negation_cannot_be_removed_or_added(self):
        for negative,positive in [('שלא כדאי','שכדאי'),('שאין מספיק','שיש מספיק'),
                                  ('ושלא כדאי','ושכדאי'),('כשלא כדאי','כשכדאי'),
                                  ('בלי מים','עם מים'),('ללא מים','עם מים')]:
            with self.subTest(negative=negative):
                old='את יודעת '+negative+' ללכת לשם.'
                correct='אתה יודע '+negative+' ללכת לשם.'
                wrong='אתה יודע '+positive+' ללכת לשם.'
                original=[block(1,old)]
                fn,_=repair([block(1,'You know the situation.')],{1:correct},block(1,wrong))
                self.assertEqual(fn(original,[1]),original)
                fn,_=repair([block(1,'You know the situation.')],{1:correct},block(1,correct))
                self.assertEqual(fn(original,[1]),[block(1,correct)])
                fn,_=repair([block(1,'You know the situation.')],{1:correct},block(1,correct))
                positive_original=[block(1,'את יודעת '+positive+' ללכת לשם.')]
                self.assertEqual(fn(positive_original,[1]),positive_original)

    def test_reverse_candidate_and_ambiguous_controls(self):
        cases=[('את עייפה.','אתה עייף.',[1]),('בואי הנה.','אתה צריך לבוא.',[1]),
               ('ראיתי את דני.','אתה ראית את דני.',[]),('אני עייפה.','אתה עייף.',[]),
               ('את עייפה והוא אמר שאתה עייף.','אתה עייף.',[]),('את עייפה.','את עייפה ואתה עייף.',[])]
        for current,ref,wanted in cases:
            with self.subTest(current=current,ref=ref):
                self.assertEqual(ag.wrong_gender_entries([block(1,current)],{1:ref},'he',both_directions=True),wanted)

    def test_actual_pipeline_enables_reverse_detection(self):
        calls=[n for n in ast.walk(TREE) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='wrong_gender_entries']
        self.assertEqual(len(calls),1)
        ns=dict(arabic_gender=ag,out_blocks=[block(1,'את עייפה.')],_ar_map={1:'אתה עייף.'},_ref_lang='he')
        self.assertEqual(eval(compile(ast.Expression(calls[0]),'<actual-wiring>','eval'),ns),[1])

    def test_one_batch_carries_independent_gender_targets(self):
        current=[block(1,'את עייפה מאוד.'),block(2,'אתה עייף מאוד.')]
        expected=[block(1,'אתה עייף מאוד.'),block(2,'את עייפה מאוד.')]
        fn,calls=repair([block(1,'You are very tired, Daniel.'),block(2,'You are very tired, Mary.')],
                        {1:'אתה עייף מאוד.',2:'את עייפה מאוד.'},'\n\n'.join(expected))
        self.assertEqual(fn(current,[1,2]),expected);self.assertEqual(len(calls),1)
        import json
        evidence=json.loads(calls[0]['prompt'].split('\n\n',1)[1])
        self.assertEqual([e['suggested_addressee_gender'] for e in evidence],['M','F'])

    def test_reverse_refuses_unfixed_negation_number_and_unrelated_rewrites(self):
        original=[block(1,'את לא חייבת לי 25 שקלים.')]
        for text in ['את לא חייבת לי 25 שקלים.','אתה חייב לי 25 שקלים.','אתה לא חייב לי 50 שקלים.','מחר נטייל בירושלים.']:
            fn,_=repair([block(1,'You do not owe me 25 shekels.')],{1:'אתה לא חייב לי 25 שקלים.'},block(1,text))
            self.assertEqual(fn(original,[1]),original)

    def test_reverse_keep_missing_and_duplicate_sources(self):
        original=[block(1,'את עייפה.')]
        for source,ref,reply in [([block(1,'You are tired.')],{1:'אתה עייף.'},''),
                                 ([block(1,'You are tired.')],{1:'אתה עייף.'},original[0]),
                                 ([block(1,'You are tired.'),block(1,'Other.')],{1:'אתה עייף.'},block(1,'אתה עייף.'))]:
            fn,_=repair(source,ref,reply);self.assertEqual(fn(original,[1]),original)

if __name__=='__main__':unittest.main()
