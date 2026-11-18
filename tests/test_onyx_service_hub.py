"""Onyx 1.0.16: a streaming service's own page in the home (tools/skin_onyx/gen_home.py "service hubs").

A viewer sent another app's page ("the same view as the home, filtered to Netflix / Disney / Apple, with
films / series / all at the top") and its author said to take it. Here it is a tab of the home with no
button: a service's chip names the service in home-window properties and shows the tab.
"""
import importlib.util
import re
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, unquote

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / 'skin.povil.onyx/xml'
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
ROWS = ['50%d' % n for n in range(91, 100)]


class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = ET.parse(XML / 'Home.xml').getroot()
        cls.includes = ET.parse(XML / 'Includes_POVIL_Home.xml').getroot()
        cls.controls = {c.get('id'): c for c in cls.home.iter('control') if c.get('id')}
        cls.variables = {v.get('name'): v for v in cls.includes.findall('variable')}

    def chips(self, tab):
        shown = 'String.IsEqual(Window(home).Property(povil.tab),%s)' % tab
        row = self.controls['9100']
        return [c for c in row if c.tag == 'control' and (c.findtext('visible') or '').startswith(shown)]

    def test_a_services_chip_names_the_service_and_shows_its_page(self):
        for tab, kind in (('movies', 'movie'), ('tv', 'tv')):
            chips = {c.findtext('label'): [n.text for n in c.findall('onclick')] for c in self.chips(tab)}
            netflix = chips['נטפליקס']
            self.assertEqual(netflix[:3], ['SetProperty(povil.hub.id,8,home)', 'SetProperty(povil.hub.net,213,home)',
                                           'SetProperty(povil.hub.name,Netflix,home)'])
            self.assertIn('SetProperty(povil.hub.type,%s,home)' % kind, netflix, 'films from the films tab, series from the series tab')
            self.assertLess(netflix.index('SetProperty(povil.hub.type,%s,home)' % kind), netflix.index('SetProperty(povil.tab,hub,home)'))
            self.assertEqual(netflix[-1], 'SetProperty(povil.hub.enter,1,home)')
            for label in ('דיסני+', 'Apple TV+', 'Prime Video'):
                self.assertIn('SetProperty(povil.tab,hub,home)', chips[label], label)
            self.assertNotIn('Paramount+', chips, 'its provider id answered two series: no nearly empty page')

    def test_the_page_has_no_button_in_the_tab_bar_and_back_leaves_it(self):
        tabs = self.controls['9000']
        # (Onyx 1.0.18: the bar is a list of the tabs' buttons; nine tabs)
        buttons = [c for c in tabs.iter('control') if c.get('type') == 'togglebutton']
        self.assertEqual(len(buttons), 9)
        self.assertNotIn('hub', ' '.join(c.get('description') for c in buttons))
        for chip in self.chips('hub'):
            self.assertEqual((chip.findtext('onup'), chip.findtext('onback')), ('9000', '9000'), chip.findtext('label'))
        for rid in ROWS:
            self.assertEqual(self.controls[rid].findtext('onback'), '9000')
        # the power button still sits beside the leftmost tab, the settings (the first cell of the list)
        self.assertEqual(buttons[0].get('description'), 'tab settings')
        self.assertEqual(self.controls['9099'].findtext('onright'), buttons[0].get('id'))

    def test_the_pressed_chip_leaving_the_screen_does_not_bring_its_tab_back(self):
        # Kodi hands the focus to the window's default -- a tab's button -- when the chip that was pressed
        # goes with its tab (seen in the QA Kodi: the page flashed and the films tab was back)
        for button in (c for c in self.controls['9000'].iter('control') if c.get('type') == 'togglebutton'):
            switching = [n for n in button.findall('onfocus') if 'SetProperty(povil.tab' in n.text]
            self.assertEqual(len(switching), 2)
            for node in switching:
                self.assertEqual(node.get('condition'), 'String.IsEmpty(Window(home).Property(povil.hub.enter))')
        timers = {t.findtext('name'): t for t in ET.parse(XML / 'Timers.xml').getroot().findall('timer')}
        enter = timers['povil_hub_enter']
        first = self.chips('hub')[-1]            # written last: the rightmost, read first
        self.assertIn('Control.IsVisible(%s)' % first.get('id'), enter.findtext('start'))
        starts = [(n.text, n.get('condition')) for n in enter.findall('onstart')]
        self.assertEqual(starts[0], ('ClearProperty(povil.hub.enter,home)', None))
        self.assertEqual(len([s for s in starts if s[0].startswith('SetFocus(')]), 3, 'the chip of what is shown')
        self.assertEqual(enter.findtext('stop'), 'true')
        # the mark never outlives the entering: while it is set no tab button chooses its tab
        guard = timers['povil_hub_enter_guard']
        self.assertEqual(guard.findtext('start'), 'String.IsEqual(Window(home).Property(povil.hub.enter),1)')
        for part in ('!String.IsEqual(Window(home).Property(povil.tab),hub)', '!Window.IsActive(home)',
                     'Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_hub_enter_guard),2)'):
            self.assertIn(part, guard.findtext('stop'), 'two seconds at most, whatever happens to the page')
        self.assertEqual(guard.findtext('onstop'), 'ClearProperty(povil.hub.enter,home)')
        self.assertIn('ClearProperty(povil.hub.enter,home)', [n.text for n in self.home.findall('onload')])

    def test_all_films_series_are_one_press_and_the_one_that_is_on_looks_it(self):
        chips = self.chips('hub')
        by_label = {c.findtext('label'): c for c in chips}
        first = chips[-1]
        self.assertEqual(first.findtext('label'), '$INFO[Window(home).Property(povil.hub.name)]  ·  הכול',
                         'the first chip names the service')
        self.assertIsNone(re.search(r' \+ .*hub', first.findtext('visible')), 'it always shows on the page')
        for label, kind in ((first.findtext('label'), 'all'), ('סרטים', 'movie'), ('סדרות', 'tv')):
            chip = by_label[label]
            self.assertEqual([n.text for n in chip.findall('onclick')], ['SetProperty(povil.hub.type,%s,home)' % kind])
            fill = self.variables['POVIL_ChipFill_%s' % chip.get('id')]
            self.assertEqual(fill.find('value').get('condition'), 'String.IsEqual(Window(home).Property(povil.hub.type),%s)' % kind)
            self.assertIn('$VAR[POVIL_ChipFill_%s]' % chip.get('id'), chip.find('texturenofocus').get('colordiffuse'))
        # another service from the page itself: the same rows, another service's lists
        disney = by_label['דיסני+']
        self.assertEqual([n.text for n in disney.findall('onclick')][0], 'SetProperty(povil.hub.id,337,home)')
        self.assertNotIn('SetProperty(povil.hub.type', ' '.join(n.text for n in disney.findall('onclick')), 'what is shown stays')
        self.assertEqual(by_label['חזרה'].findtext('onclick'), 'SetFocus(9000)')

    def test_every_row_asks_tmdb_for_the_service_and_follows_the_choice(self):
        for rid in ROWS:
            values = self.variables['POVIL_Path_%s' % rid].findall('value')
            plain = [v for v in values if 'povil.retry' not in v.get('condition')]
            self.assertEqual(len(plain), 3, rid)
            kinds = []
            for value in plain:
                kind = re.search(r'povil\.hub\.type\),(\w+)\)', value.get('condition')).group(1)
                kinds.append(kind)
                params = dict(parse_qsl(value.text.split('?', 1)[1], keep_blank_values=True))
                self.assertEqual((params['action'], params['povil_hub'], params['povil_rtl']), ('tmdb_media_discover', '1', '1'))
                query = params['query']
                media = 'movie' if params['mode'] == 'build_movie_list' else 'tv'
                self.assertTrue(query.startswith('discover/%s?' % media), query)
                self.assertTrue(query.endswith('&page=%s'), 'POV fills the page number in')
                service = ('with_watch_providers=$INFO[Window(home).Property(povil.hub.id)]' in query or
                           'with_networks=$INFO[Window(home).Property(povil.hub.net)]' in query)
                self.assertTrue(service, query)
                if kind in ('movie', 'tv'):
                    self.assertEqual(media, kind, 'films only, or series only')
                self.assertTrue(params['name'], 'a Hebrew name for the list')
            self.assertEqual(kinds, ['all', 'movie', 'tv'])
            title = self.variables['POVIL_HubTitle_%d' % ROWS.index(rid)]
            self.assertEqual(len(title.findall('value')), 3)
        # "new" lists end today, by Kodi's own date
        new = [v.text for v in self.variables['POVIL_Path_5092'].findall('value') if 'movie)' in v.get('condition')][-1]
        # (to the month, not the day: the address names the saved list, and a day in it is a new copy a day)
        self.assertIn('primary_release_date.lte%3D$INFO[System.Date(yyyy-mm)]-28', new)
        self.assertEqual(unquote(new).count('$INFO['), 2)

    def test_the_first_row_ranks_its_titles_with_a_numeral_beside_each_poster(self):
        row = self.controls['5091']
        include = row.find('include')
        self.assertEqual(include.get('content'), 'POVIL_Item_ranked')
        layout = next(i for i in self.includes.findall('include') if i.get('name') == 'POVIL_Item_ranked')
        ranks = [c for c in layout.iter('control') if c.get('description') == 'rank']
        self.assertEqual(len(ranks), 2, 'at rest and focused')
        for rank in ranks:
            self.assertEqual(rank.findtext('label'), '$INFO[ListItem.Property(povil_rank)]')
            self.assertEqual(rank.findtext('font'), 'povil_rank')
            self.assertIn('new_page=', rank.findtext('visible'), 'never beside the "more" tile')
        self.assertEqual([r.findtext('textcolor') for r in ranks][1], 'povil_gold', "the focused title's numeral is gold")
        # drawn before the poster, so the poster covers the numeral's near side
        for group in layout.iter('control'):
            children = [c.get('description') for c in group if c.tag == 'control']
            if 'rank' in children:
                self.assertEqual(children.index('rank'), 0)
        self.assertIn('<name>povil_rank</name>', (XML / 'Font.xml').read_text('utf-8'))
        # the numeral is the title's place in the add-on's own order: the Wizard's reversed rows carry it
        source = (WIZARD / 'resources/libs/patches/povil_rtl.py').read_text('utf-8')
        self.assertIn("listitem.setProperty('povil_rank', str(len(items) - index))", source)
        # a poster's shape everywhere else: the hero treats the row as a row of posters
        ambient = self.variables['POVIL_HeroAmbient']
        self.assertTrue(any('Container(5091)' in (v.get('condition') or '') and 'Art(fanart)' in (v.get('condition') or '')
                            for v in ambient.findall('value')))

    def test_nine_lists_are_not_asked_for_at_once(self):
        gates = {rid: re.search(r'Property\((povil\.\w+\.hub)\)', self.variables['POVIL_Path_%s' % rid].find('value').get('condition')).group(1)
                 for rid in ROWS}
        self.assertEqual([gates[r] for r in ROWS[:3]], ['povil.tab.hub', 'povil.deep.hub', 'povil.deep.hub'])
        self.assertEqual(set(gates[r] for r in ROWS[3:]), {'povil.far.hub'}, 'the rest once the viewer is among the rows')
        timers = {t.findtext('name'): t for t in ET.parse(XML / 'Timers.xml').getroot().findall('timer')}
        self.assertIn('Control.HasFocus(5091)', timers['povil_far_hub'].findtext('start'))
        # another service chosen from a tab starts the lower rows waiting again
        netflix = next(c for c in self.chips('movies') if c.findtext('label') == 'נטפליקס')
        clicks = [n.text for n in netflix.findall('onclick')]
        self.assertIn('ClearProperty(povil.far.hub,home)', clicks)
        self.assertLess(clicks.index('ClearProperty(povil.far.hub,home)'), clicks.index('SetProperty(povil.tab,hub,home)'))

    def test_the_wizard_keeps_these_lists_and_leaves_povs_discover_history_alone(self):
        env = types.SimpleNamespace(log=lambda *a: None, LOGINFO=1, LOGWARNING=2)
        with mock.patch.dict(sys.modules, {'xbmc': env}):
            spec = importlib.util.spec_from_file_location('snap_hub_test', WIZARD / 'resources/libs/patches/pov_list_snapshot.py')
            snap = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(snap)
        hub = {'mode': 'build_movie_list', 'action': 'tmdb_media_discover', 'povil_hub': '1', 'query': 'x'}
        self.assertTrue(snap.eligible(hub))
        self.assertFalse(snap.eligible(dict(hub, povil_hub='')), "a viewer's own discover search is not kept")
        self.assertFalse(snap.eligible({'mode': 'build_movie_list', 'action': 'tmdb_movies_search', 'povil_hub': '1'}))
        spec = importlib.util.spec_from_file_location('patches_config_hub_test', WIZARD / 'resources/libs/patches/patches_config.py')
        config = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
            spec.loader.exec_module(config)
        patches = next(v for v in vars(config).values() if isinstance(v, list) and v and isinstance(v[0], dict) and 'hook' in v[0])
        patch = next(p for p in patches if p['id'] == 'pov_hub_no_discover_history')
        self.assertTrue(patch.get('optional'), 'a POV without that line is not held up')
        scope = {}
        exec('def set_history(mediatype, name, query):\n' + patch['hook'] + '\tnoted.append(query)\n', {'noted': scope.setdefault('noted', [])}, scope)
        with mock.patch.object(sys, 'argv', ['plugin://plugin.video.pov/', '5', '?mode=build_movie_list&povil_hub=1&query=a']):
            scope['set_history']('movie', 'n', 'a')
        with mock.patch.object(sys, 'argv', ['plugin://plugin.video.pov/', '5', '?mode=build_movie_list&query=b']):
            scope['set_history']('movie', 'n', 'b')
        self.assertEqual(scope['noted'], ['b'])
        # the ratings of the page's titles are asked ahead like any home row's
        spec = importlib.util.spec_from_file_location('ratings_hub_test', WIZARD / 'resources/libs/ratings.py')
        ratings = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ratings)
        self.assertTrue(ratings.HOME_ROWS[0] <= 5091 and 5099 <= ratings.HOME_ROWS[1])


class HebrewMenuTests(unittest.TestCase):
    """A viewer, with a photo of POV's menu on a title: "can this be put into Hebrew?"."""

    def test_the_context_menu_of_a_title_is_in_hebrew_in_povs_own_form(self):
        spec = importlib.util.spec_from_file_location('pov_ui_labels_test', WIZARD / 'resources/libs/patches/pov_ui_labels.py')
        labels = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(labels)
        english = {32646: '[B]Options...[/B]', 32645: '[B]Extras...[/B]', 32198: '[B]Trakt Lists Manager[/B]',
                   32200: '[B]MDBList Manager[/B]', 32199: '[B]TMDb Lists Manager[/B]', 32197: '[B]Favorites Manager[/B]',
                   32196: '[B]Dropped Manager[/B]', 32642: '[B]Mark Watched %s[/B]', 32643: '[B]Mark Unwatched %s[/B]',
                   32651: '[B]Clear Progress[/B]', 32649: '[B]Exit Movie List[/B]', 32650: '[B]Exit TV Show List[/B]',
                   32652: '[B]Browse...[/B]', 32653: '[B]Browse Season...[/B]', 32174: 'Playback', 32799: 'Next Page',
                   32800: 'Jump To...'}
        for key, text in english.items():
            hebrew = labels.hebrew_label(key)
            self.assertIsNotNone(hebrew, key)
            self.assertTrue(any('֐' <= ch <= '׿' for ch in hebrew), hebrew)
            # POV fills these in with %: the same places must be there, and its bold stays
            self.assertEqual(hebrew.count('%s'), text.count('%s'), key)
            self.assertEqual(hebrew.startswith('[B]') and hebrew.endswith('[/B]'), text.startswith('[B]'), key)
        self.assertEqual(labels.hebrew_label('32642') % 'POV', '[B]סימון כנצפה ב-POV[/B]')
        self.assertIsNone(labels.hebrew_label('a list of mine'), 'never a title or a list name')


if __name__ == '__main__':
    unittest.main()
