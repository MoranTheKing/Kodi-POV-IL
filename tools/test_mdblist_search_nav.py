"""The three navigation defects reported against 0.2.496, each run for real.

All three are reachable in about three keypresses, and the first one shipped:

  1. Like/Unlike on a SEARCH result re-opened the keyboard. POV's search results
     live at a path with no search_title in it, and SearchMdblLists falls back
     to dialog.input() whenever that parameter is absent -- so the bare
     Container.Refresh that 0.2.496 shipped re-ran the prompt.
  2. Cancelling the search built an empty screen and navigated to it.
  3. Searching a second time meant going back to the home screen.

These are not asserted by reading the generated text. The refresh helper is
extracted and EXECUTED against stubbed Kodi info labels, and the two class
overrides are bound to a stub base so their control flow really runs. A test
that only greps for a substring passes just as happily on code that never runs.

Run: python3 tools/test_mdblist_search_nav.py
"""
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATCHER = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                       'resources', 'lib', 'pov_mdblist_like_patcher.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# Same stock tree the sibling patcher test uses, and the same rule: when it is
# absent, build the shape inline rather than skip. A skip that exits 0 reports
# green while proving nothing -- that mistake is already recorded in
# test_mdblist_like_patcher.py and is not repeated here.
STOCK = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6813/plugin.video.pov')

def stock_version():
    """Read it. Never print a hardcoded one -- a banner that names a version
    the tree is not is exactly the small lie that makes a later reader trust
    the wrong thing. Same helper, same reason, as in
    tools/test_umbrella_mdblist_sync.py."""
    try:
        with open(os.path.join(STOCK, 'addon.xml'), encoding='utf-8') as f:
            m = re.search(r'<addon[^>]*?version="([0-9.]+)"', f.read(), re.S)
        return m.group(1) if m else 'unknown version'
    except Exception:
        return 'unknown version'


# THE INLINE FIXTURES ARE REAL POV, NOT A SKETCH OF IT.
#
# They used to be hand-written miniatures, and on any machine without a stock
# POV tree this file reported TEN FAILURES -- not "unverified", FAILURES --
# because the miniatures were missing shapes the patcher anchors on: no
# top-level search_mdbl_lists, and a delete_mdbl_list that did not call
# container_refresh. Every check downstream of those failed for a reason that
# had nothing to do with the code under test. A red test nobody believes is
# worse than no test, because it trains people to scroll past red.
#
# So both fixtures are now byte-slices of real POV 6.08.13, generated rather
# than typed, and asserted at generation time to be substrings of the real
# files. menus/mdblist.py is carried whole: it is 198 lines, every anchor the
# patcher uses lives in it, and any reduction is drift waiting to happen.
# mdblist_api.py is the module header (what the injected block needs in scope)
# plus POV's real delete_mdbl_list, which is its only anchor.
FIXTURE_MENU = (
    'from indexers import mdblist_api, list_helper\n'
    'from menus.episodes import Episodes\n'
    'from menus.movies import Movies\n'
    'from menus.seasons import Seasons\n'
    'from menus.tvshows import TVShows\n'
    'from modules import kodi_utils\n'
    '# logger = kodi_utils.logger\n'
    '\n'
    'KODI_VERSION, ls = kodi_utils.get_kodi_version(), kodi_utils.local_string\n'
    'build_url, make_listitem = kodi_utils.build_url, kodi_utils.make_listitem\n'
    "fanart = kodi_utils.get_addoninfo('fanart')\n"
    "default_icon = kodi_utils.media_path('mdblist.png')\n"
    "add2menu_str, add2folder_str, copy2str = ls(32730), ls(32731), '[B]Export to TMDB[/B]'\n"
    "newlist_str, deletelist_str, nextpage_str = '[B]Make a new MDBList list[/B]', ls(32781), ls(32799)\n"
    'watchl_str, fav_str, coll_str = ls(32500), ls(32453), ls(32499)\n'
    '\n'
    'def search_mdbl_lists(params):\n'
    '\treturn SearchMdblLists(params).build()\n'
    '\n'
    'def get_mdbl_lists(params):\n'
    '\treturn GetMdblLists(params).build()\n'
    '\n'
    'def get_mdbl_top_lists(params):\n'
    '\treturn GetTopLists(params).build()\n'
    '\n'
    'def build_mdbl_list(params):\n'
    '\treturn MdblistBuilder(params).build()\n'
    '\n'
    'def mdbl_account_info():\n'
    '\tfrom modules.utils import jsondate_to_datetime\n'
    '\ttry:\n'
    '\t\tkodi_utils.show_busy_dialog()\n'
    "\t\taccount_info = mdblist_api.call_mdblist('user')\n"
    "\t\tjoined = jsondate_to_datetime(account_info['date_joined']).astimezone()\n"
    "\t\tapi_requests = account_info['api_requests']\n"
    "\t\tremaining = api_requests - account_info['api_requests_count']\n"
    '\t\tbody = []\n'
    '\t\tappend = body.append\n'
    "\t\tappend('[B]Username:[/B] %s' % account_info['username'])\n"
    "\t\tappend('[B]Joined:[/B] %s' % joined.date())\n"
    "\t\tappend('[B]Supporter:[/B] %s' % account_info['is_supporter'])\n"
    "\t\tappend('[B]API Request Limit:[/B] %s' % api_requests)\n"
    "\t\tappend('[B]API Request Remaining:[/B] %s' % remaining)\n"
    '\t\tkodi_utils.hide_busy_dialog()\n'
    "\t\treturn kodi_utils.show_text('MDBList'.upper(), '[CR]'.join(body), font_size='large')\n"
    '\texcept: kodi_utils.hide_busy_dialog()\n'
    '\n'
    'class BaseMdblList(list_helper.BaseList):\n'
    '\tdef process_results(self):\n'
    '\t\tfor item in self.lists:\n'
    '\t\t\ttry:\n'
    '\t\t\t\tcm = []\n'
    '\t\t\t\tcm_append = cm.append\n'
    '\t\t\t\titem, list_type = self.parse_item(item)\n'
    '\t\t\t\tif not item: continue\n'
    "\t\t\t\tname, user, slug, list_id = item['name'], item['user_name'], item.get('slug', ''), item['id']\n"
    "\t\t\t\titem_count = item.get('items')\n"
    "\t\t\t\turl = build_url({'mode': 'build_mdbl_list', 'user': user, 'slug': slug, 'list_id': list_id, 'list_type': list_type, 'name': name})\n"
    '\t\t\t\tdisplay, plot = self.get_display_and_plot(item, name, item_count, user)\n'
    "\t\t\t\tif list_type == 'my_lists':\n"
    "\t\t\t\t\tcm_append((newlist_str, 'RunPlugin(%s)' % build_url({'mode': 'mdblist.make_new_mdbl_list'})))\n"
    "\t\t\t\t\tcm_append((deletelist_str, 'RunPlugin(%s)' % build_url({'mode': 'mdblist.delete_mdbl_list', 'list_id': list_id})))\n"
    "\t\t\t\tcm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': name, 'iconImage': 'mdblist.png'})))\n"
    "\t\t\t\tcm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': name, 'iconImage': 'mdblist.png'})))\n"
    "\t\t\t\tcm_append((copy2str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb_manager_choice', 'mdbl_list_id': list_id, 'mdbl_list_name': name, 'user': user, 'list_slug': slug})))\n"
    '\t\t\t\tlistitem = make_listitem()\n'
    '\t\t\t\tlistitem.setLabel(display)\n'
    "\t\t\t\tlistitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})\n"
    "\t\t\t\tif plot: listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)\n"
    '\t\t\t\tlistitem.addContextMenuItems(cm)\n'
    '\t\t\t\tyield (url, listitem, True)\n'
    '\t\t\texcept: pass\n'
    '\n'
    'class SearchMdblLists(BaseMdblList):\n'
    '\tdef __init__(self, params):\n'
    '\t\tsuper().__init__(params)\n'
    "\t\tself.page = params.get('new_page', '1')\n"
    '\t\tself.pages = self.page\n'
    "\t\tself.search_title = params.get('search_title') or kodi_utils.dialog.input('POV')\n"
    '\t\tself.category_name = self.search_title\n'
    '\n'
    '\tdef fetch_results(self):\n'
    "\t\tif self.search_title: self.lists, self.pages = mdblist_api.mdbl_search_lists(self.search_title), '1'\n"
    '\t\telse: self.lists, self.pages = [], self.page\n'
    '\n'
    '\tdef add_next_page(self):\n'
    '\t\tif int(self.pages) <= int(self.page): return\n'
    "\t\turl = {'mode': 'build_mdbl_list.search_mdbl_lists', 'search_title': self.search_title, 'new_page': int(self.page) + 1}\n"
    '\t\tkodi_utils.add_dir(self.handle, url, nextpage_str)\n'
    '\n'
    'class GetMdblLists(BaseMdblList):\n'
    '\tdef __init__(self, params):\n'
    '\t\tsuper().__init__(params)\n'
    "\t\tself.sort_method = 'label'\n"
    "\t\tself.list_type = params['list_type']\n"
    '\n'
    '\tdef fetch_results(self):\n'
    '\t\tself.lists = []\n'
    "\t\tif self.list_type == 'liked_lists': lists = ('liked_lists',)\n"
    "\t\telse: lists = ('my_lists', 'external')\n"
    '\t\tfor i in lists:\n'
    '\t\t\titems = mdblist_api.mdbl_get_lists(i)\n'
    '\t\t\tif isinstance(items, list): self.lists.extend(items)\n'
    '\n'
    '\tdef parse_item(self, item):\n'
    "\t\tif self.list_type == 'liked_lists': list_type = 'liked_lists'\n"
    "\t\telse: list_type = 'external' if 'source' in item else 'my_lists'\n"
    '\t\treturn item, list_type\n'
    '\n'
    '\tdef get_display_and_plot(self, item, name, item_count, user):\n'
    "\t\tprivacy = item.get('private')\n"
    "\t\tif self.list_type == 'liked_lists':\n"
    "\t\t\tdisplay = '%s (x%s) - [I]%s[/I]' % (name, item_count, user) if item_count else '%s - [I]%s[/I]' % (name, user)\n"
    '\t\telse:\n'
    "\t\t\tdisplay = '%s (x%s)' % (name, item_count) if item_count else name\n"
    "\t\t\tif privacy: display = '[I]%s[/I]' % display\n"
    '\t\treturn display, None\n'
    '\n'
    'class GetTopLists(BaseMdblList):\n'
    '\tdef fetch_results(self):\n'
    '\t\tself.lists = mdblist_api.mdbl_top_lists()\n'
    '\n'
    'class MdblistBuilder(list_helper.BaseMediaListBuilder):\n'
    "\tmode = 'build_mdbl_list'\n"
    '\n'
    '\tdef __init__(self, params):\n'
    '\t\tsuper().__init__(params)\n'
    "\t\tself.slug = params.get('slug')\n"
    "\t\tself.list_type = params.get('list_type')\n"
    '\n'
    '\tdef fetch_results(self):\n'
    '\t\treturn mdblist_api.get_mdbl_list_contents(self.list_type, self.list_id)\n'
    '\n'
    '\tdef process_media_types(self, queue, process_list):\n'
    "\t\tmovies, tvshows = Movies({'id_type': 'trakt_dict'}), TVShows({'id_type': 'trakt_dict'})\n"
    "\t\tepisodes, seasons = Episodes({'id_type': 'trakt_dict'}), Seasons({'id_type': 'trakt_dict'})\n"
    '\t\tfor idx, tag in enumerate(process_list, 1):\n'
    "\t\t\tmtype = tag['mediatype']\n"
    "\t\t\tif   mtype == 'movie':\n"
    "\t\t\t\tqueue.put((movies.build_movie_content, idx, {'imdb': tag['imdb_id'], 'tmdb': tag['id']}))\n"
    "\t\t\telif mtype == 'show':\n"
    "\t\t\t\tqueue.put((tvshows.build_tvshow_content, idx, {'imdb': tag['imdb_id'], 'tmdb': tag['id']}))\n"
    "\t\t\telif mtype == 'episode':\n"
    "\t\t\t\ttmdb_id = tag.get('show_id') or tag.get('show_tmdb') or ''\n"
    "\t\t\t\tids = {'media_ids': {'tmdb': tmdb_id}, 'season': tag['season_number'], 'episode': tag['episode_number']}\n"
    '\t\t\t\tqueue.put((episodes.build_episode_content, idx, ids))\n'
    "\t\t\telif mtype == 'season':\n"
    "\t\t\t\ttmdb_id = tag.get('show_id') or tag.get('show_tmdb') or ''\n"
    "\t\t\t\tids = {'tmdb_id': tmdb_id, 'season': tag['season_number'], 'sort': idx}\n"
    '\t\t\t\tqueue.put((seasons.build_season_list, ids))\n'
    "\t\treturn {'movies': movies, 'tvshows': tvshows, 'episodes': episodes, 'seasons': seasons}\n"
    '\n'
    'class MdbListManager(list_helper.BaseListManager):\n'
    "\tsetting_key = 'mdblist_user'\n"
    "\ticon_file = 'mdblist.png'\n"
    '\theading_id = 32200\n'
    '\n'
    '\tdef _get_api(self):\n'
    '\t\treturn mdblist_api\n'
    '\n'
    '\tdef get_custom_lists(self):\n'
    '\t\tlist1 = [\n'
    "\t\t\t(str(item['id']), item['name'], '%s items' % item['items'], self.icon)\n"
    "\t\t\tfor item in self.api.mdbl_get_lists('my_lists') if not item['dynamic']\n"
    '\t\t]\n'
    "\t\tlist2 = [('new', 'Create a new list', '', self.icon)]\n"
    '\t\treturn list1, list2\n'
    '\n'
    '\tdef get_default_choices(self):\n'
    "\t\tchoices = [(i.lower(), i, '', self.icon) for i in (watchl_str, coll_str)]\n"
    "\t\tif self.mediatype == 'tvshow': choices.append(('dropped', 'Toggle Dropped', '', self.icon))\n"
    '\t\treturn choices\n'
    '\n'
    '\tdef handle_special_action(self, choice_id, choice_name):\n'
    "\t\tif 'new' in choice_id:\n"
    '\t\t\tkodi_utils.show_busy_dialog()\n'
    '\t\t\ttry: self.api.make_new_mdbl_list(None)\n'
    '\t\t\texcept: return kodi_utils.notification(32574)\n'
    '\t\t\tfinally: kodi_utils.hide_busy_dialog()\n'
    '\t\t\treturn self.manage()\n'
    "\t\tif 'dropped' in choice_id:\n"
    "\t\t\targs = self.params['tmdb_id'], 'shows', self.params['imdb_id']\n"
    "\t\t\treturn self.api.hide_unhide_mdbl_items(*args, 'dropped')\n"
    '\t\treturn False\n'
    '\n'
    '\tdef check_item_exists(self, choice_id):\n'
    "\t\tif 'collection' in choice_id: list_items = self.api.mdblist_collection('all', None)\n"
    "\t\telif 'watchlist' in choice_id: list_items = self.api.mdblist_watchlist('all', None)\n"
    "\t\telse: list_items = self.api.get_mdbl_list_contents('my_lists', choice_id)\n"
    "\t\treturn self.tmdb_id in {i['id'] for i in list_items}\n"
    '\n'
    '\tdef execute_toggle(self, choice, action_add):\n'
    "\t\tif 'collection' in choice[0]:\n"
    "\t\t\tdata = {'shows' if self.mediatype == 'tvshow' else 'movies': [{'ids': {'tmdb': self.tmdb_id}}]}\n"
    '\t\t\treturn self.api.add_to_collection(data) if action_add else self.api.remove_from_collection(data)\n'
    "\t\tdata = {'shows' if self.mediatype == 'tvshow' else 'movies': [{'tmdb': self.tmdb_id}]}\n"
    '\t\treturn self.api.add_to_list(choice[0], data) if action_add else self.api.remove_from_list(choice[0], data)\n'
    '\n'
)

# The API half: real POV module header + real delete_mdbl_list, the only
# shape the patcher anchors on in this file.
FIXTURE_API = (
    'import requests\n'
    'from threading import Thread\n'
    'from concurrent.futures import ThreadPoolExecutor\n'
    'from caches import mdbl_cache\n'
    'from caches.main_cache import cache_object\n'
    'from indexers.tmdb_api import movie_external_id, tvshow_external_id\n'
    'from magneto.modules import client\n'
    'from modules import kodi_utils, settings\n'
    'from modules.cache import check_databases\n'
    'from modules.utils import sort_for_article, jsondate_to_datetime, paginate_list, get_datetime\n'
    '\n'
    'EXPIRES_1_HOURS, EXPIRES_2_DAYS, MAX_LIST_ITEMS = 1, 48, 250_000\n'
    'get_setting, set_setting, logger = kodi_utils.get_setting, kodi_utils.set_setting, kodi_utils.logger\n'
    "base_url = 'https://api.mdblist.com/%s'\n"
    'timeout = 10.05\n'
    'session = requests.Session()\n'
    'retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(502, 503, 504))\n'
    "session.mount('https://api.mdblist.com', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))\n"
    '\n'
    'def delete_mdbl_list(params):\n'
    '\tif not kodi_utils.confirm_dialog(): return\n'
    "\tlist_id = params['list_id']\n"
    "\turl = 'lists/%s' % list_id\n"
    "\tresult = call_mdblist(url, method='delete')\n"
    '\tif result is None: return kodi_utils.notification(32574)\n'
    "\tmdbl_cache.clear_mdbl_list_data('my_lists')\n"
    '\tkodi_utils.notification(32576)\n'
    '\tkodi_utils.container_refresh()\n'
)

def lay_down_pristine(dest):
    """An UNPATCHED POV tree at `dest`.

    Every site that needs one calls this. Two of them used to write
    `STOCK if os.path.isdir(STOCK) else root` instead -- and `root` is the tree
    this file patched three hundred lines earlier. With a stock tree present
    that reads fine; without one, the upgrade replay was handed a tree already
    carrying the CURRENT marker, so the v2 patcher it was supposed to simulate
    saw its own marker family and returned 'unchanged', and all five checks
    below it failed for a reason that had nothing to do with the patcher.
    """
    if os.path.isdir(STOCK):
        shutil.copytree(STOCK, dest)
        return
    for rel, body in (('resources/lib/menus/mdblist.py', FIXTURE_MENU),
                      ('resources/lib/indexers/mdblist_api.py', FIXTURE_API)):
        p = os.path.join(dest, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(body)


work = tempfile.mkdtemp()
root = os.path.join(work, 'addons', 'plugin.video.pov')
print('fixture: %s' % ('real stock POV ' + stock_version()
                       if os.path.isdir(STOCK)
                       else 'inline slices of real POV (no stock tree here)'))
lay_down_pristine(root)

ku = types.ModuleType('kodi_utils')
ku.log = lambda *a, **k: None
sys.modules['kodi_utils'] = ku
vfs = types.ModuleType('xbmcvfs')
vfs.translatePath = lambda p: p.replace('special://home/addons/',
                                        os.path.join(work, 'addons') + os.sep)
sys.modules['xbmcvfs'] = vfs
spec = importlib.util.spec_from_file_location('_p', PATCHER)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
status = patcher.ensure_patched()
check('the patcher applies to a stock POV tree', 'patched' in str(status),
      repr(status))

API = os.path.join(work, 'addons', 'plugin.video.pov', 'resources', 'lib',
                   'indexers', 'mdblist_api.py')
MENU = os.path.join(work, 'addons', 'plugin.video.pov', 'resources', 'lib',
                    'menus', 'mdblist.py')
api_src = open(API, encoding='utf-8').read()
menu_src = open(MENU, encoding='utf-8').read()

def body(src, name):
    """Just that function, not everything after it. Scoping this to
    end-of-file instead reported a failure on the first run -- it was reading
    POV's OWN delete_mdbl_list, which calls container_refresh and is right to:
    Delete only ever appears on your own lists, never on search results."""
    m = re.search(r'^def %s\(params\):.*?(?=\n(?:def |class )|\Z)' % name,
                  src, re.S | re.M)
    assert m, 'could not extract %s' % name
    return m.group(0)


for _fn in ('mdbl_like_a_list', 'mdbl_unlike_a_list'):
    check('%s no longer calls the bare container_refresh()' % _fn,
          'kodi_utils.container_refresh()' not in body(api_src, _fn),
          'a bare refresh survives in that body -- that IS the shipped bug')
    check('%s routes through the search-aware refresh instead' % _fn,
          '_ai_refresh_after_like()' in body(api_src, _fn))

check("POV's own delete_mdbl_list is left exactly as it was",
      'kodi_utils.container_refresh()' in body(api_src, 'delete_mdbl_list'),
      'the patcher reached code it has no business editing')


# --- 1. the refresh helper, executed -------------------------------------
def extract(src, name):
    m = re.search(r'^def %s\(\):.*?(?=\n(?:def |class )|\Z)' % name, src,
                  re.S | re.M)
    assert m, 'could not extract %s' % name
    return m.group(0)


def run_refresh(folder_path, category, boom=False):
    """Execute the REAL generated helper; return the builtin it fired, if any."""
    fired = []
    xbmc = types.ModuleType('xbmc')

    def _label(k):
        if boom:
            raise RuntimeError('getInfoLabel unavailable')
        return {'Container.FolderPath': folder_path,
                'Container.PluginCategory': category}.get(k, '')
    xbmc.getInfoLabel = _label
    sys.modules['xbmc'] = xbmc

    k = types.ModuleType('ku2')
    k.execute_builtin = lambda s: fired.append(s)
    k.container_refresh = lambda: fired.append('Container.Refresh')
    g = {'kodi_utils': k}
    exec(extract(api_src, '_ai_refresh_after_like'), g)
    g['_ai_refresh_after_like']()
    return fired


SEARCH = 'plugin://plugin.video.pov/?mode=build_mdbl_list.search_mdbl_lists'

fired = run_refresh(SEARCH, 'Sport')
check('on a search screen it refreshes WITH the typed title, not blindly',
      len(fired) == 1 and 'search_title=Sport' in fired[0]
      and fired[0] != 'Container.Refresh', repr(fired))
check('...and it stays on the same path rather than navigating somewhere new',
      fired and fired[0].startswith('Container.Refresh(' + SEARCH), repr(fired))

fired = run_refresh(SEARCH, '')
check('with no recoverable title it does NOTHING rather than re-prompt',
      fired == [], repr(fired))

fired = run_refresh(SEARCH + '&search_title=Sport', 'Sport')
check('a search path that already carries the title refreshes normally',
      fired == ['Container.Refresh'], repr(fired))

fired = run_refresh('plugin://plugin.video.pov/?mode=mdblist.get_mdbl_lists'
                    '&list_type=liked_lists', 'My Liked Lists')
check('on any ordinary listing the plain refresh still happens',
      fired == ['Container.Refresh'], repr(fired))

fired = run_refresh(SEARCH, 'Sport', boom=True)
check('if it cannot tell which screen this is, it fails CLOSED',
      fired == [], repr(fired) + ' -- an unknown screen must not be refreshed')


# --- 2 & 3. the two class overrides, executed ----------------------------
def bind_overrides():
    """Bind the generated build/process_results onto a stub whose base records
    what it was asked to do."""
    calls = {'base_build': 0, 'ended': []}

    class Base(object):
        def build(self):
            calls['base_build'] += 1

        def process_results(self):
            yield ('url://real', 'real-item', True)

    body = re.search(
        r'^(?P<ind>[ \t]+)def build\(self\):  # AI_SUBS_MDBL_LIKE.*?'
        r'(?=\n(?P=ind)def fetch_results)', menu_src, re.S | re.M)
    assert body, 'the search overrides are not in the patched file'
    text = body.group(0)
    ind = body.group('ind')
    text = '\n'.join(ln[len(ind):] if ln.startswith(ind) else ln
                     for ln in text.split('\n'))

    xp = types.ModuleType('xbmcplugin')
    xp.endOfDirectory = lambda h, succeeded=True: calls['ended'].append(succeeded)
    sys.modules['xbmcplugin'] = xp
    sys.argv = ['plugin://x', '7', '']

    # serialise the WHOLE param dict, so a check can assert what the row
    # actually asks for rather than only which mode it names
    g = {'build_url': lambda d: 'url://' + d['mode'] + ''.join(
             '&%s=%s' % kv for kv in sorted(d.items())
             if kv[0] != 'mode'),
         '_ai_hist_key': 'mdbl_list_queries',
         '_ai_new_search_item': lambda: 'new-search-item'}
    ns = {}
    exec('class Sub(Base):\n' + '\n'.join(
        '    ' + ln if ln.strip() else '' for ln in text.split('\n')),
        dict(g, Base=Base), ns)
    return ns['Sub'], calls


Sub, calls = bind_overrides()

s = Sub()
s.search_title = ''
s.build()
check('a cancelled search ends the directory as NOT succeeded',
      calls['ended'] == [False], repr(calls['ended']))
check('...and never builds the listing behind it',
      calls['base_build'] == 0,
      'POV built an empty directory anyway -- that is the blank screen')

s = Sub()
s.search_title = 'Sport'
s.build()
check('a real search still builds normally', calls['base_build'] == 1
      and calls['ended'] == [False], repr(calls))

rows = list(Sub().process_results())
check('the "new search" row comes FIRST in the results',
      len(rows) == 2 and rows[0][1] == 'new-search-item', repr(rows))
# It must carry ai_prompt. Absence of search_title is NOT enough any more:
# that combination now renders the intermediate screen, so a row relying on it
# would bounce the user to the screen instead of opening the keyboard.
check('...and it asks for the keyboard explicitly, via ai_prompt',
      rows and rows[0][0] ==
      'url://build_mdbl_list.search_mdbl_lists&ai_prompt=1',
      repr(rows[0] if rows else None))
check('...and the real results are still all there, after it',
      len(rows) == 2 and rows[1] == ('url://real', 'real-item', True),
      repr(rows))

# --- SABOTAGE: the refresh checks must be able to fail --------------------
# Restore the shipped-and-wrong behaviour and confirm the suite goes red.
sab = api_src.replace(
    extract(api_src, '_ai_refresh_after_like'),
    'def _ai_refresh_after_like():\n\tkodi_utils.container_refresh()\n')
saved, api_src = api_src, sab
try:
    fired = run_refresh(SEARCH, 'Sport')
    check('SABOTAGE: the 0.2.496 behaviour is detected as wrong',
          fired == ['Container.Refresh'],
          'restoring the bare refresh did not change the outcome -- the '
          'checks above are not testing the fix')
finally:
    api_src = saved


# --- the intermediate search screen, executed -----------------------------
# This is what makes Back mean what the build owner expected. The routing is
# the whole feature: the tile must render a SCREEN, the new-search rows must
# reach the KEYBOARD, and a history row must go straight to RESULTS. Get any
# one of those backwards and either Back breaks again or the tile stops
# prompting entirely.
entry = re.search(r'^def search_mdbl_lists\(params\):\n(?:[ \t]+.*\n)+',
                  menu_src, re.M)
check('the search entry point was patched', entry is not None)

if entry:
    routed = []
    g = {'_ai_mdbl_search_screen': lambda p: routed.append(('screen', p)),
         'SearchMdblLists': type('S', (), {
             '__init__': lambda self, p: routed.append(('list', p)) or None,
             'build': lambda self: 'built'})}
    exec(entry.group(0), g)
    fn = g['search_mdbl_lists']

    routed[:] = []
    fn({'name': 'MDBLIST: Search Lists'})
    check('the home tile opens the SCREEN, not the keyboard',
          routed and routed[0][0] == 'screen', repr(routed))

    routed[:] = []
    fn({'ai_prompt': '1'})
    check('a "new search" row goes on to prompt',
          routed and routed[0][0] == 'list', repr(routed))

    routed[:] = []
    fn({'search_title': 'Sport'})
    check('a history row goes straight to the results, no prompt',
          routed and routed[0][0] == 'list'
          and routed[0][1].get('search_title') == 'Sport', repr(routed))

    # SABOTAGE: if the redirect is dropped the tile prompts again and Back
    # goes back to being broken.
    g2 = dict(g)
    exec('def search_mdbl_lists(params):\n'
         '\treturn SearchMdblLists(params).build()\n', g2)
    routed[:] = []
    g2['search_mdbl_lists']({'name': 'x'})
    check('SABOTAGE: without the redirect the tile skips the screen',
          routed and routed[0][0] == 'list',
          'the routing checks above are not testing the redirect')

check('the screen offers a new search that prompts',
      "'ai_prompt': '1'" in menu_src and '_ai_new_search_str' in menu_src)
check('the screen reuses POV\'s own history storage and menus',
      '_ai_hist_key' in menu_src and 'remove_from_history' in menu_src
      and 'clear_search_history' in menu_src,
      'a parallel history mechanism was grown instead')
check('a completed search is remembered',
      'add_to_search_history' in menu_src,
      'the history screen would always be empty')


# --- the search screen itself, EXECUTED -----------------------------------
# Review mutated the history rows to point at ai_prompt instead of
# search_title -- which would make every remembered query re-open a blank
# keyboard rather than jump to its results, defeating the whole screen -- and
# both suites stayed green. The routing checks above stub this function out,
# so they cannot see inside it, and the substring checks stay true no matter
# WHICH row a string is attached to: the mutated line still contained
# "'ai_prompt': '1'". So the function is extracted and run here, and the
# assertions are on the URLs it actually emits.
screen_src = re.search(
    r'^def _ai_mdbl_search_screen\(params\):.*?(?=\n(?:def |class )|\Z)',
    menu_src, re.S | re.M)
check('the search screen builder was injected', screen_src is not None)

if screen_src:
    added_dirs, added_items, ended = [], [], []

    class _LI(object):
        def __init__(self):
            self.label, self.cm = None, []

        def setLabel(self, s):
            self.label = s

        def setArt(self, d):
            pass

        def addContextMenuItems(self, items):
            self.cm = items

    class _Cache(object):
        rows = ['Sport', 'Comedy']

        def get(self, key):
            return list(self.rows)

    mc = types.ModuleType('caches.main_cache')
    mc.MainCache = _Cache
    sys.modules['caches'] = types.ModuleType('caches')
    sys.modules['caches.main_cache'] = mc

    k = types.ModuleType('ku3')
    k.add_dir = lambda h, u, label, iconImage=None: added_dirs.append((u, label))
    k.add_items = lambda h, items: added_items.extend(items)
    k.set_category = lambda h, c: None
    k.set_content = lambda h, c: None
    k.end_directory = lambda h: ended.append(h)
    k.set_view_mode = lambda *a: None

    sys.argv = ['plugin://x', '9', '']
    g = {'kodi_utils': k, 'make_listitem': _LI, 'default_icon': 'i.png',
         'fanart': 'f.jpg', 'ls': lambda i: 'str%d' % i,
         '_ai_new_search_str': 'NEW', '_ai_hist_key': 'mdbl_list_queries',
         'build_url': lambda d: 'url://' + d['mode'] + ''.join(
             '&%s=%s' % kv for kv in sorted(d.items()) if kv[0] != 'mode')}
    exec(screen_src.group(0), g)
    g['_ai_mdbl_search_screen']({'name': 'MDBLIST: Search Lists'})

    check('the screen offers exactly one "new search" action',
          len(added_dirs) == 1, repr(added_dirs))
    check('...and it asks for the keyboard (ai_prompt), not another screen',
          added_dirs and added_dirs[0][0].get('ai_prompt') == '1'
          and 'search_title' not in added_dirs[0][0], repr(added_dirs))

    check('every remembered query is shown', len(added_items) == 2,
          repr([i[0] for i in added_items]))
    check('a history row jumps STRAIGHT to its results',
          all('search_title=' in i[0] for i in added_items),
          repr([i[0] for i in added_items]))
    check('...and never re-opens the keyboard instead',
          not any('ai_prompt' in i[0] for i in added_items),
          'a remembered query would prompt again -- the screen is pointless')
    check('the rows carry the query that was remembered',
          [i[0] for i in added_items] == [
              'url://build_mdbl_list.search_mdbl_lists&search_title=Sport',
              'url://build_mdbl_list.search_mdbl_lists&search_title=Comedy'],
          repr([i[0] for i in added_items]))
    check('each row can be removed, and the history cleared',
          all(len(i[1].cm) == 2 for i in added_items)
          and all('remove_from_history' in i[1].cm[0][1]
                  and 'clear_search_history' in i[1].cm[1][1]
                  and 'mdbl_list_queries' in i[1].cm[0][1]
                  for i in added_items),
          repr([i[1].cm for i in added_items]))
    check('the directory is finished exactly once', ended == [9], repr(ended))

    # ...and with nothing remembered yet, still a usable screen.
    added_dirs[:], added_items[:], ended[:] = [], [], []
    _Cache.rows = []
    g['_ai_mdbl_search_screen']({'name': 'x'})
    check('an empty history still renders the new-search action',
          len(added_dirs) == 1 and added_items == [] and ended == [9],
          'dirs=%r items=%r ended=%r' % (added_dirs, added_items, ended))
    _Cache.rows = ['Sport', 'Comedy']


# --- THE UPGRADE PATH: a device already carrying v2 must be healed ---------
# This is the scenario that made the whole release pointless and that neither
# suite covered. Both halves used to return 'unchanged' on seeing ANY marker in
# the family, so every device that took 0.2.496 kept v2 -- and nothing else
# would ever replace those files: the quickfix ships NO POV python, and the
# full build ships mdblist_api.py but not menus/mdblist.py. The fix would have
# reached only the users who did not have the bug.
import subprocess

v2_src = subprocess.run(
    ['git', 'show', 'a8e8634:addons/service.subtitles.kodipovilai/resources/'
     'lib/pov_mdblist_like_patcher.py'],
    capture_output=True, text=True, cwd=ROOT).stdout

if not v2_src.strip():
    check('the v2 patcher could be fetched from git', False,
          'cannot test the upgrade path without the real v2')
else:
    up = tempfile.mkdtemp()
    uproot = os.path.join(up, 'addons', 'plugin.video.pov')
    lay_down_pristine(uproot)
    pristine = {}
    for rel in ('resources/lib/menus/mdblist.py',
                'resources/lib/indexers/mdblist_api.py'):
        pristine[rel] = open(os.path.join(uproot, *rel.split('/')),
                             encoding='utf-8').read()

    vfs.translatePath = lambda p: p.replace(
        'special://home/addons/', os.path.join(up, 'addons') + os.sep)
    v2p = os.path.join(up, 'v2_patcher.py')
    with open(v2p, 'w', encoding='utf-8') as f:
        f.write(v2_src)
    sp = importlib.util.spec_from_file_location('_v2', v2p)
    v2mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(v2mod)
    st2 = v2mod.ensure_patched()
    check('v2 applies to the stock tree (the state real devices are in)',
          'patched' in str(st2), repr(st2))

    # ...and now the CURRENT patcher meets that device.
    importlib.reload(patcher) if False else None
    sp3 = importlib.util.spec_from_file_location('_v3', PATCHER)
    v3mod = importlib.util.module_from_spec(sp3)
    sp3.loader.exec_module(v3mod)
    st3 = v3mod.ensure_patched()
    check('the current patcher does NOT walk away from a v2 device',
          'unchanged' not in str(st3),
          'status %r -- v2 devices keep the bug forever' % (st3,))
    check('...and reports that it re-patched, so it is visible in the log',
          'repatched' in str(st3), repr(st3))

    up_menu = open(os.path.join(uproot, 'resources', 'lib', 'menus',
                                'mdblist.py'), encoding='utf-8').read()
    up_api = open(os.path.join(uproot, 'resources', 'lib', 'indexers',
                               'mdblist_api.py'), encoding='utf-8').read()
    check('the search-nav fix actually landed on the upgraded device',
          '_ai_new_search_item' in up_menu and 'succeeded=False' in up_menu,
          'the v3 menu overrides are not there')
    check('...including the intermediate screen and its entry redirect',
          '_ai_mdbl_search_screen' in up_menu
          and "params.get('ai_prompt')" in up_menu,
          'the newest half of the fix did not survive the upgrade')
    check('the refresh fix actually landed on the upgraded device',
          '_ai_refresh_after_like' in up_api
          and 'kodi_utils.container_refresh()' not in body(up_api,
                                                           'mdbl_like_a_list'),
          'the like body still carries the bare refresh')
    check('no v2 remnant is left stacked underneath',
          'AI_SUBS_MDBL_LIKE_v2' not in up_menu
          and 'AI_SUBS_MDBL_LIKE_v2' not in up_api,
          'both versions are now injected -- the user sees duplicate entries')
    check('exactly ONE Like entry, not two',
          up_menu.count('_ai_likelist_str, _ai_unlikelist_str') == 1,
          'the label block was injected twice')

    # The strongest check available: reverting a freshly patched file must
    # reproduce POV's own bytes. If it does not, the revert is shaving or
    # adding something and every upgrade drifts the file a little further.
    for rel, original in pristine.items():
        patched_now = open(os.path.join(uproot, *rel.split('/')),
                           encoding='utf-8').read()
        check('revert(patched %s) == POV byte for byte'
              % rel.split('/')[-1],
              v3mod._revert(patched_now) == original,
              'the revert does not round-trip -- repeated upgrades will drift '
              'this file')

    shutil.rmtree(up, ignore_errors=True)


# --- the revert_failed net, forced to fire --------------------------------
# Unreachable by construction today: every marker-bearing line is either the
# trigger for its own strip or nested inside a block already being discarded,
# so nothing survives _revert. 3000 fuzz trials in review found no input that
# left one behind. It is kept anyway, because it is the ONLY thing between a
# future change to _revert and silently writing a file with two versions
# stacked in it -- and a branch that has never once executed is not a net.
# So it is exercised here by making _revert fail on purpose.
rf = tempfile.mkdtemp()
rfroot = os.path.join(rf, 'addons', 'plugin.video.pov')
lay_down_pristine(rfroot)
vfs.translatePath = lambda p: p.replace('special://home/addons/',
                                        os.path.join(rf, 'addons') + os.sep)
sp = importlib.util.spec_from_file_location('_rf', PATCHER)
rfmod = importlib.util.module_from_spec(sp)
sp.loader.exec_module(rfmod)
rfmod.ensure_patched()                       # get the tree into a patched state

before = {}
for rel in ('resources/lib/menus/mdblist.py',
            'resources/lib/indexers/mdblist_api.py'):
    before[rel] = open(os.path.join(rfroot, *rel.split('/')),
                       encoding='utf-8').read()

rfmod.MARKER = '# AI_SUBS_MDBL_LIKE_v99'     # pretend a newer version arrived
rfmod._revert = lambda c: c                  # ...whose revert does not work
st = rfmod.ensure_patched()
check('a revert that leaves a marker behind is REFUSED, not written over',
      'revert_failed' in str(st), repr(st))
check('...and the file on disk is untouched',
      all(open(os.path.join(rfroot, *rel.split('/')),
               encoding='utf-8').read() == was
          for rel, was in before.items()),
      'the patcher wrote a file it had just refused')
check('...and the status is one service.py WARNs about',
      all(part.split('=', 1)[-1].strip()
          not in ('patched', 'repatched', 'unchanged', 'no_file')
          for part in str(st).split(',')
          if 'revert_failed' in part),
      'revert_failed would be logged as healthy')
shutil.rmtree(rf, ignore_errors=True)

shutil.rmtree(work, ignore_errors=True)
print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
