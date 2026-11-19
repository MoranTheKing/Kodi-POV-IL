"""The "שליחת לוג" tile runs the Wizard's uploader: POV 6.11.03 has no "Changelog & Log Utils" menu."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# (by its file: the Wizard's "resources" package must not take the name from MoranSubs' in other tests)
_spec = importlib.util.spec_from_file_location(
    'qa_favourites_repair', ROOT / 'plugin.program.kodipovilwizard/resources/libs/favourites_repair.py')
favourites_repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(favourites_repair)

spec = importlib.util.spec_from_file_location(
    'qa_af3_send_log', ROOT / 'service.subtitles.kodipovilai/resources/lib/af3_home_patcher.py')
af3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(af3)

OLD = ('ActivateWindow(10025,"plugin://plugin.video.pov/?iconImage=special%3a%2f%2fhome%2faddons%2fplugin.video.pov'
       '%2fresources%2fskins%2fDefault%2fmedia%2fsettings.png&amp;mode=navigator.log_utils&amp;name=Changelog%20%26'
       '%20Log%20Utils",return)')
NEW = 'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=uploadlog")'
FAVOURITES = ('<favourites>\r\n'
              '    <favourite name="[B]סרטים[/B]" thumb="special://home/media/m.png">ActivateWindow(10025,"plugin://plugin.video.pov/?mode=movies",return)</favourite>\r\n'
              '    <favourite name="[B]שליחת לוג[/B]" thumb="special://home/media/povil_icons/twilight_send_log.png">%s</favourite>\r\n'
              '</favourites>\r\n')


class FavouritesSendLogTests(unittest.TestCase):
    def test_the_shipped_file_is_left_to_the_start_up_repair(self):
        # (a new settings pack would need a new bundled seed: the repair covers a new install too)
        for name in ('userdata/favourites.xml',):
            self.assertIn('mode=navigator.log_utils', (ROOT / name).read_text(encoding='utf-8'),
                          'the shipped file still has it: the start-up repair is what fixes it')

    def test_the_tile_runs_the_uploader_and_keeps_its_name_picture_and_place(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'favourites.xml')
            with open(path, 'wb') as handle:
                handle.write((FAVOURITES % OLD).encode('utf-8'))
            said = []
            self.assertEqual(favourites_repair.run(path, log=said.append), 1)
            with open(path, 'rb') as handle:
                fixed = handle.read()
            self.assertEqual(fixed, (FAVOURITES % NEW).encode('utf-8'))
            self.assertEqual(len(said), 1)
            # nothing to repair the next time: the file is only read
            before = os.path.getmtime(path)
            self.assertEqual(favourites_repair.run(path, log=said.append), 0)
            self.assertEqual(os.path.getmtime(path), before)
            self.assertEqual(len(said), 1)
            self.assertEqual(os.listdir(folder), ['favourites.xml'])

    def test_no_file_and_other_favourites_are_left(self):
        self.assertEqual(favourites_repair.run(os.path.join(tempfile.gettempdir(), 'no-such-dir-povil', 'f.xml')), 0)
        content = (FAVOURITES % NEW).encode('utf-8')
        self.assertEqual(favourites_repair.repoint(content), (content, 0))

    def test_the_wizard_tools_row_and_af3_menu_run_the_uploader(self):
        wizard = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/wizard.py').read_text(encoding='utf-8')
        self.assertNotIn('?mode=navigator.log_utils', wizard)
        self.assertIn("'builtin': '%s'" % NEW, wizard)
        rows = [row for row in af3.POWER_MENU if row['label'] == 'שליחת לוג']
        self.assertEqual([row['path'] for row in rows], [NEW])

    def test_an_af3_menu_gets_the_new_command_in_the_same_place(self):
        old = {'label': 'שליחת לוג', 'icon': 'special://home/media/povil_icons/twilight_send_log.png',
               'path': 'ActivateWindow(10025,"plugin://plugin.video.pov/?mode=navigator.log_utils'
                       '&name=Changelog%20%26%20Log%20Utils",return)', 'target': ''}
        first = {'label': 'POV', 'icon': 'p.png', 'path': 'RunAddon("plugin.video.pov")', 'target': ''}
        last = {'label': 'יציאה', 'icon': 'q.png', 'path': 'Quit()', 'target': ''}
        new = dict(old, path=NEW)
        name = 'skinvariables-shortcut-powermenu.json'
        files = {af3.AF3_NODES + name: json.dumps([first, dict(old, label='לוג'), last]),
                 af3.POV_BASELINE_DIR + name: json.dumps([first, old, last])}
        with patch.object(af3, '_exists', side_effect=lambda p: p in files), \
                patch.object(af3, '_read', side_effect=files.__getitem__), \
                patch.object(af3, '_write', side_effect=files.__setitem__), \
                patch.object(af3, '_mkdir'):
            self.assertTrue(af3._merge_widget_nodes(name, [first, new, last]))
        # one row, where it was, with the viewer's own label and the uploader
        self.assertEqual(json.loads(files[af3.AF3_NODES + name]), [first, dict(new, label='לוג'), last])


if __name__ == '__main__':
    unittest.main()
