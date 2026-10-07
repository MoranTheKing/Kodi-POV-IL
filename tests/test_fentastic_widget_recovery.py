"""A saved widget must survive regeneration and an addon replacement."""
import ast
import hashlib
from contextlib import closing
import importlib.util
import sqlite3
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
spec = importlib.util.spec_from_file_location('widget_recovery', LIB/'fentastic_widgets.py')
widgets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(widgets)


class WidgetRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.addons = root/'addons'; self.userdata = root/'userdata'
        self.xml = self.addons/'skin.fentastic/xml/script-fentastic-widget_movies.xml'
        self.xml.parent.mkdir(parents=True)
        self.db = self.userdata/'addon_data/script.fentastic.helper/cpath_cache.db'
        self.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('CREATE TABLE custom_paths (cpath_setting text unique, cpath_path text, '
                      'cpath_header text, cpath_type text, cpath_label text)')

    def save(self, index, url, header='My movies', kind='WidgetListBigPoster', label='Poster'):
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('INSERT INTO custom_paths VALUES (?,?,?,?,?)',
                      ('movie.widget.%s' % index, url, header, kind, label))
            c.commit()

    def repair(self):
        return widgets.repair_saved_widgets(str(self.addons), str(self.userdata))

    def test_missing_popular_row_restored_between_existing_rows_and_survives_second_boot(self):
        self.save(2, 'plugin://test/new')
        self.save(3, 'plugin://plugin.video.pov/?action=tmdb_movies_popular&amp;mode=build_movie_list')
        self.save(4, 'plugin://test/networks')
        root = ET.Element('includes'); group=ET.SubElement(root,'include',name='MovieWidgets')
        for i,url in ((2,'plugin://test/new'),(4,'plugin://test/networks')):
            node=widgets._block('WidgetListBigPoster',url,'My movies',19010+i)
            ET.SubElement(node,'param',name='limit',value='12'); group.append(node)
        self.xml.write_bytes(ET.tostring(root))
        original_db=self.db.read_bytes()
        self.assertEqual(self.repair(),1)
        rows=ET.parse(self.xml).findall("include/include")
        self.assertEqual([widgets._params(x)['list_id'] for x in rows],['19012','19013','19014'])
        self.assertIn('&mode=',widgets._params(rows[1])['content_path'])
        self.assertEqual(widgets._params(rows[0])['limit'],'12')
        repaired=self.xml.read_bytes()
        self.assertEqual(self.repair(),0)
        self.assertEqual(self.xml.read_bytes(),repaired)
        self.assertEqual(self.db.read_bytes(),original_db)

    def test_addon_default_cannot_replace_saved_custom_widget(self):
        self.save(3,'plugin://test/my-list?sort=custom&owner=me','My "A & B"')
        root=ET.Element('includes'); group=ET.SubElement(root,'include',name='MovieWidgets')
        node=widgets._block('WidgetListBigPoster','plugin://test/default','Default',19013)
        ET.SubElement(node,'param',name='sortorder',value='descending');group.append(node)
        self.xml.write_bytes(ET.tostring(root)); self.assertEqual(self.repair(),1)
        row=ET.parse(self.xml).find('include/include')
        self.assertEqual(widgets._params(row)['content_path'],'plugin://test/my-list?sort=custom&owner=me')
        self.assertEqual(widgets._params(row)['widget_header'],'My "A & B"')
        self.assertEqual(widgets._params(row)['sortorder'],'descending')

    def test_empty_database_does_not_resurrect_intentionally_removed_widgets(self):
        self.xml.write_text('<includes><include name="MovieWidgets"/></includes>','utf8')
        before=self.xml.read_bytes();self.assertEqual(self.repair(),0)
        self.assertEqual(self.xml.read_bytes(),before)

    def test_missing_generated_file_and_stacked_rows_use_saved_paths(self):
        self.save(1,'plugin://test/categories','Categories','WidgetListPoster','Poster | Stacked')
        self.assertEqual(self.repair(),1)
        nodes=ET.parse(self.xml).findall('include/include')
        self.assertEqual([widgets._params(n)['list_id'] for n in nodes],['19011','190111'])
        self.assertEqual(nodes[0].get('content'),'WidgetListCategoryStacked')
        self.assertEqual(self.repair(),0)

    def test_unknown_layout_and_duplicate_custom_ids_are_preserved(self):
        self.save(3,'plugin://test/popular')
        for payload in ('<includes><include name="PrivateLayout"/></includes>',
                        '<includes><include name="MovieWidgets">'+
                        '<include><param name="list_id" value="19013"/></include>'*2+
                        '</include></includes>'):
            self.xml.write_text(payload,'utf8');before=self.xml.read_bytes()
            self.assertEqual(self.repair(),0);self.assertEqual(self.xml.read_bytes(),before)

    def test_helper_regeneration_keeps_escaped_url_and_quote_header(self):
        helper=self.addons/'script.fentastic.helper/resources/lib/modules/cpath_maker.py'
        helper.parent.mkdir(parents=True)
        source='''class CPaths:
    def make_widget_xml(self, active_cpaths):
        final_format = '<includes>'
        for cpath_type, cpath_path, cpath_header in active_cpaths:
            body = '<include content="{cpath_type}"><param name="content_path" value="{cpath_path}"/><param name="widget_header" value="{cpath_header}"/></include>'
            body = body.format(
                cpath_type=cpath_type,
                cpath_path=cpath_path,
                cpath_header=cpath_header,
            )
            if not "&amp;" in body:
                final_format += body.replace("&", "&amp;")
        return final_format + '</includes>'
    def write_xml(self, *args):
        pass
'''
        helper.write_text(source,'utf8')
        ns={};exec(source,ns)
        records=[('WidgetListPoster','plugin://test/?a=1&amp;b=2','A &amp; "B"')]
        self.assertEqual(len(ET.fromstring(ns['CPaths']().make_widget_xml(records))),0)
        self.assertTrue(widgets.repair_helper(str(self.addons)))
        ns={};exec(helper.read_text('utf8'),ns)
        node=ET.fromstring(ns['CPaths']().make_widget_xml(records)).find('include')
        self.assertEqual(widgets._params(node)['content_path'],'plugin://test/?a=1&b=2')
        self.assertEqual(widgets._params(node)['widget_header'],'A & "B"')
        self.assertFalse(widgets.repair_helper(str(self.addons)))


class PopularDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.addons = root/'addons'; self.userdata = root/'userdata'
        self.db = self.userdata/'addon_data/script.fentastic.helper/cpath_cache.db'
        self.db.parent.mkdir(parents=True)
        self.defaults = []
        for media, actions in (('movie', ('new', 'tmdb_movies_popular', 'networks')),
                               ('tvshow', ('new', 'trakt_tv_trending', 'networks'))):
            for index, action in enumerate(actions, 1):
                mode = 'build_movie_list' if media == 'movie' else 'build_tvshow_list'
                self.defaults.append((media+'.widget.'+str(index),
                    'plugin://plugin.video.pov/?mode='+mode+'&action='+action,
                    'Popular' if index == 2 else action, 'WidgetListBigPoster', 'BigPoster'))
        seed = root/'seed.db'
        self.write_database(seed, self.defaults)
        self.archive = root/'defaults.zip'
        with zipfile.ZipFile(self.archive, 'w') as z:
            z.writestr('addon_data/script.fentastic.helper/cpath_cache.db', seed.read_bytes())
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def write_database(self, path, rows):
        with closing(sqlite3.connect(path)) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS custom_paths (cpath_setting text unique, '
                         'cpath_path text, cpath_header text, cpath_type text, cpath_label text)')
            conn.execute('DELETE FROM custom_paths')
            conn.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)', rows);conn.commit()

    def repair(self, digest=None):
        return widgets.restore_popular_defaults(str(self.addons), str(self.userdata),
            str(self.archive), digest or self.digest)

    def rows(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute('SELECT '+widgets.FIELDS+' FROM custom_paths ORDER BY cpath_setting').fetchall()

    def test_missing_movie_and_tv_defaults_restored_once_with_original_backup(self):
        existing = [r for r in self.defaults if not r[0].endswith('.2')]
        self.write_database(self.db, existing)
        self.assertEqual(self.repair(), 2)
        self.assertEqual(self.rows(), sorted(self.defaults))
        with closing(sqlite3.connect(self.db.with_name('cpath_cache.before-popular-v1.db'))) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM custom_paths').fetchone()[0], 4)
        before = self.db.read_bytes()
        self.assertEqual(self.repair(), 0); self.assertEqual(self.db.read_bytes(), before)
        # A user may remove these rows after the migration without resurrection.
        self.write_database(self.db, existing)
        self.assertEqual(self.repair(), 0); self.assertEqual(self.rows(), sorted(existing))

    def test_empty_and_custom_layouts_preserved(self):
        for rows in ([], [('movie.widget.1', 'plugin://other/custom', 'Mine', 'WidgetListPoster', '')]):
            self.write_database(self.db, rows)
            self.assertEqual(self.repair(), 0);self.assertEqual(self.rows(), rows)

    def test_existing_custom_or_moved_popular_slot_not_overwritten(self):
        for scenario in ('custom', 'moved'):
            receipt=self.db.with_name('povil-popular-defaults-v1.json')
            if receipt.exists(): receipt.unlink()
            rows=list(self.defaults)
            if scenario == 'custom':
                rows[1]=('movie.widget.2', 'plugin://other/custom', 'Mine', 'WidgetListPoster', '')
            else:
                rows[1]=('movie.widget.8',)+rows[1][1:]
            self.write_database(self.db, rows)
            self.assertEqual(self.repair(), 0);self.assertEqual(self.rows(), sorted(rows))

    def test_changed_filter_is_a_custom_route_and_prevents_reseeding(self):
        rows=[r for r in self.defaults if r[0].startswith('movie') and not r[0].endswith('.2')]
        rows[0]=(rows[0][0], rows[0][1]+'&genre=family')+rows[0][2:]
        self.write_database(self.db, rows)
        self.assertEqual(self.repair(),0);self.assertEqual(self.rows(),sorted(rows))

    def test_failed_integrity_check_does_not_modify_database_or_create_receipt(self):
        self.write_database(self.db, self.defaults)
        before=self.db.read_bytes()
        with self.assertRaises(ValueError): self.repair('0'*64)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(self.db.with_name('povil-popular-defaults-v1.json').exists())


class BuildIdentityTests(unittest.TestCase):
    def run_case(self, version='0.4.14', pending=False, config_pending=False):
        tree=ast.parse((LIB/'modular_updater.py').read_text('utf8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ModularUpdater')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_record_build_identity')
        settings={'buildversion':'0.1.40'}
        config=types.SimpleNamespace(BUILDVERSION_DEFAULT='0.1.45',get_setting=settings.get,
            set_setting=lambda k,v:settings.__setitem__(k,v))
        namespace={'CONFIG':config}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'identity','exec'),namespace)
        owner=types.SimpleNamespace(_config_pending=lambda m:config_pending,ON_DEMAND_SKINS=('skin.optional',),
            get_local_version=lambda aid:None if aid=='skin.optional' else version,
            _pending_addon_receipt=lambda aid:pending,
            _version_tuple=lambda v:tuple(map(int,v.split('.'))))
        result=namespace['_record_build_identity'](owner,{'addons':{
            'wizard':{'version':'0.4.14'},'skin.optional':{'version':'1.0.0'}}})
        return result,settings

    def test_ota_completion_records_build_version_without_full_install(self):
        result,settings=self.run_case();self.assertTrue(result)
        self.assertEqual(settings['buildversion'],'0.1.45')

    def test_failed_config_extraction_or_old_service_does_not_certify_build(self):
        for options in ({'pending':True},{'config_pending':True},{'version':'0.4.13'}):
            result,settings=self.run_case(**options)
            self.assertFalse(result);self.assertEqual(settings['buildversion'],'0.1.40')
