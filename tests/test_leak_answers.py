"""The answer a leaked cue is repaired with is whole and the model's (srt.py).

Reviewer findings on 0.3.57 (the read repair writes cached files in place,
so a wrong answer is permanent): an arrow inside a bracketed note gave a
piece of the note ("אין לך)"); a note after the settled line threw it away
for the wrong-gender draft; drafts side by side dropped the next speaker's
line; a word swapped mid-sentence cut the sentence short; with no source a
kept English title or quote was cut; and "Wait," in the source let a
"Let's use:" through. The cues below are the corpus ones (QA runs) or built
the same way.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
spec = importlib.util.spec_from_file_location('srt_answers', LIB / 'srt.py')
srt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srt)


def block(index, start, end, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,000\n%s' % (index, start, end, text)


class Answers(unittest.TestCase):

    def test_an_arrow_inside_a_note_is_not_the_answer(self):
        cases = [
            ('גברת, אין לך מושג כמה\n-> גברת, אין לך מושג כמה\n'
             'נואשות אני רוצה לעזור. (Michel speaking to Emily, Emily is female -> אין לך)',
             'גברת, אין לך מושג כמה\nנואשות אני רוצה לעזור.'),
            ('-> תביאי נגן מפוחית. (Lorelai is female -> תביאי)', 'תביאי נגן מפוחית.'),
            ('.טוב. חברת המטוסים-- אה, אוטובוס בית הספר פנוי\n'
             "*(Wait, school bus, let's keep it accurate:)*\n.טוב. אוטובוס בית הספר פנוי",
             '.טוב. אוטובוס בית הספר פנוי'),
        ]
        for text, answer in cases:
            self.assertEqual(srt.leaked_cue_answer(text), answer, text)

    def test_a_note_after_the_settled_line_is_cut_off(self):
        self.assertEqual(srt.leaked_cue_answer(
            '.אוקיי. אני נגן נבל מעולה\n-> אוקיי. אני נגנית נבל מעולה. (Drella is female)'),
            'אוקיי. אני נגנית נבל מעולה.')
        self.assertEqual(srt.leaked_cue_answer(
            "תודה שבאת. Let's use: תודה שבאתם. (plural)"), 'תודה שבאתם.')

    def test_every_speaker_and_the_whole_sentence(self):
        # drafts side by side, then the next speaker
        self.assertEqual(srt.leaked_cue_answer(
            '.כשאחזור, תוכל ללכת. / כשאחזור, תוכלי ללכת -\n.אוקיי -'),
            '.כשאחזור, תוכל ללכת. -\n.אוקיי -')
        # a word swapped mid-sentence: no draft of the whole line
        for text in ('?וזו הקיתארה / הנבל הנהדרת שלי, נכון',
                     'אלוהים, מתוק. אתה צריך לראות איך\n.הבחורות האלה ב"פאנפיי" / "ראנוויי" מתלבשות'):
            self.assertEqual(srt.leaked_cue_answer(text), '', text)
        self.assertEqual(srt.leaked_cue_answer(
            ',זה לא היה ביג דיל\nאפילו לא בולטה בראש. -> *בבלטה בראש / בליטה בראש'),
            ',זה לא היה ביג דיל\nאפילו לא בולטה בראש.')
        # the settled line answers one speaker of two: the draft has both
        text = "- את באה?\n- כן. (Wait, Spanish: Sí.) Let's use: כן."
        self.assertEqual(srt.leaked_cue_answer(text, '- Are you coming?\n- Yes.'),
                         '- את באה?\n- כן.')

    def test_two_speakers_without_a_source(self):
        # review round 2: the pool-dialog path has no source line
        self.assertEqual(srt.leaked_cue_answer(
            "- היי.\n- תודה שבאת. Let's use: תודה שבאתם."), '- היי.\n- תודה שבאת.')
        self.assertEqual(srt.leaked_cue_answer(
            '- את באה? (Wait, Spanish: ¿Vienes?)\n- כן.'), '- את באה?\n- כן.')
        # reverse-mode dashes after the line, the settled lines after an arrow
        self.assertEqual(srt.leaked_cue_answer(
            '?שאלתי אם את אוהבת עוגה -\n.כן, שאלת -\n?-> - שאלתי אם את אוהבת עוגה\n.כן, שאלת -'),
            '- שאלתי אם את אוהבת עוגה?\n.כן, שאלת -')

    def test_names_and_tags_are_not_source_words(self):
        source = '<i>NARRATOR: Bring it.</i>'
        self.assertEqual(srt.leaked_cue_answer("Let's use: תביא את זה.", source), 'תביא את זה.')
        self.assertEqual(srt.leaked_cue_answer(
            "Let's use: תביא את זה.", '-\n- Bring it to me now, Jake.'), 'תביא את זה.')

    def test_a_piece_is_not_an_answer(self):
        self.assertEqual(srt.leaked_cue_answer('-> אין לך)'), '')
        self.assertEqual(srt.leaked_cue_answer('-> הוא כתב "'), '')
        # under 40% of the source line's words
        self.assertEqual(srt.leaked_cue_answer(
            "Let's use: תביאי.", 'Go and bring me a harmonica player, Lorelai.'), '')
        # a quotation spanning cues is fine
        self.assertEqual(srt.leaked_cue_answer('יקבל מענה." / \nיגיע ליעדו."'), 'יקבל מענה."')

    def test_the_reverse_end_mark_stays(self):
        self.assertEqual(srt.leaked_cue_answer(
            ".תודה שבאשת. / תודה שבאתם Let's use: תודה שבאת"), 'תודה שבאת.')
        self.assertEqual(srt.leaked_cue_answer('?-> מה'), 'מה?')

    def test_the_line_after_a_note_is_the_correction(self):
        text = ('ולא רצית\n.ע/ עוררת עאזפה נבל מעולה? (Wait, Drella is speaking to '
                'Lorelai, feminine addressee)\n?האם לא רצית נגנית נבל מעולה')
        self.assertEqual(srt.leaked_cue_answer(text), '?האם לא רצית נגנית נבל מעולה')
        # a note that ends the cue leaves the line before it as the answer
        self.assertEqual(srt.leaked_cue_answer(
            'דברים שתבוא ותלמד עלי\n(Walter speaking to Walter Jr., male addressee)'),
            'דברים שתבוא ותלמד עלי')

    def test_position_and_italics_stay(self):
        self.assertEqual(srt.restyle_like('{\\an8}<i>שלום. -> Wait, hi</i>', 'שלום.'),
                         '{\\an8}<i>שלום.</i>')
        self.assertEqual(srt.restyle_like('<i>שלום</i> -> <i>היי</i>', 'היי'), 'היי')


class Detection(unittest.TestCase):

    def leaks(self, text, source='', strong_only=False):
        src = [block(1, 1, 2, source)] if source else []
        return srt.generated_editorial_leak_indices(
            src, [block(1, 1, 2, text)], strong_only=strong_only)

    def test_no_source_needs_a_strong_sign(self):
        for kept in ('הוא כתב "Let\'s check" על הקיר.', 'קוראים לו Singular Value.'):
            self.assertEqual(self.leaks(kept, strong_only=True), [], kept)
            self.assertEqual(self.leaks(kept), [0], kept)   # the broad first look
        for text in ("מנפרדי נולד בר מזל. Let's use: מנפרדי נולד בר מזל.",
                     'תודה שבאת. (masc. singular) Wait, plural?',
                     'תודה שבאת. / תודה שבאתם.'):
            self.assertEqual(self.leaks(text, strong_only=True), [0], text)

    def test_each_phrase_needs_its_own_place_in_the_source(self):
        self.assertEqual(self.leaks("רגע, תודה שבאת. Let's use: רגע, תודה שבאתם.",
                                    'Wait, thanks for coming.'), [0])
        self.assertEqual(self.leaks('רגע, תודה שבאת. Wait, ', 'Wait, thanks for coming.'), [])

    def test_a_line_drafted_again_after_an_arrow(self):
        text = "?ולמה שאעשה זאת\n?[Lama she-e'ese zot?] -> ולמה שאעשה זאת"
        self.assertEqual(self.leaks(text, 'And why would I do that?'), [0])
        self.assertTrue(srt.may_carry_reasoning(block(1, 1, 2, text)))
        # the question mark 'reverse' moved to the front comes back at the end
        self.assertEqual(srt.leaked_cue_answer(text, 'And why would I do that?'), 'ולמה שאעשה זאת?')
        # an arrow to new words, or one the source has, is dialogue
        for kept, source in (('הפונקציה היא x -> y והכול תקין.', 'Wait.'),
                             ('לך שמאלה -> לך שמאלה', 'Go left -> go left')):
            self.assertEqual(self.leaks(kept, source), [], kept)

    def test_the_pre_check_sees_what_the_scan_sees(self):
        for body in ('-> 10:30:00 בבוקר', 'אוהבת אותך <3\n-> אוהבת אותך'):
            text = block(1, 1, 2, body)
            self.assertEqual(srt.generated_editorial_leak_indices([], [text]), [0], body)
            self.assertTrue(srt.may_carry_reasoning(text), body)


if __name__ == '__main__':
    unittest.main()
