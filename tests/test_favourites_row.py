"""The Onyx home's favourites row (Wizard favourites_row.py): Kodi's favourites, first on the right."""
import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'

FAVOURITES = '''<favourites>
    <favourite name="[B]POV[/B]" thumb="special://home/pov.png">ActivateWindow(10025,&quot;plugin://plugin.video.pov/&quot;,return)</favourite>
    <favourite name="Umbrella" thumb="">ActivateWindow(10025,&quot;plugin://plugin.video.umbrella/&quot;,return)</favourite>
    <favourite name="Settings">ActivateWindow(Settings)</favourite>
</favourites>
'''


class _Item:
    def __init__(self, label='', offscreen=False):
        self.label, self.art, self.props = label, {}, {}

    def setArt(self, art):
        self.art.update(art)

    def setProperty(self, key, value):
        self.props[key] = value


class FavouritesRowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='povil-fav-'))
        (self.tmp / 'favourites.xml').write_text(FAVOURITES, encoding='utf-8')
        self.calls = []
        self.child = False
        calls = self.calls
        fake = {
            'xbmc': types.SimpleNamespace(executebuiltin=lambda b: calls.append(('builtin', b))),
            'xbmcgui': types.SimpleNamespace(ListItem=_Item),
            'xbmcplugin': types.SimpleNamespace(
                addDirectoryItems=lambda h, items, n=0: calls.append(('items', items)),
                endOfDirectory=lambda h, **k: calls.append(('end',)),
                setResolvedUrl=lambda h, ok, item: calls.append(('resolved', ok))),
            'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: str(self.tmp / 'favourites.xml')),
        }
        self.saved = {k: sys.modules.get(k) for k in fake}
        sys.modules.update(fake)
        spec = importlib.util.spec_from_file_location('qa_favourites_row', WIZARD / 'resources/libs/favourites_row.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod._child = lambda: self.child

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def row(self):
        self.mod.row(1)
        return next(c[1] for c in self.calls if c[0] == 'items')

    def test_the_first_favourite_is_last_in_the_list_so_on_the_right(self):
        items = self.row()
        self.assertEqual([i[1].label for i in items], ['Settings', 'Umbrella', '[B]POV[/B]'])
        self.assertTrue(all(i[1].props['povil_rtl'] == '1' and i[2] is False for i in items))
        self.assertEqual(items[-1][1].art['thumb'], 'special://home/pov.png')
        query = dict(parse_qsl(items[-1][0].split('?', 1)[1]))
        self.assertEqual((query['mode'], query['i'], query['n']), ('favourite_run', '0', '[B]POV[/B]'))

    def test_a_tap_runs_the_favourites_own_command(self):
        url = self.row()[-1][0]
        self.mod.run(5, dict(parse_qsl(url.split('?', 1)[1])))
        self.assertIn(('resolved', False), self.calls)
        self.assertIn(('builtin', 'ActivateWindow(10025,"plugin://plugin.video.pov/",return)'), self.calls)

    def test_a_moved_favourite_is_found_by_its_name(self):
        self.mod.run(-1, {'i': '0', 'n': 'Settings'})
        self.assertEqual(self.calls[-1], ('builtin', 'ActivateWindow(Settings)'))

    def test_a_removed_favourite_refreshes_the_home(self):
        self.mod.run(-1, {'i': '7', 'n': 'Gone'})
        self.assertEqual(self.calls[-1], ('builtin', 'Container.Refresh'))

    def test_nothing_in_a_kids_profile(self):
        self.child = True
        self.mod.row(1)
        self.assertNotIn('items', [c[0] for c in self.calls])
        self.mod.run(-1, {'i': '0', 'n': '[B]POV[/B]'})
        self.assertFalse([c for c in self.calls if c[0] == 'builtin'])

    def test_no_file_no_items(self):
        (self.tmp / 'favourites.xml').unlink()
        self.mod.row(1)
        self.assertEqual(self.calls, [('end',)])


if __name__ == '__main__':
    unittest.main()
