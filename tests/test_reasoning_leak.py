"""Model working notes inside generated Hebrew are rejected (srt.py).

QA, Oct 2026: a Gilmore Girls chunk came back with draft lines opened by
"->", "Let's check Arabic: ..." / "Hebrew: ..." lines and English notes on
who is female, passed its retry, and reached the subtitle. The bracketed
self-edit detector needed "wait" followed by "fix"/"->" inside the same
brackets, so none of these shapes was caught.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
spec = importlib.util.spec_from_file_location('srt_reasoning', LIB / 'srt.py')
srt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srt)


def block(index, start, end, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,000\n%s' % (index, start, end, text)


SOURCE = [block(1, 1, 2, 'And did you not want a great harp player?')]


def leaks(text, source=SOURCE):
    return srt.generated_editorial_leak_indices(source, [block(1, 1, 2, text)])


class ReasoningLeak(unittest.TestCase):

    def test_observed_shapes_are_rejected(self):
        shapes = [
            # verbatim from the QA output (RTL punctuation moved to the front)
            'ולא רצית\nע/ עוררת עאזפה נבל מעולה? (Wait: Drella to Lorelai, Lorelai is female)\n'
            '?-> ולא רצית עאזפה נבל מעולה',
            '.אוקיי. אני נגן נבל מעולה\n-> אוקיי. אני עאזפה נבל מעולה. (Drella is female)',
            '.Let\'s check Arabic: ألم تطلبي (feminine addressee: تطلبي)\n?Hebrew: ולא רצית',
            'נואשות אני רוצה לעזור. (Michel speaking to Emily, Emily is female -> אין לך)',
            'דברים שתבוא ותלמד עלי\n(Walter speaking to Walter Jr., male addressee)',
            '.היא אגדה מהחיים\n(wait, אגדה מהחיים / אגדה חיה)\n.היא אגדה מהחיים',
            '.טוב. אוטובוס בית הספר פנוי\n*(Wait, school bus, let\'s keep it accurate:)*',
            'אז אם את מחפשת מישהו\n-> אז אם את מחפשת מישהו',
            '<i>→ תביאי נגן מפוחית.</i>',
        ]
        for text in shapes:
            self.assertEqual(leaks(text), [0], text)

    def test_dialogue_is_kept(self):
        kept = [
            'הוא לחש (Wait) ואז יצא.',
            'המתן כאן. (Wait)',
            'הסיסמה היא "Wait->Go".',
            'הפונקציה היא x -> y והכול תקין.',
            '- אתה בא?\n- כן, אני בא.',
            '...רגע, רגע\nאני לא מבין',
            'היא כתבה בטופס: (נקבה)',
            '<i>[מוזיקה]</i>',
        ]
        for text in kept:
            self.assertEqual(leaks(text), [], text)

    def test_source_with_the_same_words_is_dialogue(self):
        source = [block(1, 1, 2, 'Note: the patient is female.')]
        self.assertEqual(leaks('הערה: המטופלת (is female) היא אישה.', source), [])
        source = [block(1, 1, 2, '-> Turn left here.')]
        self.assertEqual(leaks('-> פנה שמאלה כאן.', source), [])

    def test_caption_markers_and_source_lines_are_dialogue(self):
        # validator round 2: the source exemption must look at each source
        # line cleaned like the output, and '>' / '>>' is a speaker marker
        cases = [
            ('Hi there.\n>> Hello.', 'היי.\n>> שלום.'),
            ('- Fine.\n>> Good.', '- בסדר.\n>> טוב.'),
            ('<i>>> Who?</i>', '<i>>> מי?</i>'),
            ('{\\an8}> TRANSMISSION', '{\\an8}> שידור'),
            ('<i>> Access granted</i>', '<i>> הגישה אושרה</i>'),
            ('Mom texted:\n> Where are you?', 'אמא שלחה:\n> איפה אתה?'),
            ('- → Exit', '- → יציאה'),
            ('- This way.\n- → Exit', '- מכאן.\n- → יציאה'),
            ('"Note: buy milk."', '"Note: לקנות חלב."'),
            ('Call me.\nNOTE: ALL CALLS RECORDED', 'תתקשר אליי.\nNOTE: ALL CALLS RECORDED'),
            ('Exit →', '→ יציאה'),            # round 3: word order turned around
            ('Go -> there', '-> לך לשם'),
        ]
        for src, out in cases:
            self.assertEqual(leaks(out, [block(1, 1, 2, src)]), [], out)
        # a bare '>>' line with no marker in the source is still not an arrow
        self.assertEqual(leaks('היי.\n>> שלום.'), [])

    def test_english_only_cue_is_left_to_the_fallback(self):
        self.assertEqual(leaks('-> (Drella is female)'), [])

    def test_final_gate_drops_the_cue(self):
        bad = [block(1, 1, 2, '.אוקיי\n-> אוקיי. (Drella is female)')]
        out, missing, rejected = srt.generated_output_blocks(
            SOURCE, srt.stitch_blocks(bad), fill_missing=True)
        self.assertEqual(rejected, 1)
        self.assertEqual(out, SOURCE)


if __name__ == '__main__':
    unittest.main()
