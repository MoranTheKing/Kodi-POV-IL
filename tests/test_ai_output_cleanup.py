"""AI translation: output defects measured in Kodi runs of the free model.

Every bad line below came back from Gemini 3.5 Flash-Lite in a real Kodi
"AI translation" of an English subtitle.
"""

import importlib.util
import json
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load(name):
    spec = importlib.util.spec_from_file_location('aioc_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


srt = _load('srt')
sr = _load('script_residual')
er = _load('english_residual')


def block(n, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n, n, text)


def crlf(*blocks):
    return '\r\n\r\n'.join(b.replace('\n', '\r\n') for b in blocks) + '\r\n'


class StrayLatinLetterTests(unittest.TestCase):
    def test_a_stray_latin_letter_is_spelled_in_hebrew(self):
        for bad, good in (('.טוב, זה ממש לא מקובל. בואi, מתוקה', '.טוב, זה ממש לא מקובל. בואי, מתוקה'),
                          ('אני יכול להבין בהTחשב בהיסטוריה שלנו', 'אני יכול להבין בהתחשב בהיסטוריה שלנו'),
                          ('...בעזרת חbרה של', '...בעזרת חברה של'),
                          ('<i>בואi</i>', '<i>בואי</i>'),
                          ('...את הולכת להרוג את עצמc בשביל', '...את הולכת להרוג את עצמך בשביל')):
            self.assertEqual(srt.fold_stray_latin_letter(bad), good)

    def test_latin_words_and_prefixed_names_stay(self):
        for kept in ('ראיתי את זה בNetflix', 'הDJ היה טוב', 'קיבלתי בA', 'תודהe', 'ויטמין C'):
            self.assertIs(srt.fold_stray_latin_letter(kept), kept)



class PronounStutterTests(unittest.TestCase):
    def test_a_stutter_takes_the_gender_of_the_word_it_repeats(self):
        # Measured after a repair: "You-you look nice".
        self.assertEqual(srt.fix_pronoun_stutter('.את-אתה נראה טוב'), '.אתה-אתה נראה טוב')
        self.assertEqual(srt.fix_pronoun_stutter('אתה-את בסדר?'), 'את-את בסדר?')
        # A pause between the words: the first is as often the object marker
        # (review finding), so nothing is touched.
        for kept in ('ראיתי את-את הכלב', 'את-את נראית טוב', 'זאת-אתה',
                     'הוא לקח את... אתה יודע, הדבר הזה', 'ראיתי את - אתה יודע - הבחור',
                     'אתה... את מי אתה מחפש?'):
            self.assertIs(srt.fix_pronoun_stutter(kept), kept)

class SoundCueTests(unittest.TestCase):
    SRC = crlf(block(1, 'HEAVY BREATHING'), block(2, 'GET OUT!'), block(3, 'Who is it?'),
               block(4, 'BELL RINGS\n- Who is it?'), block(5, 'Here we go.'), block(6, 'Fine.'),
               block(7, 'See you later.'), block(8, 'Not now.'), block(9, 'Maybe tomorrow.'))

    def test_a_capital_cue_left_in_english_is_dropped(self):
        out = crlf(block(1, 'HEAVY BREATHING'), block(2, '!צא החוצה'), block(3, '?מי זה'),
                   block(4, 'BELL RINGS\n?מי זה -'), block(5, '.הנה זה בא'), block(6, '.בסדר'))
        self.assertEqual(srt.drop_untranslated_sound_cues(out, self.SRC),
                         crlf(block(2, '!צא החוצה'), block(3, '?מי זה'), block(4, 'BELL RINGS\n?מי זה -'),
                              block(5, '.הנה זה בא'), block(6, '.בסדר')))

    def test_a_translated_cue_is_kept(self):
        out = crlf(block(1, 'נשימות כבדות'), block(2, '!צא החוצה'), block(3, '?מי זה'))
        self.assertIs(srt.drop_untranslated_sound_cues(out, self.SRC), out)

    def test_an_all_capitals_file_is_dialogue(self):
        # Broadcast captions write every line in capitals (review finding).
        src = crlf(block(1, "I DON'T KNOW WHAT"), block(2, 'GET OUT'), block(3, 'SIRENS WAILING'))
        out = crlf(block(1, "I DON'T KNOW WHAT"), block(2, 'GET OUT'), block(3, 'SIRENS WAILING'))
        self.assertIs(srt.drop_untranslated_sound_cues(out, src), out)

    def test_a_line_that_speaks_to_someone_stays(self):
        src = crlf(block(1, 'COME HERE'), block(2, 'Okay then.'), block(3, 'Fine.'), block(4, 'Sure.'))
        out = crlf(block(1, 'COME HERE'), block(2, '.בסדר אז'), block(3, '.טוב'), block(4, '.בטח'))
        self.assertIs(srt.drop_untranslated_sound_cues(out, src), out)


class ModelNoteTests(unittest.TestCase):
    def test_a_latin_name_in_parentheses_beside_hebrew_is_a_note(self):
        self.assertEqual(srt.drop_model_notes(block(14, '.סקיילר\n(Skyler)')), block(14, '.סקיילר'))

    def test_a_lone_or_descriptive_parenthesis_stays(self):
        for kept in (block(14, '(Skyler)'), block(3, 'שלום\n(in Spanish)')):
            self.assertEqual(srt.drop_model_notes(kept), kept)



class TitleCaseSpeakerTagTests(unittest.TestCase):
    # Big Little Lies narration: "Celeste: <i>...</i>" came back as "סלסט:"
    # or with "Celeste:" copied.
    SRC = crlf(block(1, 'Celeste: <i>Look at me. Look at the camera.</i>'),
               block(2, "- Stu:<i> Thing about fundraisers...</i>\n- Melissa:<i> They're vicious.</i>"),
               block(3, "Look: I don't know."),
               block(4, 'Rachel: Hi!'))

    def test_names_the_file_vouches_for_are_removed(self):
        out = crlf(block(1, 'סלסט: <i>תסתכלו עלי. תסתכלו אל המצלמה.</i>'),
                   block(2, '- Stu: <i>העניין באירועי התרמה...</i>\n- מליסה: <i>הם אכזריים.</i>'),
                   block(3, 'תראה: אני לא יודע.'),
                   block(4, "רייצ'ל: היי!"))
        self.assertEqual(srt.strip_hebrew_speaker_prefix(out, self.SRC),
                         crlf(block(1, '<i>תסתכלו עלי. תסתכלו אל המצלמה.</i>'),
                              block(2, '- <i>העניין באירועי התרמה...</i>\n- <i>הם אכזריים.</i>'),
                              block(3, 'תראה: אני לא יודע.'),
                              block(4, "רייצ'ל: היי!")))


class ForeignScriptRepairTests(unittest.TestCase):
    SRC = [block(1, "I'm running the place now."), block(2, 'She can be hostile to me.'),
           block(3, 'Moscow, Москва.'), block(4, 'With 400 million on board.')]
    OUT = [block(1, '.אฉัน מנהלת את המקום עכשיו'), block(2, '.א她是 יכולה להיות עוינת כלפיי'),
           block(3, '.מוסקבה, Москва'), block(4, 'وعلى متنها 400 مليون دولار')]

    def test_only_a_third_script_the_source_lacks_is_selected(self):
        self.assertEqual([(i, o) for i, o, _ in sr.candidates(self.SRC, self.OUT)],
                         [(0, 2), (1, 2), (3, 2)])

    def test_clean_answers_are_taken_and_a_dirty_one_refused(self):
        prompts = []

        def request(prompt):
            prompts.append(prompt)
            return json.dumps([
                {'id': '0:0', 'text': '.אני מנהלת את המקום עכשיו'},
                {'id': '1:0', 'text': '.היא יכולה להיות עוינת כלפיי ก'},
                {'id': '3:0', 'text': 'ועל הסיפון 400 מיליון דולר'}], ensure_ascii=False)

        blocks, counts = sr.repair(self.SRC, self.OUT, request)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(counts, {'selected': 3, 'requests': 1, 'repaired': 2, 'rejected': 1,
                                  'kept': 0, 'error': ''})
        self.assertEqual(blocks, [block(1, '.אני מנהלת את המקום עכשיו'), self.OUT[1],
                                  self.OUT[2], block(4, 'ועל הסיפון 400 מיליון דולר')])

    def test_a_repair_may_not_drop_a_negation_or_rewrite_a_hebrew_word(self):
        # Review traps: both used to be accepted.
        out = [block(1, '.אני ฉัน לא יודעת'), block(2, 'אฉัן מנהלת')]

        def request(prompt):
            return json.dumps([{'id': '0:0', 'text': '.אני יודעת'},
                               {'id': '1:0', 'text': 'אני מנהל'}], ensure_ascii=False)

        blocks, counts = sr.repair(self.SRC[:2], out, request)
        self.assertEqual(blocks, out)
        self.assertEqual(counts['rejected'], 2)

    def test_a_repair_may_not_flip_gender_or_lose_a_number(self):
        out = [block(1, '.אני יודעת שזה ฉัน'), block(2, 'ועם 400 מיליוןの')]

        def request(prompt):
            return json.dumps([{'id': '0:0', 'text': '.אני יודע שזה'},
                               {'id': '1:0', 'text': 'ועם מיליון'}], ensure_ascii=False)

        blocks, counts = sr.repair(self.SRC[:2], out, request)
        self.assertEqual(blocks, out)
        self.assertEqual(counts['rejected'], 2)

    def test_a_stray_answer_costs_the_others_nothing(self):
        def request(prompt):
            return json.dumps([{'id': '9:9', 'text': 'x'}, 'junk',
                               {'id': '0:0', 'text': '.אני מנהלת את המקום עכשיו', 'note': 'x'},
                               {'id': '0:0', 'text': '.שוב'}], ensure_ascii=False)

        blocks, counts = sr.repair(self.SRC, self.OUT, request)
        self.assertEqual(blocks[0], block(1, '.אני מנהלת את המקום עכשיו'))
        self.assertEqual((counts['repaired'], counts['rejected']), (1, 3))

    def test_a_broken_reply_keeps_everything(self):
        for reply in ('not json', json.dumps([{'id': '9:9', 'text': 'x'}]), RuntimeError('quota')):
            def request(prompt, _r=reply):
                if isinstance(_r, Exception):
                    raise _r
                return _r
            blocks, counts = sr.repair(self.SRC, self.OUT, request)
            self.assertEqual(blocks, self.OUT)
            self.assertEqual(counts['repaired'], 0)

    def test_nothing_to_repair_costs_no_request(self):
        clean = [block(1, 'שלום')]
        blocks, counts = sr.repair([block(1, 'Hello')], clean,
                                   lambda p: self.fail('no request expected'))
        self.assertEqual((blocks, counts['requests']), (clean, 0))



class EnglishResidualTests(unittest.TestCase):
    def test_one_request_holds_a_whole_untranslated_scene(self):
        # Measured: about 40 lines of one scene came back in English; room
        # for 16 left 25 of them on screen.
        before = [block(i + 1, 'We know the way to the house') for i in range(60)]
        prompts = []
        out, counts = er.repair(before, before, 'en', lambda p: prompts.append(p) or '[]')
        self.assertEqual((counts['selected'], len(prompts)), (40, 1))

    def test_a_named_speaker_does_not_hide_an_english_line(self):
        self.assertTrue(er._candidate('Perry: Do you want to know a secret?'))
        self.assertTrue(er._candidate('JOSH: What is it you want from me?'))
        self.assertFalse(er._candidate('WARNING: Do not enter the room'))
        self.assertFalse(er._candidate('http://www.example.com is where we go'))

class WiringTests(unittest.TestCase):
    def test_translate_runs_every_cleanup(self):
        text = (LIB / 'translate.py').read_text(encoding='utf-8')
        for call in ('srt.fold_stray_latin_letter(final)',
                     'srt.drop_untranslated_sound_cues(final, src_text)',
                     'script_residual.repair('):
            self.assertIn(call, text)
        # A chunk that passes on the fallback reference is topped up too.
        alt = text.index('passed with fallback reference')
        self.assertIn('_top_up_missing(', text[alt:alt + 600])


if __name__ == '__main__':
    unittest.main()
