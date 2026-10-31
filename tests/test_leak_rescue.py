"""Cached and pooled translations lose the model's working on the way in.

Field report (update 756): a translation shared before the leak check knew
every shape carried "... Let's use: ..." and drafts side by side in some cues,
and a cache or pool hit served it as it was. Each read now replaces such a
cue with the model's own answer in it (it knew the speaker's gender), Google's
Hebrew for its source line only when it wrote no Hebrew answer, and the pool
takes no file that carries it.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
MARKS = chr(0x202b) + chr(0x202c)   # the rtl_base wrap (RLE, PDF)


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import google_translate, translate  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return translate, mods


def block(n, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n * 3, n * 3 + 1, text)


def srt_text(*texts):
    return '\n\n'.join(block(i, t) for i, t in enumerate(texts, 1)) + '\n'


SOURCE = srt_text('Thanks for coming.', 'Manfredi was born lucky.', 'Goodbye.',
                  'Thanks for coming.')
LEAKY = srt_text(
    'תודה שבאשת. / תודה שבאשת... wait, "Thanks for coming." Let\'s check '
    'Spanish ref: "Gracias por venir." Let\'s use: תודה שבאת.',
    'מנפרדי נולד בר מזל. / מנפרדי נולד עם מזל. Let\'s use: מנפרדי נולד בר מזל.',
    '-להתראות.',
    '(Wait, "שבאת" is female) Let\'s check Spanish ref: "Gracias por venir."')
CLEAN = ['תודה שבאת.', 'מנפרדי נולד בר מזל.', '-להתראות.']


class LeakRescue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tr, cls.mods = _load()

    def setUp(self):
        patcher = mock.patch.dict(sys.modules, self.mods)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.gt = self.mods['resources.lib.google_translate']
        self.asked = []

    def google(self, answer):
        def translate_lines(lines, src_lang='auto', timeout=30):
            self.asked.append((tuple(lines), src_lang, timeout))
            if isinstance(answer, Exception):
                raise answer
            return answer
        return mock.patch.object(self.gt, 'translate_lines', side_effect=translate_lines)

    def texts(self, text):
        srt = self.tr.srt
        return [srt.block_text_only(b).strip(MARKS) for b in srt.parse_blocks(text)]

    def test_the_models_own_answer_comes_first(self):
        # it knew the speaker's gender; Google only for a cue with no Hebrew answer
        with self.google(['תודה שבאתם.']):
            text, n = self.tr._rescue_reasoning_leaks(LEAKY, SOURCE, 'en')
        self.assertEqual(n, 3)
        self.assertEqual(self.texts(text), CLEAN + ['תודה שבאתם.'])
        self.assertEqual(self.asked, [(('Thanks for coming.',), 'en', 4)])

    def test_without_a_hebrew_google_answer_the_source_line_stays(self):
        for answer in (None, ['Thanks for coming.'], OSError('offline')):
            with self.google(answer):
                text, n = self.tr._rescue_reasoning_leaks(LEAKY, SOURCE, 'en')
            self.assertEqual((n, self.texts(text)[3]), (3, 'Thanks for coming.'))
        self.asked[:] = []
        with self.google(AssertionError('no source line, no request')):
            text, n = self.tr._rescue_reasoning_leaks(LEAKY, None, 'en')
        # no source line for the cue with no answer: left for a later read
        self.assertEqual((n, self.asked), (2, []))
        self.assertEqual(self.texts(text)[:3], CLEAN)

    def test_google_never_waits_past_the_budget(self):
        with self.google(['תודה.']):
            self.assertIsNone(self.tr._google_lines(['Thanks.'], 'en', 0))
            self.assertEqual(self.asked, [])
            import time
            self.assertEqual(self.tr._google_lines(['A.', 'B.'], 'en', time.monotonic() + 2.5),
                             ['תודה.', 'תודה.'])
        self.assertTrue(all(0 < a[2] <= 2.5 for a in self.asked))

    def test_the_cue_keeps_its_position_and_italics(self):
        text = srt_text('{\\an8}<i>מנפרדי נולד בר מזל. / מנפרדי נולד עם מזל.</i>')
        with self.google(AssertionError('the model answered')):
            fixed, n = self.tr._rescue_reasoning_leaks(
                text, srt_text('Manfredi was born lucky.'), 'en')
        self.assertEqual(n, 1)
        self.assertIn('{\\an8}<i>מנפרדי נולד בר מזל.</i>', fixed)

    def test_a_cue_missing_from_the_source_needs_a_strong_sign(self):
        # review round 2: the source file is there, this cue's start is not
        text = srt_text('קוראים לו Singular Value.', "תודה שבאת. Let's use: תודה שבאתם.")
        source = '1\n00:00:50,000 --> 00:00:51,000\nUnrelated.\n'
        with self.google(None):
            fixed, n = self.tr._rescue_reasoning_leaks(text, source, 'en')
        self.assertEqual(n, 1)
        self.assertEqual(self.texts(fixed), ['קוראים לו Singular Value.', 'תודה שבאתם.'])

    def test_a_clean_file_reads_no_source(self):
        clean = srt_text(*CLEAN)
        source = mock.Mock(side_effect=AssertionError('source read'))
        self.assertEqual(self.tr._rescue_reasoning_leaks(clean, source, 'en'), (clean, 0))

    def test_dialogue_the_source_says_is_kept(self):
        source = srt_text('He wrote "Let\'s check" on the wall.')
        text = srt_text('הוא כתב "Let\'s check" על הקיר.')
        loader = mock.Mock(return_value=source)
        self.assertEqual(self.tr._rescue_reasoning_leaks(text, loader, 'en'), (text, 0))
        loader.assert_called_once_with()

    def test_cache_read_repairs_the_file_and_the_pool_refuses_it(self):
        self.assertFalse(self.tr._pool_quality_ok(SOURCE, LEAKY))
        self.assertTrue(self.tr._pool_quality_ok(SOURCE, srt_text(*(CLEAN + ['תודה שבאת.']))))
        ku = self.mods['resources.lib.kodi_utils']
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'tt1.he.srt')
            src_path = os.path.join(tmp, 'tt1.en.srt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(LEAKY)
            with open(src_path, 'w', encoding='utf-8') as f:
                f.write(SOURCE)
            with self.google(['תודה שבאתם.']), \
                    mock.patch.object(ku, 'get_setting', return_value='rtl_base'):
                self.tr._reapply_rtl_fix_in_place(
                    path, source=self.tr._prepared_source_reader(src_path),
                    source_lang='en')
            with open(path, encoding='utf-8') as f:
                fixed = f.read()
            self.assertNotIn("Let's", fixed)
            self.assertEqual(self.texts(fixed), CLEAN + ['תודה שבאתם.'])
            # a Google Translate file is not ours to judge: left as it is
            with open(path, 'w', encoding='utf-8') as f:
                f.write(LEAKY)
            open(path + '.google', 'w').close()
            with self.google(AssertionError('google file judged')), \
                    mock.patch.object(ku, 'get_setting', return_value='rtl_base'):
                self.tr._reapply_rtl_fix_in_place(path, source=SOURCE, source_lang='en')
            with open(path, encoding='utf-8') as f:
                self.assertIn("Let's use", f.read())

    def test_every_read_passes_its_source(self):
        src = (ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8')
        self.assertIn('_reapply_rtl_fix_in_place(\n                translated, source_lang=source_lang,\n'
                      '                source=(_prepared_source_reader(local_source)',
                      src.replace('\r\n', '\n'))
        self.assertEqual(src.count('source=src_text'), 2)


if __name__ == '__main__':
    unittest.main()
