"""Legacy compressed layouts must retain both catalogues after helper rebuilds."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalogue_widgets',
    ROOT/'plugin.program.kodipovilwizard/resources/libs/fentastic_widgets.py')
widgets = importlib.util.module_from_spec(spec); spec.loader.exec_module(widgets)
ARCHIVE = ROOT/'plugin.program.kodipovilwizard/resources/bootstrap/config.zip'
DIGEST = '20f3f23b5571bc48be7313096e144fd01e903b346b050ca9a7a2899a92963f85'


class CataloguePairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addons = self.root/'addons'; self.profile = self.root/'profile'
        self.folder = self.profile/'addon_data/script.fentastic.helper'
        self.folder.mkdir(parents=True); self.db = self.folder/'cpath_cache.db'
        seed = self.root/'seed.db'
        with zipfile.ZipFile(ARCHIVE) as source:
            seed.write_bytes(source.read('addon_data/script.fentastic.helper/cpath_cache.db'))
        with closing(sqlite3.connect(seed)) as conn:
            self.defaults = conn.execute('SELECT '+widgets.FIELDS+' FROM custom_paths').fetchall()
        self.legacy = []
        for media, missing in (('movie', widgets.POPULAR['movie']),
                               ('tvshow', widgets.NEW_RELEASES['tvshow'])):
            rows = sorted([r for r in self.defaults if r[0].startswith(media+'.widget.')
                           and widgets._path_identity(r[1])[3:5] != missing])
            self.legacy.extend((media+'.widget.'+str(i),)+r[1:] for i, r in enumerate(rows, 1))
        self.write(self.legacy)
        for name, value in (('povil-popular-defaults-v1.json', {'restored': []}),
                            ('povil-new-before-popular-v1.json', {'aligned': []})):
            (self.folder/name).write_text(json.dumps(value), 'utf8')

    def write(self, rows):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS custom_paths (cpath_setting text unique, '
                         'cpath_path text, cpath_header text, cpath_type text, cpath_label text)')
            conn.execute('DELETE FROM custom_paths')
            conn.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)', rows); conn.commit()

    def rows(self, path=None):
        with closing(sqlite3.connect(path or self.db)) as conn:
            return conn.execute('SELECT '+widgets.FIELDS+' FROM custom_paths ORDER BY cpath_setting').fetchall()

    def recover(self, digest=DIGEST):
        return widgets.restore_catalogue_pair(str(self.addons), str(self.profile), str(ARCHIVE), digest)

    def test_old_compacted_movie_and_tv_pairs_recover_despite_noop_v1_receipts(self):
        other = ('custom1.widget.1', 'plugin://private/custom', 'Mine', 'WidgetListPoster', 'Poster')
        self.write(self.legacy+[other]); self.assertEqual(self.recover(), 2)
        result = self.rows()
        self.assertIn(other, result)
        for media in ('movie', 'tvshow'):
            rows = [r for r in result if r[0].startswith(media+'.widget.')]
            self.assertEqual(len(rows), 5)
            self.assertEqual(widgets._path_identity(rows[1][1])[3:5], widgets.NEW_RELEASES[media])
            self.assertEqual(widgets._path_identity(rows[2][1])[3:5], widgets.POPULAR[media])
            for old in [r for r in self.legacy if r[0].startswith(media+'.widget.')]:
                self.assertIn(old[1:], [r[1:] for r in rows])
        self.assertEqual(self.rows(self.folder/'cpath_cache.before-catalogue-v2.db'), sorted(self.legacy+[other]))
        self.assertEqual(self.recover(), 0)

    def test_generated_routes_and_options_follow_their_rows_after_slot_insertion(self):
        xml = self.addons/'skin.fentastic/xml'; xml.mkdir(parents=True)
        for media, filename in (('movie', 'movies'), ('tvshow', 'tvshows')):
            root = ET.Element('includes'); group = ET.SubElement(root, 'include', name=widgets.GROUPS[media][0])
            for row in [r for r in self.legacy if r[0].startswith(media+'.widget.')]:
                node = widgets._block(row[3], row[1], row[2], widgets.GROUPS[media][1]+int(row[0][-1]))
                ET.SubElement(node, 'param', name='item_limit', value=str(11+int(row[0][-1])))
                group.append(node)
            (xml/('script-fentastic-widget_'+filename+'.xml')).write_bytes(ET.tostring(root))
        self.assertEqual(self.recover(), 2)
        self.assertEqual(widgets.repair_saved_widgets(str(self.addons), str(self.profile)), 2)
        for media, filename in (('movie', 'movies'), ('tvshow', 'tvshows')):
            nodes=ET.parse(xml/('script-fentastic-widget_'+filename+'.xml')).findall('include/include')
            self.assertEqual(len(nodes), 5)
            routes = [widgets._path_identity(widgets._params(n)['content_path']) for n in nodes]
            self.assertEqual(routes[1][3:5], widgets.NEW_RELEASES[media])
            self.assertEqual(routes[2][3:5], widgets.POPULAR[media])
            for old in [r for r in self.legacy if r[0].startswith(media+'.widget.')]:
                node=nodes[routes.index(widgets._path_identity(old[1]))]
                self.assertEqual(widgets._params(node)['item_limit'], str(11+int(old[0][-1])))

    def test_public_legacy_genre_spelling_is_recognized_without_replacing_its_url(self):
        legacy=[(r[0], r[1].replace('%27',''))+r[2:] for r in self.legacy]
        self.write(legacy); self.assertEqual(self.recover(), 2)
        for old in legacy:
            self.assertIn(old[1:], [r[1:] for r in self.rows()])
        # A similarly named personal folder is still custom, not a build alias.
        receipt=self.folder/'povil-catalogue-pair-v2.json'; receipt.unlink()
        legacy=[(r[0], r[1].replace('FENtastic+', 'My+FENtastic+'))+r[2:] for r in legacy]
        self.write(legacy); before=self.db.read_bytes()
        self.assertEqual(self.recover(), 0); self.assertEqual(self.db.read_bytes(), before)

    def test_gapped_shipped_slots_can_restore_missing_tv_new(self):
        rows = [r for r in self.defaults if (r[0].startswith('movie.widget.') or
            r[0].startswith('tvshow.widget.')) and widgets._path_identity(r[1])[3:5] not in
            (widgets.POPULAR['movie'], widgets.NEW_RELEASES['tvshow'])]
        self.write(rows); self.assertEqual(self.recover(), 2)

    def test_missing_exact_old_genre_folder_is_seeded_without_replacing_existing_contents(self):
        folder=self.profile/'addon_data/plugin.video.pov'; folder.mkdir(parents=True)
        database=folder/'navigator.db'
        with closing(sqlite3.connect(database)) as c:
            c.execute('CREATE TABLE navigator (list_name text,list_type text,list_contents text)')
            c.executemany('INSERT INTO navigator VALUES (?,?,?)',[
                ("FENtastic - סרטים - ז'אנרים",'shortcut_folder','movie genres'),
                ("FENtastic - סדרות - ז'אנרים",'shortcut_folder','tv genres'),
                ('FENtastic - סדרות - זאנרים','shortcut_folder','my existing genres')])
            c.commit()
        legacy=[(r[0],r[1].replace('%27',''))+r[2:] for r in self.legacy]
        self.write(legacy); self.assertEqual(self.recover(),2)
        with closing(sqlite3.connect(database)) as c:
            self.assertEqual(c.execute('SELECT list_contents FROM navigator WHERE list_name=?',
                ('FENtastic - סרטים - זאנרים',)).fetchone()[0],'movie genres')
            self.assertEqual(c.execute('SELECT list_contents FROM navigator WHERE list_name=?',
                ('FENtastic - סדרות - זאנרים',)).fetchone()[0],'my existing genres')
        with closing(sqlite3.connect(folder/'navigator.before-catalogue-v2.db')) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM navigator').fetchone()[0],3)

    def test_successful_previous_repair_protects_later_user_removal(self):
        (self.folder/'povil-popular-defaults-v1.json').write_text('{"restored":["movie.widget.3"]}')
        (self.folder/'povil-new-before-popular-v1.json').write_text('{"aligned":["tvshow"]}')
        before=self.db.read_bytes(); self.assertEqual(self.recover(), 0)
        self.assertEqual(self.db.read_bytes(), before)

    def test_user_removal_after_v2_is_not_resurrected(self):
        self.assertEqual(self.recover(), 2); self.write(self.legacy)
        self.assertEqual(self.recover(), 0); self.assertEqual(self.rows(), sorted(self.legacy))

    def test_custom_filtered_moved_stacked_and_empty_layouts_preserved(self):
        for mode in ('custom', 'filtered', 'moved', 'stacked', 'style', 'empty'):
            with self.subTest(mode=mode):
                receipt=self.folder/'povil-catalogue-pair-v2.json'
                if receipt.exists(): receipt.unlink()
                rows=[r for r in self.legacy if r[0].startswith('movie.widget.')]
                row=rows[1]
                if mode=='custom': rows[1]=(row[0], 'plugin://other/custom')+row[2:]
                if mode=='filtered': rows[1]=(row[0], row[1]+'&genre=family')+row[2:]
                if mode=='moved': rows[1]=('movie.widget.8',)+row[1:]
                if mode=='stacked': rows[1]=row[:4]+(row[4]+' | Stacked',)
                if mode=='style': rows[1]=row[:3]+('WidgetListCategory', row[4])
                if mode=='empty': rows=[]
                self.write(rows); before=self.db.read_bytes()
                self.assertEqual(self.recover(), 0); self.assertEqual(self.db.read_bytes(), before)

    def test_integrity_or_bad_old_receipt_does_not_certify_or_change_layout(self):
        before=self.db.read_bytes()
        with self.assertRaises(ValueError): self.recover('0'*64)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertFalse((self.folder/'povil-catalogue-pair-v2.json').exists())
        (self.folder/'povil-popular-defaults-v1.json').write_text('invalid')
        with self.assertRaises(ValueError): self.recover()
        self.assertEqual(self.db.read_bytes(), before)


if __name__=='__main__': unittest.main()
