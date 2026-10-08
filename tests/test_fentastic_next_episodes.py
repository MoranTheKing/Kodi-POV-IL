"""Upgrade an intact TV layout without taking over saved custom widgets."""
from contextlib import closing
import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('next_widgets', ROOT /
    'plugin.program.kodipovilwizard/resources/libs/fentastic_widgets.py')
widgets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(widgets)


class NextEpisodeDefaultsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.addons = self.root/'addons'
        self.userdata = self.root/'userdata'
        self.db = self.userdata/'addon_data/script.fentastic.helper/cpath_cache.db'
        self.db.parent.mkdir(parents=True)
        self.archive = ROOT/'plugin.program.kodipovilwizard/resources/bootstrap/config.zip'
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(self.archive) as z:
            self.db.write_bytes(z.read('addon_data/script.fentastic.helper/cpath_cache.db'))
        widgets.align_default_order(str(self.addons), str(self.userdata),
                                    str(self.archive), self.digest)
        self.before = self.rows()
        self.tv = [r for r in self.before if r[0].startswith('tvshow.widget.')]
        self.xml = self.addons/'skin.fentastic/xml/script-fentastic-widget_tvshows.xml'
        self.xml.parent.mkdir(parents=True)

    def rows(self, database=None):
        with closing(sqlite3.connect(database or self.db)) as c:
            return c.execute('SELECT '+widgets.FIELDS+' FROM custom_paths ORDER BY cpath_setting').fetchall()

    def save(self, rows):
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('DELETE FROM custom_paths')
            c.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)', rows)
            c.commit()

    def migrate(self, digest=None):
        return widgets.seed_next_episode_default(str(self.addons), str(self.userdata),
            str(self.archive), digest or self.digest)

    def test_default_preview_precedes_new_popular_and_survives_regeneration(self):
        self.assertEqual(self.migrate(), 1)
        tv = [r for r in self.rows() if r[0].startswith('tvshow.widget.')]
        self.assertEqual([r[0] for r in tv], ['tvshow.widget.'+str(i) for i in range(1,7)])
        self.assertEqual(tv[1][1], widgets.NEXT_EPISODES)
        self.assertEqual(tv[1][3], 'WidgetListBigEpisodes')
        self.assertEqual([widgets._path_identity(r[1])[3:5] for r in tv[2:4]],
                         [widgets.NEW_RELEASES['tvshow'], widgets.POPULAR['tvshow']])
        self.assertEqual([r[1:] for r in tv[2:]], [r[1:] for r in self.tv[1:]])
        self.assertEqual([r for r in self.rows() if not r[0].startswith('tvshow.widget.')],
                         [r for r in self.before if not r[0].startswith('tvshow.widget.')])
        self.assertEqual(self.rows(self.db.with_name('cpath_cache.before-next-episode-v1.db')), self.before)
        self.assertGreater(widgets.repair_saved_widgets(str(self.addons), str(self.userdata)), 0)
        nodes = ET.parse(self.xml).findall('include/include')
        self.assertEqual([widgets._params(n)['list_id'] for n in nodes], [str(i) for i in range(22011,22017)])
        self.assertEqual(nodes[1].get('content'), 'WidgetListBigEpisodes')
        self.assertEqual(self.migrate(), 0)
        self.assertEqual(widgets.repair_saved_widgets(str(self.addons), str(self.userdata)), 0)

    def test_row_options_follow_their_route_when_slots_shift(self):
        root = ET.Element('includes')
        group = ET.SubElement(root,'include',name='TVShowWidgets')
        for index, row in enumerate(self.tv, 1):
            node = widgets._block(row[3], row[1], row[2], 22010+index)
            ET.SubElement(node,'param',name='limit',value=str(10+index))
            ET.SubElement(node,'param',name='sortorder',value='descending')
            group.append(node)
        self.xml.write_bytes(ET.tostring(root))
        self.assertEqual(self.migrate(),1)
        widgets.repair_saved_widgets(str(self.addons), str(self.userdata))
        nodes = ET.parse(self.xml).findall('include/include')
        self.assertNotIn('sortorder', widgets._params(nodes[1]))
        self.assertNotIn('limit', widgets._params(nodes[1]))
        for index, node in enumerate(nodes[2:],2):
            self.assertEqual(widgets._params(node)['limit'],str(10+index))
            self.assertEqual(widgets._params(node)['sortorder'],'descending')

    def test_deliberate_removal_is_not_resurrected_on_next_boot(self):
        self.assertEqual(self.migrate(),1)
        self.save([r for r in self.rows() if r[1] != widgets.NEXT_EPISODES])
        before = self.rows()
        self.assertEqual(self.migrate(),0)
        self.assertEqual(self.rows(),before)

    def test_custom_filtered_moved_incomplete_and_existing_next_layouts_are_preserved(self):
        scenarios = []
        scenarios.append([])
        scenarios.append(self.before + [('tvshow.widget.6','plugin://private/custom','Mine','WidgetListPoster','Poster')])
        scenarios.append([(r[0],r[1]+'&genre=family')+r[2:] if r==self.tv[1] else r for r in self.before])
        scenarios.append([('tvshow.widget.8',)+r[1:] if r==self.tv[1] else r for r in self.before])
        scenarios.append([r for r in self.before if r != self.tv[1]])
        scenarios.append([(r[0], widgets.NEXT_EPISODES)+r[2:] if r==self.tv[1] else r for r in self.before])
        for rows in scenarios:
            with self.subTest(rows=len(rows)):
                receipt = self.db.with_name('povil-next-episode-v1.json')
                if receipt.exists(): receipt.unlink()
                self.save(rows)
                before = self.rows()
                self.assertEqual(self.migrate(),0)
                self.assertEqual(self.rows(),before)

    def test_bad_defaults_digest_cannot_change_the_live_layout(self):
        before = self.db.read_bytes()
        with self.assertRaises(ValueError): self.migrate('0'*64)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(self.db.with_name('povil-next-episode-v1.json').exists())


if __name__ == '__main__': unittest.main()
