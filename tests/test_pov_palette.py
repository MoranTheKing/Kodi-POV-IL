"""Wizard 0.5.5: the build's colours in POV's and Umbrella's own windows, once (patches/pov_palette.py)."""
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'


class FakeAddon:
    def __init__(self, values):
        self.values = values

    def getSetting(self, key):
        return self.values.get(key, '')

    def setSetting(self, key, value):
        self.values[key] = value


def palette(addons, installed=('plugin.video.pov', 'plugin.video.umbrella')):
    cleared = []
    xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, log=lambda *a, **k: None,
                                 getCondVisibility=lambda text: any(('(%s)' % name) in text for name in installed))

    def addon(name):
        if name not in addons:
            raise RuntimeError('Unknown addon id')
        return addons[name]
    window = types.SimpleNamespace(clearProperty=cleared.append)
    stubs = {'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(Addon=addon),
             'xbmcgui': types.SimpleNamespace(Window=lambda _id: window)}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location('pov_palette_under_test', WIZARD / 'resources/libs/patches/pov_palette.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    module.cleared = cleared
    return module


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.wizard = FakeAddon({})
        self.pov = FakeAddon({'scraper_4k_highlight': 'magenta', 'scraper_1080p_highlight': 'cyan',
                              'scraper_720p_highlight': 'mediumorchid', 'scraper_SD_highlight': 'dodgerblue',
                              'int_dialog_highlight': 'magenta', 'ext_dialog_highlight': 'cyan'})
        self.umbrella = FakeAddon({'sources.torbox.color': 'FF00B445', 'sources.highlight.color': 'FF4DFFFF',
                                   'scraper.dialog.color': 'FFFFFF33', 'highlight.color': 'FFFFFF33'})
        self.addons = {'plugin.program.kodipovilwizard': self.wizard, 'plugin.video.pov': self.pov,
                       'plugin.video.umbrella': self.umbrella}

    def test_the_add_ons_default_colours_become_the_builds(self):
        module = palette(self.addons)
        done = module.apply_once()
        self.assertEqual(self.pov.values['scraper_4k_highlight'], module.GOLD)
        self.assertEqual(self.pov.values['scraper_1080p_highlight'], module.ICE)
        # the owner: "the colours separate 4K from 1080 from 720 -- keep that": one colour per quality in
        # POV, one per service in Umbrella
        qualities = [module.POV[key][1] for key in ('scraper_4k_highlight', 'scraper_1080p_highlight',
                                                    'scraper_720p_highlight', 'scraper_SD_highlight')]
        self.assertEqual(len(set(qualities)), 4)
        services = [colour for key, (_old, colour) in module.UMBRELLA.items() if key.startswith('sources.') and
                    key != 'sources.highlight.color']
        self.assertEqual(len(set(services)), len(services))
        self.assertEqual(self.umbrella.values['sources.torbox.color'], module.GOLD)
        # Umbrella's settings page shows each colour from a second setting beside it
        self.assertEqual(self.umbrella.values['sources.torbox.color.display'], '[COLOR=%s]%s[/COLOR]' % (module.GOLD, module.GOLD))
        self.assertNotIn('scraper_4k_highlight.display', self.pov.values)
        self.assertEqual(len(done), len(module.POV) + len(module.UMBRELLA))
        self.assertEqual(module.cleared, ['pov_settings', 'umbrella_settings'], 'both build their settings copy again')
        for colour in (module.GOLD, module.ICE, module.SAGE, module.SLATE, module.AMETHYST, module.ROSE, module.STONE, module.WHITE):
            self.assertRegex(colour, r'^FF[0-9A-F]{6}$')

    def test_a_colour_the_viewer_chose_is_the_viewers(self):
        self.pov.values['scraper_4k_highlight'] = 'red'
        self.umbrella.values['sources.torbox.color'] = 'FF123456'
        module = palette(self.addons)
        module.apply_once()
        self.assertEqual(self.pov.values['scraper_4k_highlight'], 'red')
        self.assertEqual(self.umbrella.values['sources.torbox.color'], 'FF123456')
        self.assertEqual(self.pov.values['scraper_SD_highlight'], module.SLATE, 'the others still change')

    def test_it_is_done_once(self):
        module = palette(self.addons)
        module.apply_once()
        self.pov.values['scraper_4k_highlight'] = 'magenta'         # the viewer went back to it
        self.assertEqual(module.apply_once(), [])
        self.assertEqual(self.pov.values['scraper_4k_highlight'], 'magenta')
        self.assertEqual(self.wizard.values, {'_pov_palette_v1': 'true', '_umbrella_palette_v1': 'true'})

    def test_a_settings_file_replaced_whole_gets_the_colours_again(self):
        # a fresh install run again over the device puts the pack's POV file back; the mark outlives it
        module = palette(self.addons)
        module.apply_once()
        for key, (defaults, _colour) in module.POV.items():
            self.pov.values[key] = defaults[0]
        self.assertEqual(len(module.apply_once()), len(module.POV))
        self.assertEqual(self.pov.values['scraper_4k_highlight'], module.GOLD)
        # Umbrella's installed default for its highlight is known too
        self.assertIn('FF33ADFF', module.UMBRELLA['highlight.color'][0])

    def test_an_add_on_that_is_not_installed_waits_for_the_start_at_which_it_is(self):
        module = palette(self.addons, installed=('plugin.video.pov',))
        module.apply_once()
        self.assertEqual(self.wizard.values, {'_pov_palette_v1': 'true'})
        self.assertEqual(self.umbrella.values['sources.torbox.color'], 'FF00B445')
        module = palette(self.addons)
        self.assertTrue(module.apply_once())
        self.assertEqual(self.umbrella.values['sources.torbox.color'], module.GOLD)

    def test_one_add_on_failing_does_not_stop_the_other(self):
        del self.addons['plugin.video.pov']
        module = palette(self.addons)
        module.apply_once()
        self.assertNotIn('_pov_palette_v1', self.wizard.values, 'not marked: tried again at the next start')
        self.assertEqual(self.umbrella.values['sources.torbox.color'], module.GOLD)

    def test_it_is_wired_into_the_start_and_the_marks_are_hidden_settings(self):
        startup = (WIZARD / 'startup.py').read_text('utf-8')
        self.assertIn('pov_palette.apply_once()', startup)
        settings = (WIZARD / 'resources/settings.xml').read_text('utf-8')
        for mark in ('_pov_palette_v1', '_umbrella_palette_v1'):
            self.assertIsNotNone(re.search(r'<setting id="%s" type="bool"[^>]*default="false" visible="false"/>' % mark, settings))


if __name__ == '__main__':
    unittest.main()
