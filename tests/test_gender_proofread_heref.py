"""No gender proofread after a Hebrew gender reference (0.3.72).

Two blind studies on the same eight TV episodes (4 Nov 2026): with a Hebrew
subtitle as the gender reference the proofread broke more lines than it fixed
(15 to 12); with an Arabic one it fixed 21 and broke 7. A translation made here
records its reference beside it (.gpref); one of unknown origin (pooled, or
made before 0.3.72) that was made with a reference (a pooled "_ar" variant, an
".ar" tier file) counts as Hebrew-referenced when the title's last search found
a human Hebrew subtitle; a plain one had no reference at all.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
TRANSLATE_SRC = (ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8')


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import (arabic_gender, cache,  # noqa: F401
                                       subs_engine_bridge, translate)
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return translate, cache, subs_engine_bridge, mods


translate, cache, bridge, MODS = _load()

HE = '1\n00:00:01,000 --> 00:00:02,000\nאתה בא?\n'
EN = '1\n00:00:01,000 --> 00:00:02,000\nAre you coming?\n'
INFO = {'imdb_id': 'tt1', 'title': 'T', 'year': '2020'}
HUMAN_HE = {'language': 'Hebrew', '_engine_kind': 'human_he', 'filename': 'T.2020.srt'}
ENGLISH = {'language': 'English', 'filename': 'T.2020.srt'}


class HebrewReference(unittest.TestCase):

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'tt1.he.srt')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(HE)
        settings = {'api_key': 'k'}
        for target, value in (
                ('get_setting', lambda k, d='': settings.get(k, d)),
                ('get_bool', lambda k, d=False: True),
                ('log', lambda *a, **k: None),
                ('cache_dir', lambda: self.dir)):
            p = mock.patch.object(translate.kodi_utils, target, value)
            p.start()
            self.addCleanup(p.stop)
        for target, value in (('_gp_models_left', lambda: True),
                              ('_is_google_translated', lambda p: False)):
            p = mock.patch.object(translate, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.listed = []
        p = mock.patch.object(bridge, 'reusable_results', lambda info: list(self.listed))
        p.start()
        self.addCleanup(p.stop)

    def due(self, info=INFO):
        return translate._proofread_due(self.path, EN, object(), info=info)

    def test_made_here_with_a_hebrew_reference_is_not_due(self):
        translate._gp_ref_mark(self.path, 'he')
        self.assertFalse(self.due())

    def test_made_here_with_another_reference_or_none_is_due(self):
        for lang in ('ar', 'hi', ''):
            translate._gp_ref_mark(self.path, lang)
            self.assertTrue(self.due(), lang)
        with open(self.path + '.gpref', encoding='utf-8') as f:
            self.assertEqual(f.read(), '-')

    def test_its_own_record_wins_over_the_search(self):
        # an Arabic reference while a Hebrew subtitle was listed (it did not
        # align): the proofread runs
        self.listed = [HUMAN_HE]
        translate._gp_ref_mark(self.path, 'ar')
        self.assertTrue(self.due())

    def test_unknown_origin_goes_by_the_titles_search(self):
        self.listed = [ENGLISH]
        self.assertTrue(self.due())
        self.listed = [ENGLISH, HUMAN_HE]
        self.assertFalse(self.due())

    def test_a_machine_hebrew_subtitle_is_not_a_reference(self):
        self.listed = [dict(HUMAN_HE, _engine_kind='mt_he'), dict(HUMAN_HE, _is_mt=True)]
        self.assertTrue(self.due())

    def test_without_the_title_unknown_stays_due(self):
        # a plain (no-reference) translation of unknown origin: its callers
        # pass no title, and a Hebrew subtitle in the list changes nothing
        self.listed = [HUMAN_HE]
        self.assertTrue(self.due(info=None))

    def test_which_unknown_ones_were_made_with_a_reference(self):
        tier = translate._gp_ref_tier
        self.assertTrue(tier('/c/pool_x.source.srt', 'abc_ar'))
        self.assertFalse(tier('/c/pool_x.source.srt', 'abc'))
        self.assertTrue(tier('/c/tt1_S1E1_en_abc.ar.he.srt'))
        self.assertFalse(tier('/c/tt1_S1E1_en_abc.he.srt'))
        # the pooled hash decides over the slot it was saved in
        self.assertFalse(tier('/c/tt1_S1E1_en_abc.ar.he.srt', 'abc'))

    def test_a_reference_of_unknown_language_asks_the_search(self):
        # a pooled "_ar" variant saved in the plain slot (reference setting
        # off): every later open still knows it had a reference
        plain = os.path.join(self.dir, 'tt1_S1E1_en_abc.he.srt')
        with open(plain, 'w', encoding='utf-8') as f:
            f.write(HE)
        self.assertFalse(translate._gp_ref_tier(plain))
        translate._gp_ref_mark(plain, '?')
        self.assertTrue(translate._gp_ref_tier(plain))
        self.listed = [HUMAN_HE]
        self.assertTrue(translate._gp_hebrew_ref(plain, INFO))
        self.listed = [ENGLISH]
        self.assertFalse(translate._gp_hebrew_ref(plain, INFO))
        self.assertFalse(translate._gp_hebrew_ref(plain, None))

    def test_an_unknown_marker_is_removed(self):
        translate._gp_ref_mark(self.path, 'he')
        translate._gp_ref_mark(self.path, None)
        self.assertFalse(os.path.exists(self.path + '.gpref'))
        translate._gp_ref_mark(self.path, None)      # none there: no error

    def test_the_marker_ages_with_its_translation(self):
        self.assertEqual(cache._sidecar_parent(self.path + '.gpref'), self.path)


class FreshTranslation(unittest.TestCase):
    """resolve(): the saved translation records its reference, and the
    proofread on the live path skips a Hebrew one."""

    def test_the_reference_is_recorded_beside_both_slots(self):
        save = TRANSLATE_SRC.index('    cache.save_text(translated, final)\n')
        after = TRANSLATE_SRC[save:save + 1400]
        self.assertIn("_gp_ref = _ref_lang if (_ar_on and _used_ar) else ''", after)
        self.assertIn('_gp_ref_mark(translated, _gp_ref)', after)
        self.assertIn('_gp_ref_mark(_content_slot, _gp_ref)', after)

    def test_the_live_proofread_skips_a_hebrew_reference(self):
        self.assertIn("if (progressive_cb is not None and _gp_ref != 'he'\n"
                      "            and kodi_utils.get_bool('gender_proofread', True)):",
                      TRANSLATE_SRC.replace('\r\n', '\n'))

    def test_telemetry_says_why(self):
        src = TRANSLATE_SRC.replace('\r\n', '\n')
        note = src.index('def _gp_event_note(')
        self.assertIn("if _gp_ref == 'he':\n                return 'heref'",
                      src[note:note + 1200])

    def test_every_opened_translation_check_gets_the_title_when_it_had_a_reference(self):
        src = TRANSLATE_SRC.replace('\r\n', '\n')
        calls = [src[i:i + 200] for i in range(len(src)) if src.startswith('_proofread_due(', i)
                 and not src.startswith('_proofread_due(path, source_text, progressive_cb, marker', i)]
        self.assertEqual(len(calls), 3)
        self.assertEqual(sum('info=_gp_info' in c for c in calls), 2)       # the pooled pick
        self.assertEqual(sum('info=(info if _gp_ref_tier(path, pooled_hash)' in c
                             for c in calls), 1)                            # cached / pool reuse
        self.assertIn('_gp_info = info if _gp_ref_tier(_praw, _phash) else None', src)

    def test_a_reused_pool_variant_and_a_discarded_file_leave_no_stale_marker(self):
        src = TRANSLATE_SRC.replace('\r\n', '\n')
        reuse = src.index('                cache.save_text(translated, pooled)\n')
        self.assertIn("_gp_ref_mark(translated, '?' if _pooled_ar else '')", src[reuse:reuse + 300])
        for slot in ('translated', 'translated_by_content'):
            i = src.index('                os.remove(%s)\n            except OSError:\n'
                          '                pass\n' % slot)
            self.assertIn('_gp_ref_mark(%s, None)' % slot, src[i:i + 200])


if __name__ == '__main__':
    unittest.main()
