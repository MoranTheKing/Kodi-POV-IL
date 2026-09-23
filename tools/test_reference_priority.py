import ast,importlib.util,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]/'addons/service.subtitles.kodipovilai/resources/lib'
spec=importlib.util.spec_from_file_location('priority_prompt',BASE/'prompt.py');prompt=importlib.util.module_from_spec(spec);spec.loader.exec_module(prompt)
class Priority(unittest.TestCase):
 def assembled(self,lang=None):
  tree=ast.parse((BASE/'translate.py').read_text(encoding='utf-8'))
  node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_call_gemini')
  index=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='overload_attempts' for x in n.targets))
  node.body=node.body[:index]+[ast.Return(ast.Name('full_prompt',ast.Load()))]
  scope=dict(prompt=prompt,prev_context_by_idx={},_ref_stack=[(lang,{1:'את מוכנה.'})] if lang else [],prompt_template=prompt.build('en','',0,[]),_AR_EXPLICIT_MARKERS=[],whole_subtitle_request=False,chunks=[],prev_context_lines=5,_source_context_for_subchunk=lambda *args: [])
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual-prompt-assembly','exec'),scope)
  return scope['_call_gemini'](0,['1\n00:00:01,000 --> 00:00:02,000\nYou are ready.'])
 def test_actual_hebrew_path_uses_source_priority(self):
  text=self.assembled('he');self.assertIn('SOURCE PRIORITY:',text);self.assertNotIn('HARD CONSTRAINT, NOT A HINT.',text);self.assertIn('את מוכנה.',text)
 def test_no_reference_path_still_works(self):
  self.assertNotIn('SOURCE PRIORITY:',self.assembled())
 def test_arabic_branch_unchanged(self):
  text=self.assembled('ar');self.assertIn('ARABIC GENDER REFERENCE -- HARD CONSTRAINT',text);self.assertNotIn('SOURCE PRIORITY:',text)
 def test_literal_reference_payload_is_unchanged(self):
  payload='SRT to translate ( HARD CONSTRAINT, NOT A HINT. you MUST make your Hebrew agree'
  text=prompt.build_gender_block([(1,payload)],'he')
  self.assertIn('1: '+payload+'\n',text)
  self.assertEqual(text.count('SOURCE PRIORITY:'),1)
if __name__=='__main__':unittest.main()
