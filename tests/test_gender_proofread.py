"""One stronger-model request proofreads a translation's gender and number
(gender_proofread.py).

Field report (31 Oct 2026, "Blue"): about one in seven gendered lines was
wrong, and the film had no Arabic or Hebrew subtitle to mark it. One
gemini-3.8-flash request over the whole film proposed 35 corrections; a blind
judge found 34 right and 1 wrong. A correction is applied only when it
changes nothing but gendered/numbered word forms.
"""
import importlib.util
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
spec = importlib.util.spec_from_file_location('gender_proofread', LIB / 'gender_proofread.py')
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)
RLE, PDF = chr(0x202b), chr(0x202c)


class Inflections(unittest.TestCase):

    def test_gender_and_number_forms_are_inflections(self):
        for a, b in (('אתה', 'את'), ('צריך', 'צריכה'), ('תעזור', 'תעזרי'),
                     ('חייבות', 'חייבים'), ('הולך', 'הולכת'), ('שתינו', 'שנינו'),
                     ('הוא', 'היא'), ('ואתה', 'ואת'), ('תן', 'תני'), ('לכי', 'לך'),
                     ('תזדייני', 'תזדיין'), ('מצטער', 'מצטערת'), ('בוא', 'בואו'),
                     ('לו', 'לה'), ('מוכן', 'מוכנה'), ('היה', 'הייתה'), ('יבוא', 'תבוא'),
                     ('ממנו', 'ממנה'), ('לכם', 'לכן'), ('נכון', 'נכונה')):
            self.assertTrue(gp.inflection_of(a, b), (a, b))

    def test_other_words_are_not(self):
        # review of 0.3.58: a stem rule alone read these as one word inflected
        for a, b in (('הולך', 'בא'), ('אבא', 'אמא'), ('כן', 'לא'), ('הביתה', 'לעבודה'),
                     ('אין', 'אני'), ('אל', 'אלי'), ('כל', 'כלה'), ('שיר', 'שר'),
                     ('יום', 'ים'), ('עוד', 'עד'), ('איש', 'אש'),
                     # under a prefix letter, and a change of person (round 2)
                     ('ואין', 'ואני'), ('כשאין', 'כשאני'), ('וכל', 'וכלה'), ('ומה', 'ומי'),
                     ('אמרתי', 'אמרת'), ('שלי', 'שלו'), ('אותי', 'אותו'), ('ממני', 'ממנו')):
            self.assertFalse(gp.inflection_of(a, b), (a, b))
        # a verb that only looks like ש + a word that never changes
        self.assertTrue(gp.inflection_of('שאל', 'שאלה'))
        self.assertTrue(gp.inflection_of('מלא', 'מלאה'))


class ApplyCorrection(unittest.TestCase):

    def test_the_gendered_words_change_and_nothing_else(self):
        self.assertEqual(gp.apply_correction('.אני מצטער, אבא\n.הייתי צריך לספר לך',
                                             '.אני מצטערת, אבא / .הייתי צריכה לספר לך'),
                         '.אני מצטערת, אבא\n.הייתי צריכה לספר לך')
        # tags and direction marks of the original line stay where they were
        self.assertEqual(gp.apply_correction('<i>' + RLE + 'אתה בא?' + PDF + '</i>', 'את באה?'),
                         '<i>' + RLE + 'את באה?' + PDF + '</i>')

    def test_anything_more_is_refused(self):
        for old, new in (('.אני הולך הביתה', '.אני הולכת לעבודה'),   # another word
                         ('.תודה שבאת', '.תודה שבאת!'),               # punctuation
                         ('שלום', 'שלום עליכם'),                       # a word added
                         ('אתה בא?\nכן', 'את באה? כן'),              # the line break
                         ('אתה בא?', 'אתה בא?'),                       # unchanged
                         ('אתה  בא?', 'אתה בא?'),                      # only a space
                         ('ראיתי את הילד', 'ראיתי אתה הילד'),         # the object marker
                         ('ואת הילד', 'ואתה הילד'),
                         ('אני רוצה את זה', 'אני רוצה אתה זה'),
                         ('אין לי כסף', 'אני לי כסף')):                # a negation
            self.assertIsNone(gp.apply_correction(old, new), new)
        # "you" with a verb that changes along is not the object marker
        self.assertEqual(gp.apply_correction('את הולכת?', 'אתה הולך?'), 'אתה הולך?')
        self.assertEqual(gp.apply_correction('את בסדר?', 'אתה בסדר?'), 'אתה בסדר?')
        self.assertEqual(gp.apply_correction('את הכי טובה', 'אתה הכי טוב'), 'אתה הכי טוב')
        # one person or several
        self.assertEqual(gp.apply_correction('אתה בא איתי? תגיד לך', 'אתם באים איתי? תגידו לכם'),
                         'אתם באים איתי? תגידו לכם')


class Proofread(unittest.TestCase):
    SOURCES = ["I'm sorry, Dad.", 'Do you love me?', 'Bye.']
    TEXTS = ['.אני מצטער, אבא', '?את אוהבת אותי', '.ביי']

    def test_falls_through_models_that_cannot_answer(self):
        asked = []

        def request(model, prompt):
            asked.append(model)
            if model != 'gemini-3.6-flash':
                raise gp.Skip(model)
            self.assertIn("1 | SOURCE: I'm sorry, Dad. | HE: .אני מצטער, אבא", prompt)
            self.assertIn('- Luce (female)', prompt)
            return ('1|.אני מצטערת, אבא\n2|?אתה אוהב אותי\n'
                    '3|.להתראות\nnot a line\n9|.מחוץ לטווח')
        out, report = gp.proofread(self.SOURCES, self.TEXTS, request,
                                   cast=[('Luce', 'female'), ('Loris', 'male')])
        self.assertEqual(asked, ['gemini-3.7-flash', 'gemini-3.8-flash', 'gemini-3.6-flash'])
        self.assertEqual(out, ['.אני מצטערת, אבא', '?אתה אוהב אותי', '.ביי'])
        self.assertEqual((report['model'], report['proposed'], report['applied'], report['refused']),
                         ('gemini-3.6-flash', 3, 2, 1))

    def test_nothing_changes_without_an_answer(self):
        def skip(model, prompt):
            raise gp.Skip(model)

        def broken(model, prompt):
            raise ValueError('network')
        for request in (skip, broken):
            out, report = gp.proofread(self.SOURCES, self.TEXTS, request)
            self.assertEqual(out, self.TEXTS)
            self.assertEqual(report['applied'], 0)
        out, report = gp.proofread(self.SOURCES, self.TEXTS, skip, cancelled=lambda: True)
        self.assertEqual((out, report['tried']), (self.TEXTS, []))


class QuotaRecord(unittest.TestCase):

    def test_its_own_record_of_spent_models(self):
        class Settings(object):
            store = {}

            def get_setting(self, k, default=''):
                return self.store.get(k, default)

            def set_setting(self, k, v):
                self.store[k] = v
        s = Settings()
        self.assertFalse(gp.exhausted_today('gemini-3.8-flash', s))
        gp.note_exhausted('gemini-3.8-flash', s)
        gp.note_exhausted('gemini-3.7-flash', s)
        gp.note_exhausted('gemini-3.8-flash', s)
        self.assertTrue(gp.exhausted_today('gemini-3.8-flash', s))
        self.assertTrue(gp.exhausted_today('gemini-3.7-flash', s))
        self.assertFalse(gp.exhausted_today('gemini-3.6-flash', s))
        self.assertEqual(list(s.store), [gp.EXHAUSTED_SETTING])   # not the translator's
        s.store[gp.EXHAUSTED_SETTING] = '2000-01-01 gemini-3.6-flash'
        self.assertFalse(gp.exhausted_today('gemini-3.6-flash', s))


class Wiring(unittest.TestCase):

    def test_translate_runs_it_on_the_live_path_after_the_save(self):
        src = (LIB / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        # after the translation is saved: a stop or a crash in its minutes keeps
        # it; the corrected file goes out with 'done'
        save = src.index('    cache.save_text(translated, final)\n    _clear_google_marker(translated)')
        run = src.index("    if (progressive_cb is not None and _gp_ref != 'he'\n")
        self.assertLess(save, run)
        self.assertLess(src.index('_proofed = _proofread_gender(_proof_blocks)', run),
                        src.index("progressive_cb('done'", run))
        self.assertIn("'merged_text': final", src[run:run + 900])
        wrap = src[src.index('    def _proofread_gender(blocks):'):src.index('    final = srt.stitch_blocks(out_blocks)')]
        self.assertIn('_proofread_stopper(_progressive_source_id, _translation_cancelled)', wrap)
        call = src[src.index('def _run_gender_proofread'):src.index('def _title_cast')]
        # the usage figure counts it only when the model IS the translator's
        self.assertIn('count_usage=(proof_model == model)', call)
        self.assertIn('except gemini.GeminiError as e:', call)
        # a model that took the request is not followed by another (0.3.65)
        self.assertIn('raise gender_proofread.Spent(proof_model)', call)
        self.assertIn('gender_proofread.note_exhausted(proof_model, kodi_utils)', call)
        self.assertNotIn('gemini_quota.note_exhausted', call)
        gem = (LIB / 'gemini.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        self.assertIn('    if count_usage:\n        try:\n            from . import gemini_quota\n'
                      '            gemini_quota.note_request(model)', gem)
        settings = (LIB.parent / 'settings.xml').read_text(encoding='utf-8')
        self.assertIn('<setting id="gender_proofread" type="boolean" label="32556" help="32557">', settings)
        # marked when a model answered; the pool upload says it is proofread,
        # by which model and how many lines it fixed (0.3.60)
        self.assertIn("        if _gp_report.get('model'):\n"
                      "            # proofread: opening it again spends no request\n"
                      "            _gp_mark(translated, _gp_report)", src)
        self.assertIn("proofread=(_gp_stats(_gp_report) or False))", src)
        # the telemetry event names them too (0.3.61, the dashboard's Recent
        # activity): the report is set before _emit is defined, so an early
        # failure's emit reads an empty one
        emit_at = src.index('    def _emit(ok, note=\'\'):')
        self.assertEqual(src.count('    _gp_report = {}\n'), 1)
        self.assertLess(src.index('    _gp_report = {}\n'), emit_at)
        emit = src[emit_at:src.index('    if whole_subtitle_request:', emit_at)]
        self.assertIn("'gp_model': _gp_stats(_gp_report).get('model', ''),", emit)
        self.assertIn("'gp_fixed': _gp_stats(_gp_report).get('applied', 0)\n"
                      "                if _gp_report.get('model') else None,", emit)
        self.assertLess(src.index('_proofed = _proofread_gender(_proof_blocks)'),
                        src.index('    _emit(True)\n'))

    def test_opened_translations_get_it_once_and_never_a_translation(self):
        src = (LIB / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        res = src[src.index('def resolve('):]
        # the two cache hits and the pool reuse go through it
        self.assertEqual(res.count('_opened = _open_with_proofread('), 3)
        self.assertEqual(res.count('if _opened or _proofread_only:'), 2)
        # proofread_later's job never translates
        self.assertIn('    if _proofread_only:\n'
                      '        return None     # nothing cached to proofread; it never translates\n\n'
                      '    # No hit: settle on the early-source-id slot', res)
        self.assertIn("        if _proofread_only:\n            payload['proofread_only'] = True", res)
        # its job is quiet, and nothing corrected is no failure
        self.assertIn("    if _proofread_only:\n        set_quiet(True)", res)
        bg = (LIB.parents[1] / 'default.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        self.assertIn("    if not _resolved and not (translate._decode_link(link) or {}).get(\n"
                      "            'proofread_only'):", bg)
        # what launches it after a pick shown without a live preview
        for rel, needle in (('default.py', 'translate.proofread_later(link, _timing_selection)'),
                            ('resources/lib/subs_chooser.py', '_t.proofread_later(link, timing_selection)'),
                            ('resources/lib/autosub_service.py', 'translate.proofread_later(chosen_link, selection)')):
            self.assertIn(needle, (LIB.parents[1] / rel).read_text(encoding='utf-8'), rel)


if __name__ == '__main__':
    unittest.main()
