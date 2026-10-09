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

    def test_deletion_before_service_disconnect_survives_reconnection(self):
        first = self._refresh()
        root = ET.fromstring(first)
        for item in list(root):
            if 'Umbrella' in item.get('name') or '(Trakt)' in item.get('name'):
                root.remove(item)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        self.visibility.active -= {'umbrella', 'trakt'}
        self._refresh()
        self.visibility.active |= {'umbrella', 'trakt'}
        restored = _items(self._refresh())
        self.assertEqual(sum('Umbrella' in i.get('name') for i in restored), 0)
        self.assertEqual(sum('(Trakt)' in i.get('name') for i in restored), 0)

    def test_legacy_explicit_deletions_are_not_reset_by_update(self):
        import json
        first = self._refresh(); root = ET.fromstring(first)
        names = {i.get('name') for i in root if 'Umbrella' in i.get('name') or '(Trakt)' in i.get('name')}
        for item in list(root):
            if item.get('name') in names: root.remove(item)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        state_path=Path(generator._state_file());state=json.loads(state_path.read_text('utf8'))
        state['layout_version']=2;state['deleted']=sorted(names)
        state_path.write_text(json.dumps(state), 'utf8')
        restored=self._refresh()
        self.assertFalse(names & {i.get('name') for i in _items(restored)})
        # Deliberate removals following migration stay removed on later boots.
        root=ET.fromstring(restored)
        for item in list(root):
            if item.get('name') in names: root.remove(item)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        self.assertFalse(names & {i.get('name') for i in _items(self._refresh())})

    def test_deleted_tile_stays_deleted_across_label_and_action_update(self):
        import json
        first = self._refresh()
        root = ET.fromstring(first)
        tile = next(i for i in root if i.get('name') == '[B]סדרות חדשות[/B]')
        root.remove(tile)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        self._refresh()
        config = generator._load_config()
        config['tiles']['shows_new']['name'] = '[B]סדרות חדשות — מעודכן[/B]'
        config['tiles']['shows_new']['action'] = tile.text.replace('tmdb_tv_premieres', 'tmdb_tv_recent')
        with mock.patch.object(generator, '_load_config', return_value=config):
            for _ in range(3):
                self.assertFalse(any('סדרות חדשות' in i.get('name') for i in _items(self._refresh())))
        state = json.loads(Path(generator._state_file()).read_text('utf8'))
        self.assertIn('povil.tile:shows_new', state['deleted'])

    def test_rename_keeps_user_tile_without_adding_duplicate(self):
        first = self._refresh()
        root = ET.fromstring(first)
        item = next(i for i in root if i.get('name') == '[B]סדרות חדשות[/B]')
        item.set('name', 'My renamed shows')
        item.set('thumb', 'custom.png')
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        rows = _items(self._refresh())
        self.assertEqual(sum('action=tmdb_tv_premieres' in i.text for i in rows), 1)
        self.assertTrue(any(i.get('name') == 'My renamed shows' and i.get('thumb') == 'custom.png' for i in rows))

    def test_untouched_label_upgrade_does_not_duplicate_or_move_tile(self):
        first = self._refresh()
        config = generator._load_config()
        config['tiles']['shows_new']['name'] = '[B]Updated new shows[/B]'
        with mock.patch.object(generator, '_load_config', return_value=config):
            rows = _items(self._refresh())
        old = [i.get('name') for i in _items(first)]
        new = [i.get('name') for i in rows]
        self.assertEqual(new, ['[B]Updated new shows[/B]' if n == '[B]סדרות חדשות[/B]' else n for n in old])

    def test_delete_before_skin_excludes_tile_stays_deleted_on_return(self):
        self._refresh()
        root = ET.fromstring(self._installed().read_text('utf8'))
        name = '[B]הסדרות שלי (MDBList)[/B]'
        root[:] = [i for i in root if i.get('name') != name]
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        self._refresh('skin.arctic.fuse.3')
        self.assertNotIn(name, [i.get('name') for i in _items(self._refresh())])

    def test_explicit_readd_clears_stable_deletion(self):
        first = self._refresh()
        root = ET.fromstring(first)
        tile = next(i for i in root if i.get('name') == '[B]סדרות חדשות[/B]')
        root.remove(tile)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        self._refresh()
        root = ET.fromstring(self._installed().read_text('utf8'))
        root.append(tile)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        self.assertEqual(_items(self._refresh())[-1].get('name'), tile.get('name'))

    def test_concurrent_refreshes_serialize_xml_and_baseline(self):
        import threading, time
        original=generator._generate_favourites_xml
        active=[0]; peak=[0]; results=[]
        def run(*args):
            active[0]+=1;peak[0]=max(peak[0],active[0]);time.sleep(.08)
            try: return original(*args)
            finally: active[0]-=1
        with mock.patch.object(generator, '_generate_favourites_xml', side_effect=run):
            threads=[threading.Thread(target=lambda:results.append(self._refresh())) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(5)
        self.assertEqual(peak[0],1);self.assertEqual(len(results),2)
        self.assertTrue(all(result for result in results))
        baseline,_=generator._load_state()
        self.assertEqual({i.get('name') for i in _items(baseline)},
                         {i.get('name') for i in _items(self._installed().read_text('utf8'))})

    def test_connecting_mdblist_inserts_each_tile_in_its_personal_group(self):
        self.visibility.active.remove('mdblist')
        first = self._refresh('skin.povil.nox')
        before = [i.get('name') for i in _items(first)]
        self.visibility.active.add('mdblist')
        after = [i.get('name') for i in _items(self._refresh('skin.povil.nox'))]
        for media in ('הסרטים', 'הסדרות'):
            mdbl = '[B]%s שלי (MDBList)[/B]' % media
            pov = '[B]%s שלי (POV)[/B]' % media
            self.assertEqual(after.index(mdbl), after.index(pov) + 1)
        self.assertEqual([n for n in after if n in before], before)

    def test_legacy_appended_mdblist_tiles_repaired_once_and_edits_preserved(self):
        import json
        first = self._refresh()
        root = ET.fromstring(first)
        for item in list(root):
            if 'action=mdblist_my_' in (item.text or ''):
                root.remove(item)
                root.append(item)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        state_path = Path(generator._state_file())
        state = json.loads(state_path.read_text('utf8'))
        state.pop('layout_version')
        state_path.write_text(json.dumps(state), 'utf8')
        repaired = self._refresh()
        self.assertEqual([i.get('name') for i in _items(repaired)], [i.get('name') for i in _items(first)])
        root = ET.fromstring(repaired)
        item = next(i for i in root if 'action=mdblist_my_movies' in (i.text or ''))
        root.remove(item)
        root.append(item)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        # A later deliberate move stays authoritative on every refresh.
        self.assertEqual(_items(self._refresh())[-1].get('name'), item.get('name'))

    def test_legacy_edited_mdblist_tail_is_not_moved(self):
        import json
        first = self._refresh()
        root = ET.fromstring(first)
        item = next(i for i in root if 'action=mdblist_my_movies' in (i.text or ''))
        root.remove(item)
        item.set('thumb', 'my-icon.png')
        root.append(item)
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        path = Path(generator._state_file())
        state = json.loads(path.read_text('utf8')); state.pop('layout_version')
        path.write_text(json.dumps(state), 'utf8')
        self.assertEqual(_items(self._refresh())[-1].get('thumb'), 'my-icon.png')

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
        self.assertTrue(any('action=mdblist_my_movies' in path for path in mdblist_widgets))
        self.assertTrue(any('action=mdblist_my_tvshows' in path for path in mdblist_widgets))

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

    def test_stale_build_watchlist_routes_repair_without_baseline_and_keep_order_icons(self):
        import json
        desired = self._refresh('skin.povil.nox')
        for lost_baseline in (False, True):
            root = ET.fromstring(desired)
            for item in root:
                if 'action=mdblist_my_' in (item.text or ''):
                    item.text = item.text.replace('action=mdblist_my_movies',
                        'action=mdblist_watchlist').replace('action=mdblist_my_tvshows',
                        'action=mdblist_watchlist').replace('name=MDBList', 'name=MDBList%20Watchlist')
                    item.set('thumb', 'my-custom-thumbnail.png')
            root[:] = list(reversed(list(root)))
            self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
            state_path = Path(generator._state_file())
            if lost_baseline:
                state_path.unlink()
            else:
                state = json.loads(state_path.read_text('utf8'))
                # Baseline already canonical, installed legacy route wrongly
                # considered an edit by the previous three-way merge.
                self.assertIn('action=mdblist_my_', state['baseline'])
            repaired = _items(self._refresh('skin.povil.nox'))
            self.assertEqual([i.get('name') for i in repaired], [i.get('name') for i in root])
            for item in repaired:
                if 'MDBList' in item.get('name'):
                    self.assertEqual(item.get('thumb'), 'my-custom-thumbnail.png')
                    self.assertIn('action=mdblist_my_', item.text)
                    self.assertNotIn('Watchlist', item.text)
            self.assertEqual(_items(self._refresh('skin.povil.nox'))[-1].get('name'), root[-1].get('name'))

    def test_custom_filtered_watchlist_and_deleted_build_tile_stay_authoritative(self):
        first = self._refresh()
        root = ET.fromstring(first)
        for item in list(root):
            if 'action=mdblist_my_movies' in (item.text or ''):
                root.remove(item)
            elif 'action=mdblist_my_tvshows' in (item.text or ''):
                item.text = item.text.replace('action=mdblist_my_tvshows',
                                              'action=mdblist_watchlist')
                item.text = item.text.replace('&name=MDBList', '&name=MDBList&filter=unwatched')
                custom = item.text
        self._installed().write_text(ET.tostring(root, encoding='unicode'), 'utf8')
        repaired = _items(self._refresh())
        self.assertFalse(any('action=mdblist_my_movies' in i.text for i in repaired))
        self.assertTrue(any(i.text == custom for i in repaired))

    def test_legacy_encoded_icon_route_repairs_but_custom_or_ambiguous_queries_do_not(self):
        from urllib.parse import urlencode
        desired = ET.fromstring(self._refresh())
        target = next(i for i in desired if 'action=mdblist_my_tvshows' in i.text)
        by_name = {i.get('name'): i for i in desired}
        params = dict(action='mdblist_watchlist', mode='build_tvshow_list',
                      name='MDBList Watchlist', iconImage=(
                          'special://home/addons/plugin.video.pov/resources/'
                          'skins/Default/media/mdblist.png'))
        for extra, should_repair in (('', True), ('&action=mdblist_watchlist', False),
                                    ('&list_id=123', False)):
            item = ET.fromstring(ET.tostring(target))
            original = 'ActivateWindow(10025,"plugin://plugin.video.pov/?%s%s",return)' % (urlencode(params), extra)
            item.text = original
            generator._repair_mdbl_personal(item, by_name)
            self.assertEqual(item.text, target.text if should_repair else original)
        for change in ({'iconImage': 'my-icon.png'}, {'mode': 'build_movie_list'},
                       {'name': 'My custom Watchlist'}):
            item = ET.fromstring(ET.tostring(target))
            original = 'ActivateWindow(10025,"plugin://plugin.video.pov/?%s",return)' % urlencode(dict(params, **change))
            item.text = original
            generator._repair_mdbl_personal(item, by_name)
            self.assertEqual(item.text, original)


if __name__ == '__main__':
    unittest.main()
