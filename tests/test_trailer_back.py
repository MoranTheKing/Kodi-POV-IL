"""Onyx 1.0.31 / Wizard 0.5.36: Back over a trailer, and a season's own trailer.

A viewer, Nov 2026, on his phone (Dexter: Resurrection's seasons): "focusing season 2 showed the same trailer as the
series ... when I pressed Back after the trailer went full screen, it went to a screen that has nothing to do with the
seasons ... after Back on a full-screen trailer it should come back to the title whose trailer played, and not play
the trailer again".
  * TMDb keeps that series' "Season 2 Official Trailer" on season 2 only; POV read the series' videos only.
  * Kodi's home window turns Back into its full-screen player whenever anything plays (Kodi 21, CGUIWindowHome::
    OnAction); the trailer's timers took the player for "the home was left", stopped the trailer, and the home asked
    for it again from its start. In the Videos window's views Back left the list.
QA Kodi, on the screen: season 2 its own trailer, season 1 the series'; Back over the full-screen trailer -- the seasons'
screen back on season 2, the trailer on (5.7 -> 12.0 s); Back with the screen shown -- back to the home as before; the
home: Kodi's player for under half a second, the trailer on without a restart; a service's page: Back with the screen
shown goes to the tabs as before, over the full-screen trailer only brings the page back.
"""
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / 'skin.povil.onyx/xml'
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
spec = importlib.util.spec_from_file_location('pov_trailer_pick_back_test', WIZARD / 'resources/libs/patches/pov_trailer_pick.py')
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)
ADDRESS = 'plugin://plugin.video.youtube/play/?video_id=%s'


def video(key, lang, name, published='2025-05-31T00:00:00.000Z', kind='Trailer'):
    return {'key': key, 'iso_639_1': lang, 'name': name, 'published_at': published, 'type': kind, 'site': 'YouTube'}


# Dexter: Resurrection (TMDb 259909), as TMDb answered on 20 Nov 2026
DEXTER = {'tmdb_id': 259909,
          'season_data': [{'season_number': 0, 'air_date': '2026-02-17'}, {'season_number': 1, 'air_date': '2025-07-13'},
                          {'season_number': 2, 'air_date': '2026-11-01'}],
          'all_trailers': [video('84o1Q6fB20k', 'en', 'Official Trailer'),
                           video('raQz-4a4tyo', 'en', 'The official trailer drops tomorrow', '2025-05-30', 'Teaser')]}
SEASON_ANSWER = {'season/1/videos': {'results': [video('FLRi0mqcej4', 'en', 'Recap', kind='Recap')]},
                 'season/2/videos': {'results': [
                     video('fA1RIbB-0XE', 'en', 'New York Comic Con Panel', '2026-10-08', 'Featurette'),
                     video('nTOf1FIsBcs', 'en', 'Season 2 Official Trailer', '2026-10-01'),
                     video('_Sk8zacqVd0', 'en', 'A killer binge awaits.', '2026-09-09', 'Teaser'),
                     video('zGfqYh_O2mw', 'en', 'Season 2 Official Teaser and Date Announcement', '2026-09-08', 'Teaser'),
                     video('old1recap00', 'en', 'Season 1 trailer', '2025-05-01')]}}


def patches():
    spec_c = importlib.util.spec_from_file_location('patches_config_back_test', WIZARD / 'resources/libs/patches/patches_config.py')
    config = importlib.util.module_from_spec(spec_c)
    with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
        spec_c.loader.exec_module(config)
    found = next(v for v in vars(config).values() if isinstance(v, list) and v and isinstance(v[0], dict) and 'hook' in v[0])
    return {p['id']: p for p in found}


class SeasonsOwnTrailers(unittest.TestCase):
    def setUp(self):
        tp._SEASON_VIDEOS.clear()
        self.folder = tempfile.mkdtemp()
        self.owners = os.path.join(self.folder, tp.OWNERS_FILE)
        self.asked, self.kept = [], {}

    def get(self, url):
        self.asked.append(url)
        return dict(SEASON_ANSWER, name='Dexter: Resurrection', overview='...')

    def cache(self, function, key, url, expiration=24):
        if key not in self.kept:
            result = function(url)
            if result:
                self.kept[key] = result
            return result
        return self.kept[key]

    def read(self, numbers=(1, 2)):
        return tp.read_season_videos(DEXTER, list(numbers), get=self.get, cache=self.cache, owners=self.owners)

    def test_one_request_for_all_the_seasons_kept_by_povs_cache(self):
        self.read()
        self.assertEqual(self.asked, ['/3/tv/259909?append_to_response=season/1/videos,season/2/videos'
                                      '&include_video_language=he,en,null'])
        self.assertEqual(list(self.kept.values())[0], SEASON_ANSWER, 'only the seasons\' videos are kept, not the series')
        self.read()
        self.assertEqual(len(self.asked), 1, 'the second visit is answered from the cache')

    def test_a_season_gets_its_own_trailer_and_its_teasers_as_alternatives(self):
        self.read()
        self.assertEqual(tp.for_season(DEXTER, 2), ADDRESS % 'nTOf1FIsBcs&povil_alt=_Sk8zacqVd0.zGfqYh_O2mw',
                         'not the featurette, not a trailer whose name says it is another season\'s')
        self.assertEqual(tp.for_season(DEXTER, 1), ADDRESS % '84o1Q6fB20k&povil_alt=raQz-4a4tyo',
                         'a season with none of its own: the series\' trailers of that season, as before')

    def test_without_the_read_the_choice_is_as_before(self):
        self.assertIsNone(tp.for_season(DEXTER, 2))
        self.assertEqual(tp.for_season(DEXTER, 1), ADDRESS % '84o1Q6fB20k&povil_alt=raQz-4a4tyo')

    def test_a_hebrew_trailer_of_the_season_comes_first(self):
        answer = {'season/2/videos': {'results': [video('en2', 'en', 'Season 2 Trailer'), video('he2', 'he', 'טריילר עונה 2')]}}
        tp.read_season_videos(DEXTER, [2], get=lambda url: answer, cache=lambda f, k, u, expiration=0: f(u), owners=None)
        self.assertEqual(tp.for_season(DEXTER, 2), ADDRESS % 'he2&povil_alt=en2')

    def test_twenty_seasons_a_request(self):
        tp.read_season_videos({'tmdb_id': 1}, list(range(0, 46)) + [None, 'x'], get=self.get, cache=self.cache, owners=None)
        self.assertEqual(len(self.asked), 3)
        self.assertIn('season/1/videos', self.asked[0])
        self.assertNotIn('season/0/', ''.join(self.asked), 'the specials are not asked')
        self.assertEqual([u.count('/videos') for u in self.asked], [20, 20, 5])

    def test_a_failed_answer_is_not_kept_and_breaks_nothing(self):
        found = tp.read_season_videos(DEXTER, [1, 2], get=lambda url: None, cache=self.cache, owners=self.owners)
        self.assertEqual(found, {1: [], 2: []})
        self.assertEqual(self.kept, {})
        self.assertIsNone(tp.for_season(DEXTER, 2))

    def test_whose_each_trailer_is_kept_for_the_wizard(self):
        self.read()
        kept = json.load(open(self.owners, encoding='utf-8'))
        self.assertEqual(sorted(kept), sorted(['nTOf1FIsBcs', '_Sk8zacqVd0', 'zGfqYh_O2mw', 'old1recap00']),
                         'trailers and teasers only')
        self.assertEqual(kept['nTOf1FIsBcs'][:3], ['259909', 2, 'en'])
        self.assertEqual(tp.season_owner(self.owners, 'nTOf1FIsBcs'), ('259909', 2, 'en'))
        self.assertIsNone(tp.season_owner(self.owners, 'nothing0000'))
        self.assertIsNone(tp.season_owner(os.path.join(self.folder, 'missing.json'), 'nTOf1FIsBcs'))
        before = os.path.getmtime(self.owners)
        os.utime(self.owners, (before - 100, before - 100))
        self.assertFalse(tp.remember(self.owners, '259909', tp._SEASON_VIDEOS['259909']), 'nothing new: not written')

    def test_the_kept_list_is_bounded(self):
        with mock.patch.object(tp, 'OWNERS_KEEP', 3):
            tp.remember(self.owners, '1', {1: [video('a%d' % n, 'en', 'Trailer') for n in range(5)]}, now=10)
        self.assertEqual(len(json.load(open(self.owners, encoding='utf-8'))), 3)

    def test_the_hook_reads_the_seasons_of_the_list(self):
        patch = patches()['pov_trailer_season_videos']
        self.assertEqual((patch['action'], patch['target_file'], patch['anchor']),
                         ('append_after', 'resources/lib/menus/seasons.py', 'running_ep_count = show.total_aired_eps'))
        order = list(patches())
        self.assertLess(order.index('pov_trailer_season_videos'), order.index('pov_trailer_season'))
        called = []
        fake = types.SimpleNamespace(read_season_videos=lambda meta, numbers: called.append((meta['tmdb_id'], numbers)))
        scope = {'show': types.SimpleNamespace(meta=DEXTER), 'season_data': [{'season_number': 1}, {'season_number': 2}]}
        with mock.patch.dict(sys.modules, {'pov_trailer_pick': fake, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            exec(patch['hook'], scope)
        self.assertEqual(called, [(259909, [1, 2])])
        broken = types.SimpleNamespace(read_season_videos=lambda meta, numbers: 1 / 0)
        with mock.patch.dict(sys.modules, {'pov_trailer_pick': broken, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            exec(patch['hook'], scope)          # (a failure leaves POV's list as it was)


class TheWizardKnowsWhoseItIs(unittest.TestCase):
    def setUp(self):
        spec_t = importlib.util.spec_from_file_location('trailers_back_test', WIZARD / 'resources/libs/trailers.py')
        self.trailers = importlib.util.module_from_spec(spec_t)
        spec_t.loader.exec_module(self.trailers)
        # (the desk imports the choice as the Wizard's own package: the module under test stands in for it)
        patches_pkg = types.ModuleType('resources.libs.patches')
        patches_pkg.pov_trailer_pick = tp
        libs = types.ModuleType('resources.libs')
        libs.patches = patches_pkg
        res = types.ModuleType('resources')
        res.libs = libs
        modules = mock.patch.dict(sys.modules, {'resources': res, 'resources.libs': libs, 'resources.libs.patches': patches_pkg,
                                                'resources.libs.patches.pov_trailer_pick': tp})
        modules.start()
        self.addCleanup(modules.stop)
        self.folder = tempfile.mkdtemp()
        self.cache = os.path.join(self.folder, 'metacache.db')
        con = sqlite3.connect(self.cache)
        con.execute('CREATE TABLE metadata (db_type text, tmdb_id text, meta text)')
        con.execute('INSERT INTO metadata VALUES (?, ?, ?)', ('tvshow', '259909', json.dumps(dict(DEXTER, title='דקסטר: התחייה', year=2025))))
        con.commit()
        con.close()
        self.owners = os.path.join(self.folder, 'season_trailers.json')
        json.dump({'nTOf1FIsBcs': ['259909', 2, 'en', 1], 'heb2xxxxxxx': ['259909', 2, 'he', 1]}, open(self.owners, 'w'))

    def test_a_seasons_own_trailer_is_its_series_and_season(self):
        meta, hebrew = self.trailers.owned_title(sqlite3.connect, self.cache, self.owners, 'nTOf1FIsBcs')
        self.assertEqual((meta['povil_id'], meta['povil_season'], meta['title'], hebrew), ('tvshow:259909', 2, 'דקסטר: התחייה', False))
        self.assertEqual(self.trailers.trailer_season(meta, 'nTOf1FIsBcs'), 2, 'the channel\'s post says "season 2"')
        self.assertTrue(self.trailers.owned_title(sqlite3.connect, self.cache, self.owners, 'heb2xxxxxxx')[1])

    def test_anything_else_is_nobodys(self):
        self.assertEqual(self.trailers.owned_title(sqlite3.connect, self.cache, self.owners, 'unknown0000'), (None, False))
        self.assertEqual(self.trailers.owned_title(sqlite3.connect, self.cache, os.path.join(self.folder, 'none.json'),
                                                   'nTOf1FIsBcs'), (None, False))
        self.assertEqual(self.trailers.owned_title(sqlite3.connect, os.path.join(self.folder, 'none.db'), self.owners,
                                                   'nTOf1FIsBcs'), (None, False))

    def test_the_desk_reads_it_when_the_series_videos_do_not_have_it(self):
        source = (WIZARD / 'resources/libs/trailers.py').read_text(encoding='utf-8')
        self.assertIn("owners_path = os.path.join(os.path.dirname(kept_path), SEASON_OWNERS_FILE)", source)
        self.assertEqual(self.trailers.SEASON_OWNERS_FILE, tp.OWNERS_FILE)
        describe = source.split('    def describe(video, key):')[1].split('    def load_captions')[0]
        self.assertIn('meta, _hebrew = owned_title(sqlite3.connect, pov_cache, owners_path, own)', describe)
        look_up = source.split('    def look_up(video, key):')[1].split('    def make_item')[0]
        self.assertIn("return []           # (a season's own trailer", look_up, 'no translated upload of the series for it')


def timers():
    return {t.findtext('name'): t for t in ET.parse(XML / 'Timers.xml').getroot().findall('timer')}


class BackOverATrailer(unittest.TestCase):
    def test_the_home_leaves_kodis_full_screen_player_at_once_when_it_is_the_trailers(self):
        back = timers()['povil_trailer_a_back']
        player = ('Window.IsActive(fullscreenvideo) + !String.IsEmpty(Window(home).Property(povil.tr.on)) + '
                  'String.IsEqual(Player.FilenameAndPath,Window(home).Property(povil.tr.file))')
        # (the trailer's own file: a film or a channel started meanwhile is never taken out of its full screen)
        self.assertEqual(back.findtext('start'), player)
        self.assertEqual(back.find('start').get('reset'), 'true')
        starts = back.findall('onstart')
        self.assertEqual(starts[0].text, 'Action(FullScreen)')
        # on a service's page Back goes to the tabs, as its own Back does -- unless the trailer had the screen to itself
        self.assertEqual((starts[1].get('condition'), starts[1].text),
                         ('Window.Previous(home) + String.IsEqual(Window(home).Property(povil.tab),hub) + '
                          '!Skin.TimerIsRunning(povil_trailer_alone)', 'SetFocus(9000)'))
        self.assertEqual(back.findtext('stop'), 'true')
        # Kodi keeps the timers by name: this one is looked at before the alone timer has seen the key
        self.assertLess('povil_trailer_a_back', 'povil_trailer_alone')

    def test_the_trailer_is_not_stopped_meanwhile(self):
        stop = timers()['povil_trailer_stop'].findtext('start')
        self.assertIn('![[Window.IsActive(home) | Window.IsActive(videos)] | [Window.IsActive(fullscreenvideo) + '
                      '!String.IsEmpty(Window(home).Property(povil.tr.on)) + '
                      'String.IsEqual(Player.FilenameAndPath,Window(home).Property(povil.tr.file))]]', stop)
        self.assertNotIn('| [!Window.IsActive(busydialog)', stop, 'the title is read on its own screen only')

    def test_the_views_lists_send_back_to_a_button_that_gives_the_focus_straight_back(self):
        views = (XML / 'View_POVIL.xml').read_text(encoding='utf-8')
        for vid in (51, 55):
            with self.subTest(vid):
                lst = views.split('<control type="list" id="%d">' % vid)[1].split('<itemlayout')[0]
                self.assertIn('<onback condition="Skin.TimerIsRunning(povil_trailer_alone)">9810</onback>', lst)
        self.assertEqual(views.count('id="9810"'), 1)
        button = re.search(r'<control type="button" id="9810"[^>]*>(.*?)</control>', views, re.S).group(1)
        self.assertIn('<left>-2000</left>', button)
        self.assertNotIn('<visible>', button, 'always focusable: Back moves the focus only to a control that can take it')
        # (a focus animation of no time: Kodi runs onfocus a frame later -- at once, the list and the button would
        # both hold the focus)
        self.assertIn('<animation effect="fade" start="100" end="100" time="0">Focus</animation>', button)
        self.assertEqual(re.findall(r'<onfocus condition="([^"]*)">([^<]*)</onfocus>', button),
                         [('Control.IsVisible(55)', 'SetFocus(55)'), ('!Control.IsVisible(55)', 'SetFocus(51)')])


if __name__ == '__main__':
    unittest.main()
