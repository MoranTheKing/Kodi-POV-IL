"""Onyx 1.0.32 / Wizard 0.5.37: the home's trailers on Onyx without the Wizard.

The owner, Nov 2026: "whoever downloads only the Onyx skin -- the trailers won't work for him? ... do that too". The skin
only asks for a title's trailer (NotifyAll(povil.trailer,...)); the Wizard's trailer desk plays it. Onyx now carries a copy
of that desk (tools/skin_onyx/gen_standalone.py) and the home starts it while the Wizard is not installed.
QA Kodi 21 (the Wizard's addon.xml hidden, so Kodi does not see it): "the skin plays the trailers (no Wizard)", the
focused title's trailer on the screen, its subtitles looked up; the Wizard back while Kodi ran -- "the Wizard is here: its
own trailers take over" within seconds; a start with the Wizard -- the skin's copy never started, the Wizard's played.
"""
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
LIBS = SKIN / 'scripts/povil_menu/resources/libs'
COPIES = ('trailers.py', 'trailer_subs.py', 'youtube_port.py', 'trailer_timing.py', 'patches/pov_trailer_pick.py')


class TheCopy(unittest.TestCase):
    def test_the_skin_carries_the_wizard_s_own_trailer_desk_unchanged(self):
        for name in COPIES:
            self.assertEqual((LIBS / name).read_bytes(), (WIZARD / 'resources/libs' / name).read_bytes(),
                             '%s: the skin\'s copy is the Wizard\'s (tools/skin_onyx/build.py copies it)' % name)
        self.assertTrue((LIBS / 'patches/__init__.py').exists())
        allowed = {'youtube_port', 'trailer_subs', 'trailer_timing'}
        for name in COPIES:
            source = (LIBS / name).read_text(encoding='utf-8')
            self.assertLessEqual(set(re.findall(r'from resources\.libs import (\w+)', source)), allowed, name)
            self.assertLessEqual(set(re.findall(r'from resources\.libs\.(\w+) import', source)), {'patches'}, name)
            self.assertNotIn('xbmcaddon.Addon()', source, '%s: a script run from the skin has no add-on of its own' % name)

    def test_the_desk_takes_a_folder_of_its_own_and_runs_as_long_as_it_is_told(self):
        source = (WIZARD / 'resources/libs/trailers.py').read_text(encoding='utf-8')
        self.assertIn("DATA = 'special://profile/addon_data/plugin.program.kodipovilwizard/'", source)
        self.assertIn('def watch(data=None, stay=None):', source)
        watch = source.split('def watch(data=None, stay=None):')[1]
        self.assertIn('kept_path = os.path.join(xbmcvfs.translatePath(data), TRANSLATED_FILE)', watch)
        self.assertIn('os.path.join(xbmcvfs.translatePath(data), WEBOS_OFF_FILE)', watch)
        self.assertIn("trailer_subs.CACHE = data + 'trailer_subs/'", watch)
        self.assertNotIn("'special://profile/addon_data/plugin.program.kodipovilwizard/'", watch, 'every file in data')
        self.assertIn('while not listener.waitForAbort(600 if stay is None else KEEP_LOOK_S):', watch)
        self.assertIn('if stay is not None and not stay():', watch)
        # (its own keep() saves the translated trailers: the parameter must not be named so -- QA Kodi, a TypeError)
        self.assertIn('    def keep(update):', watch)


def launcher_run(wizard=False, skin='skin.povil.onyx', running=''):
    """Run scripts/povil_trailers.py with Kodi's modules faked; what it did."""
    text = (SKIN / 'scripts/povil_trailers.py').read_text(encoding='utf-8')
    did = {'props': {'povil.tr.desk': running} if running else {}, 'watch': None, 'mkdirs': [], 'threads': []}
    state = {'wizard': wizard, 'skin': skin}

    class Window:
        def __init__(self, wid):
            assert wid == 10000

        def getProperty(self, k):
            return did['props'].get(k, '')

        def setProperty(self, k, v):
            did['props'][k] = v
            did.setdefault('set', []).append((k, v))

        def clearProperty(self, k):
            did['props'].pop(k, None)

    def watch(data=None, stay=None):
        did['watch'] = (data, stay())
        state['wizard'] = True
        did['stay_after'] = stay()
    trailers = types.SimpleNamespace(watch=watch)
    libs = types.SimpleNamespace(trailers=trailers, youtube_port=types.SimpleNamespace(run=lambda log: None))
    xbmc = types.SimpleNamespace(getCondVisibility=lambda c: state['wizard'] if 'kodipovilwizard' in c else False,
                                 getSkinDir=lambda: state['skin'], log=lambda *a, **k: None, LOGINFO=1,
                                 Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda s: True))
    modules = {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(Window=Window),
               'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p, mkdirs=lambda p: did['mkdirs'].append(p)),
               'resources': types.SimpleNamespace(libs=libs), 'resources.libs': libs,
               'resources.libs.trailers': trailers, 'resources.libs.youtube_port': libs.youtube_port}

    class Thread:
        def __init__(self, target=None, name=None):
            did['threads'].append(name)

        def start(self):
            pass
    with mock.patch.dict(sys.modules, modules), mock.patch.object(sys, 'path', list(sys.path)), \
            mock.patch('threading.Thread', Thread):
        exec(compile(text, 'povil_trailers.py', 'exec'), {'__name__': '__main__'})
    return did


class TheLauncher(unittest.TestCase):
    def test_without_the_wizard_it_plays_them_in_the_skin_s_folder_and_gives_way_to_the_wizard(self):
        did = launcher_run()
        self.assertEqual(did['watch'], ('special://profile/addon_data/skin.povil.onyx/', True))
        self.assertFalse(did['stay_after'], 'the Wizard installed: it stops')
        self.assertEqual(did['mkdirs'], ['special://profile/addon_data/skin.povil.onyx/'])
        self.assertEqual(did['set'], [('povil.tr.desk', 'skin')])
        self.assertEqual(did['props'], {}, 'and says so when it ends')
        self.assertEqual(did['threads'], ['POVILYouTubePort'])

    def test_with_the_wizard_another_skin_or_one_already_running_it_does_nothing(self):
        for kwargs in ({'wizard': True}, {'skin': 'skin.estuary'}, {'running': 'skin'}):
            with self.subTest(kwargs):
                did = launcher_run(**kwargs)
                self.assertIsNone(did['watch'])
                self.assertNotIn('set', did)


class TheHome(unittest.TestCase):
    def test_a_pressed_title_s_background_search_stops_the_trailer(self):
        # (without the Wizard nothing else stops it before POV's player starts -- the reviewer)
        timers = (SKIN / 'xml/Timers.xml').read_text(encoding='utf-8')
        stop = timers.split('<name>povil_trailer_stop</name>')[1].split('</start>')[0]
        self.assertIn('| Window.IsVisible(extendedprogressdialog) |', stop)
        ask = timers.split('<name>povil_trailer</name>')[1].split('</start>')[0]
        self.assertIn('!Window.IsVisible(extendedprogressdialog)', ask)

    def test_the_home_starts_it_only_without_the_wizard_and_with_youtube(self):
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        self.assertIn('<onload condition="!System.HasAddon(plugin.program.kodipovilwizard) + System.HasAddon(plugin.video.youtube) + '
                      'String.IsEmpty(Window(home).Property(povil.tr.desk))">RunScript(special://skin/scripts/povil_trailers.py)'
                      '</onload>', home)

    def test_the_trailer_tiles_show_without_the_wizard_too(self):
        source = (ROOT / 'tools/skin_onyx/gen_home.py').read_text(encoding='utf-8')
        tiles = source.split('SETTINGS_ITEMS = [')[1].split('\n]')[0]
        on_off = tiles.split("('$VAR[POVIL_TrailersTile]'")[1].split('),')[0]
        self.assertIn("'System.HasAddon(plugin.video.youtube)'", on_off)
        self.assertNotIn('WIZ', on_off)
        timing = tiles.split("('תזמון טריילרים'")[1].split("('שליחת לוג'")[0]
        self.assertIn("'RunScript(%s,trailer_timing)' % EDITOR_SCRIPT", timing)
        self.assertNotIn('+ %s + %s\' % (WIZ', timing)
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        self.assertIn('<onclick condition="!System.HasAddon(plugin.program.kodipovilwizard)">'
                      'RunScript(special://skin/scripts/povil_menu_editor.py,trailer_timing)</onclick>', home)
        launcher = (SKIN / 'scripts/povil_menu_editor.py').read_text(encoding='utf-8')
        calls = []
        timing_mod = types.SimpleNamespace(choose=lambda: calls.append('timing'))
        libs = types.SimpleNamespace(trailer_timing=timing_mod)
        with mock.patch.dict(sys.modules, {'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p),
                                           'resources': types.SimpleNamespace(libs=libs), 'resources.libs': libs,
                                           'resources.libs.trailer_timing': timing_mod}), \
                mock.patch.object(sys, 'argv', ['x', 'trailer_timing']), mock.patch.object(sys, 'path', list(sys.path)):
            exec(compile(launcher, 'povil_menu_editor.py', 'exec'), {'__name__': '__main__'})
        self.assertEqual(calls, ['timing'])


if __name__ == '__main__':
    unittest.main()
