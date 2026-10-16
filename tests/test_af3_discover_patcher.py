"""Arctic Fuse 3 discover grid: the POV path must land on AF3 3.3.12 too.

3.3.12 rebuilt the discover tab, so the stock `<visible>` line the patcher
restores after an old flip no longer exists in any form. That repair-only
slot used to fail the whole file, leaving the grid on TMDbHelper's
`&with_text_query=` suffix that POV cannot read once the user types.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
           / 'af3_discover_pov_patcher.py')

CONTENT_STOCK = (
    '<param name="content">'
    '$INFO[window(home).property(tmdbhelper.userdiscover.folderpath)]'
    '$INFO[Control.GetLabel(3000).index(1),&amp;with_text_query=,]</param>')
CONTENT_POV = (
    '<param name="content">'
    '$INFO[window(home).property(tmdbhelper.userdiscover.folderpath)]'
    '$VAR[Path_SearchTerm_SingleEncoded,&amp;query=,]</param>')
ONCLICK = ('<onclick>RunPlugin(plugin://plugin.video.themoviedb.helper/'
           '?info=user_discover$INFO[Window(Home).Property(TMDbHelper.'
           'UserDiscover.Folderpath.ParamString),&amp;,])</onclick>')

# Timing-free shapes of the discover tab, AF3 3.3.12 and before.
AF3_3312 = '\n'.join([
    '<includes>',
    '    <include name="Search_Switcher_Discover_Items">',
    '        <item>',
    '            ' + ONCLICK,
    '            <visible>!Container(501).IsUpdating</visible>',
    '        </item>',
    '    </include>',
    '    ' + CONTENT_STOCK,
    '</includes>',
    ''])
AF3_OLD = '\n'.join([
    '<includes>',
    '    <item>',
    '        ' + ONCLICK,
    '        <visible>!Integer.IsEqual(Container(501).NumItems,0)</visible>',
    '    </item>',
    '    ' + CONTENT_STOCK,
    '</includes>',
    ''])
CUSTOM_1105 = '\n'.join([
    '<window>',
    '    <onload>SetProperty(TMDbHelper.UserDiscover.FolderPath,'
    'plugin://plugin.video.themoviedb.helper/?info=discover&amp;with_id=True'
    '&amp;tmdb_type=movie,Home)</onload>',
    '    <onload>SetProperty(TMDbHelper.UserDiscover.FolderPath.Name,'
    '$LOCALIZE[467] $LOCALIZE[342],Home)</onload>',
    '</window>',
    ''])


class Af3DiscoverPatcherTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.dir = os.path.join(self.home, 'addons', 'skin.arctic.fuse.3',
                                '1080i')
        os.makedirs(self.dir)
        vfs = types.SimpleNamespace(translatePath=lambda p: self.home + os.sep)
        with patch.dict(sys.modules, {'xbmcvfs': vfs}):
            spec = importlib.util.spec_from_file_location('af3_discover', PATCHER)
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)
        self.mod.xbmcvfs = vfs
        self.mod.kodi_utils = None

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), 'w', encoding='utf-8') as f:
            f.write(text)

    def read(self, name):
        with open(os.path.join(self.dir, name), encoding='utf-8') as f:
            return f.read()

    def run_on(self, includes):
        self.write('Includes_Search.xml', includes)
        self.write('Custom_1105_Search.xml', CUSTOM_1105)
        return self.mod.ensure_patched()

    def test_af3_3_3_12_gets_the_pov_grid(self):
        self.assertEqual(self.run_on(AF3_3312), '1105=patched, search=patched')
        text = self.read('Includes_Search.xml')
        self.assertIn(CONTENT_POV, text)
        self.assertNotIn('with_text_query', text)
        # Nothing invented for the tab 3.3.12 rebuilt.
        self.assertIn('<visible>!Container(501).IsUpdating</visible>', text)
        self.assertNotIn('Integer.IsEqual(Container(501).NumItems,0)', text)
        self.assertEqual(self.mod.ensure_patched(),
                         '1105=already_patched, search=already_patched')

    def test_older_af3_is_patched_as_before(self):
        self.assertEqual(self.run_on(AF3_OLD), '1105=patched, search=patched')
        self.assertIn(CONTENT_POV, self.read('Includes_Search.xml'))

    def test_an_old_flip_is_still_restored(self):
        flipped = AF3_OLD.replace(ONCLICK, '<onclick>SetFocus(501)</onclick>')
        flipped = flipped.replace(
            '<visible>!Integer.IsEqual(Container(501).NumItems,0)</visible>',
            '<visible>true</visible>')
        self.run_on(flipped)
        text = self.read('Includes_Search.xml')
        self.assertIn(ONCLICK, text)
        self.assertIn('<visible>!Integer.IsEqual(Container(501).NumItems,0)'
                      '</visible>', text)

    def test_a_skin_without_the_grid_line_is_left_alone(self):
        changed = AF3_3312.replace(CONTENT_STOCK, '<param name="x"/>')
        status = self.run_on(changed)
        self.assertIn('search=unmatched', status)
        self.assertEqual(self.read('Includes_Search.xml'), changed)


if __name__ == '__main__':
    unittest.main()
