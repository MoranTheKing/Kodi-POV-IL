"""A pooled EMBEDDED translation gets its gender proofread too (0.3.65).

The proofread of a pooled translation needs the subtitle it was translated
from, and looked for it under the pool row's release and content hash. An
embedded translation (pool kind ai_emb) carries the video's release, and its
source is either the video's own text track, extracted, or an external
subtitle retimed onto that track's cue times ("embedded timing"). Neither
was ever found, so none was proofread after the device that made it (field
data, 1-2 Nov 2026: 3 of 8 embedded translations proofread, none later). The
device that made one keeps its source under that hash; any other finds an
external subtitle that lays onto the Hebrew's own cue times.
"""
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
LIB = ADDON / 'resources' / 'lib'


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import release_match, subsync, sync_align, translate  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return translate, mods


translate, MODS = _load()


def stamp(ms):
    ms = max(0, int(round(ms)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return '%02d:%02d:%02d,%03d' % (h, m, s, ms)


def cues(seed, count=300):
    rng = random.Random(seed)
    clock, out = 15000, []
    for _ in range(count):
        clock += rng.randint(1800, 5200)
        out.append((clock, clock + rng.randint(900, 3000)))
    return out


def srt(timed, texts):
    return '\n\n'.join('%d\n%s --> %s\n%s' % (i, stamp(a), stamp(b), t)
                       for i, ((a, b), t) in enumerate(zip(timed, texts), 1)) + '\n'


WORDS = ('Where are you going', 'I told you so', 'Come back here',
         'She is not coming', 'We need to talk', 'Leave him alone')
BASE = cues(4242)
TEXTS = ['%s, %d.' % (WORDS[i % len(WORDS)], i) for i in range(len(BASE))]
ENGLISH = srt(BASE, TEXTS)
# embedded timing: the same subtitle on the video's own clock (PAL speed-up
# and an offset), which the Hebrew inherits cue for cue
K, OFF = 25 / 23.976, 3500
EMBEDDED_TIMED = srt([(a / K + OFF, b / K + OFF) for a, b in BASE], TEXTS)
HEBREW = srt([(a / K + OFF, b / K + OFF) for a, b in BASE],
             ['שורה בעברית %d' % i for i in range(len(BASE))])
OTHER = srt(cues(777), TEXTS)            # same lines, another subtitle's cues


class Base(unittest.TestCase):

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.dir = tempfile.mkdtemp()
        for target, value in (('cache_dir', lambda: self.dir),
                              ('log', lambda *a, **k: None)):
            p = mock.patch.object(translate.kodi_utils, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.he = os.path.join(self.dir, 'pool_x.source.srt')
        with open(self.he, 'w', encoding='utf-8') as f:
            f.write(HEBREW)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path


class Laid(Base):

    def test_the_subtitle_it_was_made_from_lays_on_the_hebrew_cues(self):
        laid = translate._emb_source_laid(HEBREW, ENGLISH)
        self.assertTrue(laid)
        blocks = translate.srt.parse_blocks(HEBREW)
        pairs = translate.srt.aligned_source_texts(translate.srt.parse_blocks(laid), blocks)
        right = sum(1 for i, t in enumerate(pairs) if t == TEXTS[i])
        self.assertGreaterEqual(right, 0.97 * len(blocks))

    def test_another_subtitle_does_not(self):
        self.assertEqual(translate._emb_source_laid(HEBREW, OTHER), '')
        self.assertEqual(translate._emb_source_laid(HEBREW, srt(cues(9), TEXTS[:120])), '')


class Pick(Base):

    def bridge(self, rows):
        fake = mock.MagicMock()
        fake.reusable_results.return_value = rows
        paths = {}

        def download(p, for_delivery=True):
            return paths.get(p.get('filename'))
        fake.download.side_effect = download
        return fake, paths

    def run_pick(self, fake, h):
        with mock.patch.dict(sys.modules, {'resources.lib.subs_engine_bridge': fake}), \
                mock.patch.object(sys.modules['resources.lib'], 'subs_engine_bridge', fake,
                                  create=True), \
                mock.patch.object(MODS['resources.lib.subsync'], 'playing_release',
                                  lambda info: 'Show.S01E01.1080p.WEB-DL'):
            return translate._pool_pick_emb_source({}, h, 'en', self.he)

    def row(self, name, lang='en', kind='other'):
        return {'language': lang, '_engine_kind': kind,
                'link': translate._encode_link({'type': 'engine', 'filename': name})}

    def test_the_device_that_made_it_has_its_source(self):
        emb = self.write('embedded_aligned_en.srt', EMBEDDED_TIMED)
        translate._keep_embedded_source(emb)
        h = translate._content_hash(translate._prepare_source(EMBEDDED_TIMED))
        fake, _paths = self.bridge([])
        self.assertEqual(self.run_pick(fake, h), translate._prepare_source(EMBEDDED_TIMED))
        self.assertEqual(self.run_pick(fake, h + '_ar'), translate._prepare_source(EMBEDDED_TIMED))
        fake.reusable_results.assert_not_called()

    def test_another_device_finds_the_external_subtitle(self):
        fake, paths = self.bridge([self.row('Show.S01E01.720p.HDTV', lang='es'),
                                   self.row('Show.S01E01.HDTV-OTHER'),
                                   self.row('Show.S01E01.1080p.WEB-DL-RIGHT'),
                                   self.row('Hebrew', lang='he', kind='human_he')])
        paths['Show.S01E01.HDTV-OTHER'] = self.write('other.srt', OTHER)
        paths['Show.S01E01.1080p.WEB-DL-RIGHT'] = self.write('right.srt', ENGLISH)
        laid = self.run_pick(fake, 'f' * 16)
        self.assertTrue(laid)
        pairs = translate.srt.aligned_source_texts(
            translate.srt.parse_blocks(laid), translate.srt.parse_blocks(HEBREW))
        self.assertGreaterEqual(sum(1 for i, t in enumerate(pairs) if t == TEXTS[i]),
                                0.97 * len(TEXTS))
        fake.search.assert_not_called()                              # never a new search
        names = [c[0][0].get('filename') for c in fake.download.call_args_list]
        self.assertEqual(names, ['Show.S01E01.1080p.WEB-DL-RIGHT'])  # best release first

    def test_none_that_lays_on_is_not_there(self):
        fake, paths = self.bridge([self.row('A'), self.row('B')])
        paths['A'] = self.write('a.srt', OTHER)
        paths['B'] = self.write('b.srt', srt(cues(31), TEXTS))
        self.assertEqual(self.run_pick(fake, 'f' * 16), '')
        # nothing searched lately, or the look failed: again another time,
        # not a week's pause
        fake.reusable_results.return_value = []
        self.assertIsNone(self.run_pick(fake, 'f' * 16))
        fake.reusable_results.side_effect = OSError('engine')
        self.assertIsNone(self.run_pick(fake, 'f' * 16))

    def test_downloads_that_fail_are_no_look(self):
        # review of 0.3.65: a provider down is not "looked, not there"
        fake, paths = self.bridge([self.row('A'), self.row('B')])
        self.assertIsNone(self.run_pick(fake, 'f' * 16))
        self.assertEqual(fake.download.call_count, 2)
        fake, paths = self.bridge([])
        self.assertIsNone(self.run_pick(fake, 'f' * 16))           # nothing searched
        fake, paths = self.bridge([self.row('A', lang='es')])
        self.assertEqual(self.run_pick(fake, 'f' * 16), '')       # none in its language
        # one came through and did not lay on, the other did not come
        # through: that one may be the source -- looked for again after the
        # in-progress pause, not at every pick (0.3.66)
        fake, paths = self.bridge([self.row('A'), self.row('B')])
        paths['A'] = self.write('a2.srt', OTHER)
        self.assertIs(self.run_pick(fake, 'f' * 16), False)

    def test_a_partial_look_keeps_the_pause(self):
        src = (LIB / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        branch = src[src.index('                # held through the look'):]
        branch = branch[:branch.index('return _proofread_opened(')]
        partial = branch.index('                if _psource is False:\n'
                               '                    return None')
        self.assertLess(partial, branch.index('                if _psource is None:\n'
                                              '                    _gp_try_mark(_gp_base, False)'))

    def test_as_far_down_the_list_as_the_embedded_path_went(self):
        rows = [self.row('Show.S01E01.%d' % i) for i in range(12)]
        fake, paths = self.bridge(rows)
        for i in range(12):
            paths['Show.S01E01.%d' % i] = self.write('c%d.srt' % i, OTHER if i != 6 else ENGLISH)
        with mock.patch.object(MODS['resources.lib.release_match'], 'match_pct',
                               lambda a, b: 100 - int(b.rsplit('.', 1)[1])):
            self.assertTrue(self.run_pick(fake, 'f' * 16))      # the seventh
        paths['Show.S01E01.6'] = paths['Show.S01E01.0']
        fake.download.reset_mock()
        with mock.patch.object(MODS['resources.lib.release_match'], 'match_pct',
                               lambda a, b: 100 - int(b.rsplit('.', 1)[1])):
            self.assertEqual(self.run_pick(fake, 'f' * 16), '')
        self.assertEqual(fake.download.call_count, translate._EMB_SRC_TRIES)


class Wiring(unittest.TestCase):

    def test_kept_when_made_and_looked_for_its_own_way(self):
        src = (LIB / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        emb = src[src.index("    if kind == 'embedded_ai':"):src.index("    if kind == 'engine_ai':")]
        self.assertLess(emb.index("deferring to the external path"),
                        emb.index('_keep_embedded_source(emb_path)'))
        self.assertLess(emb.index('_keep_embedded_source(emb_path)'),
                        emb.index("payload = {'type': 'ai',"))
        self.assertIn("                if _pkind == 'ai_emb':\n"
                      "                    _psource = _pool_pick_emb_source(info, _phash, _psrc, _praw)\n"
                      "                else:\n"
                      "                    _psource = _pool_pick_source(info, _phash,", src)


if __name__ == '__main__':
    unittest.main()
