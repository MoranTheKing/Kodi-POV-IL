"""AI translation: speaker/addressee gender checks and source/output hygiene.

Every Hebrew pair below is a real error measured in a Kodi run of Gemini
3.5 Flash-Lite against a human translation of the same line, or a trap the
detector must stay silent on.
"""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load(name):
    spec = importlib.util.spec_from_file_location('aigp_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hpg = _load('he_person_gender')
srt = _load('srt')
sr = _load('script_residual')
with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
        log=lambda *a, **k: None)}):
    ag = _load('arabic_gender')


def block(n, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n, n, text)


class PersonGenderTests(unittest.TestCase):
    REAL = [
        ('אני יודע שזה די קלישאי', 'אני יודעת שזו קלישאה', [('speaker', 'F')]),
        ('?לאיזו מוזיקה את מאזינה', '?לאיזו מוזיקה אתה מאזין', [('addressee', 'M')]),
        ('.טוב, אל תדאגי לגבי התינוק', '.אל תדאג לתינוק', [('addressee', 'M')]),
        ('...תירגעי, ותני לזה', '...תירגע, ותן לזה', [('addressee', 'M')]),
        ('ואני בהחלט לא מרגיש', 'ואני בהחלט לא מרגישה', [('speaker', 'F')]),
        ('.אני, אמ, אני מחבבת אותך', '.אני... מחבב אותך', [('speaker', 'M')]),
        ('.תאמיני לי, אני יודעת', '.תאמין לי, אני יודע',
         [('addressee', 'M'), ('speaker', 'M')]),
        # Two speakers on one human line behind an invisible direction mark.
        ('- אז, את אוהבת עוגה?\n- מה?', '\u202b-אתה אוהב עוגה?\u202c \u202b-מה?\u202c',
         [('addressee', 'M')]),
        # Commands: the human's own word without / with the feminine י.
        ('.תישארי פה. תישארי חגורה', '.תישאר פה. אל תפתח .את חגורת הבטיחות',
         [('addressee', 'M')]),
        ('.בטח. פשוט תבקש מנייתן שיחזור אלי', 'נכון. -כמובן. תבקשי מנייתן .שיתקשר אליי',
         [('addressee', 'F')]),
        ('- ספר לי על סלסט רייט.\n- משהו היה חייב להיות לא בסדר.',
         '.ספרי לי על סלסט רייט .משהו לא היה בסדר שם-', [('addressee', 'F')]),
        # Two AI turns against one human turn: the shared word places it.
        ('- היא בסדר?\n- אני לא יודעת.', '.אני לא יודע, תכף נדע .תני לה שנייה',
         [('speaker', 'M')]),
        # The same words after "אתה" in the human line and "את" in the AI's.
        ('...ה - / ?את האבא החדש שלי -'.replace(' / ', '\n'), '\u202bאתה האבא החדש שלי?\u202c',
         [('addressee', 'M')]),
        # "את" before "כמו" can only be the pronoun.
        ('אלוהים! את כמו רות גורדון\nשעומדת שם', '\u202bאתה כמו רות גורדון, עומד שם כמו גולם.\u202c',
         [('addressee', 'M')]),
    ]
    TRAPS = [
        ('.זה בשביל רורי, אני נשבעת', 'זה עבור רורי, אני נשבעת.'),   # agrees
        ('.אבל הם מאוד בריאים', 'אבל הן מאוד בריאות.'),              # things, not people
        ('?אין הליך הוגן לתלמיד כיתה א', 'הליך תקין לתלמידי כיתה א?'),  # a noun
        ('.אל תגידי לי. בואי', '.אל תגיד לי. בואי'),               # "Bowie"
        ('ראיתי את דני אתמול', 'ראיתי את דני אתמול'),               # object marker
        ('אולי תוכל להראות לי', 'אולי תוכלי להראות לי'),            # "she could" too
        ('-אתה אוהב עוגה?', '-אתה אוהב עוגה?\n-מה?'),               # turn shape differs
        ('ראיתי את הילדה', 'ראיתי את הילד'),                       # a third person
        ('אני כותב שירה', 'אני כותב שיר'),                          # a noun, not the speaker
        ('- אמרתי את זה.\n- באמת?', '-אמרתי את זה. -באמת?'),      # inline turns, no person
        # Every false alarm of the first pair rule on five baseline episodes:
        ('זיגי, קדימה\n- בוא, זיג', '.בוא, זיג'),                    # a name + י
        ('היי, יו. קרייזי, מה העניינים', '?היי, קרייז, מה שלומך, בנאדם'),
        ('דרמטית? היית', '-היית בשולחן עכשיו? -כן, הייתי.'),          # you / I
        ('?ראית אותי באיזשהו משהו', '?ראיתי אותך משחק איפשהו'),
        ('.ברור שכן, חזרתי', '?מה? חזרת לעניינים .ועוד איך חזרתי-'),
        ('מה זה אמור', 'מהי כוונתך, אמא?'),                            # question word
        ('אני יודעת. בגלל זה התכוונתי להתחתן', '.אנ יודעת, בגלל זה התחתנתי'),  # typo
        ('.ולו... ול-לי אין', '.ולי אין .אני אמא'),
        # object marker + a person noun, and "there will be" (review finding)
        ('פגשתי את חברה שלך', 'פגשתי את החבר שלך'),
        ('תהיה מסיבה מחר', 'תהיה מסיבה מחר בערב'),
    ]

    def test_measured_errors_are_found(self):
        for ai, ref, want in self.REAL:
            self.assertEqual(hpg.conflicts(ai, ref), sorted(want), msg=ai)

    def test_traps_stay_silent(self):
        for ai, ref in self.TRAPS:
            self.assertEqual(hpg.conflicts(ai, ref), [], ai)

    def test_nouns_and_futures_are_not_addressees(self):
        self.assertEqual(hpg.read('פגשתי את חברה שלך'), [{'speaker': None, 'addressee': None}])
        self.assertEqual(hpg.read('תהיה מסיבה מחר'), [{'speaker': None, 'addressee': None}])
        self.assertEqual(hpg.read('אל תהיה כזה'), [{'speaker': None, 'addressee': 'M'}])

    def test_turns_are_read_separately(self):
        self.assertEqual(hpg.read('- אני יודעת.\n- אתה בטוח?'),
                         [{'speaker': 'F', 'addressee': None},
                          {'speaker': None, 'addressee': 'M'}])

    def test_the_reference_is_the_lexicon(self):
        # A verb outside the word list still pairs with the human's own form.
        self.assertEqual(hpg.conflicts('אני מתאמנת כל יום', 'אני מתאמן כל יום'),
                         [('speaker', 'M')])
        self.assertEqual(hpg.conflicts('מי את?', 'מי אתה?'), [('addressee', 'M')])
        self.assertFalse(hpg.fixed('אני מתאמן כל יום', [('speaker', 'M')]))
        self.assertTrue(hpg.fixed('אני מתאמן כל יום', [('speaker', 'M')], 'אני מתאמן כל יום'))
        self.assertFalse(hpg.fixed('אני מתאמנת כל יום', [('speaker', 'M')], 'אני מתאמן כל יום'))
        self.assertTrue(ag.person_roles_fixed('אני מתאמן', [('speaker', 'M')], 'אני מתאמן'))

    def test_a_repair_needs_proof(self):
        self.assertTrue(ag.person_roles_fixed('אני יודע שזה', [('speaker', 'M')]))
        self.assertFalse(ag.person_roles_fixed('אני יודעת שזה', [('speaker', 'M')]))
        self.assertFalse(ag.person_roles_fixed('שלום לכולם', [('speaker', 'M')]))
        self.assertTrue(ag.person_roles_fixed('אל תדאג לתינוק', [('addressee', 'M')]))
        self.assertFalse(ag.person_roles_fixed('אל תדאגי לתינוק', [('addressee', 'M')]))
        # a rewrite that still contradicts the Hebrew reference is no fix
        # (measured: only the verb changed, the stuttered pronoun stayed)
        ref = '‫אתה נראה נחמד. באמת נחמד.‬'
        self.assertFalse(ag.person_roles_fixed('וואו!\nאת-את נראה נחמד.', [('addressee', 'M')], ref))
        self.assertTrue(ag.person_roles_fixed('וואו!\nאתה-אתה נראה נחמד.', [('addressee', 'M')], ref))
        # both forms at once is a hedge, never proof (measured in a repair)
        self.assertFalse(ag.person_roles_fixed('תוכל/י להיות נחמדה?', [('addressee', 'F')]))

    def test_conflicts_against_each_reference_language(self):
        out = [block(1, 'אני יודע.'), block(2, 'אני מצטערת.'), block(3, 'אתה בטוח?'),
               block(4, 'אני הלכתי הביתה.')]
        self.assertEqual(ag.person_gender_conflicts(out, {1: 'אני יודעת.'}, 'he'),
                         {1: [('speaker', 'F')]})
        self.assertEqual(ag.person_gender_conflicts(
            out, {2: u'أنا آسف.', 4: u'أنا متأكدة.'}, 'ar'), {2: [('speaker', 'M')]})
        self.assertEqual(ag.person_gender_conflicts(
            out, {1: u'Я знала это.', 2: u'Я не знал.'}, 'ru'),
            {1: [('speaker', 'F')], 2: [('speaker', 'M')]})
        self.assertEqual(ag.reference_speaker_gender(u'Estoy segura.', 'es'), None)

    def test_speaker_readers_for_the_rest_of_the_chain(self):
        for lang, text, want in (
                ('pl', u'Nie wiedziałam, że tu jesteś.', 'F'), ('pl', u'Ja zrobiłem to sam.', 'M'),
                ('pl', u'Usiadł przed stołem.', None), ('pl', u'Zdołam to zrobić.', None),
                ('pl', u'Całym ciałem czuję zimno.', None),
                ('cs', u'Byla jsem tam.', 'F'), ('cs', u'Udělal jsem chybu.', 'M'),
                ('sk', u'Bola som doma.', 'F'), ('sr', u'Bio sam tamo.', 'M'),
                ('hr', u'Bila sam umorna.', 'F'),
                ('pt', u'Obrigada, querido.', 'F'), ('pt', u'Muito obrigado!', 'M'),
                ('pt', u'Estou cansada.', None),
                # gender-neutral and third-person traps (review finding)
                ('ar', u'أنا بحاجة إلى مساعدة', None), ('ar', u'أنا عادة أنام مبكرا', None),
                ('ar', u'أنا آسفة', 'F'), ('ar', u'أنا متأكدة', 'F'),
                ('pt', u'Ela foi obrigada a sair.', None)):
            self.assertEqual(ag.reference_speaker_gender(text, lang), want, msg=text)

    def test_arabic_without_harakat(self):
        # Lines from human Arabic subtitles whose gender the reader used to
        # leave unread, and the traps measured while widening it.
        for text, want in (
                (u'أتريدين توصيلة أو ما شابه', 'F'), (u'تبدين رائعة', 'F'),
                (u'ماذا ستفعلين؟', 'F'), (u'عليك أن تكوني قوية', 'F'),
                (u'لا تسألي عن أي شيء', 'F'), (u'انظري إلى تلك المزبلة', 'F'),
                (u'أمابيلا، عزيزتي هل يُمكنك الإشارة', 'F'),
                (u'تعال هنا.', 'M'), (u'صدقني، فأنا أعلم', 'M'), (u'انظر إلى حياتنا', 'M'),
                (u'أنت تتصرف بسخافة', 'M'), (u'لا، أنت وسيم جدًا', 'M'),
                (u'تبدو جميلاً', 'M'), (u'هل تحب الكعك؟', 'M'), (u'وأتعرف ماذا أيضًا ؟', 'M'),
                # traps
                (u'أتفق معك', None),                        # I agree
                (u'سأعرفك على صديقتي الجديدة', None),        # a third person
                (u'أتعتقد أنها يجب ان تبقي كل عواطفها', 'M'),  # تبقي: she keeps
                (u'هل تمزح معي؟', None),                    # idiom, said to anyone
                (u'تعالِ إلى هنا', None),                    # kasra: not masculine
                (u'هل تحققت من الكابحات بسيارتي', None),     # a past tense
                (u'أعرف ما يعني رغبة الحصول على اشياء', None),
                # review findings: not verbs, past tenses, "I ...", possessives
                (u'أنت تعيسة', None), (u'أنت تلك الفتاة', None), (u'أنت تحت الاعتقال', None),
                (u'اتصل بي أبي، لكنك محقة', None), (u'أنا أتفهم ذلك', None),
                (u'يسعدني أن أتعرف عليك', None), (u'سوف أعطيك', None),
                (u'بعد توقفي عن التدخين', None), (u'ابنتي في المستشفى', None),
                (u'حبيبتي تركتني', None), (u'صديقي يعمل هنا', None),
                (u'هي تبدو هكذا', None), (u'تبدو وكأنها مريضة', None), (u'وتنانين', None),
                (u'- توقف -', 'M'), (u'توقفي عن هذا', 'F'),
                # second review round
                (u'أنت تركتني', None), (u'أنت تجاهلتني طوال اليوم', None),
                (u'أنت تعرفها', 'M'), (u'أنت تحبينه', 'F'), (u'أنت ترى', 'M'),
                (u'هذه ابنتي.', None), (u'هذا صديقي.', None), (u'تركتني حبيبتي.', None),
                (u'تبدو تماماً مثل أمها', None), (u'تبدو فعلاً متعبة', None),
                (u'تبدو جميلاً', 'M'), (u'قلت له: توقف.', None),
                (u'‏- انتظر،', 'M'), (u'عزيزي، اسمع', 'M')):
            self.assertEqual(ag.reference_addressee_gender(text, 'ar'), want, msg=text)
        for text, want in (
                (u'آسفة على التأخير', 'F'), (u'فأنا متأكدة', 'F'), (u'إنني سعيدة', 'F'),
                (u'أنا ذاهب', 'M'), (u'لست متأكداً', 'M'),
                (u'أعرف', None), (u'أنا بحاجة إلى مساعدة', None)):
            self.assertEqual(ag.reference_speaker_gender(text, 'ar'), want, msg=text)

    def test_the_reference_clock_is_measured_on_the_original_cues(self):
        # Merging a Netflix file's split captions made every reference fail
        # local consistency in Kodi; the gate must see the authored cues.
        seen = []

        def fake_align(src, blocks, ref, timing_text=None):
            seen.append((src, timing_text))
            return {1: 'hint'}, 'gate OK'

        with patch.object(ag, '_download_candidate', lambda c: 'REF'),                 patch.object(ag, 'align_one', fake_align):
            plan = ag.ReferencePlan('MERGED', [], [('he', {})], 1,
                                    timing_text='AUTHORED')
            self.assertEqual(plan.next(), ('he', {1: 'hint'}))
        self.assertEqual(seen, [('MERGED', 'AUTHORED')])


class SourceHygieneTests(unittest.TestCase):
    NETFLIX = ('1\n00:00:10,000 --> 00:00:12,000\n<c.white><c.mono_sans>We\'re open.</c.mono_sans></c.white>\n\n'
               '2\n00:00:10,000 --> 00:00:12,000\n<c.white><c.mono_sans>Everything\'s half off.</c.mono_sans></c.white>\n\n'
               '3\n00:00:13,000 --> 00:00:14,000\nWe have contact.\n')

    def test_same_time_pairs_become_one_caption(self):
        out = srt.merge_same_time_cues(srt.strip_vtt_class_tags(self.NETFLIX))
        self.assertEqual(srt.parse_blocks(out), [
            "1\n00:00:10,000 --> 00:00:12,000\nWe're open.\nEverything's half off.",
            '2\n00:00:13,000 --> 00:00:14,000\nWe have contact.'])

    def test_ordinary_subtitles_are_untouched(self):
        plain = ('1\n00:00:01,000 --> 00:00:02,000\n<i>Hello</i>\n\n'
                 '2\n00:00:03,000 --> 00:00:04,000\nThere\n')
        self.assertIs(srt.merge_same_time_cues(plain), plain)
        self.assertIs(srt.strip_vtt_class_tags(plain), plain)

    def test_merge_caps_the_lines_per_caption(self):
        same = '\n\n'.join('%d\n00:00:01,000 --> 00:00:02,000\nline %d' % (n, n) for n in range(1, 6))
        blocks = srt.parse_blocks(srt.merge_same_time_cues(same))
        self.assertEqual([len(b.split('\n')) - 2 for b in blocks], [3, 2])

    def test_model_notes_never_reach_the_screen(self):
        self.assertEqual(srt.drop_model_notes(block(20, 'דברים שתלמד עלי\n(Walter speaking to Walter Jr., male addressee)')),
                         block(20, 'דברים שתלמד עלי'))
        kept = block(1, 'אני הולך\nMale nurse!')
        self.assertEqual(srt.drop_model_notes(kept), kept)
        lone = block(2, '(Speaker: John)')
        self.assertEqual(srt.drop_model_notes(lone), lone)



class CastTests(unittest.TestCase):
    def test_episode_guest_stars_follow_the_regulars(self):
        tmdb = _load('tmdb_helper')
        credits = {'cast': [{'id': 1, 'name': 'A', 'character': 'Lorelai', 'gender': 1, 'order': 0}],
                   'guest_stars': [{'id': 2, 'name': 'B', 'character': 'Dean', 'gender': 2, 'order': 0},
                                   {'id': 1, 'name': 'A', 'character': 'Lorelai', 'gender': 1, 'order': 1}]}
        tmdb._get_tmdb_key = lambda: 'k'
        tmdb._get = lambda url, params, timeout=15: credits
        cast = tmdb.fetch_cast(tmdb_id='1', media_type='tv', season='1', episode='1')
        self.assertEqual([(c['character'], c['gender']) for c in cast],
                         [('Lorelai', 'female'), ('Dean', 'male')])

    def test_people_who_share_a_character_name_are_kept(self):
        # Talk and reality shows: everybody is "Self" (review finding).
        tmdb = _load('tmdb_helper')
        credits = {'cast': [{'id': 1, 'name': 'A', 'character': 'Self', 'gender': 1, 'order': 0},
                            {'id': 2, 'name': 'B', 'character': 'Self', 'gender': 2, 'order': 1}],
                   'guest_stars': [{'id': 2, 'name': 'B', 'character': 'Self', 'gender': 2, 'order': 0}]}
        tmdb._get_tmdb_key = lambda: 'k'
        tmdb._get = lambda url, params, timeout=15: credits
        cast = tmdb.fetch_cast(tmdb_id='1', media_type='tv', season='1', episode='1')
        self.assertEqual([c['gender'] for c in cast], ['female', 'male'])


class WiringTests(unittest.TestCase):
    def test_translate_uses_the_new_checks(self):
        self.maxDiff = 200
        text = (LIB / 'translate.py').read_text(encoding='utf-8')
        self.assertIn('arabic_gender.person_gender_conflicts(', text)
        self.assertIn('arabic_gender.person_roles_fixed(', text)
        self.assertIn("_ar_map.get(num) if _ref_lang == 'he' else None", text)
        self.assertIn('raw_src = srt.strip_vtt_class_tags(raw_src)', text)
        self.assertIn('raw_src = srt.merge_same_time_cues(raw_src)', text)
        self.assertIn('srt.drop_model_notes(b) for b in out_blocks', text)
        self.assertIn('_timing_src = _prepare_source(src_text, merge=False)', text)
        self.assertIn('info, src_text, timing_text=_timing_src)', text)
        self.assertIn('srt.fold_stray_latin_letter(final)', text)
        self.assertIn('srt.drop_untranslated_sound_cues(final, src_text)', text)
        self.assertIn('script_residual.repair(', text)
        # a chunk that passes on the fallback reference is topped up too
        alt = text.index('passed with fallback reference')
        self.assertIn('_top_up_missing(', text[alt:alt + 600])


if __name__ == '__main__':
    unittest.main()
