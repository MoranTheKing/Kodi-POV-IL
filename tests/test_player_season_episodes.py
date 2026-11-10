"""The skins' 'פרקי העונה' list for Israeli VOD (Wizard 0.4.95, FENtastic 1.0.32,
Nox 1.0.20).

Idan Plus VOD (Kan 11, Keshet 12, Reshet 13) plays as an episode with no TMDb
id; the list asked POV for build_episode_list&tmdb_id= and POV threw KeyError
'tmdb_id' over the video. The list now comes from the Wizard's
player_season_episodes: the season of the Idan Plus episode on screen as Idan
Plus saved it when the season was listed (seasons.json, through its own
watch_store), no request. POV keeps every episode with a TMDb id.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / 'plugin.program.kodipovilwizard/resources/libs/player_styles.py'
ROUTER = ROOT / 'plugin.program.kodipovilwizard/resources/libs/common/router.py'

# The part of Idan Plus's watch_store (4.0.3+) the Wizard uses, as Idan Plus
# defines it: SeasonIndex/EpisodeMeta(folder).load(), episode_entry(seasons,
# key), play_url(addon_id, entry, more_data).
FAKE_WATCH_STORE = '''
import json, os
from urllib.parse import quote_plus, urlencode
class SeasonIndex(object):
    def __init__(self, folder):
        self._path = os.path.join(folder, 'seasons.json')
    def load(self):
        try:
            with open(self._path, encoding='utf-8') as f:
                return json.load(f).get('seasons', {})
        except Exception:
            return {}
class EpisodeMeta(object):
    def __init__(self, folder):
        self._path = os.path.join(folder, 'episodes.json')
    def load(self):
        try:
            with open(self._path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
def episode_entry(seasons, key):
    for season_url, season in seasons.items():
        if key in season.get('order', []):
            return dict({'play_mode': 4}, **dict(season['eps'][key], key=key,
                        series_title=season.get('series_title', ''), season_url=season_url))
    return None
def play_url(addon_id, entry, more_data=''):
    params = {'name': entry['name'], 'url': quote_plus(entry['url']), 'mode': entry.get('play_mode', 4),
              'iconimage': quote_plus(entry.get('icon', '')), 'module': entry['key'].split(':')[0],
              'moredata': quote_plus(more_data)}
    return 'plugin://{0}/?{1}'.format(addon_id, urlencode(params))
'''

SEASONS = {'seasons': {
    '/mako-vod-keshet/the_escape-s1': {
        'series': '/mako-vod-keshet/the_escape', 'series_title': 'הבריחה', 'title': '',
        'order': ['keshet:a1', 'keshet:a2', 'keshet:a3'],
        'eps': {'keshet:a1': {'name': 'ההחלטה', 'icon': 'http://i/1.jpg', 'number': 1, 'url': 'https://m/1', 'aired': '2026-10-10', 'play_mode': 4},
                'keshet:a2': {'name': 'מבצע החילוץ מתחיל', 'icon': 'http://i/2.jpg', 'number': 2, 'url': 'https://m/2', 'aired': '', 'play_mode': 4},
                'keshet:a3': {'name': 'השיחה', 'icon': '', 'number': None, 'url': 'https://m/3', 'aired': '', 'play_mode': 4}},
        'fetched': 1}}}


class Tag(object):
    def __init__(self):
        self.info = {}

    def __getattr__(self, name):
        if name.startswith('set'):
            return lambda *v: self.info.__setitem__(name[3:].lower(), v[0] if len(v) == 1 else v)
        raise AttributeError(name)


class ListItem(object):
    def __init__(self, label='', offscreen=False):
        self.label, self.art, self.props, self.tag = label, {}, {}, Tag()

    def setArt(self, art):
        self.art.update(art)

    def setProperty(self, k, v):
        self.props[k] = v

    def getVideoInfoTag(self):
        return self.tag


def run(key='keshet:a2', seasons=SEASONS, facts=None, season_no='1', quality='', broken=False, no_meta=False):
    tmp = tempfile.mkdtemp()
    try:
        return _run(tmp, key, seasons, facts, season_no, quality, broken, no_meta)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(tmp, key, seasons, facts, season_no, quality, broken, no_meta):
    lib = os.path.join(tmp, 'home', 'addons', 'plugin.video.idanplus', 'resources', 'lib')
    os.makedirs(lib)
    with open(os.path.join(lib, 'watch_store.py'), 'w', encoding='utf-8') as f:
        f.write('raise RuntimeError("broken")' if broken else
                FAKE_WATCH_STORE.replace('class EpisodeMeta', 'class _NoEpisodeMeta') if no_meta else FAKE_WATCH_STORE)
    watch = os.path.join(tmp, 'profile', 'addon_data', 'plugin.video.idanplus', 'watch')
    os.makedirs(watch)
    with open(os.path.join(watch, 'seasons.json'), 'w', encoding='utf-8') as f:
        json.dump(seasons, f, ensure_ascii=False)
    with open(os.path.join(watch, 'episodes.json'), 'w', encoding='utf-8') as f:
        json.dump(facts or {'keshet:a1': {'plot': 'עלילה'}}, f)
    out = {'items': [], 'ended': [], 'content': None, 'logs': [], 'settings': []}

    class Player(object):
        def getPlayingItem(self):
            if key is None:
                raise RuntimeError('Kodi is not playing any media file')
            return types.SimpleNamespace(getProperty=lambda name: key if name == 'idanplus_key' else '')

    xbmc = types.SimpleNamespace(Player=Player, getInfoLabel=lambda k: season_no if k == 'VideoPlayer.Season' else '',
                                 log=lambda msg, level=0: out['logs'].append(msg), LOGWARNING=2)
    xbmcvfs = types.SimpleNamespace(translatePath=lambda p: p.replace('special://', tmp + os.sep).replace('/', os.sep))
    xbmcplugin = types.SimpleNamespace(
        setContent=lambda h, c: out.__setitem__('content', c),
        addDirectoryItems=lambda h, items, n: out['items'].extend(items),
        endOfDirectory=lambda h, **kw: out['ended'].append(kw))
    xbmcaddon = types.SimpleNamespace(Addon=lambda aid: types.SimpleNamespace(
        getSetting=lambda k: (out['settings'].append((aid, k)), quality)[1]))
    xbmcgui = types.SimpleNamespace(ListItem=ListItem, Window=lambda i: None, Dialog=lambda: None)
    with patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcvfs': xbmcvfs, 'xbmcplugin': xbmcplugin,
                                  'xbmcaddon': xbmcaddon, 'xbmcgui': xbmcgui}):
        spec = importlib.util.spec_from_file_location('season_styles_test', STYLES)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.season_episodes(7)
    return out


class SeasonEpisodes(unittest.TestCase):

    def test_the_saved_season_in_order_and_playable(self):
        out = run()
        self.assertEqual(out['content'], 'episodes')
        self.assertEqual(out['ended'], [{'succeeded': True, 'cacheToDisc': False}])
        labels = [li.label for _, li, _ in out['items']]
        self.assertEqual(labels, ['1. ההחלטה', '[B]2. מבצע החילוץ מתחיל[/B]', 'השיחה'])   # the one on screen in bold
        url, li, folder = out['items'][0]
        self.assertFalse(folder)
        self.assertEqual(li.props['IsPlayable'], 'true')
        self.assertTrue(url.startswith('plugin://plugin.video.idanplus/?'))
        self.assertIn('module=keshet', url)
        self.assertIn('moredata=best', url)     # an unset quality is 'best', as Idan Plus's own GetAddonSetting gives it
        self.assertIn(('plugin.video.idanplus', 'keshet_res'), out['settings'])
        self.assertEqual(li.art['thumb'], 'http://i/1.jpg')
        self.assertEqual(li.tag.info['episode'], 1)
        self.assertEqual(li.tag.info['season'], 1)
        self.assertEqual(li.tag.info['tvshowtitle'], 'הבריחה')
        self.assertEqual(li.tag.info['plot'], 'עלילה')
        self.assertEqual(li.tag.info['firstaired'], '2026-10-10')
        self.assertNotIn('episode', out['items'][2][1].tag.info)  # no number saved
        self.assertEqual(li.tag.info['resumepoint'], (0.0, 1.0))  # Idan Plus keeps the resume point

    def test_a_set_quality_is_passed_on(self):
        url = run(quality='720')['items'][0][0]
        self.assertIn('moredata=720', url)

    def test_an_idan_plus_without_episode_facts_still_lists(self):
        out = run(no_meta=True)
        self.assertEqual(len(out['items']), 3)
        self.assertNotIn('plot', out['items'][0][1].tag.info)

    def test_nothing_from_idan_plus_on_screen_lists_nothing(self):
        for key in ('', None):
            out = run(key=key)
            self.assertEqual(out['items'], [])
            self.assertEqual(out['ended'], [{'succeeded': True, 'cacheToDisc': False}])

    def test_a_season_never_listed_lists_nothing(self):
        out = run(key='kan:zzz')
        self.assertEqual(out['items'], [])

    def test_a_broken_store_lists_nothing_and_says_why(self):
        out = run(broken=True)
        self.assertEqual(out['items'], [])
        self.assertEqual(out['ended'], [{'succeeded': True, 'cacheToDisc': False}])
        self.assertTrue(any('season_episodes' in m for m in out['logs']))


class Wiring(unittest.TestCase):

    def test_the_router_serves_it_even_in_a_child_profile(self):
        src = ROUTER.read_text(encoding='utf-8').replace('\r\n', '\n')
        guard = src[src.index('if profile_age_guard.active_policy() is not None'):]
        guard = guard[:guard.index(':\n')]
        self.assertIn("'player_season_episodes'", guard)
        self.assertIn("elif mode == 'player_season_episodes':", src)
        self.assertIn('player_styles.season_episodes(handle)', src)

    def test_fentastic_lists_idan_plus_from_the_wizard(self):
        var = (ROOT / 'skin.fentastic/xml/Variables.xml').read_text(encoding='utf-8')
        block = var[var.index('<variable name="build_Episodes_Url_OSD">'):]
        block = block[:block.index('</variable>')]
        self.assertIn('<value condition="$EXP[__episode_OSD] + !String.IsEmpty(VideoPlayer.UniqueID(tmdb))">', block)
        idan = ('<value condition="$EXP[__episode_OSD] + $EXP[__CheckIdanplus_OSD]">'
                'plugin://plugin.program.kodipovilwizard/?mode=player_season_episodes'
                '&ep=$ESCINFO[VideoPlayer.TVShowTitle]$ESCINFO[VideoPlayer.Title]')
        self.assertIn(idan, block)
        # the first matching value wins: POV for every episode with a TMDb id
        self.assertLess(block.index('build_episode_list'), block.index(idan))
        for name in ('Includes_VideoOsd1.xml', 'Includes_VideoOsd2.xml', 'Includes_Items.xml'):
            text = (ROOT / 'skin.fentastic/xml' / name).read_text(encoding='utf-8')
            self.assertIn('[!String.IsEmpty(VideoPlayer.UniqueID(tmdb)) | String.Contains(Player.FolderPath,idanplus)]', text, name)

    def test_nox_lists_idan_plus_from_the_wizard(self):
        text = (ROOT / 'skin.povil.nox/xml/Includes_POVIL_Players.xml').read_text(encoding='utf-8')
        block = text[text.index('<variable name="POVIL_Player_build_Episodes_Url_OSD">'):]
        block = block[:block.index('</variable>')]
        self.assertIn('plugin://plugin.program.kodipovilwizard/?mode=player_season_episodes'
                      '&amp;ep=$ESCINFO[VideoPlayer.TVShowTitle]$ESCINFO[VideoPlayer.Title]', block)
        self.assertEqual(text.count('[!String.IsEmpty(VideoPlayer.UniqueID(tmdb)) | String.Contains(Player.FolderPath,idanplus)]'), 2)


if __name__ == '__main__':
    unittest.main()
