"""Content-preservation regressions against the real subtitle cleanup helpers."""
import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('cleanup_srt',Path(__file__).resolve().parents[1]/'addons/service.subtitles.kodipovilai/resources/lib/srt.py')
srt=importlib.util.module_from_spec(spec);spec.loader.exec_module(srt)
def cue(text,nl='\n'):return ('1\n00:00:01,000 --> 00:00:02,000\n'+text).replace('\n',nl)
class Preservation(unittest.TestCase):
    def test_no_orphaned_nested_style_across_lines(self):
        for nl in ('\n','\r\n'):
            for text in ('<i>Hello\nשלום</i>','<font color="red"><b>Hello\nשלום</b></font>','</i>Hello\nשלום'):
                value=cue(text,nl);self.assertEqual(srt.strip_source_echo(value),value)
    def test_self_contained_plain_echo_still_removed(self):
        for text in ('Hello\nשלום','<i>Hello</i>\nשלום'):
            self.assertEqual(srt.strip_source_echo(cue(text)),cue('שלום'))
    def test_independent_numeric_content_not_deleted(self):
        for value in ('17:45','Flight 841','12.50 USD','2026-09-13'):
            source=cue(value+'\nזמן היציאה');self.assertEqual(srt.strip_source_echo(source),source)
        self.assertEqual(srt.strip_source_echo(cue('There are 25\nיש 25')),cue('יש 25'))
    def test_markup_attributes_are_exact_including_multiline_and_quotes(self):
        for value in ('<font title="שלום سلام">שלום</font>',"<font title='שלום سلام'\n color='red'>שלום</font>",'<font title="אבβ > سلام">שלום</font>'):
            for nl in ('\n','\r\n'):
                value=value.replace('\n',nl)
                for function in (srt.strip_leaked_arabic,srt.fold_foreign_in_hebrew_word):
                    self.assertEqual(function(value),value)
    def test_quoted_literals_survive_with_spacing(self):
        for quote in ('"{}"','“{}”','«{}»'):
            for token in ('سلام','אבβ'):
                value='הסיסמה היא '+quote.format(token)+'.'
                self.assertEqual(srt.fold_foreign_in_hebrew_word(srt.strip_leaked_arabic(value)),value)
        value=cue('"Password سلام"\nהסיסמה');self.assertEqual(srt.strip_source_echo(value),value)
    def test_visible_repairs_outside_protected_attributes_still_work(self):
        self.assertEqual(srt.strip_leaked_arabic('<font title="אב سلام">האوר</font>'),'<font title="אב سلام">האור</font>')
        self.assertEqual(srt.fold_foreign_in_hebrew_word('<i title="אבβ">אמм</i>'),'<i title="אבβ">אמם</i>')
    def test_cleanup_chain_is_idempotent(self):
        value=cue('<i>Hello\nשלום</i>')+'\n\n'+cue('הסיסמה היא "سلام".').replace('1\n','2\n',1)
        def clean(x):return srt.fold_foreign_in_hebrew_word(srt.strip_source_echo(srt.strip_leaked_arabic(x)))
        self.assertEqual(clean(value),value);self.assertEqual(clean(clean(value)),clean(value))
if __name__=='__main__':unittest.main()
