"""The extra backstops of the Hebrew gender repair (gender_guard.py).

Cases ported from SRT AI Translator NG's gates (Round 19A A.1, A.3, A.4,
RR-2 W3, R19 H.1 C1; MIT, Akila3), run against our own proof
(arabic_gender.person_roles_fixed) and srt.looks_hebrew.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load(name):
    spec = importlib.util.spec_from_file_location('gg_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gg = _load('gender_guard')
srt = _load('srt')
with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
        log=lambda *a, **k: None)}):
    ag = _load('arabic_gender')


def splice(old, roles, reply):
    """The repair verdict as translate.py applies it: (text kept, reason)."""
    old_lines = [l for l in old.split('\n') if l.strip()]
    new_lines = [l for l in reply.split('\n') if l.strip()]
    lines, why = gg.vet_repair(old_lines, new_lines, roles,
                               lambda body: ag.person_roles_fixed(body, roles),
                               lambda body: srt.looks_hebrew(body, min_alpha=1))
    return ('\n'.join(lines) if lines else old), (why or 'accepted')


class MixedAddress(unittest.TestCase):
    def test_a_you_that_disagrees_with_its_own_verb(self):
        self.assertEqual([gg.mixed_address(t) for t in (
            'אתה חושבת שזה טוב', 'אתה תוכלי לבוא', 'אתה ממש לא יודעת', 'ואתה צודקת',
            'טוב, את חושב שכן?', 'אתה תלכי הביתה')], [True] * 6)

    def test_grammatical_and_object_marker_lines(self):
        self.assertEqual([gg.mixed_address(t) for t in (
            'אתה רוצה', 'אתה טועה', 'אתה חושב שזה טוב', 'את חושבת שזה טוב', 'ראיתי את חושב',
            'את הולך', 'אתה תלמידי', 'אני חושבת שאתה צודק')], [False] * 8)

    def test_direction_marks_do_not_hide_it(self):
        self.assertTrue(gg.mixed_address('\u202bאתה חושבת שזה טוב\u202c'))


class VetRepair(unittest.TestCase):
    def test_a_reply_that_creates_a_mismatched_you_is_refused(self):
        self.assertEqual(splice('את חושבת שזה טוב', [('addressee', 'M')], 'אתה חושבת שזה טוב'),
                         ('את חושבת שזה טוב', 'mixed'))
        self.assertEqual(splice('את תוכלי לבוא', [('addressee', 'M')], 'אתה תוכלי לבוא'),
                         ('את תוכלי לבוא', 'mixed'))

    def test_the_grammatical_reply_is_taken(self):
        self.assertEqual(splice('את חושבת שזה טוב', [('addressee', 'M')], 'אתה חושב שזה טוב'),
                         ('אתה חושב שזה טוב', 'accepted'))

    def test_a_mismatch_the_old_line_already_had_does_not_block(self):
        self.assertEqual(
            splice('את צודקת. אתה תוכלי לבוא', [('addressee', 'M')], 'אתה צודק. אתה תוכלי לבוא'),
            ('אתה צודק. אתה תוכלי לבוא', 'accepted'))

    def test_stray_letters_and_backslashes(self):
        self.assertEqual(splice('אה, אתה עייף', [('addressee', 'F')], 'אه, את עייפה'),
                         ('אה, אתה עייף', 'stray'))
        self.assertEqual(splice('אתה עייף', [('addressee', 'F')], 'את עייפה OK'),
                         ('אתה עייף', 'stray'))
        self.assertEqual(splice('אתה עייף, Dan', [('addressee', 'F')], 'את עייפה, Dan'),
                         ('את עייפה, Dan', 'accepted'))
        self.assertEqual(splice('אמרת "שלום", אתה עייף', [('addressee', 'F')],
                                'אמרת \\"שלום\\", את עייפה'),
                         ('אמרת "שלום", את עייפה', 'accepted'))
        self.assertEqual(splice('אמרת "שלום", אתה עייף', [('addressee', 'F')],
                                'אמרת "שלום"\\, את עייפה'),
                         ('אמרת "שלום", אתה עייף', 'stray'))
        self.assertEqual(splice('C:\\ אתה עייף', [('addressee', 'F')], 'C:\\ את עייפה \\"'),
                         ('C:\\ אתה עייף', 'stray'))

    def test_the_speaker_keeps_his_own_words_on_an_addressee_fix(self):
        # Before Sunset 314, 593, 594: addressee F requested.
        self.assertEqual(splice('ובכן, אני מתכוון, אתה יודע, כמו...', [('addressee', 'F')],
                                'ובכן, אני מתכוונת, את יודעת, כמו...'),
                         ('ובכן, אני מתכוון, את יודעת, כמו...', 'accepted'))
        self.assertEqual(splice('אני רוצה להיות בן אדם טוב יותר, אתה יודע?', [('addressee', 'F')],
                                'אני רוצה להיות בת אדם טובה יותר, את יודעת?'),
                         ('אני רוצה להיות בן אדם טוב יותר, את יודעת?', 'accepted'))

    def test_an_addressee_form_goes_back_on_a_speaker_only_fix(self):
        self.assertEqual(splice('אני עייף, תגיד לי', [('speaker', 'F')], 'אני עייפה, תגידי לי'),
                         ('אני עייפה, תגיד לי', 'accepted'))
        self.assertEqual(splice('אני עייף, תגיד לי', [('speaker', 'F'), ('addressee', 'F')],
                                'אני עייפה, תגידי לי'),
                         ('אני עייפה, תגידי לי', 'accepted'))

    def test_put_back_limits(self):
        self.assertEqual(splice('ובכן, אני מתכוון, אתה יודע', [('addressee', 'F')],
                                'ובכן, אני מתכוונת, אתה יודע'),
                         ('ובכן, אני מתכוון, אתה יודע', 'unrequested'))
        # A different word count: nothing is put back; the proof decides.
        self.assertEqual(splice('אני מתכוון, אתה יודע', [('addressee', 'F')],
                                'אני מתכוונת, את יודעת היטב')[0],
                         'אני מתכוונת, את יודעת היטב')
        # A third-person change is not a role of this cue: kept.
        self.assertEqual(splice('הוא עייף, אתה יודע', [('addressee', 'F')], 'היא עייפה, את יודעת'),
                         ('היא עייפה, את יודעת', 'accepted'))

    def test_you_know_what_is_the_addressee(self):
        # validator: 'יודע מה?' at a line start was taken as the speaker's word
        self.assertEqual(splice('יודע מה? לך הביתה.', [('addressee', 'F')], 'יודעת מה? לכי הביתה.'),
                         ('יודעת מה? לכי הביתה.', 'accepted'))
        self.assertEqual(gg.clause_words('יודעת שאני צודקת.')[0][2], 'speaker')

    def test_the_old_checks_still_hold(self):
        self.assertEqual(splice('אתה עייף', [('addressee', 'F')], 'אתה עייף')[1], 'unchanged')
        self.assertEqual(splice('אתה לא עייף', [('addressee', 'F')], 'את עייפה')[1], 'invariant')
        self.assertEqual(splice('אתה עייף\nבוא', [('addressee', 'F')], 'את עייפה בואי')[1], 'shape')
        self.assertEqual(splice('אתה עייף', [('addressee', 'F')], 'أنتِ متعبة')[1], 'not_hebrew')


class TwoSpeakers(unittest.TestCase):
    def test_a_later_speaker(self):
        self.assertEqual([gg.two_speakers(t) for t in (
            '- Are you sure?\n- I am.', 'Are you sure?\n- I am.', '<i>- Wait.</i>\n<i>- No.</i>',
            '\u200f- את בטוחה?\n\u200f- אני עייף.', '\u2013 Yes.\n\u2013 No.', 'Hi. - Hello.',
            '- Hi.\r\n- Hello.')], [True] * 7)

    def test_one_speaker(self):
        self.assertEqual([gg.two_speakers(t) for t in (
            'I am tired.', 'I am\nvery tired.', '- I am tired.', 'A well-known man.',
            'Wait - what?', 'I am tired -\nreally tired.')], [False] * 6)


class RomanceAddressee(unittest.TestCase):
    def test_reviewed_predicates(self):
        self.assertEqual([gg.romance_addressee(t, 'es') for t in (
            'tú estás cansada', 'tú estás cansado', 'estás muy segura', 'eres realmente seguro')],
            ['F', 'M', 'F', 'M'])
        self.assertEqual([gg.romance_addressee(t, 'pt') for t in (
            'você está cansada', 'você está cansado', 'tu estás muito pronta',
            'tu estás realmente pronto')], ['F', 'M', 'F', 'M'])

    def test_nouns_third_persons_and_other_languages_read_nothing(self):
        self.assertEqual([gg.romance_addressee(t, 'es') for t in (
            'eres una estrella', 'tienes una casa', 'ella está cansada', 'la mujer está cansada',
            'te quiero', 'una mujer preocupada')], [None] * 6)
        self.assertEqual([gg.romance_addressee(t, 'pt') for t in (
            'é uma estrela', 'é uma casa', 'ela está cansada', 'a casa está pronta',
            'você tem uma casa', 'uma mulher preocupada')], [None] * 6)
        self.assertIsNone(gg.romance_addressee('tú estás cansada', 'fr'))
        self.assertIsNone(gg.romance_addressee('Eres solo una niña.', 'es'))   # solo = only
        self.assertIsNone(gg.romance_addressee('estás cansada y estás cansado', 'es'))


class DirectionMarks(unittest.TestCase):
    LINES = ('את נראית עייפה.', 'את לא יכולה לומר שלא ניסיתי.', 'את יודעת מה הייתי עושה?',
             'ואת בטעות מעמידה פנים')

    def test_a_human_line_that_starts_with_a_mark_still_reads_female(self):
        rle, pdf = '\u202b', '\u202c'
        self.assertEqual([ag.reference_addressee_gender(rle + t + pdf, 'he') for t in self.LINES],
                         ['F'] * 4)
        self.assertEqual([ag.addresses_female(rle + t) for t in self.LINES], [True] * 4)

    def test_marks_change_no_reading(self):
        plain = ('ואת עייפה', 'ראיתי את דני', 'אני כאן ואתה עייף', 'אני הולכת', 'אני הולך את דני')

        def marked(t):
            return '\u202b' + t[:2] + '\u2067' + t[2:] + '\u2069\u202c'
        self.assertEqual([(ag.addresses_female(marked(t)), ag.addresses_male(marked(t)),
                           ag.reference_addressee_gender(marked(t), 'he')) for t in plain],
                         [(ag.addresses_female(t), ag.addresses_male(t),
                           ag.reference_addressee_gender(t, 'he')) for t in plain])


if __name__ == '__main__':
    unittest.main()
