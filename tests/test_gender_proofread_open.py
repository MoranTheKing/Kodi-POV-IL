"""An older AI translation gets the gender proofread the first time it is
opened, and the pool takes the corrected file (translate.py, pool.py).

0.3.58 proofread fresh translations only; asked what happens to the ones made
before ("Blue" came from the pool), 0.3.59 proofreads a cached or pooled one
once when it is opened from the list, and a pooled pick or the automatic
translation on play -- shown with no live preview to swap into -- in a job of
its own that never translates. A pooled pick needs the subtitle it was
translated from: the engine's cached search has it under the same release,
and the pool's key is that subtitle's content hash.
"""
import base64
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import pool, translate  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return translate, pool, mods


translate, pool, MODS = _load()


def block(n, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n * 3, n * 3 + 1, text)


def srt_text(*texts):
    return '\n\n'.join(block(i, t) for i, t in enumerate(texts, 1)) + '\n'


HE = srt_text('אתה בא?', 'כן, אני מצטער.', 'תודה רבה לך.')
EN = srt_text('Are you coming?', "Yes, I'm sorry.", 'Thank you very much.')


class Base(unittest.TestCase):

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'tt1.he.srt')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(HE)
        settings = {'api_key': 'k', 'model': 'gemini-3.5-flash-lite'}
        for target, value in (
                ('get_setting', lambda k, d='': settings.get(k, d)),
                ('get_bool', lambda k, d=False: True),
                ('notify', lambda *a, **k: None),
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


class Due(Base):

    def test_once_from_the_list_for_an_ai_translation(self):
        due = translate._proofread_due
        cb = object()
        self.assertTrue(due(self.path, EN, cb))
        self.assertTrue(due(self.path, None, cb))        # before looking for a source
        self.assertFalse(due(self.path, '', cb))         # no source found
        self.assertFalse(due(self.path, EN, None))       # no live preview
        self.assertFalse(due(self.path, HE, cb))         # a Hebrew source passed through
        self.assertFalse(due(os.path.join(self.dir, 'none.srt'), EN, cb))
        translate._gp_mark(self.path)
        self.assertFalse(due(self.path, EN, cb))         # proofread before
        other = os.path.join(self.dir, 'marker')
        self.assertTrue(due(self.path, EN, cb, marker=other))
        with mock.patch.object(translate, '_gp_models_left', lambda: False):
            self.assertFalse(due(self.path, EN, cb, marker=other))
        with mock.patch.object(translate, '_is_google_translated', lambda p: True):
            self.assertFalse(due(self.path, EN, cb, marker=other))


class Opened(Base):

    def run_it(self, report, change=True, shown_already=False):
        phases, shared = [], []

        def fake_proofread(blocks, src, key, model, cast, stopped):
            self.assertEqual(model, 'gemini-3.5-flash-lite')
            if change:
                blocks = list(blocks)
                blocks[0] = blocks[0].replace('אתה בא?', 'את באה?')
            return blocks, report
        with mock.patch.object(translate, '_run_gender_proofread', fake_proofread), \
                mock.patch.object(translate, '_title_cast', lambda *a: ([], '', '')):
            out = translate._proofread_opened(
                self.path, EN, 'sid1', 'Rel', lambda ph, pl: phases.append((ph, pl)),
                lambda p: p, lambda: False, {'imdb_id': 'tt1'},
                share=shared.append, shown_already=shown_already)
        return out, phases, shared

    def test_on_screen_at_once_then_the_corrected_file(self):
        out, phases, shared = self.run_it({'model': 'gemini-3.7-flash', 'applied': 1})
        self.assertEqual([p for p, _ in phases], ['first_ready', 'chunk_ready', 'done'])
        self.assertEqual(phases[0][1]['fallback_text'], HE)
        self.assertEqual(phases[1][1]['merged_text'], HE)
        self.assertTrue(all(pl['source_id'] == 'sid1' for _, pl in phases))
        self.assertEqual(phases[2][1]['success'], True)
        self.assertEqual(phases[2][1]['path'], self.path)
        self.assertEqual(out, self.path)
        text = open(self.path, encoding='utf-8').read()
        self.assertIn('את באה?', text)
        self.assertTrue(translate._gp_done(self.path))
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0].split(), text.split())

    def test_no_model_answered(self):
        out, phases, shared = self.run_it({'model': ''}, change=False)
        self.assertEqual([p for p, _ in phases], ['first_ready', 'chunk_ready', 'done'])
        self.assertEqual(out, self.path)
        self.assertFalse(translate._gp_done(self.path))   # tried again next time
        self.assertEqual(shared, [])

    def test_nothing_to_fix_is_marked_and_still_told_to_the_pool(self):
        out, phases, shared = self.run_it({'model': 'gemini-3.7-flash'}, change=False)
        self.assertTrue(translate._gp_done(self.path))
        self.assertEqual(shared, [HE])                    # the worker marks it

    def test_never_without_its_source(self):
        # review of 0.3.59: a source look that failed must not become a proofread
        # of the Hebrew alone, uploaded to the pool as proofread
        def no_request(*a):
            raise AssertionError('a request without a source')
        shared, phases = [], []
        with mock.patch.object(translate, '_run_gender_proofread', no_request):
            for src in (None, ''):
                self.assertIsNone(translate._proofread_opened(
                    self.path, src, 'sid1', 'Rel', lambda ph, pl: phases.append(ph),
                    lambda p: p, lambda: False, {}, share=shared.append,
                    shown_already=True))
                self.assertEqual(translate._proofread_opened(
                    self.path, src, 'sid1', 'Rel', lambda ph, pl: phases.append(ph),
                    lambda p: p, lambda: False, {}, share=shared.append), self.path)
        self.assertEqual((shared, phases), ([], []))
        self.assertFalse(translate._gp_done(self.path))
        src = (ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8')
        self.assertIn("if _psource is None:\n                    return None", src.replace('\r\n', '\n'))

    def test_one_attempt_at_a_time_and_a_pause_after_no_answer(self):
        # review of 0.3.59: two opens in its minutes spent two requests, and an
        # overloaded model was asked again at every open
        with mock.patch.object(translate, '_proofread_stopper', lambda sid, c: (lambda: False)):
            self.run_it({'model': ''}, change=False)
        self.assertTrue(os.path.isfile(self.path + '.gp.try'))
        self.assertFalse(translate._proofread_due(self.path, EN, object()))
        os.utime(self.path + '.gp.try', (1, 1))           # six hours on
        self.assertTrue(translate._proofread_due(self.path, EN, object()))
        with mock.patch.object(translate, '_proofread_stopper', lambda sid, c: (lambda: False)):
            self.run_it({'model': 'gemini-3.7-flash'}, change=False)
        self.assertFalse(os.path.isfile(self.path + '.gp.try'))
        self.assertTrue(translate._gp_done(self.path))

    def test_shown_already_swaps_only_a_corrected_file(self):
        out, phases, shared = self.run_it({'model': 'gemini-3.7-flash'}, change=False,
                                          shown_already=True)
        self.assertIsNone(out)
        self.assertEqual([p for p, _ in phases], ['first_ready', 'done'])
        self.assertEqual(phases[-1][1]['success'], False)
        out, phases, shared = self.run_it({'model': 'gemini-3.8-flash', 'applied': 1},
                                          shown_already=True)
        self.assertEqual(out, self.path)
        self.assertEqual([p for p, _ in phases], ['first_ready', 'done'])
        self.assertEqual(phases[-1][1]['success'], True)


class Later(Base):

    def fired(self, link, selection=None):
        calls = []
        with mock.patch.object(sys.modules['xbmc'], 'executebuiltin', calls.append):
            translate.proofread_later(link, selection or {'token': 't', 'link_hash': 'l',
                                                          'stream_hash': 's', 'x': 'no'})
        return calls

    @staticmethod
    def args(call):
        inner = call[call.index('(') + 1:-1].split(',')
        out = dict(a.split('=', 1) for a in inner[1:])
        return dict((k, base64.b64decode(v).decode('utf-8')) for k, v in out.items()
                    if k.endswith('_b64'))

    def test_a_pooled_pick_gets_a_proofread_only_job(self):
        link = translate._encode_link({'type': 'pool', 'hash': 'abcdef0123456789',
                                       'release': 'Blue.2026', 'pool_kind': 'ai'})
        calls = self.fired(link)
        self.assertEqual(len(calls), 1)
        self.assertIn('action=bg_translate_picker', calls[0])
        a = self.args(calls[0])
        payload = json.loads(urllib.parse.unquote(a['link_b64']))
        self.assertEqual(payload['proofread_only'], True)
        self.assertEqual(payload['hash'], 'abcdef0123456789')
        self.assertEqual(a['source_id_b64'], 'pool_abcdef0123456789')
        self.assertEqual(json.loads(a['selection_b64']),
                         {'token': 't', 'link_hash': 'l', 'stream_hash': 's'})
        # the job's id is the one the pool branch sends its phases with
        self.assertEqual(translate._pool_job_id(translate._pool_gp_base('abcdef0123456789')),
                         'pool_abcdef0123456789')

    def test_when_none_is_due_nothing_starts(self):
        pooled = {'type': 'pool', 'hash': 'abcdef0123456789', 'pool_kind': 'ai'}
        self.assertEqual(self.fired(translate._encode_link(dict(pooled, pool_kind='ktuvit'))), [])
        self.assertEqual(self.fired(translate._encode_link(dict(pooled, proofread_only=True))), [])
        self.assertEqual(self.fired(translate._encode_link({'type': 'engine', 'filename': 'x'})), [])
        # its source not in the list lately: a week before the next look
        nosrc = translate._pool_gp_base('abcdef0123456789') + '.gp.nosrc'
        open(nosrc, 'w').close()
        self.assertEqual(self.fired(translate._encode_link(pooled)), [])
        os.utime(nosrc, (1, 1))
        self.assertEqual(len(self.fired(translate._encode_link(pooled))), 1)
        translate._gp_mark(translate._pool_gp_base('abcdef0123456789'))
        self.assertEqual(self.fired(translate._encode_link(pooled)), [])
        with mock.patch.object(translate, '_gp_models_left', lambda: False):
            self.assertEqual(self.fired(translate._encode_link(
                {'type': 'engine_ai', 'filename': 'x'})), [])
        # the automatic translation on play: its own link, id adopted later
        calls = self.fired(translate._encode_link({'type': 'engine_ai', 'filename': 'x'}))
        self.assertEqual(self.args(calls[0])['source_id_b64'], '')

    def test_an_ar_hash_has_a_marker_name_of_its_own(self):
        base = translate._pool_gp_base('abcdef0123456789_ar')
        self.assertTrue(os.path.basename(base).startswith('pool_h'))
        self.assertNotEqual(base, translate._pool_gp_base('abcdef0123456789'))

    def test_an_ar_variant_is_kept_where_its_proofread_is(self):
        # QA: a "<hash>_ar" pick was fetched again on every pick, so a proofread
        # kept only in its copy would be lost on the next one
        fetched = []
        fake = mock.MagicMock()
        fake.fetch.side_effect = lambda info, h: fetched.append(h) or HE
        with mock.patch.object(translate, 'pool', fake):
            text, sid = translate._pool_source_text({}, 'abcdef0123456789_ar')
            self.assertEqual(text, HE)
            self.assertEqual(os.path.join(self.dir, 'pool_%s.source.srt' % sid),
                             translate._pool_gp_base('abcdef0123456789_ar'))
            self.assertEqual(translate._pool_source_text({}, 'abcdef0123456789_ar'), (HE, sid))
            self.assertEqual(translate._pool_source_text(
                {}, 'abcdef0123456789_ar', cache_only=True), (HE, sid))
        self.assertEqual(fetched, ['abcdef0123456789_ar'])      # once


class PoolPickSource(Base):

    def test_the_same_release_and_the_same_content_hash(self):
        src = os.path.join(self.dir, 'en.srt')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(EN)
        h = translate._content_hash(translate._prepare_source(EN))
        cands = [{'link': translate._encode_link({'type': 'engine', 'filename': 'Other'})},
                 {'link': translate._encode_link({'type': 'engine', 'filename': 'Blue.2026'})}]
        bridge = mock.MagicMock()
        bridge.search.return_value = cands
        bridge.download.return_value = src
        with mock.patch.dict(sys.modules, {'resources.lib.subs_engine_bridge': bridge}), \
                mock.patch.object(sys.modules['resources.lib'], 'subs_engine_bridge', bridge,
                                  create=True):
            self.assertEqual(translate._pool_pick_source({}, h, 'Blue.2026'),
                             translate._prepare_source(EN))
            self.assertEqual(translate._pool_pick_source({}, h + '_ar', 'Blue.2026'),
                             translate._prepare_source(EN))
            self.assertEqual(bridge.download.call_count, 2)       # only the same release
            self.assertEqual(translate._pool_pick_source({}, '0' * 16, 'Blue.2026'), '')
            self.assertEqual(translate._pool_pick_source({}, h, 'Missing'), '')
            self.assertEqual(translate._pool_pick_source({}, h, ''), '')
        _, kw = bridge.search.call_args
        self.assertEqual(kw.get('cache_only'), True)               # never a new search
        # a look that failed is not "not there" (no week's pause for it)
        bridge.search.side_effect = OSError('engine')
        with mock.patch.dict(sys.modules, {'resources.lib.subs_engine_bridge': bridge}), \
                mock.patch.object(sys.modules['resources.lib'], 'subs_engine_bridge', bridge,
                                  create=True):
            self.assertIsNone(translate._pool_pick_source({}, h, 'Blue.2026'))


class PoolUpload(Base):

    INFO = {'imdb_id': 'tt1', 'tmdb_id': '1', 'title': 'Blue', 'year': '2026'}

    def post(self, variants, body_extra, capacity=False):
        body = pool._build_body(self.INFO, 'h1', 'en', HE, **body_extra)
        sent = []
        with mock.patch.object(pool, '_lookup_raw', lambda p: {'variants': variants}), \
                mock.patch.object(pool, '_srt_quality_ok', lambda s: True), \
                mock.patch.object(pool, '_MAX_VARIANTS', 1 if capacity else 25), \
                mock.patch.object(pool, '_urlreq') as ur:
            ur.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                sent.append(json.loads(data.decode('utf-8'))) or 'req')
            pool._post(body, marker_path=os.path.join(self.dir, 'm'))
        return sent, os.path.isfile(os.path.join(self.dir, 'm.shared'))

    def test_a_proofread_file_replaces_a_pooled_one_that_is_not(self):
        self.assertNotIn('proofread', pool._build_body(self.INFO, 'h1', 'en', HE))
        sent, marked = self.post([{'hash': 'h1'}], {'proofread': True})
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['proofread'], 1)
        self.assertTrue(marked)
        # the pool's is proofread already: nothing sent
        sent, marked = self.post([{'hash': 'h1', 'gp': 1}], {'proofread': True})
        self.assertEqual((sent, marked), ([], True))
        # a full episode still takes the replacement (it adds no variant)
        sent, _ = self.post([{'hash': 'h1'}], {'proofread': True}, capacity=True)
        self.assertEqual(len(sent), 1)
        # a plain upload of a pooled source stays skipped
        sent, marked = self.post([{'hash': 'h1'}], {})
        self.assertEqual((sent, marked), ([], True))


if __name__ == '__main__':
    unittest.main()
