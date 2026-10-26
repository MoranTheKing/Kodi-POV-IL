"""Idan Plus VOD: Kan through the mobile-API host, Kan's new player config,
the redesigned Kan archive lobby, and the i24NEWS English catalog.

The fixtures carry Idan Plus 4.0.2's anchor text verbatim around small
stand-ins, and the tests EXECUTE the injected code against them -- the
property that matters is what the patched add-on does, not that a marker
landed. Set IDANPLUS_402 to a real plugin.video.idanplus 4.0.2 tree to also
patch, compile and revert the real files.
"""

import importlib.util
import os
import re
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
           / 'idanplus_vod_patcher.py')
SERVICE = ROOT / 'service.subtitles.kodipovilai' / 'service.py'
T = '\t'

COMMON = '\n'.join([
    '# -*- coding: utf-8 -*-',
    'import re, json, time',
    'userAgent = "UA"',
    '',
    'def OpenURL(url, headers={}, retries=1, responseMethod="text"):',
    T + 'return "STOCK-FALLBACK"',
    '',
    T * 13 + '   ',
    "def GetCF(url, ua=None, retries=8, responseMethod='text', referer=None):",
    T + 'ua = ua or userAgent',
    T + "home = 'https://www.kankids.org.il/' if 'kankids' in url else "
        "'https://www.kan.org.il/'",
    T + 'browseReferer = referer or home',
    T + 'SEEN.append(browseReferer)',
    T + "return 'STOCK:' + url",
    '',
])

KAN = '\n'.join([
    '# -*- coding: utf-8 -*-',
    'import re, json',
    '',
    'def _resolvePlayerKanUrl(url, headers={}, quality=\'best\'):',
    '    def _pipe_headers(u, ua, page_url):',
    "        return 'PIPE:' + u",
    '',
    '    text = _getKanPage(url, fresh=True)',
    '    if text and \'data-hls-url\' in text:',
    "        return 'OLD-ATTRIBUTE'",
    "    raise Exception('Unable to resolve playable URL from page')",
    '',
    'def GetArchiveCategoriesList(url, iconimage, catName):',
    '    text = common.GetCF(url, userAgent)',
    '    #text = common.OpenURL(url)',
    "    domain = baseKidsUrl if 'kankids' in url else baseUrl",
    '    links = []',
    "    matches = re.compile('<main id=\"main\"(.*)</main>', re.S)"
    '.findall(text)',
    '    if len(matches) < 1:',
    '        return',
    '    ',
    "    series = re.compile('<div class=\"vod-section(.*?)<div class="
    "\"section-content\">', re.S).findall(matches[0])",
    "    common.addDir('STOCK-ARCHIVE', series[0], 2, '')",
    '',
    'def _addMobEpisodes(entries, iconimage, moreData, season_filter=None):',
    "    md = moreData.split('|||')",
    "    catName = '' if len(md) < 2 else md[1]",
    '    season_filter = int(season_filter) if season_filter else None',
    '    for entry in entries:',
    '        if season_filter and _mobEpisodeSeason(entry) != season_filter:',
    '            continue',
    "        name = entry.get('title', '').strip()",
    "        common.addDir(name, entry['link']['href'], 3, '')",
    '',
    "def GetEpisodesList(url, iconimage, moreData=''):",
    "    md = moreData.split('|||')",
    "    catName = '' if len(md) < 2 else md[1]",
    '    programId, seasonFilter, _ = _extractKanIds(url)',
    '    if programId:',
    '        prog = GetMobProgram(programId)',
    "        entries = prog.get('entry') or []",
    '        if entries:',
    '            _addMobEpisodes(entries, iconimage, moreData, seasonFilter)',
    '            return',
    '',
    '    #text = common.GetCF(url)',
    "    text = cache.get(common.GetCF, 24, url, table='pages')",
    '    if text==[]:',
    "        text = cache.get(common.GetCF, 0, url, table='pages')",
    '    if not text:',
    '        return',
    "    common.addDir('STOCK-EPISODES', url, 3, '')",
    '',
])

I24 = '\n'.join([
    '# -*- coding: utf-8 -*-',
    '',
    "def ShowCatalogUnivtec(language='he'):",
    '    """Display Hebrew TV shows from the current i24NEWS website API."""',
    "    if language != 'he':",
    '        return False',
    "    data = GetUnivtecData('pages/section/HE', {'page': 1})",
    "    common.addDir(name='HEBREW', url='he', mode=-1, iconimage='', "
    "infos={}, module=module, isFolder=True)",
    '    return True',
    '',
    'def ShowCatalog(language):',
    "    if language == 'he' and ShowCatalogUnivtec(language):",
    '        return',
    "    LEGACY.append(language)",
    '',
])


class _Common:
    def __init__(self):
        self.dirs = []

    def addDir(self, *args, **kwargs):
        self.dirs.append((args, kwargs))

    @staticmethod
    def UnEscapeXML(text):
        return text.replace('&amp;', '&')

    @staticmethod
    def GetLabelColor(text, **_kwargs):
        return text

    @staticmethod
    def quoteNonASCII(text):
        return ''.join(c if ord(c) < 128 else '%%%02X' % ord(c) for c in text)

    @staticmethod
    def quote_plus(text):
        return text.replace(' ', '+')


class _Response:
    def __init__(self, url, status=200, text='PAGE', final=None):
        self.status_code = status
        self.text = text
        self.url = final or url

    def json(self):
        return {'json': True}


def _load_patcher(home):
    vfs = types.SimpleNamespace(
        translatePath=lambda p: os.path.join(
            home, p.replace('special://home/', '').replace('/', os.sep)))
    with patch.dict(sys.modules, {'xbmcvfs': vfs}):
        spec = importlib.util.spec_from_file_location('idan_vod', PATCHER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    module.xbmcvfs = vfs
    module.kodi_utils = None
    return module


class IdanPlusVodPatcherTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.lib = os.path.join(self.home, 'addons', 'plugin.video.idanplus',
                                'resources', 'lib')
        os.makedirs(self.lib)
        # The real files' own encodings: common.py LF, kan.py CRLF with a
        # BOM, i24news.py CRLF without one.
        self.write('common.py', COMMON)
        self.write('kan.py', '\ufeff' + KAN.replace('\n', '\r\n'))
        self.write('i24news.py', I24.replace('\n', '\r\n'))
        self.pristine = {name: self.read(name)
                         for name in ('common.py', 'kan.py', 'i24news.py')}
        self.mod = _load_patcher(self.home)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def write(self, name, text):
        with open(os.path.join(self.lib, name), 'w', encoding='utf-8',
                  newline='') as handle:
            handle.write(text)

    def read(self, name):
        with open(os.path.join(self.lib, name), encoding='utf-8',
                  newline='') as handle:
            return handle.read()

    def namespace(self, name, **extra):
        ns = {'__name__': 'host_' + name.split('.')[0]}
        ns.update(extra)
        exec(compile(self.read(name).lstrip('\ufeff'), name, 'exec'), ns)
        return ns

    # --- lifecycle ---------------------------------------------------------
    def test_patches_once_keeps_encodings_and_reverts_byte_for_byte(self):
        self.assertEqual(self.mod.ensure_patched(), 'patched')
        kan = self.read('kan.py')
        self.assertTrue(kan.startswith('\ufeff'))
        self.assertNotIn('\n', kan.replace('\r\n', ''))
        self.assertNotIn('\r', self.read('common.py'))
        self.assertNotIn('\n', self.read('i24news.py').replace('\r\n', ''))
        snapshot = {n: self.read(n) for n in self.pristine}
        self.assertEqual(self.mod.ensure_patched(), 'unchanged')
        self.assertEqual({n: self.read(n) for n in self.pristine}, snapshot)
        for name, original in self.pristine.items():
            text = self.read(name)
            eol = '\r\n' if '\r\n' in text else '\n'
            self.assertEqual(self.mod._revert(text, eol), original, name)

    def test_an_older_version_is_replaced_not_stacked(self):
        self.mod.ensure_patched()
        current = {n: self.read(n) for n in self.pristine}
        for name, text in current.items():
            self.write(name, text.replace(self.mod.MARKER,
                                          '# AI_SUBS_IDAN_VOD_v0'))
        self.assertEqual(self.mod.ensure_patched(), 'repatched')
        self.assertEqual({n: self.read(n) for n in self.pristine}, current)

    def test_one_changed_function_does_not_cost_the_other_fixes(self):
        # Idan Plus fixing its own null-title crash must not take the Kan
        # player fix down with it.
        self.write('kan.py', self.pristine['kan.py'].replace(
            '        if season_filter and _mobEpisodeSeason(entry) != '
            'season_filter:', '        if season_filter and False:'))
        self.assertEqual(self.mod.ensure_patched(), 'patched')
        kan = self.read('kan.py')
        self.assertIn("if text and 'data-redge-config' in text:  "
                      + self.mod.MARKER, kan)
        self.assertIn("'<div class=\"vod-section' not in matches[0]", kan)
        self.assertNotIn('entries = [dict(e, title=', kan)
        self.assertEqual(self.mod.ensure_patched(), 'unchanged')

    def test_a_file_with_no_known_function_is_left_alone_and_reported(self):
        changed = 'def somethingElse():\r\n    return 1\r\n'
        self.write('kan.py', changed)
        self.assertEqual(self.mod.ensure_patched(), 'unmatched')
        self.assertEqual(self.read('kan.py'), changed)
        # The independent files still get their fixes.
        self.assertIn(self.mod.MARKER, self.read('common.py'))
        self.assertIn(self.mod.MARKER, self.read('i24news.py'))

    def test_the_getcf_pair_is_never_split(self):
        # The call lines use the helpers: without GetCF's head neither lands.
        self.write('common.py', self.pristine['common.py'].replace(
            "def GetCF(url, ua=None, retries=8, responseMethod='text', "
            "referer=None):", "def GetCF(url, ua=None, retries=8, "
            "responseMethod='text', referer=None, extra=None):"))
        changed = self.read('common.py')
        self.assertEqual(self.mod.ensure_patched(), 'unmatched')
        self.assertEqual(self.read('common.py'), changed)

    def test_no_idanplus_is_quiet(self):
        shutil.rmtree(os.path.join(self.home, 'addons'))
        self.assertEqual(self.mod.ensure_patched(), 'no_file')

    # --- 1. the mirror host and the Referer ------------------------------
    def _getcf(self, responder):
        self.mod.ensure_patched()
        calls = []

        class _Session:
            max_redirects = 30

            def get(self, url, headers=None, timeout=None):
                calls.append((url, dict(headers or {}), self.max_redirects))
                return responder(url)

        fake = types.ModuleType('requests')
        fake.Session = _Session
        fake.utils = types.SimpleNamespace(
            requote_uri=lambda u: re.sub(
                r'[^\x00-\x7f]', lambda m: ''.join(
                    '%%%02X' % b for b in m.group(0).encode('utf-8')), u))
        utils = types.ModuleType('requests.utils')
        utils.requote_uri = fake.utils.requote_uri
        seen = []
        # Kept installed until the test ends: the injected code imports
        # requests when GetCF RUNS, and must never reach the real network.
        stub = patch.dict(sys.modules, {'requests': fake,
                                        'requests.utils': utils})
        stub.start()
        self.addCleanup(stub.stop)
        ns = self.namespace('common.py', SEEN=seen)
        return ns['GetCF'], calls, seen

    def test_kan_pages_come_from_the_mobile_api_host(self):
        getcf, calls, _seen = self._getcf(lambda url: _Response(url))
        page = ('https://www.kan.org.il/content/kan/kan-11/p-1108042/s1/'
                '1108044/')
        self.assertEqual(getcf(page, 'UA'), 'PAGE')
        url, headers, redirects = calls[0]
        self.assertEqual(url, 'https://mobapi.kan.org.il/content/kan/kan-11/'
                              'p-1108042/s1/1108044/')
        self.assertEqual(headers['User-Agent'], 'UA')
        self.assertLessEqual(redirects, 4)
        self.assertEqual(getcf(page, 'UA', responseMethod='json'),
                         {'json': True})

    def test_anything_but_a_clean_mirror_page_runs_the_stock_path(self):
        page = 'https://www.kan.org.il/lobby/archive/'
        for responder in (
                lambda url: _Response(url, status=403),
                lambda url: _Response(url, text=''),
                lambda url: _Response(url, final='https://www.kan.org.il/x/'),
                lambda url: (_ for _ in ()).throw(IOError('down'))):
            getcf, _calls, _seen = self._getcf(responder)
            self.assertEqual(getcf(page, 'UA'), 'STOCK:' + page)

    def test_kids_pages_and_full_responses_never_touch_the_mirror(self):
        getcf, calls, seen = self._getcf(lambda url: _Response(url))
        kids = ('https://www.kankids.org.il/content/kids/ktantanim-main/'
                'p-1010382/עונה-1/1010976/')
        referer = kids.rsplit('/', 2)[0] + '/'
        self.assertEqual(getcf(kids, 'UA', referer=referer), 'STOCK:' + kids)
        self.assertEqual(getcf('https://www.kan.org.il/logo.png',
                               responseMethod='full'),
                         'STOCK:https://www.kan.org.il/logo.png')
        self.assertEqual(calls, [])
        # The Hebrew season segment reaches the header percent-encoded.
        seen[0].encode('latin-1')
        self.assertIn('%D7%A2%D7%95%D7%A0%D7%94-1', seen[0])

    # --- 2. Kan's Redge player config ------------------------------------
    def _resolver(self, page):
        self.mod.ensure_patched()
        ns = self.namespace('kan.py', userAgent='UA',
                            _getKanPage=lambda url, fresh=False: page)
        return ns['_resolvePlayerKanUrl']

    @staticmethod
    def _config(cid, hls='', dash=''):
        body = json.dumps({'id': cid, 'src': '', 'file': {'hls': hls,
                                                          'dash': dash}})
        return ('<script type="application/json" data-redge-config='
                '"redge-player-%s">%s</script>' % (cid, body))

    def test_the_episode_own_config_wins_over_a_teaser(self):
        page = (self._config('999', hls='//cdn/teaser.m3u8')
                + self._config('1108044', hls='//cdn/own.m3u8?fmp4',
                               dash='//cdn/own.ism'))
        resolve = self._resolver(page)
        self.assertEqual(resolve('https://www.kan.org.il/content/kan/kan-11/'
                                 'p-1108042/s1/1108044/'),
                         'PIPE://cdn/own.m3u8?fmp4')

    def test_a_page_with_only_another_player_never_plays_it(self):
        # A teaser or promo must not stand in for the episode: the stock path
        # (here: no old attribute -> the stock exception) carries on.
        resolve = self._resolver(self._config('999', hls='//cdn/teaser.m3u8'))
        with self.assertRaises(Exception):
            resolve('https://www.kan.org.il/content/kan/kan-11/p-1/s1/1108044/')

    def test_a_url_without_an_episode_id_takes_the_first_player(self):
        resolve = self._resolver(self._config('42', hls='//cdn/item.m3u8'))
        self.assertEqual(resolve('https://www.kan.org.il/Item/?itemId=x'),
                         'PIPE://cdn/item.m3u8')

    def test_dash_is_used_when_there_is_no_hls(self):
        resolve = self._resolver(self._config('5', dash='//cdn/only.ism'))
        self.assertEqual(resolve('https://www.kankids.org.il/a/p-1/x/5/'),
                         'PIPE://cdn/only.ism')

    def test_broken_or_absent_configs_fall_through_to_stock(self):
        broken = ('<script data-redge-config="x">{not json</script>'
                  + self._config('7'))
        for page in (broken, '<div data-hls-url="//old"></div>', ''):
            resolve = self._resolver(page)
            if 'data-hls-url' in page:
                self.assertEqual(resolve('https://www.kan.org.il/p-1/7/'),
                                 'OLD-ATTRIBUTE')
            else:
                with self.assertRaises(Exception):
                    resolve('https://www.kan.org.il/p-1/7/')

    # --- 3. the archive lobby --------------------------------------------
    @staticmethod
    def _image(url, name):
        if url.startswith('http') and '?' not in url:
            # Stock 4.0.2 GetImageLink: `imageLink` unbound on this shape.
            raise UnboundLocalError('imageLink')
        return 'IMG:' + url

    def _archive(self, page):
        self.mod.ensure_patched()
        common = _Common()
        common.GetCF = lambda url, ua=None: page
        ns = self.namespace(
            'kan.py', common=common, userAgent='UA', module='kan',
            baseUrl='https://www.kan.org.il',
            baseKidsUrl='https://www.kankids.org.il',
            GetImageLink=self._image)
        ns['GetArchiveCategoriesList']('https://www.kan.org.il/lobby/archive/',
                                       'icon', 'cat')
        return common.dirs

    def test_program_cards_of_the_new_lobby_are_listed_once(self):
        card = ('<a class="card" href="{0}" data-item-type="program" '
                'data-item-id="1" aria-label="{1}"><div><img src="{2}" />'
                '</div></a>')
        page = ('<main id="main">'
                + card.format('https://www.kan.org.il/content/archive1/vod/'
                              'p-1099340/', 'A &amp; B',
                              '/media/a/א.jpg?width=490')
                + card.format('/content/archive1/projects/p-1089752/', 'C',
                              '/media/c.jpg')
                + card.format('https://www.kan.org.il/content/archive1/vod/'
                              'p-1099340/', 'A again', '/media/a.jpg')
                + '<a href="/lobby/series/" aria-label="lobby">x</a></main>')
        dirs = self._archive(page)
        self.assertEqual([(a[0], a[1], a[2]) for a, _k in dirs], [
            ('A & B', 'https://www.kan.org.il/content/archive1/vod/p-1099340/', 2),
            ('C', 'https://www.kan.org.il/content/archive1/projects/p-1089752/',
             2)])
        self.assertEqual(dirs[0][0][3], 'IMG:/media/a/%5D0.jpg?width=490')
        self.assertEqual(dirs[0][1]['moreData'], 'kan|||cat')

    def test_one_card_whose_image_fails_does_not_empty_the_menu(self):
        card = ('<a href="{0}" data-item-type="program" aria-label="{1}">'
                '<img src="{2}" /></a>')
        page = ('<main id="main">'
                + card.format('/content/archive1/vod/p-1/', 'Bad',
                              'https://cdn.example/no-query.jpg')
                + card.format('/content/archive1/vod/p-2/', 'Good',
                              '/media/g.jpg?w=1')
                + '</main>')
        dirs = self._archive(page)
        self.assertEqual([(a[0], a[3]) for a, _k in dirs],
                         [('Bad', 'icon'), ('Good', 'IMG:/media/g.jpg?w=1')])

    def test_the_old_lobby_layout_still_runs_the_stock_parser(self):
        page = ('<main id="main"><div class="vod-section">GRID'
                '<div class="section-content"></main>')
        dirs = self._archive(page)
        self.assertEqual(dirs[0][0][0], 'STOCK-ARCHIVE')

    # --- program episode lists ------------------------------------------
    def _episodes(self, api_entries, page, url=None):
        self.mod.ensure_patched()
        common = _Common()
        common.GetCF = lambda url, ua=None: page
        cache = types.SimpleNamespace(
            get=lambda function, hours, *args, **kwargs: function(*args))
        ns = self.namespace(
            'kan.py', common=common, cache=cache, module='kan', bitrate='best',
            baseUrl='https://www.kan.org.il',
            baseKidsUrl='https://www.kankids.org.il',
            GetImageLink=self._image, _mobEpisodeSeason=lambda entry: 1,
            GetMobProgram=lambda pid: {'entry': api_entries},
            _extractKanIds=lambda url: (
                (re.findall(r'/p-(\d+)', url) or [None])[0],
                (re.findall(r'/p-\d+/s(\d+)', url) or [None])[0], None))
        ns['GetEpisodesList'](url or 'https://www.kan.org.il/content/archive1/'
                              'vod/p-769693/', 'icon', 'kan|||cat')
        return common.dirs

    def test_relative_card_links_become_full_addresses(self):
        card = ('<a class="cr-item"\n href="{0}"\n aria-label="{1}">'
                '<img src="/m.jpg?w=1" /></a>')
        page = (card.format('/content/kids/x/p-55/1/', 'Kids ep')
                + card.format('/content/kids/x/p-55/2/', 'Kids ep 2'))
        dirs = self._episodes(
            [], page, url='https://www.kankids.org.il/content/kids/x/p-55/')
        self.assertEqual([a[1] for a, _k in dirs], [
            'https://www.kankids.org.il/content/kids/x/p-55/1/',
            'https://www.kankids.org.il/content/kids/x/p-55/2/'])

    def test_a_season_page_lists_only_its_own_season(self):
        card = ('<a class="cr-item"\n href="{0}"\n aria-label="{1}">'
                '<img src="/m.jpg?w=1" /></a>')
        base = 'https://www.kan.org.il/content/kan/kan-11/p-9/'
        page = (card.format(base + 's1/11/', 'S1E1')
                + card.format(base + 's2/21/', 'S2E1'))
        dirs = self._episodes([], page, url=base + 's2/')
        self.assertEqual([a[0] for a, _k in dirs], ['S2E1'])

    def test_an_untitled_api_episode_no_longer_empties_the_program(self):
        entries = [
            {'title': None, 'link': {'href': 'trailer'}, 'extensions': {
                'analyticsCustomProperties': {'episode_title': 'Trailer'}}},
            {'title': 'Episode 1', 'link': {'href': 'e1'}},
            {'title': None, 'link': {'href': 'bare'}}]
        dirs = self._episodes(entries, '')
        self.assertEqual([(a[0], a[1]) for a, _k in dirs],
                         [('Trailer', 'trailer'), ('Episode 1', 'e1'),
                          ('', 'bare')])

    def test_episode_cards_are_listed_when_the_api_has_none(self):
        card = ('<a class="cr-item unstyled-link has-title"\n   href="{0}"\n'
                '   aria-label="{1}">\n<div><img src="{2}" alt="x" /></div></a>')
        base = 'https://www.kan.org.il/content/archive1/vod/p-769693/'
        page = ('<a href="' + base + 's1/769696/" class="hero-vod-cta">x</a>'
                + card.format(base + 's1/769696/', 'Ep 1 &amp; more',
                              '/media/1.jpg?w=1')
                + card.format(base + 's1/770999/', 'Ep 2', '/media/2.jpg?w=1')
                + card.format(base + 's1/769696/', 'Ep 1 again', '/m.jpg?w=1')
                + card.format('https://www.kan.org.il/content/kan/p-1/2/',
                              'Another program', '/media/o.jpg?w=1'))
        dirs = self._episodes([], page)
        self.assertEqual([(a[0], a[1], a[2]) for a, _k in dirs], [
            ('Ep 1 & more', base + 's1/769696/', 3),
            ('Ep 2', base + 's1/770999/', 3)])
        self.assertTrue(all(k['isPlayable'] for _a, k in dirs))

    def test_a_page_without_cards_keeps_the_stock_parser(self):
        dirs = self._episodes([], '<main id="main">old layout</main>')
        self.assertEqual(dirs[0][0][0], 'STOCK-EPISODES')

    # --- 4. i24NEWS English ----------------------------------------------
    def _i24(self, items):
        self.mod.ensure_patched()
        common, calls, legacy = _Common(), [], []

        def univtec(endpoint, params=None, region='hebrew'):
            calls.append((endpoint, region))
            return {'items': items}

        ns = self.namespace('i24news.py', common=common, module='i24news',
                            moduleIcon='icon', LEGACY=legacy,
                            GetUnivtecData=univtec,
                            GetUnivtecImage=lambda item, d: item.get('img', d))
        return ns, common, calls, legacy

    def test_english_lists_the_univtec_shows_section(self):
        ns, common, calls, legacy = self._i24(
            [{'id': 'a1', 'title': 'THE RUNDOWN', 'img': 'i'}, {'title': 'x'}])
        ns['ShowCatalog']('en')
        self.assertEqual(calls, [('pages/section/6a15800ed7dd65c210d2d0c1',
                                  'all')])
        self.assertEqual(legacy, [])
        kwargs = common.dirs[0][1]
        self.assertEqual(kwargs['url'], 'action=seasons_univtec&series_id=a1'
                                        '&show_name=THE+RUNDOWN')
        self.assertEqual(len(common.dirs), 1)

    def test_an_empty_english_section_falls_back_and_hebrew_is_untouched(self):
        ns, common, calls, legacy = self._i24([])
        ns['ShowCatalog']('en')
        self.assertEqual(legacy, ['en'])
        ns['ShowCatalog']('he')
        self.assertEqual(calls[-1], ('pages/section/HE', 'hebrew'))
        self.assertEqual(common.dirs[-1][1]['name'], 'HEBREW')

    # --- Idan Plus 4.0.3 ---------------------------------------------------
    PAGE = '    text = _getKanPage(url, fresh=True)\n'
    CREDITS = ('    if page is not None and PageCredits(text):\n'
               "        page['credits'] = PageCredits(text)\n")

    def _kan_403(self):
        """kan.py as 4.0.3 has it: its own PageStream, and the credits time
        recorded on the line right after the page fetch."""
        text = KAN.replace(self.PAGE, self.PAGE + self.CREDITS, 1).replace(
            'def _resolvePlayerKanUrl(',
            "def PageStream(text):\n    return ''\n\ndef _resolvePlayerKanUrl(", 1)
        self.assertNotEqual(text, KAN)
        return '\ufeff' + text.replace('\n', '\r\n')

    def test_idan_403_reads_its_own_player_and_keeps_the_credits(self):
        self.write('kan.py', self._kan_403())
        self.assertEqual(self.mod.ensure_patched(), 'patched')
        kan = self.read('kan.py')
        self.assertNotIn("'data-redge-config' in text:", kan)
        self.assertIn((self.PAGE + self.CREDITS).replace('\n', '\r\n'), kan)
        # the archive lobby, null title and program-page fixes still land
        self.assertGreaterEqual(kan.count(self.mod.MARKER), 3)

    def test_a_v1_player_block_on_403_is_taken_back(self):
        # 0.3.53 put fix 2 above 4.0.3's credits line on devices that had
        # already updated Idan Plus: v2 takes it out again.
        v1 = self.mod._KAN_FIX.replace(self.mod.MARKER, '# AI_SUBS_IDAN_VOD_v1')
        self.write('kan.py', self._kan_403().replace(
            self.PAGE.replace('\n', '\r\n'),
            (self.PAGE + v1).replace('\n', '\r\n'), 1))
        self.assertIn("'data-redge-config' in text:", self.read('kan.py'))
        self.assertEqual(self.mod.ensure_patched(), 'repatched')
        kan = self.read('kan.py')
        self.assertNotIn("'data-redge-config' in text:", kan)
        self.assertNotIn('AI_SUBS_IDAN_VOD_v1', kan)
        self.assertIn((self.PAGE + self.CREDITS).replace('\n', '\r\n'), kan)
        self.assertEqual(self.mod.ensure_patched(), 'unchanged')

    # --- wiring ------------------------------------------------------------
    def test_service_runs_it_every_boot(self):
        source = SERVICE.read_text('utf-8-sig')
        self.assertIn('        _maybe_fix_idanplus_vod,\n', source)
        self.assertIn('idanplus_vod_patcher.ensure_patched()', source)


@unittest.skipUnless(os.environ.get('IDANPLUS_402'),
                     'set IDANPLUS_402 to a real plugin.video.idanplus 4.0.2')
class RealIdanPlusTreeTests(unittest.TestCase):
    def test_real_402_files_patch_compile_and_revert(self):
        home = tempfile.mkdtemp()
        try:
            target = os.path.join(home, 'addons', 'plugin.video.idanplus')
            shutil.copytree(os.environ['IDANPLUS_402'], target)
            lib = os.path.join(target, 'resources', 'lib')
            names = ('common.py', 'kan.py', 'i24news.py')

            def read(name):
                with open(os.path.join(lib, name), encoding='utf-8',
                          newline='') as handle:
                    return handle.read()

            before = {n: read(n) for n in names}
            mod = _load_patcher(home)
            self.assertEqual(mod.ensure_patched(), 'patched')
            for name in names:
                text = read(name)
                self.assertIn(mod.MARKER, text, name)
                eol = '\r\n' if '\r\n' in text else '\n'
                self.assertEqual(mod._revert(text, eol), before[name], name)
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
