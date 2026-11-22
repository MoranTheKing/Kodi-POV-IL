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
        # The favourite's own address, as Kodi's favourites list writes it: Kodi then offers "remove",
        # "rename" and "move" on the tile and runs its command on a press. As a link to the Wizard the
        # menu offered "add to favourites" (a second, broken copy) and no way to remove the real one
        # (field report with a video, Nov 2026).
        from urllib.parse import unquote
        self.assertTrue(all(i[0].startswith('favourites://') for i in items))
        self.assertEqual(unquote(items[-1][0][len('favourites://'):]), 'ActivateWindow(10025,"plugin://plugin.video.pov/",return)')
        self.assertNotIn('"', items[-1][0])
        self.assertIn('ActivateWindow(10025', items[-1][0], 'Kodi leaves ( ) as they are, and so does this')

    def test_a_row_kept_from_before_still_runs_the_favourites_own_command(self):
        """mode=favourite_run: the address the tiles had until Wizard 0.5.5 (a row may be older than the Wizard)."""
        self.mod.run(5, {'i': '0', 'n': '[B]POV[/B]'})
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

    def test_a_tile_carries_kodis_own_address_so_remove_removes(self):
        """Wizard 0.5.46. Kodi 21 finds the favourite "remove" / "rename" / "move" act on by comparing addresses as
        strings (favourites/ContextMenus.cpp), and writes them favourites:// + CURL::Encode(command): -_.!() and
        letters and digits as they are, every other byte %xx in lower case, nothing after (FavouritesURL.cpp). The
        tiles had %3A, %2F (Python's quote): a viewer, Nov 2026, "I press remove and it doesn't remove"; QA Kodi, 36
        of 42 favourites; after it, removed on the screen."""
        items = self.row()
        self.assertEqual(items[-1][0], 'favourites://ActivateWindow(10025%2c%22plugin%3a%2f%2fplugin.video.pov%2f%22%2creturn)')
        self.assertEqual(items[0][0], 'favourites://ActivateWindow(Settings)')
        url = self.mod.kodi_url
        self.assertEqual(url('PlayMedia("plugin://plugin.video.pov/?mode=play_media&mediatype=movie&tmdb_id=157336")'),
                         'favourites://PlayMedia(%22plugin%3a%2f%2fplugin.video.pov%2f%3fmode%3dplay_media%26mediatype%3dmovie'
                         '%26tmdb_id%3d157336%22)')
        self.assertEqual(url('a b~%-_.!()'), 'favourites://a%20b%7e%25-_.!()')
        self.assertEqual(url('\u05d1'), 'favourites://%d7%91', 'every byte of a UTF-8 letter')
        for _url, _item, _folder in items:
            self.assertFalse(_url.endswith('/'), 'nothing after the command: a "/" is only how Kodi shows it')
            self.assertNotRegex(_url, '%[0-9a-f]?[A-F]')


if __name__ == '__main__':
    unittest.main()
