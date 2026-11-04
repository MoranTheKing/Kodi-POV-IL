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

    def test_the_marker_holder_is_still_due(self):
        # 0.3.66: a pooled row's job holds the in-progress marker through its
        # source look; its own second check must not stop on it
        due = translate._proofread_due
        cb = object()
        translate._gp_try_mark(self.path, True)
        self.assertFalse(due(self.path, EN, cb))
        self.assertTrue(due(self.path, EN, cb, held=True))
        translate._gp_mark(self.path)
        self.assertFalse(due(self.path, EN, cb, held=True))      # done is done

    def test_held_through_the_look_and_a_paused_title_takes_the_pools_copy(self):
        src = (ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8')
        src = src.replace('\r\n', '\n')
        branch = src[src.index('                # held through the look'):]
        branch = branch[:branch.index('return _proofread_opened(')]
        self.assertLess(branch.index('_gp_try_mark(_gp_base, True)'),
                        branch.index('_pool_pick_emb_source(info, _phash, _psrc, _praw)'))
        self.assertEqual(branch.count('_gp_try_mark(_gp_base, False)'), 2)   # no look, not due
        self.assertIn('marker=_gp_base, held=True, info=_gp_info)', branch)
        opened = src[src.index('    def _open_with_proofread('):src.index('    # Respect the user')]
        # waiting out a pause or in progress elsewhere: the pool's proofread
        # copy is still looked for, a request is not made
        self.assertLess(opened.index('asking = not _gp_trying(path)'),
                        opened.index('_pool_proofread_text(info, pool_hash)'))
        self.assertLess(opened.index('_pool_proofread_text(info, pool_hash)'),
                        opened.index('        if not asking:\n            return None'))
        self.assertLess(opened.index('        if not asking:\n            return None'),
                        opened.index('return _proofread_opened('))


class Opened(Base):

    def run_it(self, report, change=True, shown_already=False):
        phases, shared = [], []
        self.stats = []

        def share(text, stats=None):
            shared.append(text)
            self.stats.append(stats)

        self.background = []

        def fake_proofread(blocks, src, key, model, cast, stopped, background=False):
            self.assertEqual(model, 'gemini-3.5-flash-lite')
            self.background.append(background)
            if change:
                blocks = list(blocks)
                blocks[0] = blocks[0].replace('אתה בא?', 'את באה?')
            return blocks, report
        with mock.patch.object(translate, '_run_gender_proofread', fake_proofread), \
                mock.patch.object(translate, '_title_cast', lambda *a: ([], '', '')):
            out = translate._proofread_opened(
                self.path, EN, 'sid1', 'Rel', lambda ph, pl: phases.append((ph, pl)),
                lambda p: p, lambda: False, {'imdb_id': 'tt1'},
                share=share, shown_already=shown_already)
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
        # 0.3.60: the pool's dashboard is told the model and the lines fixed,
        # and the marker keeps them for an upload offered again later
        self.assertEqual(self.stats, [{'model': 'gemini-3.7-flash', 'applied': 1}])
        self.assertEqual(translate._gp_saved(self.path),
                         {'model': 'gemini-3.7-flash', 'applied': 1})

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
        self.assertEqual(self.stats, [{'model': 'gemini-3.7-flash', 'applied': 0}])

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
        self.assertIn("if _psource is None:\n                    _gp_try_mark(_gp_base, False)\n"
                      "                    return None", src.replace('\r\n', '\n'))

    def test_one_attempt_at_a_time_and_a_pause_after_no_answer(self):
        # review of 0.3.59: two opens in its minutes spent two requests, and an
        # overloaded model was asked again at every open
        with mock.patch.object(translate, '_proofread_stopper', lambda sid, c: (lambda: False)):
            # every model out of quota: nothing was sent, no pause (0.3.65)
            self.run_it({'model': '', 'asked': False}, change=False)
            self.assertFalse(os.path.isfile(self.path + '.gp.try'))
            self.run_it({'model': '', 'asked': True}, change=False)
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
        # on screen already: nothing waits, so a busy model is asked again
        # (0.3.70, _GP_BUSY_WAIT); opened from the list, the viewer waits
        self.assertEqual(self.background, [True])
        self.run_it({'model': 'gemini-3.7-flash'})
        self.assertEqual(self.background, [False])

    def test_no_toast_once_the_viewer_moved_on(self):
        # review of 0.3.70: a late round may answer during the next video
        told = []
        with mock.patch.object(translate.kodi_utils, 'notify', lambda m, **k: told.append(m)):
            with mock.patch.object(translate, '_proofread_stopper', lambda sid, c: (lambda: False)):
                self.run_it({'model': 'gemini-3.7-flash', 'applied': 1}, shown_already=True)
            self.assertEqual(len([m for m in told if 'תוקנו' in m]), 1)
            told.clear()
            with open(self.path, 'w', encoding='utf-8') as f:
                f.write(HE)                     # the uncorrected file again
            with mock.patch.object(translate, '_proofread_stopper', lambda sid, c: (lambda: True)):
                out, phases, shared = self.run_it({'model': 'gemini-3.7-flash', 'applied': 1},
                                                  shown_already=True)
        self.assertEqual([m for m in told if 'תוקנו' in m], [])
        self.assertEqual(out, self.path)        # corrected and kept all the same


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

    def test_an_embedded_translation_made_on_play_gets_a_job_too(self):
        # 0.3.68: autosub translates an embedded track with no live preview;
        # its job proofreads the translation of the kept source copy, never
        # reading the track again
        src = os.path.join(self.dir, 'embedded_aligned_en.srt')
        with open(src, 'wb') as f:
            f.write(EN.replace('\n', '\r\n').encode('utf-8'))
        kept = translate._keep_embedded_source(src)
        self.assertTrue(kept and os.path.isfile(kept))
        self.assertEqual(open(kept, 'rb').read(), open(src, 'rb').read())   # the same bytes
        link = translate._encode_link({'type': 'embedded_ai', 'src_lang': 'en', 'stream_index': 3})
        self.assertEqual(self.fired(link), [])               # nothing resolved here
        translate._remember_embedded(link, {'type': 'ai', 'source_lang': 'en',
                                            'local_path': kept, 'embedded': True,
                                            'force_ai': True})
        calls = self.fired(link)
        self.assertEqual(len(calls), 1)
        payload = json.loads(urllib.parse.unquote(self.args(calls[0])['link_b64']))
        self.assertEqual((payload['type'], payload['local_path'], payload['embedded'],
                          payload['proofread_only']), ('ai', kept, True, True))
        # only the few latest are kept
        for i in range(translate._EMBEDDED_RESOLVED_KEEP):
            translate._remember_embedded('other%d' % i, {'type': 'ai'})
        self.assertEqual(self.fired(link), [])
        src_py = (ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8')
        branch = src_py.replace('\r\n', '\n')
        branch = branch[branch.index("    if kind == 'embedded_ai':"):branch.index("    if kind == 'engine_ai':")]
        self.assertIn('_remember_embedded(link, dict(payload, local_path=_kept_src))', branch)

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
        # nothing cached is no look: no week's pause for it (0.3.65)
        bridge.search.return_value = None
        with mock.patch.dict(sys.modules, {'resources.lib.subs_engine_bridge': bridge}), \
                mock.patch.object(sys.modules['resources.lib'], 'subs_engine_bridge', bridge,
                                  create=True):
            self.assertIsNone(translate._pool_pick_source({}, h, 'Blue.2026'))
            # the same release listed, but no download came through
            bridge.search.return_value = cands
            bridge.download.return_value = None
            self.assertIsNone(translate._pool_pick_source({}, h, 'Blue.2026'))
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

    def test_the_model_and_the_lines_it_fixed_go_along(self):
        # 0.3.60, for the pool's dashboard
        sent, _ = self.post([], {'proofread': {'model': 'gemini-3.7-flash', 'applied': 2}})
        self.assertEqual((sent[0]['proofread'], sent[0]['gp_model'], sent[0]['gp_fixed']),
                         (1, 'gemini-3.7-flash', 2))
        # proofread=True (no report kept): the flag alone
        sent, _ = self.post([], {'proofread': True})
        self.assertEqual(sent[0]['proofread'], 1)
        self.assertNotIn('gp_model', sent[0])
        self.assertNotIn('gp_fixed', sent[0])


class Stats(Base):

    def test_what_a_proofread_tells_the_pool(self):
        self.assertEqual(translate._gp_stats({'model': '', 'applied': 3}), {})
        self.assertEqual(translate._gp_stats(None), {})
        self.assertEqual(translate._gp_stats({'model': 'gemini-3.8-flash', 'applied': 'x'}),
                         {'model': 'gemini-3.8-flash', 'applied': 0})
        self.assertEqual(translate._gp_stats({'model': 'gemini-3.8-flash', 'applied': -4}),
                         {'model': 'gemini-3.8-flash', 'applied': 0})

    def test_markers_before_and_after_0_3_60(self):
        translate._gp_mark(self.path)                     # no report: as before
        self.assertTrue(translate._gp_done(self.path))
        with open(translate._gp_marker(self.path), encoding='utf-8') as f:
            self.assertEqual(f.read(), '1')
        self.assertEqual(translate._gp_saved(self.path), {})
        translate._gp_mark(self.path, {'model': 'gemini-3.7-flash', 'applied': 5,
                                       'proposed': 6, 'refused': 1})
        self.assertTrue(translate._gp_done(self.path))
        self.assertEqual(translate._gp_saved(self.path),
                         {'model': 'gemini-3.7-flash', 'applied': 5})
        os.remove(translate._gp_marker(self.path))
        self.assertEqual(translate._gp_saved(self.path), {})



class LaterJobPlainTier(Base):
    """The automatic translation on play, made with the gender reference on
    but none found, is stored in the PLAIN tier. Its proofread job looked only
    in the reference tier, so it never ran (2 Nov 2026: 0 of 6 such
    translations proofread, against 5 of 7 made with a reference)."""

    INFO = {'imdb_id': 'tt1', 'season': '1', 'episode': '2', 'title': 'Show',
            'tvshow': 'Show', 'is_episode': True}

    def setUp(self):
        super().setUp()
        self.en = os.path.join(self.dir, 'Show.S01E02.en.srt')
        with open(self.en, 'w', encoding='utf-8') as f:
            f.write(EN)
        self.payload = {'type': 'ai', 'source_lang': 'en', 'local_path': self.en,
                        'release': 'Show.S01E02.WEB', 'force_ai': True, 'proofread_only': True}
        self.sid = translate._source_id_for_ai(self.payload)
        self.base = translate._content_hash(translate._prepared_source_reader(self.en)())
        self.opened, self.sent = [], []
        for target, value in (('_reapply_rtl_fix_in_place', lambda *a, **k: None),
                              ('_pool_quality_ok', lambda *a, **k: True),
                              ('_proofread_opened', self.fake_opened)):
            p = mock.patch.object(translate, target, value)
            p.start()
            self.addCleanup(p.stop)

    def fake_opened(self, path, source_text, source_id, release, progressive_cb,
                    deliver, cancelled, info, share=None, shown_already=False, mark_path=None):
        self.opened.append({'path': path, 'source_id': source_id, 'shown_already': shown_already})
        if share is not None:
            share('fixed', {'model': 'gemini-3.7-flash', 'applied': 1})
        return path

    def slot(self, tier):
        return translate.cache.translated_path('tt1', '1', '2', 'en', source_id=self.sid, tier=tier)

    def run_job(self, held, ref_on=True):
        fake = mock.MagicMock()
        fake.use_enabled.return_value = True
        fake.share_enabled.return_value = True
        fake.was_contributed.return_value = False
        fake.lookup.return_value = [{'hash': h} for h in held]
        fake.lookup_cached.return_value = [{'hash': h} for h in held]
        fake.contribute_once.side_effect = lambda info, h, lang, text, **k: self.sent.append(
            dict(k, hash=h, text=text))
        get_bool = (lambda k, d=False: True) if ref_on else (
            lambda k, d=False: k != 'gender_ref_arabic')
        with mock.patch.object(translate, 'pool', fake), \
                mock.patch.object(translate.kodi_utils, 'get_bool', get_bool):
            return translate.resolve(translate._encode_link(self.payload), self.INFO,
                                     progressive_cb=lambda *a, **k: None)

    def test_a_plain_tier_translation_gets_its_proofread(self):
        with open(self.slot(''), 'w', encoding='utf-8') as f:
            f.write(HE)
        self.assertEqual(self.run_job([self.base]), self.slot(''))
        self.assertEqual(self.opened, [{'path': self.slot(''), 'source_id': self.sid,
                                        'shown_already': True}])
        # its upload replaces the plain variant, never one under "_ar"
        self.assertEqual([(s['hash'], s['kind']) for s in self.sent], [(self.base, 'ai')])
        self.assertEqual(self.sent[0]['proofread'], {'model': 'gemini-3.7-flash', 'applied': 1})
        # the pool did not answer: still the plain hash, not "<hash>_ar"
        self.opened, self.sent = [], []
        self.run_job([])
        self.assertEqual([(s['hash'], s['kind']) for s in self.sent], [(self.base, 'ai')])

    def test_a_reference_tier_translation_stays_where_it_was(self):
        for tier in ('', 'ar'):
            with open(self.slot(tier), 'w', encoding='utf-8') as f:
                f.write(HE)
        self.run_job([self.base + '_ar', self.base])
        self.assertEqual([o['path'] for o in self.opened], [self.slot('ar')])
        self.assertEqual([(s['hash'], s['kind']) for s in self.sent],
                         [(self.base + '_ar', 'ai_ar')])

    def test_a_reference_tier_file_under_the_content_hash_wins(self):
        # the plain file of an earlier link, and the 'ar' one made later through
        # a byte-different link of the same source: the 'ar' one is on screen
        with open(self.slot(''), 'w', encoding='utf-8') as f:
            f.write(HE)
        content_ar = translate.cache.translated_path('tt1', '1', '2', 'en',
                                                     source_id=self.base, tier='ar')
        with open(content_ar, 'w', encoding='utf-8') as f:
            f.write(HE)
        self.run_job([self.base + '_ar'])
        self.assertEqual([o['path'] for o in self.opened], [content_ar])
        self.assertEqual([(s['hash'], s['kind']) for s in self.sent],
                         [(self.base + '_ar', 'ai_ar')])

    def test_nothing_cached_nothing_done(self):
        self.assertIsNone(self.run_job([self.base]))
        self.assertEqual((self.opened, self.sent), ([], []))

    def test_with_the_reference_off_the_plain_tier_is_the_tier(self):
        with open(self.slot(''), 'w', encoding='utf-8') as f:
            f.write(HE)
        self.run_job([self.base], ref_on=False)
        self.assertEqual([o['path'] for o in self.opened], [self.slot('')])
        self.assertEqual([(s['hash'], s['kind']) for s in self.sent], [(self.base, 'ai')])


if __name__ == '__main__':
    unittest.main()
