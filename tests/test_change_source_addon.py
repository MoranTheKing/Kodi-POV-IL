"""Wizard 0.5.44: the player's "change source" goes back to the add-on that plays.

A viewer, Nov 2026, playing through Umbrella: "with change source it goes back to POV and not to Umbrella". The button
(Onyx's players, and the other skins' buttons that call the Wizard's player_change_source) followed MoranSubs' search
setting -- POV unless chosen otherwise -- not the add-on whose source played. Now the Wizard's source hooks name the
add-on that picked the source (beside its name, as the player's pills are tied), and the button asks that one.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'


class Window(object):
    def __init__(self, **properties):
        self.properties = dict(properties)

    def setProperty(self, key, value):
        self.properties[key] = value

    def getProperty(self, key):
        return self.properties.get(key, '')


class Kodi(object):
    """The playing film or episode, the add-ons installed, and what was asked of Kodi."""

    def __init__(self, window, setting='pov', umbrella=True, episode=False):
        self.window, self.setting, self.umbrella, self.episode = window, setting, umbrella, episode
        self.builtins = []
        self.labels = {'VideoPlayer.UniqueID(tmdb)': '1726', 'VideoPlayer.Title': 'Iron Man', 'VideoPlayer.Year': '2008',
                       'VideoPlayer.IMDBNumber': 'tt0371746', 'VideoPlayer.Season': '1', 'VideoPlayer.Episode': '2',
                       'VideoPlayer.TVShowTitle': 'Show'}

    def condition(self, text):
        return {'VideoPlayer.Content(episodes)': self.episode, 'System.HasAddon(plugin.video.umbrella)': self.umbrella,
                'Player.Playing': True}.get(text, False)

    def modules(self):
        xbmc = types.SimpleNamespace(
            getCondVisibility=self.condition, getInfoLabel=lambda label: self.labels.get(label, ''),
            executebuiltin=self.builtins.append, LOGINFO=1, LOGWARNING=2, log=lambda *a, **k: None,
            executeJSONRPC=lambda text: json.dumps({'result': {'totaltime': {'hours': 2, 'minutes': 6, 'seconds': 1}}}))
        addon = types.SimpleNamespace(getSetting=lambda key: self.setting if key == 'search_provider' else '')
        return {'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(Addon=lambda addon_id=None: addon),
                'xbmcgui': types.SimpleNamespace(Window=lambda wid: self.window, Dialog=lambda: types.SimpleNamespace(
                    notification=lambda *a, **k: None)),
                'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}

    def press(self):
        with mock.patch.dict(sys.modules, self.modules()):
            spec = importlib.util.spec_from_file_location('player_styles_under_test', LIBS / 'player_styles.py')
            styles = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(styles)
            styles.change_source()
        return [b for b in self.builtins if 'plugin.video.' in b]


def remember(window):
    stubs = {'xbmc': types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=3, log=lambda *a, **k: None),
             'xbmcgui': types.SimpleNamespace(Window=lambda wid: window), 'xbmcaddon': types.SimpleNamespace(),
             'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location('pov_source_remember_cs', LIBS / 'patches/pov_source_remember.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


NAME = 'Iron.Man.2008.2160p.BluRay.HEVC.DTS-HD.MA.5.1-BB'


def picked_by(addon, name=NAME, picked=NAME):
    return Window(**{'pov_picked_source_name': picked, 'povil_source_addon': addon, 'povil_source_addon_for': name})


class ChangeSourceTests(unittest.TestCase):
    def test_an_umbrella_play_goes_back_to_umbrellas_list(self):
        """The viewer's case: the search setting says POV, Umbrella played."""
        calls = Kodi(picked_by('umbrella'), setting='pov').press()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith('PlayMedia(plugin://plugin.video.umbrella/?'), calls[0])
        query = parse_qs(urlsplit(calls[0][len('PlayMedia('):-1]).query)
        self.assertEqual((query['action'], query['select'], query['tmdb']), (['play_Item'], ['0'], ['1726']))

    def test_a_pov_play_goes_back_to_povs_list_whatever_the_setting(self):
        calls = Kodi(picked_by('pov'), setting='umbrella').press()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith('RunPlugin(plugin://plugin.video.pov/?'), calls[0])
        self.assertIn('mode=play_media', calls[0])

    def test_an_episode_keeps_its_season_and_number(self):
        calls = Kodi(picked_by('umbrella'), setting='pov', episode=True).press()
        query = parse_qs(urlsplit(calls[0][len('PlayMedia('):-1]).query)
        self.assertEqual((query['season'], query['episode'], query['tvshowtitle']), (['1'], ['2'], ['Show']))

    def test_when_the_add_on_is_not_known_the_setting_decides_as_before(self):
        # another source's name on screen (a library file, another add-on's pick): the mark is not for it
        for window in (picked_by('umbrella', picked='another.mkv'), Window(), picked_by('somethingelse')):
            self.assertTrue(Kodi(window, setting='pov').press()[0].startswith('RunPlugin(plugin://plugin.video.pov/'))
            self.assertTrue(Kodi(window, setting='umbrella').press()[0].startswith('PlayMedia(plugin://plugin.video.umbrella/'))

    def test_umbrella_gone_means_pov(self):
        calls = Kodi(picked_by('umbrella'), setting='umbrella', umbrella=False).press()
        self.assertTrue(calls[0].startswith('RunPlugin(plugin://plugin.video.pov/'), calls[0])


class MarkTests(unittest.TestCase):
    def test_each_pick_names_its_add_on_beside_the_sources_name(self):
        window = Window()
        hooks = remember(window)
        hooks.run_capture(types.SimpleNamespace(), {'name': 'pov.mkv', 'debrid': 'torbox', 'size': 2}, 'link')
        self.assertEqual((window.getProperty('povil_source_addon'), window.getProperty('povil_source_addon_for')),
                         ('pov', 'pov.mkv'))
        with mock.patch.object(hooks, '_enabled', return_value=False):
            hooks.umbrella_capture({'tmdb': '1726'}, {'name': 'umb.mkv', 'debrid': 'TorBox', 'size': 3})
        self.assertEqual((window.getProperty('povil_source_addon'), window.getProperty('povil_source_addon_for')),
                         ('umbrella', 'umb.mkv'))
        hooks.run_capture(types.SimpleNamespace(), {'name': 'pov2.mkv'}, 'link')
        self.assertEqual(window.getProperty('povil_source_addon'), 'pov')
        hooks.umbrella_published({'name': 'auto.mkv'}, 'url')
        self.assertEqual((window.getProperty('povil_source_addon'), window.getProperty('povil_source_addon_for'),
                          window.getProperty('pov_picked_source_name')), ('umbrella', 'auto.mkv', 'auto.mkv'))

    def test_the_hooks_and_the_button_use_the_same_names(self):
        window = Window()
        hooks = remember(window)
        kodi = Kodi(window)
        with mock.patch.dict(sys.modules, kodi.modules()):
            spec = importlib.util.spec_from_file_location('player_styles_names', LIBS / 'player_styles.py')
            styles = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(styles)
        self.assertEqual((styles.SOURCE_ADDON, styles.SOURCE_ADDON_FOR), (hooks.SOURCE_ADDON, hooks.SOURCE_ADDON_FOR))
        hooks.umbrella_published({'name': 'auto.mkv'}, 'url')
        self.assertEqual(styles.playing_addon(window), 'umbrella')


if __name__ == '__main__':
    unittest.main()
