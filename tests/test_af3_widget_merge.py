"""AF3 home widgets: the build's updates never undo what the user set in AF3's editor."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'qa_af3_widget_merge', ROOT / 'service.subtitles.kodipovilai/resources/lib/af3_home_patcher.py')
af3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(af3)

FILE = 'skinvariables-shortcut-homewidgets.json'
MOVIES = {'label': 'Movies', 'icon': 'm.png', 'path': 'plugin://plugin.video.pov/?mode=movies',
          'target': 'videos', 'widget_style': 'Poster', 'widget_limit': '20'}
SHOWS = {'label': 'Shows', 'icon': 's.png', 'path': 'plugin://plugin.video.pov/?mode=shows',
         'target': 'videos', 'widget_style': 'Poster', 'widget_limit': '20'}
WATCHLIST = {'label': 'Watchlist', 'icon': 'w.png', 'path': 'plugin://plugin.video.pov/?mode=watchlist',
             'target': 'videos', 'widget_style': 'Landscape', 'widget_limit': '20'}


class Device:
    """The node file and our baseline sidecar, as one device keeps them between boots."""

    def __init__(self, current=None, baseline=None):
        self.files = {}
        if current is not None:
            self.files[af3.AF3_NODES + FILE] = json.dumps(current)
        if baseline is not None:
            self.files[af3.POV_BASELINE_DIR + FILE] = json.dumps(baseline)

    def boot(self, canonical, **kwargs):
        with patch.object(af3, '_exists', side_effect=lambda p: p in self.files), \
                patch.object(af3, '_read', side_effect=self.files.__getitem__), \
                patch.object(af3, '_write', side_effect=self.files.__setitem__), \
                patch.object(af3, '_mkdir'):
            return af3._merge_widget_nodes(FILE, canonical, **kwargs)

    @property
    def node(self):
        return json.loads(self.files[af3.AF3_NODES + FILE])

    def edit(self, rows):
        """What AF3's widget editor (script.skinvariables) writes: its own
        format, and a guid on every tile that has none."""
        rows = [dict(row, guid=row.get('guid') or 'guid-%08x' % n) for n, row in enumerate(rows)]
        self.files[af3.AF3_NODES + FILE] = json.dumps(rows, indent=2)
        return rows


class AF3WidgetMergeTests(unittest.TestCase):
    def test_a_widget_disabled_in_af3_stays_disabled(self):
        # Field report: "I disabled widgets in the settings, and after every
        # update they are back" -- AF3 marks a disabled tile in the tile itself.
        device = Device()
        device.boot([MOVIES, SHOWS])
        edited = device.edit([MOVIES, dict(SHOWS, disabled='True')])
        self.assertFalse(device.boot([MOVIES, SHOWS]), 'nothing to write: no AF3 rebuild on every boot')
        self.assertEqual(device.node, edited)
        self.assertEqual(device.node[1]['disabled'], 'True')

    def test_user_edits_win_and_our_other_updates_still_arrive(self):
        device = Device()
        device.boot([MOVIES, SHOWS])
        edited = device.edit([dict(MOVIES, label='My movies', widget_style='Landscape'), SHOWS])
        newer = [dict(MOVIES, widget_limit='30', icon='m2.png'), dict(SHOWS, widget_limit='30')]
        self.assertTrue(device.boot(newer))
        self.assertEqual(device.node, [
            dict(edited[0], widget_limit='30', icon='m2.png'),
            dict(edited[1], widget_limit='30')])
        self.assertFalse(device.boot(newer))

    def test_a_disabled_widget_can_be_enabled_again(self):
        device = Device()
        device.boot([MOVIES, SHOWS])
        edited = device.edit([MOVIES, dict(SHOWS, disabled='True')])
        device.boot([MOVIES, SHOWS])
        edited = device.edit([edited[0], dict(edited[1], disabled='')])   # AF3's toggle writes '' back
        device.boot([MOVIES, SHOWS])
        self.assertEqual(device.node, edited)

    def test_a_removed_widget_hidden_for_a_while_stays_removed(self):
        # The watchlist row is ours only while its service is connected; a
        # boot with it disconnected must not make it "brand-new" afterwards.
        device = Device()
        device.boot([MOVIES, SHOWS, WATCHLIST])
        edited = device.edit([MOVIES, SHOWS])    # the user removes it
        device.boot([MOVIES, SHOWS])            # service disconnected for one boot
        device.boot([MOVIES, SHOWS, WATCHLIST])  # connected again
        self.assertEqual(device.node, edited)

    def test_a_row_first_offered_later_still_arrives(self):
        device = Device()
        device.boot([MOVIES, SHOWS])            # never connected yet
        device.boot([MOVIES, SHOWS, WATCHLIST])  # the user connects the service
        self.assertEqual(device.node, [MOVIES, SHOWS, WATCHLIST])

    def test_retired_rows_are_not_remembered(self):
        device = Device([MOVIES, WATCHLIST], [MOVIES, WATCHLIST])
        device.boot([MOVIES], retired_keys=(WATCHLIST['path'],))
        self.assertEqual(device.node, [MOVIES])
        edited = device.edit([MOVIES, WATCHLIST])  # the user adds the same path back by hand
        device.boot([MOVIES], retired_keys=(WATCHLIST['path'],))
        self.assertEqual(device.node, edited, 'a row the user added again is theirs')

    def test_lost_baseline_refreshes_tiles_to_ours(self):
        device = Device([dict(MOVIES, widget_limit='7'), SHOWS], None)
        device.boot([MOVIES, SHOWS])
        self.assertEqual(device.node, [MOVIES, SHOWS])

    def test_lost_baseline_keeps_what_only_the_user_set(self):
        # e.g. MoranSubs' data cleared: the switch and the editor's guids stay
        device = Device([dict(MOVIES, widget_limit='7', guid='guid-1'),
                         dict(SHOWS, disabled='True', guid='guid-2')], None)
        device.boot([MOVIES, SHOWS])
        self.assertEqual(device.node, [dict(MOVIES, guid='guid-1'), dict(SHOWS, disabled='True', guid='guid-2')])

    def test_a_row_missing_from_the_baseline_still_gets_our_updates(self):
        # hidden at the last 0.3.54 start (service disconnected): not in its baseline
        device = Device([MOVIES, dict(WATCHLIST, widget_limit='7', disabled='True', guid='guid-3')], [MOVIES])
        device.boot([MOVIES, WATCHLIST])
        self.assertEqual(device.node, [MOVIES, dict(WATCHLIST, disabled='True', guid='guid-3')])

    def test_old_mdblist_route_upgrades_and_keeps_the_users_choices(self):
        canonical = [dict(row) for row in af3.HOME_WIDGETS if 'action=mdblist_my_movies' in row.get('path', '')]
        self.assertEqual(len(canonical), 1)
        legacy = dict(canonical[0], path=canonical[0]['path'].replace('action=mdblist_my_movies', 'action=mdblist_watchlist'))
        device = Device([dict(legacy, disabled='True', guid='guid-4', label='Mine')], [legacy])
        device.boot(canonical)
        self.assertEqual(device.node, [dict(canonical[0], disabled='True', guid='guid-4', label='Mine')])

    def test_a_copied_tile_and_widgets_of_its_own_are_kept(self):
        device = Device()
        device.boot([MOVIES, SHOWS])
        own = [{'label': 'Mine', 'path': 'plugin://plugin.video.pov/?mode=mine'}]
        edited = device.edit([MOVIES, dict(SHOWS, widgets=own), dict(SHOWS, label='Shows again')])
        device.boot([MOVIES, dict(SHOWS, widget_limit='30')])
        self.assertEqual(device.node, [edited[0], dict(edited[1], widget_limit='30'),
                                       dict(edited[2], widget_limit='30')])


if __name__ == '__main__':
    unittest.main()
