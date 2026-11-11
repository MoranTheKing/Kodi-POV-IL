"""The gender proofread asked again later (MoranSubs 0.3.75): gp_later.py keeps
the queue and its pacing, translate.py queues a proofread 3.7 did not answer
and the service asks again (gp_later_tick).

Since 0.3.75 the proofread asks gemini-3.7-flash alone (blind studies 004/005,
11 Nov 2026). 3.7 is busy much of the day and a 503 counts toward the day's 20
requests, so a translation whose proofread found it busy waits, and the
service asks again for one at a time: DAILY_CAP a day, GAP apart, each
translation further apart every time, for EXPIRE.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import gender_proofread, gp_later, pool, translate  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return gp_later, translate, pool, mods


gp_later, translate, pool, MODS = _load()
H = 3600


def block(n, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n * 3, n * 3 + 1, text)


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def srt_text(*texts):
    return '\n\n'.join(block(i, t) for i, t in enumerate(texts, 1)) + '\n'


HE = srt_text('אתה בא?', 'כן, אני מצטער.', 'תודה רבה לך.')
EN = srt_text('Are you coming?', "Yes, I'm sorry.", 'Thank you very much.')


class Pacing(unittest.TestCase):
    """gp_later.py: bookkeeping only."""

    def entry(self, marker):
        return {'marker': marker, 'path': marker, 'src': marker + '.src'}

    def test_the_numbers(self):
        self.assertEqual((gp_later.FIRST_WAIT, gp_later.BACKOFF_MAX, gp_later.GAP,
                          gp_later.DAILY_CAP, gp_later.EXPIRE, gp_later.MAX_ENTRIES),
                         (H, 8 * H, H // 2, 6, 3 * 24 * H, 20))
        # review: longer than the background job (30 min of rounds, then one
        # request of up to 15 min), which marks once at its start
        self.assertGreater(gp_later.FRESH_TRY, translate._GP_JOB_BUDGET + 900)

    def test_one_entry_a_translation_the_first_ask_an_hour_on(self):
        s = gp_later.load('/no/such/file')
        self.assertEqual(s['entries'], [])
        gp_later.add(s, self.entry('a'), now=1000)
        gp_later.add(s, dict(self.entry('a'), copies=['x']), now=5000)
        self.assertEqual(len(s['entries']), 1)
        e = s['entries'][0]
        self.assertEqual((e['copies'], e['added'], e['next'], e['tries']), (['x'], 5000, 5000 + H, 0))

    def test_the_oldest_go_past_twenty(self):
        s = gp_later.load('/no/such/file')
        for i in range(gp_later.MAX_ENTRIES):
            self.assertEqual(gp_later.add(s, self.entry('m%d' % i), now=i), [])
        dropped = gp_later.add(s, self.entry('new'), now=100)
        self.assertEqual([e['marker'] for e in dropped], ['m0'])
        self.assertEqual(len(s['entries']), gp_later.MAX_ENTRIES)

    def test_due_keeps_the_gap_the_cap_and_each_ones_time(self):
        s = gp_later.load('/no/such/file')
        gp_later.add(s, self.entry('a'), now=0)
        gp_later.add(s, self.entry('b'), now=10)
        self.assertIsNone(gp_later.due(s, H - 1, 'd1'))           # not an hour yet
        self.assertEqual(gp_later.due(s, H + 20, 'd1')['marker'], 'a')   # longest waiting
        gp_later.note_sent(s, H + 20, 'd1')
        self.assertIsNone(gp_later.due(s, H + 20 + gp_later.GAP - 1, 'd1'))
        self.assertEqual(gp_later.due(s, H + 20 + gp_later.GAP, 'd1')['marker'], 'a')
        s['sent'], s['last'] = gp_later.DAILY_CAP, 0
        self.assertIsNone(gp_later.due(s, 10 * H, 'd1'))           # today's cap spent
        self.assertEqual(gp_later.due(s, 10 * H, 'd2')['marker'], 'a')  # a new quota day
        self.assertEqual(s['sent'], 0)

    def test_each_ask_further_off_up_to_eight_hours(self):
        e = self.entry('a')
        waits = []
        for _ in range(5):
            gp_later.retry_later(e, 0)
            waits.append(e['next'] // H)
        self.assertEqual(waits, [2, 4, 8, 8, 8])
        self.assertEqual(e['tries'], 5)

    def test_prune_drops_the_expired_and_the_dead(self):
        s = gp_later.load('/no/such/file')
        gp_later.add(s, self.entry('old'), now=0)
        gp_later.add(s, self.entry('gone'), now=10)
        gp_later.add(s, self.entry('ok'), now=20)
        dropped = gp_later.prune(s, gp_later.EXPIRE + 5, lambda e: e['marker'] != 'gone')
        self.assertEqual(sorted(e['marker'] for e in dropped), ['gone', 'old'])
        self.assertEqual([e['marker'] for e in s['entries']], ['ok'])

    def test_a_broken_file_spends_todays_cap_and_saving_is_whole(self):
        # review: an unknown count must not hand out six more requests
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        f = os.path.join(d, 'q.json')
        with open(f, 'w') as fh:
            fh.write('{not json')
        s = gp_later.load(f, 'd1')
        self.assertEqual((s['entries'], s['day'], s['sent']), ([], 'd1', gp_later.DAILY_CAP))
        self.assertTrue(os.path.exists(f + '.bad'))
        self.assertIsNone(gp_later.due(dict(s, entries=[dict(self.entry('a'), next=0)]), 10 ** 10, 'd1'))
        gp_later.add(s, self.entry('a'), now=1)
        gp_later.save(f, s)
        self.assertEqual([n for n in os.listdir(d) if n.endswith('.tmp')], [])
        s = gp_later.load(f, 'd1')
        self.assertEqual((s['entries'][0]['marker'], s['sent']), ('a', gp_later.DAILY_CAP))
        self.assertNotIn('recovered', s)

    def test_the_lock(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        f = os.path.join(d, 'q.json')
        with gp_later.locked(f):
            with self.assertRaises(TimeoutError):
                with gp_later.locked(f, wait=0.2):
                    pass
        self.assertFalse(os.path.exists(f + '.lock'))
        # left by a process that died: taken over once stale
        open(f + '.lock', 'w').close()
        os.utime(f + '.lock', (0, 0))
        with gp_later.locked(f, wait=0.2):
            pass
        self.assertEqual(gp_later.update(f, lambda s: (len(s['entries']), False)), 0)
        self.assertFalse(os.path.exists(f))       # nothing changed, nothing written
        # review 2: Windows refuses a lock file still being deleted with
        # PermissionError -- a wait, not a failure
        real_open, calls = os.open, []

        def flaky_open(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise PermissionError('being deleted')
            return real_open(*a, **k)
        with mock.patch.object(gp_later.os, 'open', flaky_open):
            with gp_later.locked(f, wait=1):
                pass
        self.assertEqual(len(calls), 2)
        self.assertEqual([n for n in os.listdir(d) if 'lock' in n], [])

    def test_a_claim_counts_the_request_and_a_refund_undoes_it(self):
        s = gp_later.load('/no/such/file')
        gp_later.add(s, self.entry('a'), now=0)
        e = s['entries'][0]
        gp_later.claim(s, e, 10 * H, 'd1')
        self.assertEqual((s['sent'], s['last'], e['next']), (1, 10 * H, 12 * H))
        self.assertIsNone(gp_later.due(s, 10 * H + 60, 'd1'))
        gp_later.refund(s, 'd1')
        self.assertEqual(s['sent'], 0)
        gp_later.refund(s, 'd2')                   # another day: nothing to undo
        self.assertEqual(s['sent'], 0)


class Base(unittest.TestCase):

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, 'tt1.he.srt')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(HE)
        self.settings = {'api_key': 'k', 'model': 'gemini-3.5-flash-lite'}
        self.bools = {}
        for target, value in (
                ('get_setting', lambda k, d='': self.settings.get(k, d)),
                ('get_bool', lambda k, d=False: self.bools.get(k, True)),
                ('notify', lambda *a, **k: None),
                ('log', lambda *a, **k: None),
                ('cache_dir', lambda: self.dir)):
            p = mock.patch.object(translate.kodi_utils, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.models_left = True
        self.contributed = []
        self.pooled_proofread = False
        for target, value in (
                ('_gp_models_left', lambda: self.models_left),
                ('_title_cast', lambda *a: ([], '', '')),
                ('_pool_variant_proofread', lambda info, h, network=True: self.pooled_proofread)):
            p = mock.patch.object(translate, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.pool_use = True
        for target, value in (('share_enabled', lambda: True),
                              ('use_enabled', lambda: self.pool_use),
                              ('contribute_once', lambda *a, **k: self.contributed.append((a, k)))):
            p = mock.patch.object(pool, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.queue = os.path.join(self.dir, 'gp_later.json')

    def clear(self):
        if os.path.exists(self.queue):
            os.remove(self.queue)

    def add(self, why='busy', **kw):
        report = {'why': why}
        report.update(kw.pop('report', {}))
        args = dict(share={'hash': 'abc_ar', 'lang': 'en', 'release': 'Rel.1080p', 'kind': 'ai'})
        args.update(kw)
        translate._gp_later_add(report, self.path, EN,
                                {'imdb_id': 'tt1', 'season': '1', 'episode': '2',
                                 'cast': [{'name': 'x'}], 'n': 3}, **args)
        return gp_later.load(self.queue)


class Queueing(Base):

    def test_a_busy_proofread_waits_with_its_source_and_where_the_pool_keeps_it(self):
        s = self.add()
        e = s['entries'][0]
        self.assertEqual((e['path'], e['marker']), (self.path, self.path))
        self.assertEqual(read(e['src']), EN)
        self.assertEqual(e['info'], {'imdb_id': 'tt1', 'season': '1', 'episode': '2', 'n': 3})
        self.assertEqual(e['share'], {'hash': 'abc_ar', 'lang': 'en', 'release': 'Rel.1080p',
                                      'kind': 'ai'})

    def test_only_what_may_answer_later(self):
        for why in ('busy', 'time', 'quota', 'stopped'):
            self.clear()
            self.assertEqual(len(self.add(why)['entries']), 1, why)
        for why in ('unusable', 'key', 'error', ''):
            self.clear()
            self.assertEqual(self.add(why)['entries'], [], why)
        # review: a connection that failed (a box just awake) is kept
        self.clear()
        self.assertEqual(len(self.add('error', report={'net': True})['entries']), 1)
        self.clear()
        self.assertEqual(self.add('key', report={'net': True})['entries'], [])
        self.assertEqual(self.add('busy', report={'model': 'gemini-3.7-flash'})['entries'], [])
        self.assertEqual(self.add('busy', report={'spent': 'gemini-3.7-flash'})['entries'], [])

    def test_not_when_proofread_already_or_without_a_source(self):
        translate._gp_mark(self.path, {'model': 'gemini-3.7-flash', 'applied': 1})
        self.assertEqual(self.add()['entries'], [])
        os.remove(translate._gp_marker(self.path))
        translate._gp_later_add({'why': 'busy'}, self.path, '', {})
        self.assertFalse(os.path.exists(self.queue))

    def test_no_pool_hash_no_share(self):
        self.assertIsNone(self.add(share=None)['entries'][0]['share'])
        os.remove(self.queue)
        self.assertIsNone(self.add(share={'hash': ''})['entries'][0]['share'])

    def test_the_three_paths_queue_it(self):
        src = (ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8')
        src = src.replace('\r\n', '\n')
        # a fresh translation (with its content-hash copy)
        self.assertIn("            _gp_later_add(_gp_report, translated, src_text, info,\n"
                      "                          share={'hash': _final_pool_hash, 'lang': source_lang,", src)
        self.assertIn('copies=_gp_slots[1:])', src)
        # an opened one: _proofread_opened, with where the pool keeps it
        self.assertIn('            _gp_later_add(report, path, source_text, info, share=later,\n'
                      '                          marker=marker)', src)
        self.assertEqual(src.count('later={'), 1)          # the pool job
        self.assertEqual(src.count("later=({'hash': pool_hash"), 1)   # opened from the list


class Opened(Base):
    """_proofread_opened queues a proofread 3.7 did not answer."""

    def run_opened(self, report, later):
        def fake(blocks, src, key, model, cast, stopped, background=False, rounds=True):
            return blocks, report
        with mock.patch.object(translate, '_run_gender_proofread', fake):
            translate._proofread_opened(
                self.path, EN, 'sid1', 'Rel', lambda ph, pl: None, lambda p: p,
                lambda: False, {'imdb_id': 'tt1'}, share=None, shown_already=True,
                later=later)

    def test_busy_queued_answered_not(self):
        self.run_opened({'why': 'busy', 'asked': True}, {'hash': 'h1', 'lang': 'en',
                                                          'release': '', 'kind': 'ai'})
        e = gp_later.load(self.queue)['entries'][0]
        self.assertEqual((e['marker'], e['share']['hash']), (self.path, 'h1'))
        os.remove(self.queue)
        self.run_opened({'model': 'gemini-3.7-flash', 'applied': 0, 'asked': True}, None)
        self.assertFalse(os.path.exists(self.queue))


class Tick(Base):
    """The service's turn: one request for one due translation."""

    def setUp(self):
        super().setUp()
        self.copy = os.path.join(self.dir, 'tt1.content.he.srt')
        shutil.copyfile(self.path, self.copy)
        self.add(copies=[self.copy])
        self.make_due()
        self.calls = []

    def make_due(self, **kw):
        s = gp_later.load(self.queue)
        for e in s['entries']:
            e['next'] = 0
            e.update(kw)
        gp_later.save(self.queue, s)
        for p in (self.path, getattr(self, 'copy', '')):
            try:   # the failed attempt's in-progress markers, long past
                os.utime(translate._gp_try_marker(p), (0, 0))
            except OSError:
                pass

    def tick(self, report, change=True):
        def fake(blocks, src, key, model, cast, stopped, background=False, rounds=True):
            self.calls.append({'src': src, 'key': key, 'background': background, 'rounds': rounds})
            if change and report.get('model'):
                blocks = list(blocks)
                blocks[0] = blocks[0].replace('אתה בא?', 'את באה?')
            return blocks, dict(report)
        with mock.patch.object(translate, '_run_gender_proofread', fake):
            return translate.gp_later_tick()

    def test_answered_the_file_its_copy_their_markers_and_the_pool(self):
        e = gp_later.load(self.queue)['entries'][0]
        out = self.tick({'model': 'gemini-3.7-flash', 'applied': 1, 'asked': True})
        self.assertEqual(out, 'answered')
        self.assertEqual(self.calls, [{'src': EN, 'key': 'k', 'background': True, 'rounds': False}])
        for p in (self.path, self.copy):
            self.assertIn('את באה?', read(p))
            self.assertTrue(translate._gp_done(p))
        (args, kw), = self.contributed
        self.assertEqual(args[:3], ({'imdb_id': 'tt1', 'season': '1', 'episode': '2', 'n': 3},
                                    'abc_ar', 'en'))
        self.assertIn('את באה?', args[3])
        self.assertEqual(kw, {'marker_path': translate._gp_marker(self.path),
                              'release_override': 'Rel.1080p', 'kind': 'ai',
                              'proofread': {'model': 'gemini-3.7-flash', 'applied': 1}})
        s = gp_later.load(self.queue)
        self.assertEqual((s['entries'], s['sent']), ([], 1))
        self.assertFalse(os.path.exists(e['src']))

    def test_sharing_off_nothing_to_the_pool(self):
        with mock.patch.object(pool, 'share_enabled', lambda: False):
            self.assertEqual(self.tick({'model': 'gemini-3.7-flash', 'applied': 1, 'asked': True}),
                             'answered')
        self.assertEqual(self.contributed, [])

    def test_busy_again_further_off(self):
        out = self.tick({'why': 'busy', 'asked': True})
        self.assertEqual(out, 'busy')
        s = gp_later.load(self.queue)
        e, = s['entries']
        self.assertEqual((e['tries'], s['sent']), (1, 1))
        self.assertGreater(e['next'], s['last'] + 2 * H - 5)
        self.assertNotIn('את באה?', read(self.path))
        # the gap: nothing more for half an hour
        self.make_due()
        self.assertEqual(self.tick({'why': 'busy', 'asked': True}), '')
        self.assertEqual(len(self.calls), 1)

    def test_a_reply_of_no_use_or_a_refused_key_ends_it(self):
        for report in ({'spent': 'gemini-3.7-flash', 'why': 'unusable', 'asked': True},
                       {'why': 'key', 'asked': True}):
            if not gp_later.load(self.queue)['entries']:
                self.add(copies=[self.copy])
                self.make_due(added=10 ** 10)
                s = gp_later.load(self.queue)
                s['last'] = 0
                gp_later.save(self.queue, s)
            self.tick(report)
            self.assertEqual(gp_later.load(self.queue)['entries'], [], report)

    def test_nothing_asked_when_it_is_not_its_time(self):
        self.make_due(next=10 ** 12)
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual(self.calls, [])

    def test_nothing_asked_without_quota_the_setting_or_a_key(self):
        self.models_left = False
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.models_left = True
        self.bools['gender_proofread'] = False
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.bools['gender_proofread'] = True
        self.settings['api_key'] = ' '
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual(self.calls, [])
        self.assertEqual(len(gp_later.load(self.queue)['entries']), 1)   # it waits

    def test_todays_cap(self):
        s = gp_later.load(self.queue)
        gender_proofread = MODS['resources.lib.gender_proofread']
        s['day'], s['sent'] = gender_proofread._today(), gp_later.DAILY_CAP
        gp_later.save(self.queue, s)
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual(self.calls, [])

    def test_asked_right_now_elsewhere_held(self):
        translate._gp_try_mark(self.path, True)      # fresh: an attempt running
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'held')
        self.assertEqual(self.calls, [])
        e, = gp_later.load(self.queue)['entries']
        self.assertGreater(e['next'], 0)

    def test_someone_elses_proofread_in_the_pool(self):
        self.pooled_proofread = True
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'pooled')
        self.assertEqual((self.calls, gp_later.load(self.queue)['entries']), ([], []))

    def test_gone_proofread_meanwhile_or_expired_dropped(self):
        translate._gp_mark(self.path)                # opened again, proofread
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual((self.calls, gp_later.load(self.queue)['entries']), ([], []))
        os.remove(translate._gp_marker(self.path))
        self.add()
        self.make_due(added=0)                       # three days past
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual(gp_later.load(self.queue)['entries'], [])

    def test_an_add_while_asking_is_kept(self):
        other = os.path.join(self.dir, 'tt2.he.srt')
        shutil.copyfile(self.path, other)

        def fake(blocks, src, key, model, cast, stopped, background=False, rounds=True):
            translate._gp_later_add({'why': 'busy'}, other, EN, {'imdb_id': 'tt2'})
            return blocks, {'why': 'busy', 'asked': True}
        with mock.patch.object(translate, '_run_gender_proofread', fake):
            translate.gp_later_tick()
        self.assertEqual(sorted(e['marker'] for e in gp_later.load(self.queue)['entries']),
                         sorted([self.path, other]))


    def test_review_a_failed_connection_keeps_it(self):
        self.assertEqual(self.tick({'why': 'error', 'net': True, 'asked': True}), 'error')
        e, = gp_later.load(self.queue)['entries']
        self.assertEqual(e['tries'], 1)
        self.make_due()
        s = gp_later.load(self.queue)
        s['last'] = 0
        gp_later.save(self.queue, s)
        self.assertEqual(self.tick({'why': 'error', 'asked': True}), 'error')
        self.assertEqual(gp_later.load(self.queue)['entries'], [])     # refused unread: gone

    def test_review_the_pool_is_asked_only_when_in_use(self):
        self.pooled_proofread = True
        self.pool_use = False
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash', 'applied': 1, 'asked': True}),
                         'answered')
        self.assertEqual(len(self.calls), 1)

    def test_review_counted_when_sent_refunded_when_not(self):
        seen = []

        def fake(blocks, src, key, model, cast, stopped, background=False, rounds=True):
            s = gp_later.load(self.queue)
            e, = s['entries']
            seen.append((s['sent'], round(time.time() - s['last']), e['next'] - time.time() > H))
            seen.append(os.path.exists(translate._gp_try_marker(self.copy)))
            return blocks, {'why': 'quota', 'asked': False}
        with mock.patch.object(translate, '_run_gender_proofread', fake):
            self.assertEqual(translate.gp_later_tick(), 'quota')
        self.assertEqual(seen, [(1, 0, True), True])   # counted at the claim; copies marked
        s = gp_later.load(self.queue)
        self.assertEqual((s['sent'], s['entries'][0]['tries']), (0, 1))  # nothing went out

    def test_review_a_failed_save_after_the_request_keeps_the_count(self):
        real_save = gp_later.save
        calls = []

        def save(path, state):
            calls.append(1)
            if len(calls) == 2:            # the outcome's save
                raise PermissionError('held by a scanner')
            return real_save(path, state)
        with mock.patch.object(gp_later, 'save', save):
            self.assertEqual(self.tick({'why': 'busy', 'asked': True}), 'busy')
        s = gp_later.load(self.queue)
        self.assertEqual(s['sent'], 1)
        self.assertGreater(s['entries'][0]['next'] - time.time(), H)   # the claim's wait

    def test_review_an_add_during_the_pool_lookup_is_kept(self):
        other = os.path.join(self.dir, 'tt2.he.srt')
        shutil.copyfile(self.path, other)

        def lookup(info, h, network=True):
            translate._gp_later_add({'why': 'busy'}, other, EN, {'imdb_id': 'tt2'})
            return False
        with mock.patch.object(translate, '_pool_variant_proofread', lookup):
            self.tick({'why': 'busy', 'asked': True})
        self.assertEqual(sorted(e['marker'] for e in gp_later.load(self.queue)['entries']),
                         sorted([self.path, other]))

    def test_review_a_broken_queue_file_asks_nothing_today(self):
        with open(self.queue, 'w') as f:
            f.write('garbage')
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual(self.calls, [])
        s = gp_later.load(self.queue)
        self.assertEqual(s['sent'], gp_later.DAILY_CAP)

    def test_review_a_running_job_half_an_hour_in_is_not_asked_twice(self):
        translate._gp_try_mark(self.path, True)
        t = time.time() - 35 * 60
        os.utime(translate._gp_try_marker(self.path), (t, t))
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'held')
        self.assertEqual(self.calls, [])

    def test_review_a_reply_of_no_use_meanwhile_drops_it(self):
        translate._gp_try_mark(self.path, True, hold=7 * 24 * H)    # marker in the future
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual((self.calls, gp_later.load(self.queue)['entries']), ([], []))

    def test_review_a_copy_proofread_meanwhile_drops_it(self):
        translate._gp_mark(self.copy)
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), '')
        self.assertEqual((self.calls, gp_later.load(self.queue)['entries']), ([], []))

    def test_review_made_again_with_a_hebrew_reference_dropped(self):
        translate._gp_ref_mark(self.path, 'he')
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'heref')
        self.assertEqual((self.calls, gp_later.load(self.queue)['entries']), ([], []))
        self.assertFalse([n for n in os.listdir(self.dir) if n.startswith('gpl_')])

    def test_review_a_pooled_variant_keeps_its_hash_for_that_rule(self):
        self.clear()
        self.add(share={'hash': 'abc_ar', 'lang': 'en', 'release': '', 'kind': 'ai',
                        'ref_hash': 'abc_ar'})
        self.make_due()
        e, = gp_later.load(self.queue)['entries']
        self.assertEqual((e['ref_hash'], 'ref_hash' in e['share']), ('abc_ar', False))
        with mock.patch.object(translate, '_hebrew_subtitle_listed', lambda info: True):
            self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'heref')


    def test_review2_a_clock_gone_back_holds_it_and_keeps_it(self):
        translate._gp_try_mark(self.path, True)
        t = time.time() + 2 * H                    # a marker two hours ahead
        os.utime(translate._gp_try_marker(self.path), (t, t))
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'held')
        self.assertEqual(len(gp_later.load(self.queue)['entries']), 1)

    def test_review2_files_gone_before_the_request_nothing_sent(self):
        e, = gp_later.load(self.queue)['entries']
        open(e['src'], 'w').close()                # emptied by the cache's clean-up
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'gone')
        s = gp_later.load(self.queue)
        self.assertEqual((self.calls, s['entries'], s['sent']), ([], [], 0))
        self.assertFalse(os.path.exists(translate._gp_try_marker(self.path)))

    def test_review2_a_copy_made_again_with_a_hebrew_reference(self):
        translate._gp_ref_mark(self.copy, 'he')
        self.assertEqual(self.tick({'model': 'gemini-3.7-flash'}), 'heref')
        self.assertEqual(self.calls, [])


class Service(unittest.TestCase):

    def test_the_service_asks_every_five_minutes(self):
        src = (ADDON / 'service.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        fn = src[src.index('def _start_gp_later_runner(monitor):'):
                 src.index('def _start_he_warm_drainer(monitor):')]
        self.assertIn('translate.gp_later_tick(should_cancel=monitor.abortRequested)', fn)
        self.assertEqual(fn.count('monitor.waitForAbort(300)'), 2)
        self.assertIn('    _start_pool_queue_drainer(monitor)\n    _start_gp_later_runner(monitor)\n', src)


if __name__ == '__main__':
    unittest.main()
