"""Wizard 0.5.43: Umbrella fills the player's provider and size pills, and its search names the debrid services.

A viewer, Nov 2026: "the file size and TorBox are not in Umbrella, only in POV; in Umbrella's search TorBox is not named
either". Seen in the QA Kodi: an Umbrella play from its list left both pills empty (its play hook named the source for
the subtitles and remembered it, but never told the pills), its autoplay named nothing at all, and while it asks the
debrid services its search window says "Please wait... Checking Providers" where POV's says "Remaining: TORBOX".
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
PATCHES = WIZARD / 'resources/libs/patches'


class Window(object):
    def __init__(self):
        self.properties = {}

    def setProperty(self, key, value):
        self.properties[key] = value

    def getProperty(self, key):
        return self.properties.get(key, '')


def remember(window):
    xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=3, log=lambda *a, **k: None)
    stubs = {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(Window=lambda wid: window), 'xbmcaddon': types.SimpleNamespace(),
             'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location('pov_source_remember_umbrella', PATCHES / 'pov_source_remember.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# An Umbrella source as its list holds it (the QA Kodi, Iron Man, 21 Nov 2026)
UMBRELLA_ITEM = {'name': 'Iron.Man.2008.2160p.BluRay.HEVC.DTS-HD.MA.5.1-BB', 'debrid': 'TorBox', 'provider': 'torrentio',
                 'source': 'torrent', 'quality': '4K', 'size': 85.17, 'hash': 'abc'}
PILLS = ('povil_osd_provider', 'povil_osd_provider_for', 'povil_osd_size', 'povil_osd_size_for')


class PillTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.remember = remember(self.window)

    def pills(self):
        return [self.window.getProperty(key) for key in PILLS]

    def test_a_source_picked_from_umbrellas_list_fills_the_pills(self):
        # the remembering is off: the pills do not depend on it
        with mock.patch.object(self.remember, '_enabled', return_value=False):
            self.remember.umbrella_capture({'tmdb': '1726'}, UMBRELLA_ITEM)
        name = UMBRELLA_ITEM['name']
        self.assertEqual(self.pills(), ['TorBox', name, '85.2 GB', name])

    def test_a_pill_that_fails_never_costs_the_remembering(self):
        with mock.patch.object(self.remember, 'publish_pills', side_effect=RuntimeError('boom')), \
                mock.patch.object(self.remember, '_enabled', return_value=False):
            self.assertFalse(self.remember.umbrella_capture({'tmdb': '1726'}, UMBRELLA_ITEM))

    def test_a_source_umbrella_started_by_itself_fills_them_too(self):
        """Its autoplay and the remembered source: named as the list path names it, the pills with it."""
        self.remember.umbrella_published(UMBRELLA_ITEM, 'https://example.invalid/stream')
        name = UMBRELLA_ITEM['name']
        self.assertEqual(self.window.getProperty('pov_picked_source_name'), name)
        self.assertEqual(self.window.getProperty('subs.player_filename'), name)
        self.assertEqual(self.pills(), ['TorBox', name, '85.2 GB', name])

    def test_umbrellas_names_are_said_the_way_people_say_them(self):
        label = self.remember.provider_label
        self.assertEqual(label({'debrid': 'TorBox'}), 'TorBox')
        self.assertEqual(label({'debrid': 'Premiumize.me'}), 'Premiumize')
        self.assertEqual(label({'debrid': 'Real-Debrid'}), 'Real-Debrid')
        # a source in a debrid service's own cloud names the cloud as its provider
        self.assertEqual(label({'provider': 'tb_cloud'}), 'TorBox')
        self.assertEqual(label({'provider': 'rd_cloud'}), 'Real-Debrid')
        self.assertEqual(label({'provider': 'torrentio'}), '', 'a scraper is not a debrid service')
        self.assertEqual(self.remember.size_label({'size': 151.48}), '151.5 GB')

    def test_a_source_with_neither_leaves_no_stale_pill(self):
        self.window.properties.update({'povil_osd_provider': 'TorBox', 'povil_osd_size': '60 GB'})
        self.remember.umbrella_published({'name': 'plain.mkv', 'source': 'direct'}, '')
        self.assertEqual(self.pills(), ['', '', '', ''])

    def test_pov_still_fills_them_the_same_way(self):
        self.remember.run_capture(types.SimpleNamespace(), {'name': 'a.mkv', 'debrid': 'torbox', 'size': 12.44}, 'link')
        self.assertEqual(self.pills(), ['TorBox', 'a.mkv', '12.4 GB', 'a.mkv'])


class CheckingTests(unittest.TestCase):
    def setUp(self):
        self.remember = remember(Window())
        self.message = '[COLOR gold][B]Please wait...[CR]Checking Providers[/B][/COLOR]'

    def test_the_search_names_the_services_it_asks(self):
        checking = self.remember.umbrella_checking
        self.assertEqual(checking(self.message, ['TorBox']), '[COLOR gold][B]Please wait...[CR]Checking TorBox[/B][/COLOR]')
        self.assertEqual(checking(self.message, ['Real-Debrid', 'TorBox', 'Premiumize.me', 'TorBox']),
                         '[COLOR gold][B]Please wait...[CR]Checking Real-Debrid, TorBox, Premiumize[/B][/COLOR]')
        # the background dialog's one-line form
        self.assertEqual(checking('Please wait...  Checking Providers', ['TorBox']), 'Please wait...  Checking TorBox')

    def test_nothing_known_or_another_text_is_left_as_it_is(self):
        checking = self.remember.umbrella_checking
        self.assertEqual(checking(self.message, []), self.message)
        self.assertEqual(checking(self.message, None), self.message)
        self.assertEqual(checking('Something else', ['TorBox']), 'Something else')
        self.assertEqual(checking(self.message, ['x' * 40]), self.message, 'not a name')


class PatchTests(unittest.TestCase):
    """The two hooks land at their lines and run (the real Umbrella file was checked in the QA Kodi: each anchor once,
    the file compiles with both)."""

    HOSTS = {
        'umbrella_autoplay_source': (
            "class Sources:\r\n\tdef sourcesAutoPlay(self, items):\r\n\t\tfor i in range(len(items)):\r\n\t\t\ttry:\r\n"
            "\t\t\t\ttry:\r\n\t\t\t\t\turl = self.sourcesResolve(items[i])\r\n\t\t\t\t\tif url:\r\n\t\t\t\t\t\tbreak\r\n"
            "\t\t\t\texcept: pass\r\n\t\t\texcept: pass\r\n\t\treturn url\r\n"),
        'umbrella_checking_names': (
            "class Sources:\r\n\tdef getSources_dialog(self, progressDialog):\r\n"
            "\t\tdebrid_message = 'Please wait...[CR]Checking Providers'\r\n"
            "\t\tprogressDialog.update(100, debrid_message)\r\n\t\treturn debrid_message\r\n"),
    }

    def apply(self, pid):
        xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        logger = types.SimpleNamespace(log=mock.Mock())
        with mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace(),
                                           'resources.libs.common': types.SimpleNamespace(logging=logger)}):
            engine = load('engine_for_umbrella', WIZARD / 'resources/libs/patch_engine.py')
            config = {p['id']: p for p in load('config_for_umbrella', PATCHES / 'patches_config.py').PATCH_CONFIG}
        patch = config[pid]
        self.assertEqual((patch['addon_id'], patch['target_file'], patch['optional']),
                         ('plugin.video.umbrella', 'resources/lib/modules/sources.py', True))
        done, changed, status = engine.PatchEngine._apply_single_patch(
            engine.PatchEngine.__new__(engine.PatchEngine), self.HOSTS[pid], dict(patch, enabled=True), '\r\n')
        self.assertEqual((changed, status), (True, 'applied'), pid)
        self.assertNotIn('\n', done.replace('\r\n', ''), 'the file keeps its own line endings')
        scope = {}
        exec(compile(done, pid, 'exec'), scope)
        return scope['Sources']

    def run_with(self, fake, call):
        vfs = types.SimpleNamespace(translatePath=lambda path: path)
        with mock.patch.dict(sys.modules, {'pov_source_remember': fake, 'xbmcvfs': vfs}), \
                mock.patch.object(sys, 'path', list(sys.path)):
            return call()

    def test_the_autoplay_names_the_source_it_resolved_and_only_that_one(self):
        Sources = self.apply('umbrella_autoplay_source')
        told = []
        fake = types.SimpleNamespace(umbrella_published=lambda item, url: told.append((item['name'], url)))
        source = Sources()
        answers = iter([None, 'https://example.invalid/b'])

        def resolve(item):
            url = next(answers)
            source.url = url
            return url
        source.sourcesResolve = resolve
        self.assertEqual(self.run_with(fake, lambda: source.sourcesAutoPlay([{'name': 'a'}, {'name': 'b'}])),
                         'https://example.invalid/b')
        self.assertEqual(told, [('b', 'https://example.invalid/b')], 'a source that did not resolve is not named')
        # a hook that fails never stops the playback
        broken = types.SimpleNamespace(umbrella_published=mock.Mock(side_effect=RuntimeError('boom')))
        source.sourcesResolve = lambda item: 'https://example.invalid/c'
        self.assertEqual(self.run_with(broken, lambda: source.sourcesAutoPlay([{'name': 'c'}])), 'https://example.invalid/c')

    def test_the_search_message_names_the_services(self):
        Sources = self.apply('umbrella_checking_names')
        source = Sources()
        source.debrid_resolvers = [types.SimpleNamespace(name='TorBox')]
        shown = []
        dialog = types.SimpleNamespace(update=lambda percent, text: shown.append(text))
        fake = remember(Window())
        self.assertEqual(self.run_with(fake, lambda: source.getSources_dialog(dialog)), 'Please wait...[CR]Checking TorBox')
        self.assertEqual(shown, ['Please wait...[CR]Checking TorBox'])
        # no resolvers known (an older Umbrella): the message as it was
        del source.debrid_resolvers
        shown.clear()
        self.run_with(fake, lambda: source.getSources_dialog(dialog))
        self.assertEqual(shown, ['Please wait...[CR]Checking Providers'])


if __name__ == '__main__':
    unittest.main()
