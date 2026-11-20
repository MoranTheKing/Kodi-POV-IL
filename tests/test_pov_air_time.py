"""Wizard 0.5.38: when an episode of a streaming service counts as aired (patches/pov_air_time.py).

A viewer, Nov 2026: "a small bug: episode 6 shows in blue -- meaning no sources -- but there are sources". POV puts an
episode at 20:00 US Eastern of its TMDb date, plus 5 hours: on its own date it is "not aired" all day -- a streaming
service's is out from midnight Pacific that day.
"""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
spec = importlib.util.spec_from_file_location('pov_air_time_test', WIZARD / 'resources/libs/patches/pov_air_time.py')
air = importlib.util.module_from_spec(spec)
spec.loader.exec_module(air)


def pov_adjust(orig_date, adjust_hours):
    """POV's own adjust_premiered_date (modules/utils.py), as it is."""
    adjusted = datetime.strptime('%s 20:00:00' % orig_date, '%Y-%m-%d %H:%M:%S') + timedelta(hours=adjust_hours)
    return adjusted.date()


def patches():
    spec_c = importlib.util.spec_from_file_location('patches_config_air_test', WIZARD / 'resources/libs/patches/patches_config.py')
    config = importlib.util.module_from_spec(spec_c)
    with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
        spec_c.loader.exec_module(config)
    found = next(v for v in vars(config).values() if isinstance(v, list) and v and isinstance(v[0], dict) and 'hook' in v[0])
    return {p['id']: p for p in found}


NETFLIX = {'status': 'Returning Series', 'extra_info': {'status': 'Returning Series', air.KEY: [213]}}
NBC = {'status': 'Returning Series', 'extra_info': {'status': 'Returning Series', air.KEY: [6]}}
OLD = {'status': 'Returning Series', 'extra_info': {'status': 'Returning Series'}}


class TheHours(unittest.TestCase):
    def test_a_streaming_service_s_episode_is_out_on_its_own_date(self):
        offset = 0 + 5                      # POV's date_offset() with the build's "UTC (+/-)" 0
        self.assertEqual(pov_adjust('2026-11-20', air.hours(NETFLIX, offset)), date(2026, 11, 20))
        # (Israel: POV's "UTC (+/-)" set to 2 -- still its own date)
        self.assertEqual(pov_adjust('2026-11-20', air.hours(NETFLIX, 2 + 5)), date(2026, 11, 20))

    def test_a_network_s_and_one_saved_before_keep_the_evening(self):
        for meta in (NBC, OLD, {}, None, {'extra_info': {air.KEY: ['x']}}):
            with self.subTest(meta):
                self.assertEqual(air.hours(meta, 5), 5)
                self.assertEqual(pov_adjust('2026-11-20', air.hours(meta, 5)), date(2026, 11, 21))

    def test_hbo_is_a_channel_and_max_a_service(self):
        self.assertNotIn(49, air.STREAMING)
        self.assertIn(3186, air.STREAMING)

    def test_a_series_a_broadcaster_shows_too_keeps_the_evening(self):
        # (HBO and HBO Max, a Japanese channel and Netflix: white with no sources yet would be worse -- the reviewer)
        for nets in ([49, 3186], [213, 98], [4330, 6100]):
            with self.subTest(nets):
                meta = {'extra_info': {air.KEY: nets}}
                self.assertEqual(air.hours(meta, 5), 5)
        self.assertEqual(air.hours({'extra_info': {air.KEY: [453, 2739]}}, 5), 5 - air.EARLY_HOURS, 'Hulu and Disney+')


class TheHooks(unittest.TestCase):
    def test_pov_keeps_a_series_networks(self):
        patch = patches()['pov_air_networks']
        self.assertEqual((patch['action'], patch['target_file'], patch['anchor']),
                         ('prepend_before', 'resources/lib/indexers/metadata.py', "'last_episode_to_air': ei_last_ep"))
        data = {'networks': [{'id': 213, 'name': 'Netflix'}, {'id': 1024}, 'junk'], 'next_episode_to_air': None}
        ei_last_ep = {}
        extra = eval('{\n%s\n%s\n}' % (patch['hook'].rstrip('\n'), "'last_episode_to_air': ei_last_ep"))
        self.assertEqual(extra[air.KEY], [213, 1024])
        self.assertEqual(eval('{\n%s\n}' % patch['hook'], {'data': {}})[air.KEY], [])

    def scope(self):
        return {'sys': sys, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}

    def test_a_season_s_episodes_go_by_it(self):
        patch = patches()['pov_air_time_season']
        self.assertEqual((patch['action'], patch['target_file'], patch['anchor']),
                         ('append_after', 'resources/lib/menus/seasons.py',
                          "else: episodes_data = season_episodes_meta(params['season'], show.meta, self.meta_user_info)"))
        scope = dict(self.scope(), show=types.SimpleNamespace(meta=NETFLIX), adjust_hours=5)
        with mock.patch.dict(sys.modules, {'pov_air_time': air, 'xbmcvfs': scope['xbmcvfs']}):
            exec(patch['hook'], scope)
        self.assertEqual(scope['adjust_hours'], 5 - air.EARLY_HOURS)
        scope = dict(self.scope(), show=types.SimpleNamespace(meta=NBC), adjust_hours=5)
        with mock.patch.dict(sys.modules, {'pov_air_time': air, 'xbmcvfs': scope['xbmcvfs']}):
            exec(patch['hook'], scope)
        self.assertEqual(scope['adjust_hours'], 5)

    def test_the_episode_lists_go_by_it(self):
        patch = patches()['pov_air_time_episodes']
        self.assertEqual((patch['action'], patch['target_file'], patch['anchor']),
                         ('append_after', 'resources/lib/menus/episodes.py',
                          'episode_date, premiered = adjust_premiered_date(orig_premiered, self.adjust_hours)'))
        for meta, expected in ((NETFLIX, date(2026, 11, 20)), (NBC, date(2026, 11, 21))):
            with self.subTest(meta):
                scope = dict(self.scope(), meta=meta, orig_premiered='2026-11-20', self=types.SimpleNamespace(adjust_hours=5),
                             adjust_premiered_date=lambda d, h: (pov_adjust(d, h), str(pov_adjust(d, h))))
                scope['episode_date'], scope['premiered'] = scope['adjust_premiered_date']('2026-11-20', 5)
                with mock.patch.dict(sys.modules, {'pov_air_time': air, 'xbmcvfs': scope['xbmcvfs']}):
                    exec(patch['hook'], scope)
                self.assertEqual(scope['episode_date'], expected)
                self.assertEqual(scope['premiered'], str(expected))


class TheRefresh(unittest.TestCase):
    def test_the_running_series_saved_without_networks_are_let_go_once(self):
        folder = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(folder, 'metacache.db'))
        con.execute('CREATE TABLE metadata (db_type text, tmdb_id text, meta text)')
        rows = [('tvshow', '1', OLD), ('tvshow', '2', NETFLIX), ('tvshow', '3', dict(OLD, status='Ended')),
                ('tvshow', '4', dict(OLD, status='Canceled')), ('movie', '5', {}), ('tvshow', '6', None)]
        con.executemany('INSERT INTO metadata VALUES (?, ?, ?)',
                        [(t, i, json.dumps(m) if m is not None else '{not json') for t, i, m in rows])
        con.commit()
        con.close()
        said, forgotten = [], []
        self.assertIsNone(air.purge_once(folder, ready=lambda: False), 'not before POV can keep the networks')
        self.assertFalse(os.path.exists(os.path.join(folder, air.PURGE_FLAG)))
        self.assertEqual(air.purge_once(folder, log=said.append, forget=forgotten.append, ready=lambda: True), 1)
        con = sqlite3.connect(os.path.join(folder, 'metacache.db'))
        self.assertEqual(sorted(i for (i,) in con.execute('SELECT tmdb_id FROM metadata')), ['2', '3', '4', '5', '6'])
        con.close()
        # POV's copy in the home window's properties too (read before the database)
        self.assertEqual(forgotten, ['pov_meta_tvshow_tmdb_id_1'])
        self.assertEqual(air.held_in_memory('7', {'imdb_id': 'tt1', 'tvdb_id': 9}),
                         ['pov_meta_tvshow_tmdb_id_7', 'pov_meta_tvshow_imdb_id_tt1', 'pov_meta_tvshow_tvdb_id_9'])
        self.assertIsNone(air.purge_once(folder), 'once')
        self.assertIn('1 running series', said[0])

    def test_the_wizard_runs_it_at_its_start(self):
        source = (WIZARD / 'startup.py').read_text(encoding='utf-8')
        self.assertIn('from resources.libs.patches import pov_air_time as _air', source)
        self.assertIn("_air.purge_once(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/')", source)
        self.assertIn('forget=xbmcgui.Window(10000).clearProperty, ready=_ready)', source)
        self.assertIn("'WIZARD_POV_AIR_NETWORKS_v1' in _f.read()", source)


if __name__ == '__main__':
    unittest.main()
