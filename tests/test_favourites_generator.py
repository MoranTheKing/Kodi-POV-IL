"""Exercise favourites refresh and skin/service transitions on a fake profile."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'plugin.program.orderfavourites-hebrew/favourites_generator.py'
spec = importlib.util.spec_from_file_location('favourites_generator', MODULE)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class _VFS:
    def __init__(self, root):
        self.root = Path(root)

    def translatePath(self, special):
        return str(self.root / special.split('special://', 1)[1])

    def exists(self, special):
        return Path(self.translatePath(special)).exists()

    def File(self, special, mode='r'):
        path = Path(self.translatePath(special))
        path.parent.mkdir(parents=True, exist_ok=True)
        return open(path, mode, encoding='utf-8')


class _Visibility:
    def __init__(self):
        self.active = {'umbrella', 'mdblist', 'trakt', 'tmdb'}

    def is_service_active(self, name):
        if name.startswith('!'):
            return not self.is_service_active(name[1:])
        return name in self.active


def _items(xml):
    return list(ET.fromstring(xml))


class FavouritesGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_vfs = generator.xbmcvfs
        self.old_visibility = generator._VIS_MGR
        self.vfs = _VFS(self.tmp.name)
        self.visibility = _Visibility()
        generator.xbmcvfs = self.vfs
        generator._VIS_MGR = self.visibility
        self.addCleanup(self._restore)

    def _restore(self):
        generator.xbmcvfs = self.old_vfs
        generator._VIS_MGR = self.old_visibility

    def _installed(self):
        return Path(self.vfs.translatePath(generator.FAVOURITES_PATH))

    def _refresh(self, skin='skin.fentastic'):
        return generator.generate_favourites_xml(skin, merge=True, write=True)

    def test_user_order_edits_additions_and_deletions_survive_all_skin_switches(self):
        first = self._refresh()
        root = ET.fromstring(first)
        pov = root[0]
        root.remove(pov)
        pov.set('thumb', 'special://user/custom.png')
        root.append(pov)
        removed_name = '[B]הסרטים שלי (MDBList)[/B]'
        for item in list(root):
            if item.get('name') == removed_name:
                root.remove(item)
        root.append(ET.fromstring(
            '<favourite name="My own" thumb="mine.png">RunAddon("mine")</favourite>'))
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf-8')

        second = self._refresh()
        self.assertEqual(_items(second)[-2].get('name'), '[B]POV[/B]')
        self.assertEqual(_items(second)[-2].get('thumb'), 'special://user/custom.png')
        self.assertEqual(_items(second)[-1].get('name'), 'My own')
        self.assertNotIn(removed_name, [i.get('name') for i in _items(second)])

        af3 = self._refresh('skin.arctic.fuse.3')
        self.assertEqual(_items(af3)[-2].get('name'), '[B]POV[/B]')
        self.assertNotIn('[B]הסדרות שלי (MDBList)[/B]',
                         [i.get('name') for i in _items(af3)])
        back = self._refresh()
        self.assertIn('[B]הסדרות שלי (MDBList)[/B]',
                      [i.get('name') for i in _items(back)])
        self.assertNotIn(removed_name, [i.get('name') for i in _items(back)])

    def test_conditional_service_tile_goes_and_returns_without_losing_user_tiles(self):
        self._refresh()
        self.visibility.active.remove('umbrella')
        hidden = self._refresh()
        self.assertFalse(any('Umbrella' in i.get('name') for i in _items(hidden)))
        self.visibility.active.add('umbrella')
        visible = self._refresh()
        self.assertEqual(sum('Umbrella' in i.get('name') for i in _items(visible)), 2)

    def test_bad_existing_xml_is_never_overwritten(self):
        self._refresh()
        self._installed().write_text('<favourites><broken', 'utf-8')
        self.assertIsNone(self._refresh())
        self.assertEqual(self._installed().read_text('utf-8'), '<favourites><broken')

    def test_failed_atomic_replace_keeps_existing_file(self):
        self._refresh()
        before = self._installed().read_bytes()
        with mock.patch.object(generator.os, 'replace', side_effect=OSError('disk busy')):
            self.assertIsNone(self._refresh('skin.arctic.fuse.3'))
        self.assertEqual(self._installed().read_bytes(), before)

    def test_stable_startup_does_not_rewrite_favourites(self):
        self._refresh()
        self._refresh()  # normalise the XML produced by the initial seed
        before = self._installed().read_bytes()
        with mock.patch.object(generator, '_write_favourites',
                               side_effect=AssertionError('unnecessary write')):
            self.assertIsNotNone(self._refresh())
        self.assertEqual(self._installed().read_bytes(), before)

    def test_first_run_preserves_preexisting_named_tile_and_custom_item(self):
        self._installed().parent.mkdir(parents=True, exist_ok=True)
        self._installed().write_text(
            '<favourites><favourite name="[B]POV[/B]" thumb="mine.png">'
            'RunAddon("plugin.video.pov")</favourite><favourite name="Mine" '
            'thumb="mine.png">RunAddon("mine")</favourite></favourites>', 'utf-8')
        rows = _items(self._refresh())
        self.assertEqual(rows[0].get('thumb'), 'mine.png')
        self.assertEqual(rows[1].get('name'), 'Mine')
        self.assertEqual(sum(i.get('name') == '[B]POV[/B]' for i in rows), 1)

    def test_umbrella_search_and_mdblist_routes_across_four_skins(self):
        for skin in ('skin.estuary', 'skin.fentastic', 'skin.povil.nox'):
            rows = _items(generator.generate_favourites_xml(
                skin, merge=False, write=False))
            actions = [item.text for item in rows]
            self.assertTrue(any('RunAddon("plugin.video.umbrella")' == a
                                for a in actions), skin)
            self.assertTrue(any('action=search_provider' in a for a in actions), skin)
            for kind in ('movies', 'tvshows'):
                self.assertTrue(any('action=mdblist_my_' + kind in a
                                    for a in actions), skin)
                self.assertTrue(any('action=favorites_' + kind in a
                                    for a in actions), skin)

        af3_rows = _items(generator.generate_favourites_xml(
            'skin.arctic.fuse.3', merge=False, write=False))
        af3_actions = [item.text for item in af3_rows]
        self.assertTrue(any('action=search_provider' in a for a in af3_actions))
        af3_file = (ROOT / 'service.subtitles.kodipovilai/resources/lib/'
                    'af3_home_patcher.py')
        spec = importlib.util.spec_from_file_location('af3_home_patcher_test', af3_file)
        af3 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(af3)
        mdblist_widgets = [row['path'] for row in af3.HOME_WIDGETS
                           if 'MDBList' in row['label']]
        self.assertEqual(len(mdblist_widgets), 2)
        self.assertTrue(all('action=mdblist_watchlist' in path
                            for path in mdblist_widgets))

    def test_legacy_seed_upgrades_untouched_tile_but_keeps_user_edit(self):
        desired = generator.generate_favourites_xml(
            'skin.fentastic', merge=False, write=False)
        desired_rows = _items(desired)
        old_root = ET.fromstring(desired)
        old_root[0].set('thumb', 'old-pov.png')
        old_root[1].set('thumb', 'old-umbrella.png')
        old = ET.tostring(old_root, encoding='unicode')
        self.assertTrue(generator.seed_previous_defaults(old))
        self.assertFalse(generator.seed_previous_defaults(desired))

        old_root[0].set('thumb', 'user-pov.png')
        self._installed().parent.mkdir(parents=True, exist_ok=True)
        self._installed().write_text(ET.tostring(old_root, encoding='unicode'), 'utf-8')
        migrated = _items(self._refresh())
        self.assertEqual(migrated[0].get('thumb'), 'user-pov.png')
        self.assertEqual(migrated[1].get('thumb'), desired_rows[1].get('thumb'))


if __name__ == '__main__':
    unittest.main()
