"""skin.povil.onyx: the package, the generated XML, and the Wizard pieces it relies on."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
XML = SKIN / 'xml'
TOOLS = ROOT / 'tools' / 'skin_onyx'
PATCHES = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs' / 'patches'
LIBS = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'


class SkinPackageTests(unittest.TestCase):
    def test_every_xml_file_parses(self):
        for path in sorted(XML.glob('*.xml')):
            with self.subTest(path.name):
                ET.parse(path)

    def test_addon_identity_and_dependencies(self):
        root = ET.parse(SKIN / 'addon.xml').getroot()
        self.assertEqual(root.get('id'), 'skin.povil.onyx')
        self.assertEqual([i.get('addon') for i in root.iter('import')], ['xbmc.gui'])
        res = root.find("extension[@point='xbmc.gui.skin']/res")
        self.assertEqual(res.get('folder'), 'xml', 'the Wizard looks for Home.xml in xml/')

    def test_within_the_release_limits(self):
        files = [p for p in SKIN.rglob('*') if p.is_file()]
        self.assertLessEqual(len(files), 2000)
        self.assertLessEqual(sum(p.stat().st_size for p in files), 30 * 1024 * 1024)
        self.assertFalse([p for p in files if p.suffix == '.pyc' or '__pycache__' in p.parts])

    def test_every_build_texture_exists(self):
        used = set()
        for path in XML.glob('*.xml'):
            used.update(re.findall(r'povil/[A-Za-z0-9_/]+\.(?:png|jpg)', path.read_text(encoding='utf-8')))
        self.assertTrue(used)
        missing = sorted(t for t in used if not (SKIN / 'media' / t).is_file())
        self.assertEqual(missing, [])

    def test_every_font_is_defined(self):
        fonts = ET.parse(XML / 'Font.xml').getroot()
        defined = {f.findtext('name') for f in fonts.find("fontset[@id='Default']").iter('font')}
        for name in defined:
            filename = fonts.find("fontset[@id='Default']/font[name='%s']" % name).findtext('filename')
            self.assertTrue((SKIN / 'fonts' / filename).is_file(), filename)
        used = set()
        for path in XML.glob('*.xml'):
            used.update(re.findall(r'<font>([A-Za-z0-9_]+)</font>', path.read_text(encoding='utf-8')))
        self.assertEqual(sorted(used - defined), [])

    def test_hebrew_strings(self):
        po = (SKIN / 'language' / 'resource.language.he_il' / 'strings.po').read_text(encoding='utf-8')
        self.assertGreater(po.count('msgstr "') - po.count('msgstr ""'), 180)

    def test_home_starts_the_wizard_profile_bootstrap(self):
        home = (XML / 'Home.xml').read_text(encoding='utf-8')
        self.assertIn('plugin.program.kodipovilwizard/profile_bootstrap.py', home)
        self.assertIsNotNone(ET.parse(XML / 'Home.xml').getroot().find('controls'),
                             'child_profiles.install_home needs a root <controls>')

    def test_build_actions_are_wired(self):
        osd = (XML / 'VideoOSD.xml').read_text(encoding='utf-8')
        self.assertIn('RunScript(service.subtitles.kodipovilai,action=choose_subs)', osd)
        self.assertIn('kodipovilwizard/?mode=player_change_source', osd)
        self.assertIn('kodipovilwizard/?mode=player_episodes', osd)
        menu = (XML / 'DialogButtonMenu.xml').read_text(encoding='utf-8')
        for action in ('?action=force_close', '?mode=profile_skin', '?mode=profiles'):
            self.assertIn(action, menu)
        self.assertNotIn('<onclick>Quit()</onclick>', menu)
        keyboard = (XML / 'DialogKeyboard.xml').read_text(encoding='utf-8')
        self.assertIn('<onclick>VoiceRecognizer</onclick>', keyboard)
        self.assertIn('id="9010"', keyboard)


class GeneratedXmlTests(unittest.TestCase):
    """The generated files are what the generators write (nobody edited them by hand)."""

    def test_down_and_up_skip_any_number_of_empty_rows(self):
        # favourites: saved shows (5063), then MDBList movies and shows (5064, 5065),
        # both empty without an MDBList account: Down must not land on a hidden row
        home = ET.parse(XML / 'Home.xml').getroot()
        lists = {c.get('id'): c for c in home.iter('control') if c.get('type') == 'list'}
        downs = [(n.get('condition'), n.text) for n in lists['5063'].findall('ondown')]
        self.assertEqual([t for _c, t in downs], ['5064', '5065'])
        self.assertIn('!Integer.IsGreater(Container(5064).NumItems,0)', downs[1][0])
        ups = [(n.get('condition'), n.text) for n in lists['5065'].findall('onup')]
        self.assertEqual([t for _c, t in ups], ['5064', '5063', '5062', '5061', '9172'])

    def test_the_touch_keymap_swipes_between_home_rows(self):
        import ast
        tree = ast.parse((SKIN / 'scripts' / 'onyx_tools.py').read_text(encoding='utf-8'))
        xml = next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                   and getattr(node.targets[0], 'id', '') == 'TOUCH_KEYMAP_XML')
        swipes = {s.get('direction'): s.text for s in ET.fromstring(xml).find('home').find('touch')}
        # a swipe only names itself: under any other skin it moves nothing
        self.assertEqual(swipes, {'up': 'SetProperty(povil.swipe,down,home)',
                                  'down': 'SetProperty(povil.swipe,up,home)'})
        home = (XML / 'Home.xml').read_text(encoding='utf-8')
        self.assertIn('System.Platform.Android', home.split('touchkeymap')[0].rsplit('<onload', 1)[1])
        self.assertIn('<onload>ClearProperty(povil.swipe,home)</onload>', home)
        timers = ET.parse(XML / 'Timers.xml').getroot()
        timer = next(t for t in timers.iter('timer') if t.findtext('name') == 'povil_swipe')
        acts = [(a.get('condition') or '', a.text) for a in timer.findall('onstart')]
        self.assertEqual([t for _c, t in acts], ['SetFocus($INFO[Window(home).Property(povil.focus)])', 'Action(Down)',
                                                 'Action(Up)', 'ClearProperty(povil.swipe,home)'])
        # a finger on the hero took the focus away: it goes back where it was first,
        # else Down would land on the window's default, the first tab
        self.assertIn('String.IsEmpty(System.CurrentControlId)', acts[0][0])
        self.assertIn('Window.IsActive(home)', acts[1][0])
        self.assertIn('Window.IsActive(home)', acts[2][0])

    def test_a_touch_outside_the_rows_leaves_them_where_they_were(self):
        home = ET.parse(XML / 'Home.xml').getroot()
        controls = {c.get('id'): c for c in home.iter('control') if c.get('id')}
        for cid in ('9010', '5031', '5032', '9112'):
            with self.subTest(cid):
                self.assertIn('SetProperty(povil.focus,%s,home)' % cid, [n.text for n in controls[cid].findall('onfocus')])
        text = (XML / 'Home.xml').read_text(encoding='utf-8')
        self.assertIn('[Control.HasFocus(5032) | [String.IsEmpty(System.CurrentControlId) + '
                      'String.IsEqual(Window(home).Property(povil.focus),5032)]]', text)

    def test_a_picture_without_a_backdrop_becomes_a_soft_wash(self):
        home = ET.parse(XML / 'Home.xml').getroot()
        images = {c.get('description'): c for c in home.iter('control') if c.get('type') == 'image'}
        self.assertEqual(images['ambient wash: the small copy is made'].findtext('texture'), '$VAR[POVIL_HeroAmbient]')
        self.assertEqual(images['ambient wash jpg'].findtext('texture'), '$INFO[Window(home).Property(povil.blur)]')
        # Kodi keeps a picture with transparency (channel logos) as .png
        self.assertEqual(images['ambient wash png'].findtext('texture'), '$INFO[Window(home).Property(povil.blurpng)]')
        timers = ET.parse(XML / 'Timers.xml').getroot()
        timer = next(t for t in timers.iter('timer') if t.findtext('name') == 'povil_blur')
        self.assertIn('System.IdleTime(2)', timer.findtext('start'))
        self.assertEqual(images['ambient wash: the small copy is made'].findtext('visible'), 'System.IdleTime(1)')
        self.assertEqual([n.text for n in timer.findall('onstart')],
                         ['SetProperty(povil.blur,$INFO[Control.GetLabel(9803)],home)',
                          'SetProperty(povil.blurpng,$INFO[Control.GetLabel(9804)],home)'])
        includes = (XML / 'Includes_POVIL_Home.xml').read_text(encoding='utf-8')
        self.assertIn('!System.HasModalDialog', timer.findtext('start'), 'a dialog over the home reads no 9803')
        root = ET.fromstring('<r>%s</r>' % includes.split('<includes>', 1)[1].rsplit('</includes>', 1)[0])
        for name, art in (('POVIL_HeroAmbient', 'povil_blur'), ('POVIL_HeroAmbientFile', 'povil_blurfile'),
                          ('POVIL_HeroAmbientPng', 'povil_blurpng')):
            values = [(v.get('condition') or '', v.text or '') for v in root.find("variable[@name='%s']" % name)]
            self.assertTrue(any('ListItem.Art(%s)' % art in t for _c, t in values))
            self.assertFalse(any('Container(5032)' in t for _c, t in values), 'a landscape row has a backdrop of its own')
            # every focused row ends the variable -- with nothing when it wants no wash --
            # before the tabs' fallbacks (Reshet focused must not wash in Keshet's colours)
            stops = [i for i, (c, t) in enumerate(values) if not t and 'Control.HasFocus(' in c]
            fallback = next(i for i, (c, _t) in enumerate(values) if c.startswith('String.IsEqual(Window(home).Property(povil.tab),'))
            for rid in (5031, 5032, 5033, 5041, 5042, 5011):
                with self.subTest(name=name, row=rid):
                    self.assertTrue(any('Control.HasFocus(%d)' % rid in values[i][0] and i < fallback for i in stops))

    def test_rows_retry_and_say_empty_only_when_the_retries_are_spent(self):
        home = ET.parse(XML / 'Home.xml').getroot()
        movies_btn = next(c for c in home.iter('control') if c.get('id') == '9010')
        resets = [n for n in movies_btn.findall('onfocus') if 'povil.retry.5011' in (n.text or '')]
        self.assertEqual(len(resets), 1, 'choosing the tab again asks again')
        self.assertIn('String.IsEqual(Window(home).Property(povil.retry.5011),2)', resets[0].get('condition'))
        text = (XML / 'Home.xml').read_text(encoding='utf-8')
        empty = re.findall(r'<visible>([^<]*povil\.retry\.5011[^<]*)</visible>', text)
        self.assertTrue(empty)
        for cond in empty:
            self.assertNotIn('!!', cond)
        self.assertTrue(any('!Integer.IsGreater(Container(5011).NumItems,0) + !String.IsEqual(Window(home).Property(povil.retry.5011),2)' in c
                            for c in empty), 'the placeholder stays up while it retries')
        self.assertTrue(any(c.startswith('!String.IsEmpty(') and '+ String.IsEqual(Window(home).Property(povil.retry.5011),2)' in c
                            for c in empty), '"nothing here" only once the retries are spent')

    def test_the_player_buttons_reach_each_other(self):
        # Kodi links a grouplist's items by id: a gap without one ended the chain, and
        # left / right fell through to the video and seeked (field report: "only 10 seconds")
        osd = ET.parse(XML / 'VideoOSD.xml').getroot()
        row = next(c for c in osd.iter('control') if c.get('id') == '7000')
        self.assertEqual((row.findtext('onleft'), row.findtext('onright')), ('7000', '7000'))
        children = [c for c in row if c.tag == 'control']
        self.assertTrue(children)
        self.assertTrue(all(c.get('id') for c in children))
        self.assertIn('7024', [c.get('id') for c in children])

    def test_conditions_group_with_brackets(self):
        # Kodi groups a condition with [ ] only; "!(" splits it into broken parts
        for name in ('Home.xml', 'Includes_POVIL_Home.xml', 'View_POVIL.xml', 'Timers.xml', 'DialogKeyboard.xml'):
            with self.subTest(name):
                self.assertNotIn('!(', (XML / name).read_text(encoding='utf-8'))

    def test_generators_reproduce_the_skin(self):
        tmp = Path(tempfile.mkdtemp(prefix='povil-onyx-'))
        try:
            copy = tmp / 'skin.povil.onyx'
            shutil.copytree(SKIN, copy)
            for script in ('gen_strings.py', 'patch_onyx.py', 'gen_home.py', 'gen_views.py', 'gen_osd.py', 'gen_info.py', 'gen_dialogs.py'):
                subprocess.run([sys.executable, str(TOOLS / script), str(copy)], cwd=str(TOOLS), check=True,
                               stdout=subprocess.DEVNULL)
            for rel in ('xml/Home.xml', 'xml/Includes_POVIL_Home.xml', 'xml/View_POVIL.xml', 'xml/VideoOSD.xml',
                        'xml/DialogVideoInfo.xml', 'xml/Timers.xml', 'xml/DialogKeyboard.xml',
                        'xml/DialogButtonMenu.xml', 'xml/DialogBusy.xml', 'xml/DialogNotification.xml', 'xml/DialogConfirm.xml',
                        'language/resource.language.he_il/strings.po'):
                with self.subTest(rel):
                    self.assertEqual((copy / rel).read_bytes(), (SKIN / rel).read_bytes())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _plugin_stub():
    calls = []
    mod = types.SimpleNamespace(
        SORT_METHOD_NONE=0, SORT_METHOD_UNSORTED=40, SORT_METHOD_LABEL=1, SORT_METHOD_EPISODE=24,
        addDirectoryItem=lambda handle, url, listitem, isFolder=False, totalItems=0: calls.append(('one', url)),
        addDirectoryItems=lambda handle, items, totalItems=0: calls.append(('many', [i[0] for i in items])),
        addSortMethod=lambda handle, sortMethod, *a, **k: calls.append(('sort', sortMethod)),
        endOfDirectory=lambda handle, succeeded=True, updateListing=False, cacheToDisc=True: calls.append(('end',)),
        setContent=lambda handle, content: calls.append(('content', content)))
    return mod, calls


class _Item:
    def __init__(self, label=''):
        self.props = {}
        self.art = {}
        self.label = label

    def getLabel(self):
        return self.label

    def getProperty(self, key):
        return self.props.get(key, '')

    def setProperty(self, key, value):
        self.props[key] = value

    def getArt(self, key):
        return self.art.get(key, '')

    def setArt(self, values):
        self.art.update(values)


class RtlPatchTests(unittest.TestCase):
    def _run(self, query, skin='skin.povil.onyx', window=10000, view='51', pov=True, umbrella=False, umbrella_db='',
             sort=None, plugin=None, content='movies', keep_module=False, home=None, labels=('', '', ''),
             pinned=None, argv0='plugin://plugin.video.pov/', builtins=None, thumbs=None):
        if plugin is None:
            plugin, calls = _plugin_stub()
        else:
            plugin, calls = plugin
        home = {} if home is None else home
        home_window = types.SimpleNamespace(
            getProperty=lambda k: home.get(k, view if k.startswith('pov_view.') else ''),
            setProperty=home.__setitem__)
        fake = {'xbmcplugin': plugin,
                'xbmc': types.SimpleNamespace(getSkinDir=lambda: skin,
                                              executebuiltin=(builtins if builtins is not None else []).append),
                'xbmcgui': types.SimpleNamespace(getCurrentWindowId=lambda: window,
                                                 Window=lambda _id: home_window),
                'xbmcvfs': types.SimpleNamespace(translatePath=lambda _p: umbrella_db)}
        saved = {k: sys.modules.get(k) for k in fake}
        sys.modules.update(fake)
        sys.path.insert(0, str(PATCHES))
        argv = sys.argv
        try:
            if not keep_module:
                sys.modules.pop('povil_rtl', None)
            import povil_rtl
            sys.argv = [argv0, '1', query]
            povil_rtl.install(pov=pov and not umbrella, umbrella=umbrella)
            items = [_Item(label) for label in labels]
            for index, where in (pinned or {}).items():
                items[index].props['SpecialSort'] = where
            for index, thumb in (thumbs or {}).items():
                items[index].art['thumb'] = thumb
            if sort is not None:
                plugin.addSortMethod(1, sort)
            plugin.setContent(1, content)
            plugin.addDirectoryItems(1, [('a', items[0], False), ('b', items[1], False)])
            plugin.addDirectoryItem(1, 'c', items[2], True)
            plugin.endOfDirectory(1)
            return calls, items
        finally:
            sys.argv = argv
            sys.path.remove(str(PATCHES))
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_flagged_home_row_is_reversed_and_marked(self):
        calls, items = self._run('?mode=build_movie_list&povil_rtl=1', skin='skin.povil.nox')
        self.assertIn(('many', ['c', 'b', 'a']), calls)
        self.assertEqual(calls[-1], ('end',))
        self.assertTrue(all(i.props.get('povil_rtl') == '1' for i in items))

    def test_home_row_items_carry_their_picture_shrunk_by_kodi(self):
        thumb = 'https://raw.githubusercontent.com/Fishenzon/repo/master/plugin.video.idanplus/images/kan.jpg'
        logo = 'https://raw.githubusercontent.com/Fishenzon/repo/master/plugin.video.idanplus/images/88fm.png'
        _calls, items = self._run('?mode=1&povil_rtl=1', pov=False, thumbs={0: thumb, 2: logo},
                                  argv0='plugin://plugin.video.idanplus/')
        small = ('image://https%3A%2F%2Fraw.githubusercontent.com%2FFishenzon%2Frepo%2Fmaster%2Fplugin.video.idanplus'
                 '%2Fimages%2Fkan.jpg/transform?width=10')
        self.assertEqual(items[0].art['povil_blur'], small)
        self.assertTrue(items[0].art['povil_blurfile'].startswith('special://thumbnails/'))
        self.assertTrue(items[0].art['povil_blurfile'].endswith('.jpg'))
        self.assertEqual(items[0].art['povil_blurpng'], '', 'a JPEG is never kept as .png')
        self.assertEqual(items[2].art['povil_blurpng'], items[2].art['povil_blurfile'][:-4] + '.png')
        self.assertNotIn('povil_blur', items[1].art, 'no picture, nothing to shrink')
        sys.path.insert(0, str(PATCHES))
        try:
            import povil_rtl
            # names Kodi itself gave these addresses in the QA Kodi's texture database
            self.assertEqual(povil_rtl._kodi_cache_file(
                'image://https%3A%2F%2Fraw.githubusercontent.com%2FFishenzon%2Frepo%2Fmaster%2Fplugin.video.idanplus'
                '%2Fimages%2Fkan.jpg%7Cverifypeer%3Dfalse/transform?width=10'), 'special://thumbnails/5/53019bca.jpg')
            self.assertEqual(povil_rtl._kodi_cache_file(thumb), 'special://thumbnails/8/8593df64.jpg')
        finally:
            sys.path.remove(str(PATCHES))
        _calls, items = self._run('?mode=build_movie_list', window=10025, view='51', thumbs={0: thumb})
        self.assertNotIn('povil_blur', items[0].art, 'full screen lists draw their own backdrop')

    def test_a_pinned_next_page_keeps_its_end_in_a_name_sort(self):
        calls, items = self._run('?mode=1&povil_rtl=1', sort=1, pov=False,
                                 labels=('ג', 'Next page', 'א'), pinned={1: 'bottom'})
        self.assertIn(('many', ['b', 'a', 'c']), calls, 'next page last, then reversed: far left')

    def test_full_screen_pov_list_in_an_onyx_horizontal_view(self):
        calls, _items = self._run('?mode=build_movie_list', window=10025, view='51')
        self.assertIn(('many', ['c', 'b', 'a']), calls)

    def test_umbrella_lists_follow_its_views_for_onyx(self):
        import sqlite3
        tmp = Path(tempfile.mkdtemp(prefix='povil-umb-'))
        try:
            db = str(tmp / 'views.db')
            calls, _items = self._run('?action=movies&url=trending', window=10025, umbrella=True, umbrella_db=db)
            self.assertIn(('many', ['c', 'b', 'a']), calls, 'seeded view 51 for Onyx: reversed')
            con = sqlite3.connect(db)
            rows = dict(con.execute("SELECT view_type, view_id FROM views WHERE skin='skin.povil.onyx'").fetchall())
            self.assertEqual(rows, {'movies': '51', 'tvshows': '51', 'seasons': '51', 'episodes': '55'})
            con.execute("UPDATE views SET view_id='50' WHERE skin='skin.povil.onyx' AND view_type='movies'")
            con.commit(); con.close()
            calls, _items = self._run('?action=movies&url=trending', window=10025, umbrella=True, umbrella_db=db)
            self.assertNotIn(('many', ['c', 'b', 'a']), calls, "the user's own view is kept and not reversed")
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT view_id FROM views WHERE skin='skin.povil.onyx' AND view_type='movies'").fetchone()[0], '50')
            con.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_umbrella_views_are_seeded_once_per_session(self):
        tmp = Path(tempfile.mkdtemp(prefix='povil-umb-'))
        try:
            db = tmp / 'views.db'
            home = {}
            self._run('?action=movies&url=trending', window=10025, umbrella=True, umbrella_db=str(db), home=home)
            self.assertTrue(db.exists())
            db.unlink()
            self._run('?action=movies&url=trending', window=10000, umbrella=True, umbrella_db=str(db), home=home)
            self.assertFalse(db.exists(), 'later requests in the same session leave the database alone')
            other = tmp / 'profile2'
            other.mkdir()
            self._run('?action=movies&url=trending', window=10000, umbrella=True,
                      umbrella_db=str(other / 'views.db'), home=home)
            self.assertTrue((other / 'views.db').exists(), "another profile's Umbrella gets its own views")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_umbrella_views_wait_for_umbrellas_folder(self):
        tmp = Path(tempfile.mkdtemp(prefix='povil-umb-'))
        try:
            db = tmp / 'missing' / 'views.db'
            home = {}
            self._run('?action=movies&url=trending', window=10025, umbrella=True, umbrella_db=str(db), home=home)
            self.assertEqual(home, {}, 'not marked before Umbrella has its data folder')
            db.parent.mkdir()
            self._run('?action=movies&url=trending', window=10025, umbrella=True, umbrella_db=str(db), home=home)
            self.assertTrue(db.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_reused_interpreter_decides_for_each_request(self):
        # Idan Plus (and POV with fast navigation) keep xbmcplugin wrapped between requests
        stub = _plugin_stub()
        calls, _items = self._run('?mode=1&povil_rtl=1', skin='skin.povil.nox', pov=False, plugin=stub)
        self.assertIn(('many', ['c', 'b', 'a']), calls)
        del calls[:]
        calls, items = self._run('?mode=1', skin='skin.povil.nox', pov=False, plugin=stub, keep_module=True)
        self.assertIn(('many', ['a', 'b']), calls, 'a later plain request passes straight through')
        self.assertFalse(any(i.props for i in items))
        del calls[:]
        calls, _items = self._run('?mode=build_movie_list', window=10025, plugin=stub, keep_module=True)
        self.assertIn(('many', ['c', 'b', 'a']), calls, 'and the next Onyx full-screen list is reversed again')

    def test_season_episodes_start_on_episode_one(self):
        calls, items = self._run('?mode=build_episode_list', window=10025, view='55', sort=24, content='episodes')
        self.assertIn(('many', ['c', 'b', 'a']), calls)
        self.assertEqual([c[1] for c in calls if c[0] == 'sort'], [40], "the list's own order only: a saved sort cannot undo it")
        self.assertTrue(all(i.props.get('povil_rtl') == '1' for i in items))

    def test_episode_lists_follow_their_own_pov_view(self):
        # next episodes, in progress, calendars use view.episodes_lists (not set): no reversal
        calls, items = self._run('?mode=build_next_episode', window=10025, view='', content='episodes', sort=24)
        self.assertNotIn(('many', ['c', 'b', 'a']), calls)

    def test_a_list_sorted_another_way_keeps_its_order(self):
        calls, items = self._run('?mode=1&povil_rtl=1', sort=3, pov=False)   # by date
        self.assertNotIn(('many', ['c', 'b', 'a']), calls)
        self.assertFalse(any(i.props for i in items))
        self.assertIn(('sort', 3), calls)

    def test_a_name_sorted_list_starts_with_alef_on_the_right(self):
        # Idan Plus with its A-Z setting: the names sorted here, then reversed
        calls, items = self._run('?mode=1&povil_rtl=1', sort=1, pov=False,
                                 labels=('[B]פרק 10[/B]', 'בית', 'פרק 2'))
        self.assertIn(('many', ['a', 'c', 'b']), calls, 'reversed: פרק 10, פרק 2, בית')
        self.assertEqual([c[1] for c in calls if c[0] == 'sort'], [40], 'the reversed list only')
        self.assertTrue(all(i.props.get('povil_rtl') == '1' for i in items))

    def test_idan_plus_full_screen_lists_turn_right_to_left_in_view_51(self):
        views = []
        saved = sys.modules.get('pov_view_mode')
        sys.modules['pov_view_mode'] = types.SimpleNamespace(force_view=lambda view, content: views.append((view, content)))
        try:
            calls, items = self._run('?mode=2&module=kan', window=10025, pov=False, content='episodes',
                                     argv0='plugin://plugin.video.idanplus/')
        finally:
            if saved is None:
                sys.modules.pop('pov_view_mode', None)
            else:
                sys.modules['pov_view_mode'] = saved
        self.assertIn(('many', ['c', 'b', 'a']), calls)
        self.assertEqual(views, [('51', 'episodes')], 'view 51 once the list is on screen')
        self.assertNotIn(('content', 'tvshows'), calls, 'a list with playable items keeps its content')

    def test_other_requests_keep_their_order(self):
        for kwargs in ({'window': 10025, 'view': '50'}, {'window': 10000}, {'skin': 'skin.povil.nox', 'window': 10025}):
            with self.subTest(kwargs):
                calls, items = self._run('?mode=build_movie_list', **kwargs)
                self.assertNotIn(('many', ['c', 'b', 'a']), calls)
                self.assertFalse(any(i.props for i in items))


class LogoLanguageTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(PATCHES))
        import pov_logo_lang
        self.mod = pov_logo_lang

    def tearDown(self):
        sys.path.remove(str(PATCHES))

    def test_hebrew_logo_preferred_and_marked(self):
        data = {'images': {'logos': [{'iso_639_1': 'en', 'file_path': '/en.png'},
                                     {'iso_639_1': 'he', 'file_path': '/he.png'}]}}
        self.assertEqual(self.mod.pick(data, 'he-IL', '/en.png'), '/he.png?lang=he')
        self.assertEqual(self.mod.pick({'images': {'logos': []}}, 'he', '/en.png'), '/en.png')
        self.assertEqual(self.mod.pick(data, 'en', '/en.png'), '/en.png')

    def test_logo_for_a_hebrew_screen(self):
        hebrew_title = chr(0x05E1) + chr(0x05E8) + chr(0x05D8)
        self.assertEqual(self.mod.for_ui({'title': hebrew_title}, 'https://x/he.png?lang=he'), 'https://x/he.png?lang=he')
        self.assertEqual(self.mod.for_ui({'title': hebrew_title}, 'https://x/en.png'), '')
        self.assertEqual(self.mod.for_ui({'title': 'FBI'}, 'https://x/en.png'), 'https://x/en.png')
        self.assertEqual(self.mod.for_ui({'title': 'FBI'}, ''), '')


class WizardRegistryTests(unittest.TestCase):
    def test_onyx_is_a_known_build_skin(self):
        self.assertIn("'skin.povil.onyx'", (LIBS / 'build_skin.py').read_text(encoding='utf-8').split('SKINS = ', 1)[1].split(NL)[0])
        self.assertIn("('skin.povil.onyx', 'Onyx')", (LIBS / 'build_profiles.py').read_text(encoding='utf-8'))
        self.assertIn("'skin.povil.onyx'", (LIBS / 'child_profiles.py').read_text(encoding='utf-8').split('SKINS = ', 1)[1].split(NL)[0])
        self.assertIn("'skin.povil.onyx'", (LIBS / 'addon_origins.py').read_text(encoding='utf-8'))
        wizard = (LIBS / 'wizard.py').read_text(encoding='utf-8')
        self.assertIn("': 'skin.povil.onyx'", wizard)
        self.assertIn("if not ensure_onyx_installed():", wizard)
        updater = (LIBS / 'modular_updater.py').read_text(encoding='utf-8')
        self.assertIn("OPTIONAL_SKINS = frozenset(('skin.povil.onyx',))", updater)

    def test_rtl_patches_are_registered_first_in_their_entry_scripts(self):
        ns = {}
        exec((PATCHES / 'patches_config.py').read_text(encoding='utf-8'), ns)
        by_id = {p['id']: p for p in ns['PATCH_CONFIG']}
        self.assertEqual(by_id['pov_rtl_rows']['anchor'], "if __name__ == '__main__':")
        self.assertEqual(by_id['pov_rtl_rows']['action'], 'prepend_before')
        self.assertEqual(by_id['idanplus_rtl_rows']['anchor'], 'from sys import argv')
        self.assertEqual(by_id['idanplus_rtl_rows']['action'], 'append_after')
        self.assertEqual(by_id['umbrella_rtl_rows']['anchor'], 'from resources.lib.modules import router')
        for pid in ('pov_rtl_rows', 'idanplus_rtl_rows', 'umbrella_rtl_rows', 'pov_logo_language', 'pov_logo_for_ui'):
            compile(by_id[pid]['hook'], pid, 'exec')


NL = chr(10)

if __name__ == '__main__':
    unittest.main()
