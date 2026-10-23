"""AI translation: line breaks at natural points (BBC Subtitle Guidelines 3.4).

Every first line below came back from the model in a real Kodi translation
(Big Little Lies, Fleabag, Friends, Gilmore Girls, The Devil Wears Prada --
Oct 2026): a two-line cue whose first line ends on a preposition, "את", a
conjunction, a question word, a pronoun or a negation that belongs with the
line below. srt.mend_line_breaks moves it down; nothing else changes.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load(name):
    spec = importlib.util.spec_from_file_location('bbc_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


srt = _load('srt')


def cue(text, n=1, eol='\n'):
    return ('%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n, n, text)).replace('\n', eol) + eol


def mend(text):
    out = srt.mend_line_breaks(cue(text))
    return out.split('\n', 2)[2].strip().replace('\r', '')


class MendLineBreaks(unittest.TestCase):
    def test_measured_cases(self):
        for before, after in (
                ('היא האביר על\nהסוס הלבן שלי.', 'היא האביר\nעל הסוס הלבן שלי.'),
                ('אפשר לקבל את\nתשומת לבכם לרגע?', 'אפשר לקבל\nאת תשומת לבכם לרגע?'),
                ('אני לא בטוחה שאני\nרוצה ללכת לצ\'ילטון.', 'אני לא בטוחה\nשאני רוצה ללכת לצ\'ילטון.'),
                ('מכדי אכפת לך מה\nאת לובשת על הגוף שלך.', 'מכדי אכפת לך\nמה את לובשת על הגוף שלך.'),
                ('את מאמינה שהם כבר\nהגיעו לכיתה א\'?', 'את מאמינה\nשהם כבר הגיעו לכיתה א\'?'),
                ('בעצם, אני ממש\nלא עד כדי כך רעב.', 'בעצם,\nאני ממש לא עד כדי כך רעב.'),
                ('<i>היא האביר על\nהסוס הלבן שלי</i>.', '<i>היא האביר\nעל הסוס הלבן שלי</i>.'),
                ('♪ אם תרצאי, את\nצריכה שאהיה איתך ♪', '♪ אם תרצאי,\nאת צריכה שאהיה איתך ♪'),
                ('אז אני מניחה שאת\n♪ לא הולכת, נכון?', 'אז אני מניחה\n♪ שאת לא הולכת, נכון?'),
                ('לא שאלתי לדעתך, ואני לא\nנמשכת לאנשים דפוקים.', 'לא שאלתי לדעתך,\nואני לא נמשכת לאנשים דפוקים.')):
            with self.subTest(before=before):
                self.assertEqual(mend(before), after)

    def test_left_alone(self):
        for text in (
                '- את\n- כן, אני.',                          # dialogue: one speaker a line
                'היא אמרה את זה.\nואז הלכה.',                # first line ends a clause
                'אני לא יודע מה\nאבל זה נשמע רע.',            # second line opens a clause
                'פשוט תשלחי אותו\nלשם מחר.',                  # object pronoun closes the verb phrase
                'לא אכפת לי על\nזה שהבטחת לי את זה אתמול מול כל החברים שלנו.',   # line 2 would pass 42
                '?אתה יודע עם מי\nכיף לדבר',                  # model's misplaced mark, fixed later
                'אתה יודע עם מי\n?כיף לדבר',
                'היא האביר <b>על</b>\nהסוס.',                 # markup at the edge
                'היא האביר על\n<i>הסוס.</i>',
                'היא האביר על\n♪ <i>הסוס</i>',               # note then tag: no room between
                '<i>?היא האביר על\nהסוס',                     # misplaced mark behind a tag
                'אני לא יודע מה\nאז, מה נעשה?',               # clause opener with a comma
                'בסדר, קודם כל\nתירגעי ותקשיבי לי.',          # "first of all" stays together
                'She is the knight on\nthe white horse.',     # not Hebrew
                'שהם כבר\nהגיעו.',                            # nothing left on line 1
                'היא האביר על'):                              # one line
            with self.subTest(text=text):
                self.assertEqual(mend(text), text)

    def test_three_lines_and_whole_file_untouched_but_for_the_fix(self):
        text = cue('שורה אחת\nשורה שתיים על\nשלוש.', 1) + '\n' + cue('היא האביר על\nהסוס.', 2)
        out = srt.mend_line_breaks(text)
        blocks = srt.parse_blocks(out)
        self.assertEqual(blocks[0].strip(), srt.parse_blocks(text)[0].strip())
        self.assertEqual(blocks[1].split('\n')[:2], ['2', '00:00:02,000 --> 00:00:02,900'])
        self.assertEqual(blocks[1].split('\n')[2:], ['היא האביר', 'על הסוס.'])

    def test_crlf_kept_and_idempotent(self):
        text = cue('היא האביר על\nהסוס הלבן שלי.', eol='\r\n')
        once = srt.mend_line_breaks(text)
        self.assertIn('היא האביר\r\nעל הסוס הלבן שלי.', once)
        self.assertEqual(srt.mend_line_breaks(once), once)
        self.assertNotIn('\r\r', once)

    def test_nothing_to_do_returns_the_same_object(self):
        text = cue('שלום.\nמה שלומך?')
        self.assertIs(srt.mend_line_breaks(text), text)
        self.assertEqual(srt.mend_line_breaks(''), '')

    def test_runs_before_the_rtl_fix_in_every_ai_path(self):
        src = (LIB / 'translate.py').read_text('utf-8')
        final = src.index('final = srt.mend_line_breaks(final)')
        self.assertLess(final, src.index('final = srt.fix_rtl_punctuation(final)', final))
        preview = src[src.index('def _preview_clean'):]
        self.assertLess(preview.index('srt.fix_rtl_punctuation('), preview.index('srt.mend_line_breaks('))
        google = src[src.index('def _google_translate_and_save'):]
        self.assertLess(google.index('heb = srt.mend_line_breaks(heb)'), google.index('cache.save_text('))


if __name__ == '__main__':
    unittest.main()
