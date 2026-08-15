# Give an MDBList list the same long-press menu a Trakt list already has.
#
# THE GAP. Long-pressing a list under MDBList -> "search lists" offers only
# "Add to a Menu", "Add to a Shortcut Folder" and "Export to TMDB". The SAME
# gesture on a Trakt list also offers "Like List" and "Unlike List"
# (menus/trakt.py). Nothing about MDBList makes it the odd one out -- POV
# simply never wired the two entries there.
#
# MDBLIST DOES SUPPORT IT, and that was worth settling before writing a menu
# entry that could not work. MDBList publishes an OpenAPI schema, readable
# without credentials at GET /schema/?format=json, and it defines the route:
#
#   /lists/{listid}/like   listid: integer, "The ID of the list to like"
#     put     "Like a List"    -- "PUT ensures the list is liked"
#     delete  "Unlike a List"  -- "DELETE ensures the list is not liked"
#     200 -> {"status": "liked"|"unliked", "like_count": int}
#
# so the numeric id POV already has (item['id']) is the right key, the verbs are
# the right way round, and the success body is non-empty JSON. The schema's
# entries for /lists/{listid} and /lists/{listid}/items match calls POV already
# ships, which is what makes it trustworthy rather than merely plausible.
#
# POV already reads the other half of this feature -- mdblist_api maps
# list_type 'liked_lists' to 'lists/liked', and the list plot already shows each
# list's like count -- so only the action was missing.
#
# (An earlier note here inferred the same thing from an Allow header. The
# inference was right but the evidence as written was not: the "unknown path"
# control answers 401, not 405. The schema replaces it.)
#
# NO ROUTER CHANGE IS NEEDED. entry.py sends every mode starting with
# 'mdblist.' to indexers.mdblist_api and calls mode.split('.')[-1], so defining
# the two functions in that module is the whole wiring.
#
# NO SKIN CHANGE IS NEEDED EITHER. This is POV's own context menu, built with
# listitem.addContextMenuItems, and Kodi draws it identically under every skin.
#
# (Umbrella has exactly the same gap -- like_list/unlike_list for Trakt only,
# and for MDBList nothing but a read of /lists/liked. Checked across matrix,
# nexus, omega and piers. Nothing to mirror from there.)
#
# ANCHORED BY SHAPE, NOT BY LITERAL. POV rewrites these files between releases
# -- the favourites patcher lost a whole release to a literal that stopped
# matching when 6.08.12 changed one argument and one level of indentation. So
# the menu edit anchors on "the line that appends add2menu_str", reusing its
# captured indentation, and the API edit anchors on "the line that defines
# delete_mdbl_list". Both survive renaming, re-nesting and added arguments.

import os
import re as _re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
API_REL_PATH = 'resources/lib/indexers/mdblist_api.py'
MENU_REL_PATH = 'resources/lib/menus/mdblist.py'

MARKER = '# AI_SUBS_MDBL_LIKE_v3'
# TWO different questions, and conflating them is what broke the v2 -> v3
# upgrade. MARKER answers "is the CURRENT version already applied" -> leave it
# alone. _MARKER_ANY answers "is ANY version of ours in there" -> if it is not
# the current one it must be REVERTED first, never injected beside, or the user
# gets two of each entry. Detecting only the family and returning 'unchanged'
# meant every device that took 0.2.496 kept v2 permanently.
_MARKER_ANY = '# AI_SUBS_MDBL_LIKE_v'

# POV's own string ids, the same two menus/trakt.py uses, so the entries read
# identically to the Trakt ones in every language POV ships.
_LIKE_ID, _UNLIKE_ID = 32776, 32783

# ---- the API half ---------------------------------------------------------
# Mirrors delete_mdbl_list, which is the closest existing shape: call, treat
# None as failure, clear the cached list bucket, tell the user, refresh.
# 'liked_lists' is the bucket that changes here -- clearing it is what makes
# the list appear in (or vanish from) "My Liked Lists" without a restart.
#
# AND THE MENU'S IN-PROCESS MEMO IS RESET TOO, which is not optional. POV ships
# reuselanguageinvoker=true, so menus.mdblist stays warm in sys.modules across
# invocations, and container_refresh() redraws in the SAME interpreter. Clearing
# only the on-disk cache would leave the memo holding the pre-click answer, so
# the row you just liked would keep offering "Like" for the rest of the session
# -- defeating the entire point of showing one entry. Imported inside the
# function: menus.mdblist imports this module at its top, so a module-level
# import here would be circular.
_API_FUNCS = '''
def _ai_refresh_after_like():  ''' + MARKER + '''
	"""Redraw the current listing so the flipped entry shows -- WITHOUT
	re-running a search prompt.

	A BARE Container.Refresh IS WRONG HERE, and 0.2.496 shipped it. POV's
	search results live at a path with NO search_title in it: the title was
	typed into a dialog, and SearchMdblLists.__init__ falls back to
	dialog.input('POV') whenever that parameter is absent. Refreshing that path
	therefore re-runs the prompt -- the user pressed Like, got "Success", and
	landed back on the keyboard.

	The title is recoverable without asking: SearchMdblLists sets
	category_name = search_title, and BaseList.build() hands it to
	setPluginCategory, so the live container is already carrying it. Refresh to
	the same path WITH the parameter and the same results redraw in place.

	When the title cannot be recovered -- blank category, or getInfoLabel
	itself failing so we cannot even tell which screen this is -- DO NOTHING.
	A stale menu entry is a small wrong thing that the next navigation fixes;
	opening a keyboard the user did not ask for is a large one. The unsafe flag
	is set in the except branch for exactly that reason: not knowing where we
	are has to fail closed, not fall through to the bare refresh."""
	target, unsafe = None, False
	try:
		import xbmc
		from urllib.parse import quote_plus
		path = xbmc.getInfoLabel('Container.FolderPath') or ''
		if 'search_mdbl_lists' in path and 'search_title=' not in path:
			unsafe = True
			title = xbmc.getInfoLabel('Container.PluginCategory') or ''
			if title.strip():
				sep = '&' if '?' in path else '?'
				target = '%s%ssearch_title=%s' % (path, sep, quote_plus(title))
	except Exception:
		unsafe = True
	try:
		if target: kodi_utils.execute_builtin('Container.Refresh(%s)' % target)
		elif not unsafe: kodi_utils.container_refresh()
	except Exception: pass

def mdbl_like_a_list(params):  ''' + MARKER + '''
	list_id = params['list_id']
	result = call_mdblist('lists/%s/like' % list_id, method='put')
	if result is None: return kodi_utils.notification(32574)
	mdbl_cache.clear_mdbl_list_data('liked_lists')
	try:
		from menus import mdblist as _ai_menu
		_ai_menu._ai_liked_ids_cache[0] = False
	except Exception: pass
	kodi_utils.notification(32576)
	_ai_refresh_after_like()

def mdbl_unlike_a_list(params):  ''' + MARKER + '''
	list_id = params['list_id']
	result = call_mdblist('lists/%s/like' % list_id, method='delete')
	if result is None: return kodi_utils.notification(32574)
	mdbl_cache.clear_mdbl_list_data('liked_lists')
	try:
		from menus import mdblist as _ai_menu
		_ai_menu._ai_liked_ids_cache[0] = False
	except Exception: pass
	kodi_utils.notification(32576)
	_ai_refresh_after_like()

'''

_API_ANCHOR_RE = _re.compile(r'^def delete_mdbl_list\(params\):', _re.M)

# ---- the menu half --------------------------------------------------------
# The two labels, defined once at module level next to POV's own. Anchored on
# whichever module-level line defines deletelist_str rather than on the exact
# tuple assignment, which has changed shape before.
_LABEL_ANCHOR_RE = _re.compile(
    r'^(?P<line>[^\n]*\bdeletelist_str\b[^\n]*=[^\n]*)$', _re.M)
_LABEL_LINE = ('_ai_likelist_str, _ai_unlikelist_str = ls(%d), ls(%d)  %s'
               % (_LIKE_ID, _UNLIKE_ID, MARKER))

# Insert the like/unlike branch immediately BEFORE the add2menu append, so the
# two land at the top of the menu exactly as they do for Trakt.
_MENU_ANCHOR_RE = _re.compile(
    r'^(?P<ind>[ \t]+)cm_append\(\(add2menu_str,', _re.M)

# ---- the search-screen half ------------------------------------------------
# Two defects that belong to POV's search flow rather than to the menu, both
# reported against 0.2.496 and both reachable in three keypresses.
#
# 1. CANCEL BUILT AN EMPTY SCREEN. dialog.input() returns '' when the user
#    cancels. SearchMdblLists carried that '' through fetch_results (which sets
#    lists = []) into a finished, empty directory -- so Cancel *navigated*, to a
#    blank listing with nothing in it and no way out but Back. Ending the
#    directory as NOT succeeded is what makes Kodi stay where it was, and is
#    what POV's own get_search_term already does with `if not query.strip()`.
#
# 2. A SECOND SEARCH MEANT GOING HOME. The results are the first directory
#    pushed after the home screen -- the keyboard is a dialog, not a screen --
#    so Back from them correctly lands on home, and searching again means
#    finding the tile a second time. POV solves this everywhere else with
#    search_history, whose first row is "NEW SEARCH...". MDBList's tile skips
#    that screen entirely, so the row is added to the results themselves: it
#    re-invokes this same mode with no search_title, which is precisely what
#    makes POV prompt.
#
#    This does NOT change what Back does, and deliberately so. Making Back
#    re-prompt would mean rendering the results at a child URL of a prompt URL,
#    and the only way to do that from a FOLDER item is to leave a directory
#    behind that re-prompts every time it is popped -- including after a
#    Cancel, which is defect 1 turned into a loop. The row gets the user what
#    Back was wanted for (type another list name, without leaving the screen)
#    without putting a trap in the navigation stack.
_SEARCH_ANCHOR_RE = _re.compile(
    r'^(?P<ind>[ \t]+)def fetch_results\(self\):[^\n]*\n'
    r'[ \t]+if self\.search_title:', _re.M)

_NEW_SEARCH_HELPER = (
    "_ai_new_search_str = '[B]חיפוש חדש...[/B]'  " + MARKER + "\n"
    "_ai_hist_key = 'mdbl_list_queries'  " + MARKER + "\n\n"
    "def _ai_new_search_item():  " + MARKER + "\n"
    "\t_ai_li = make_listitem()\n"
    "\t_ai_li.setLabel(_ai_new_search_str)\n"
    "\t_ai_li.setArt({'icon': default_icon, 'poster': default_icon,\n"
    "\t\t'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})\n"
    "\treturn _ai_li\n")

# The intermediate screen, which is what makes Back mean what the user expects.
#
# Before this, the tile opened the keyboard directly, so the results were the
# FIRST directory after the home screen -- a dialog leaves nothing on the
# navigation stack -- and Back from them correctly went home. There was no
# search screen to return to because there had never been one.
#
# The obvious repair, pushing a directory that re-prompts when you land back on
# it, is a trap: Back stops meaning "get me out of here" and starts meaning
# "ask me again", the only way out becomes Cancel, and Cancel from a directory
# that must still render something is exactly the blank screen this release is
# fixing. It is not even consistent -- POV caches directory listings when
# pov_kodi_menu_cache is on, so the re-prompt would simply not happen there.
#
# So this follows POV's own answer, menus/history.py: a plain LISTING that does
# not prompt on arrival -- "new search" plus the queries you have run before.
# Back from results lands on it, Back again goes home, Cancel at the keyboard
# leaves you on it. No trap, and search history comes free.
#
# It reuses POV's storage and POV's own context-menu modes rather than growing
# a parallel one: remove_from_history and clear_search_history are already
# routed in entry.py and take exactly the setting_id/query pair used here.
_SEARCH_SCREEN = (
    "def _ai_mdbl_search_screen(params):  " + MARKER + "\n"
    "\timport sys as _ai_sys\n"
    "\t_ai_h = int(_ai_sys.argv[1])\n"
    "\tkodi_utils.add_dir(_ai_h,\n"
    "\t\t{'mode': 'build_mdbl_list.search_mdbl_lists', 'ai_prompt': '1'},\n"
    "\t\t_ai_new_search_str, iconImage=default_icon)\n"
    "\ttry:\n"
    "\t\tfrom caches.main_cache import MainCache as _ai_MC\n"
    "\t\t_ai_rows = _ai_MC().get(_ai_hist_key) or []\n"
    "\texcept Exception:\n"
    "\t\t_ai_rows = []\n"
    "\t_ai_items = []\n"
    "\tfor _ai_q in _ai_rows:\n"
    "\t\ttry:\n"
    "\t\t\t_ai_li = make_listitem()\n"
    "\t\t\t_ai_li.setLabel('[I]%s[/I]' % _ai_q)\n"
    "\t\t\t_ai_li.setArt({'icon': default_icon, 'poster': default_icon,\n"
    "\t\t\t\t'thumb': default_icon, 'fanart': fanart,\n"
    "\t\t\t\t'banner': default_icon})\n"
    "\t\t\t_ai_li.addContextMenuItems([\n"
    "\t\t\t\t(ls(32698), 'RunPlugin(%s)' % build_url({\n"
    "\t\t\t\t\t'mode': 'remove_from_history',\n"
    "\t\t\t\t\t'setting_id': _ai_hist_key, 'query': _ai_q})),\n"
    "\t\t\t\t(ls(32699), 'RunPlugin(%s)' % build_url({\n"
    "\t\t\t\t\t'mode': 'clear_search_history',\n"
    "\t\t\t\t\t'setting_id': _ai_hist_key, 'query': _ai_q}))])\n"
    "\t\t\t_ai_items.append((build_url({\n"
    "\t\t\t\t'mode': 'build_mdbl_list.search_mdbl_lists',\n"
    "\t\t\t\t'search_title': _ai_q}), _ai_li, True))\n"
    "\t\texcept Exception: pass\n"
    "\tif _ai_items: kodi_utils.add_items(_ai_h, _ai_items)\n"
    "\tkodi_utils.set_category(_ai_h, params.get('name') or 'MDBList')\n"
    "\tkodi_utils.set_content(_ai_h, '')\n"
    "\tkodi_utils.end_directory(_ai_h)\n"
    "\tkodi_utils.set_view_mode('view.main', '')\n")

# The tile's mode is unchanged, so a favourite already saved to the home screen
# keeps working: it simply renders the screen now instead of the keyboard.
# ai_prompt=1 is what asks for the keyboard, and it is what the new-search rows
# on both screens send.
#
# INSERTED BESIDE POV'S LINE, NOT OVER IT, and the round-trip test is what
# forced that. The first cut rewrote the whole function -- which reverts to
# NOTHING, because _revert can only delete, so undoing it would have deleted
# POV's own `return SearchMdblLists(params).build()` and left an empty
# function. The redirect is therefore a single marked line above POV's, with
# its body on the SAME line so no block hangs off it: revert removes exactly
# that one line and POV's original is untouched underneath.
_ENTRY_ANCHOR_RE = _re.compile(
    r'^def search_mdbl_lists\(params\):\n'
    r'(?P<ind>[ \t]+)return SearchMdblLists\(params\)\.build\(\)\n', _re.M)


def _entry_block(m):
    ind = m.group('ind')
    return ('def search_mdbl_lists(params):\n'
            + ind + "if not params.get('search_title') and not "
            "params.get('ai_prompt'): return _ai_mdbl_search_screen(params)  "
            + MARKER + '\n'
            + ind + 'return SearchMdblLists(params).build()\n')

_SEARCH_BLOCK_LINES = (
    "def build(self):  " + MARKER,
    "\tif not (self.search_title or '').strip():",
    "\t\timport sys as _ai_sys, xbmcplugin as _ai_xp",
    "\t\treturn _ai_xp.endOfDirectory(int(_ai_sys.argv[1]), succeeded=False)",
    "\ttry:",
    "\t\tfrom menus.history import add_to_search_history as _ai_remember",
    "\t\t_ai_remember(self.search_title, _ai_hist_key)",
    "\texcept Exception: pass",
    "\treturn super().build()",
    "",
    "def process_results(self):  " + MARKER,
    "\tyield (build_url({'mode': 'build_mdbl_list.search_mdbl_lists',",
    "\t\t'ai_prompt': '1'}), _ai_new_search_item(), True)",
    "\tfor _ai_row in super().process_results(): yield _ai_row",
    "",
)


def _search_block(ind):
    return ''.join((ind + ln if ln else '') + '\n'
                   for ln in _SEARCH_BLOCK_LINES)


# ---- revert-then-reapply ---------------------------------------------------
# WITHOUT THIS, A VERSION BUMP REACHES NOBODY. Both halves used to return
# 'unchanged' the moment they saw ANY marker in the family, so a device already
# carrying v2 -- which is every device that took 0.2.496 -- would keep v2
# forever. Nothing else would heal it either: the quickfix ships NO POV python
# at all, and the full build ships mdblist_api.py but not menus/mdblist.py, so
# neither artifact ever replaces an injected file. The v3 fix for "Like opens
# the keyboard" would have shipped to exactly the users who did not have the
# bug. Verified against the real artifacts, not assumed.
#
# The revert is possible because every injected region has ONE shape, in both
# versions: a line carrying the marker, followed by its block -- lines indented
# strictly deeper than the marked line. That covers all of them, the single
# label line (no block), the module-level helpers, the context-menu branch
# nested five tabs deep, and the class overrides. So removal needs no knowledge
# of what any particular version wrote, which is the point: v4 will be able to
# revert v3 the same way, and this is checked by a test that patches a stock
# tree and asserts the revert reproduces it BYTE FOR BYTE.
#
# Trailing blank lines ARE consumed, and that is measured, not assumed. The
# first attempt handed them back on the theory that a block ends against POV's
# own spacing -- it does not: every blank line following an injected block is
# one the injection itself wrote (the templates carry their own separators), so
# giving them back left five stray blanks in mdblist.py and three in
# mdblist_api.py, which would have accumulated on every future version bump.
# The round-trip test below is what caught it and is what keeps it honest.
# READ THIS BEFORE EDITING ANY INJECTED TEMPLATE ABOVE.
#
# _revert knows nothing about Python syntax. It finds a marked line and eats
# everything indented deeper, full stop. That makes ONE rule load-bearing:
#
#   EVERY line of an injected block must be indented strictly deeper than its
#   marked first line -- INCLUDING lines inside docstrings and string literals.
#
# _ai_refresh_after_like's docstring is hand-indented with a leading tab on
# every line for exactly this reason, not for looks. Paste an example into it
# at column 0, or a copied comment block that happens to start flush-left, and
# the revert stops at that line, leaves the rest of the block behind, and the
# result does not compile.
#
# It fails SAFE, not destructively: _patch_api/_patch_menu compile() the
# candidate before writing, so a broken revert is refused and nothing is
# written. But "safe" here means the device is stuck on its OLD version
# forever, at every boot, with no way forward -- which is the same
# silently-stuck-forever outcome that made v2 devices unreachable in the first
# place, reached by a different door.
#
# The guard is the byte-for-byte round-trip check in
# tools/test_mdblist_search_nav.py: revert(patch(stock)) must equal stock. It
# will fail the moment this rule is broken. Do not weaken it.
def _revert(content):
    lines = content.split('\n')
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if _MARKER_ANY not in line:
            out.append(line)
            i += 1
            continue
        base = len(line) - len(line.lstrip())
        i += 1
        block = []
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= base:
                break
            block.append(nxt)
            i += 1
    return '\n'.join(out)

_RUN = ("cm_append((%s, 'RunPlugin(%%s)' %% build_url("
        "{'mode': 'mdblist.mdbl_%s_a_list', 'list_id': list_id})))")

# The ids the user has already liked -- read from POV's OWN cache row, never
# from the network, and at most once per process.
#
# THE READ MUST NOT BLOCK THE LISTING. mdbl_get_lists() would have been the
# obvious call, but it goes through cache_mdbl_object, which falls back to a
# live request on a cache miss -- inside process_results, the generator Kodi
# drains to draw the screen. On a cold cache with MDBList unreachable that
# freezes the whole list for the request timeout, to decide the wording of a
# context-menu entry the user may never open. A screen is worth more than a
# label. So this peeks the same SQLite row cache_mdbl_object would read and
# stops there.
#
# THE SHAPE IS CHECKED, NOT COERCED. POV's cache_mdbl_object writes its row
# UNCONDITIONALLY -- including when call_mdblist swallowed a RequestException
# and returned None, which persists json.dumps(None), the literal string
# 'null', under this very key, with no TTL. An earlier version unpacked that
# with `(json.loads(row) or {}).get('lists') or []`, and every one of those
# `or`s is a place where "we could not tell" quietly becomes "we know, and the
# answer is nothing": null -> None -> {} -> [] -> set(). The user would then
# see only "Like" on a list they HAD liked, silently, for as long as the
# poisoned row lived. isinstance checks instead, so a wrong shape falls to
# unknown the same way a corrupted row already did.
#
# Entries WITHOUT an id are dropped rather than stringified. str(None) is the
# perfectly ordinary string 'None', which would sit in the set and match any
# row whose own id was also null -- so one malformed entry could flip an
# unrelated row to "Unlike". Dropping it keeps every well-formed id in the same
# answer.
#
# THREE STATES, not two. A set means we know; None means we do NOT (cold cache,
# unreadable db, MDBList never connected) -- and "don't know" shows BOTH
# entries, exactly as this feature did before it learned to choose. That is
# always safe, because MDBList defines both verbs as idempotent: PUT "ensures
# the list is liked", DELETE "ensures the list is not liked", so the wrong one
# is a no-op and not an error.
#
# This is what lets the menu offer the entry that APPLIES instead of both, and
# it is affordable only because POV already caches this exact read:
# mdbl_get_lists('liked_lists') goes through mdbl_cache.cache_mdbl_object, so a
# page of search results costs one cached lookup rather than a request per row.
# (The same idea in Umbrella would cost a live request each time, which is why
# it was not proposed there.)
#
# FAIL-OPEN TO AN EMPTY SET, deliberately. If the lookup fails -- MDBList not
# connected, token expired, cold cache with no network -- every row falls back
# to offering "Like", and MDBList's own contract makes that harmless: the
# schema defines PUT as "ensures the list is liked", so liking an already-liked
# list succeeds instead of erroring. The degraded state is a menu that is
# merely less clever, never one that breaks.
_LIKED_HELPER = (
    "_ai_liked_ids_cache = [False]  " + MARKER + "\n"
    "\n"
    "def _ai_liked_ids():  " + MARKER + "\n"
    "\tif _ai_liked_ids_cache[0] is False:\n"
    "\t\ttry:\n"
    "\t\t\timport json as _ai_json\n"
    "\t\t\tfrom caches import mdbl_cache as _ai_mc\n"
    "\t\t\t_ai_cur = _ai_mc.MDBLCache().dbcur\n"
    "\t\t\t_ai_cur.execute(_ai_mc.MC_BASE_GET, ('mdbl_liked_lists',))\n"
    "\t\t\t_ai_row = _ai_cur.fetchone()\n"
    "\t\t\t_ai_data = _ai_json.loads(_ai_row[0]) if _ai_row else None\n"
    "\t\t\t_ai_lists = _ai_data.get('lists') if isinstance(_ai_data, dict)"
    " else None\n"
    "\t\t\t_ai_liked_ids_cache[0] = set(\n"
    "\t\t\t\tstr(i.get('id')) for i in _ai_lists\n"
    "\t\t\t\tif i.get('id') is not None\n"
    "\t\t\t) if isinstance(_ai_lists, list) else None\n"
    "\t\texcept Exception:\n"
    "\t\t\t_ai_liked_ids_cache[0] = None\n"
    "\treturn _ai_liked_ids_cache[0]\n")


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_mdblist_like_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _write(path, new_content):
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        return True
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return False


def _read(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return None


def _menu_block(ind):
    """The like/unlike branch, indented to match the menu POV already builds.

    The inner indent is derived from the captured one rather than assumed:
    POV writes these files with tabs, but a file that ever arrives
    space-indented would otherwise get a tab spliced into it and stop
    compiling -- which the compile check would catch, but only by refusing to
    apply the fix at all.
    """
    step = '\t' if ind.endswith('\t') else '    '
    inner, inner2 = ind + step, ind + step + step
    like = _RUN % ('_ai_likelist_str', 'like')
    unlike = _RUN % ('_ai_unlikelist_str', 'unlike')
    # ONE entry, the one that applies -- not both. A list you own gets neither
    # (POV already gives my_lists its own new/delete pair). A list already in
    # your liked lists can only be unliked, whether you reached it from "My
    # Liked Lists" or from a search. Anything else can only be liked.
    #
    # POV shows BOTH for Trakt in this same situation, so this is deliberately
    # better than the thing it was modelled on -- and it costs nothing extra,
    # because the liked set is a cached read POV already performs.
    # 'external' is EXCLUDED, and that is not tidiness. POV classifies a list
    # imported from another platform as 'external' and fetches it from a
    # different resource entirely -- external/lists/user, and its items from
    # external/lists/<id>/items, which POV's own get_mdbl_list_contents already
    # does. MDBList's schema has no write routes under external/lists at all,
    # so "Like" on such a row would call lists/<id>/like with an id from the
    # wrong id space: a guaranteed failure notification at best, and at worst a
    # numeric collision that likes a stranger's list. A button that can never
    # work does not belong in the menu.
    return (
        "%sif list_type not in ('my_lists', 'external'):  %s\n"
        "%s_ai_liked = _ai_liked_ids()\n"
        "%sif list_type == 'liked_lists' or (_ai_liked and str(list_id) in _ai_liked):\n"
        "%s%s\n"
        "%selse:\n"
        "%s%s\n"
        "%sif _ai_liked is None: %s\n"
        % (ind, MARKER, inner, inner, inner2, unlike,
           inner, inner2, like, inner2, unlike))


def _patch_api():
    path = _pov_path(API_REL_PATH)
    if not path:
        return 'no_file'
    content = _read(path)
    if content is None:
        return 'read_failed'
    if MARKER in content:
        return 'unchanged'
    # An OLDER version of ours is in there. Strip it and reapply, or this
    # device keeps the version it already has -- see _revert.
    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content)
        repatch = True
        if _MARKER_ANY in content:
            _log('could not fully remove the previous injection -- leaving '
                 'the file alone rather than stacking on top of it',
                 level='WARNING')
            return 'revert_failed'
    m = _API_ANCHOR_RE.search(content)
    if not m:
        _log('mdblist_api.py: delete_mdbl_list anchor not found -- shape '
             'changed upstream, skipping', level='WARNING')
        return 'unmatched'
    new_content = content[:m.start()] + _API_FUNCS.lstrip('\n') + content[m.start():]
    try:
        compile(new_content, path, 'exec')
    except Exception as e:
        # Not just SyntaxError: compile() also raises ValueError (a NUL byte in
        # the source is enough), and ensure_patched promises it never raises.
        _log('mdblist_api.py: patched content would not compile -- skipping '
             '({0})'.format(e), level='WARNING')
        return 'compile_failed'
    ok = 'repatched' if repatch else 'patched'
    return ok if _write(path, new_content) else 'write_failed'


def _patch_menu():
    path = _pov_path(MENU_REL_PATH)
    if not path:
        return 'no_file'
    content = _read(path)
    if content is None:
        return 'read_failed'
    if MARKER in content:
        return 'unchanged'
    # An OLDER version of ours is in there. Strip it and reapply, or this
    # device keeps the version it already has -- see _revert.
    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content)
        repatch = True
        if _MARKER_ANY in content:
            _log('could not fully remove the previous injection -- leaving '
                 'the file alone rather than stacking on top of it',
                 level='WARNING')
            return 'revert_failed'

    # Same uniqueness discipline as the menu anchor below. Taking the first of
    # several hits is a guess, and this file is one POV edit away from having
    # two label blocks.
    labels = _LABEL_ANCHOR_RE.findall(content)
    if len(labels) != 1:
        _log('mdblist.py: deletelist_str line matched {0} times, expected 1 -- '
             'not editing'.format(len(labels)), level='WARNING')
        return 'unmatched'
    hits = _MENU_ANCHOR_RE.findall(content)
    if len(hits) != 1:
        # Two call sites means POV grew a second list menu we have not looked
        # at; patching "the first" would be a guess.
        _log('mdblist.py: add2menu anchor matched {0} times, expected 1 -- '
             'not editing'.format(len(hits)), level='WARNING')
        return 'unmatched'
    # The search overrides are anchored separately, and their absence is NOT
    # fatal: the like/unlike menu is the feature, the search repairs ride
    # along. If POV reshapes SearchMdblLists we still want the menu, with a
    # warning naming what was skipped -- not a silent all-or-nothing.
    searches = _SEARCH_ANCHOR_RE.findall(content)
    if len(searches) != 1:
        _log('mdblist.py: SearchMdblLists.fetch_results anchor matched {0} '
             'times, expected 1 -- shipping the menu without the search '
             'repairs'.format(len(searches)), level='WARNING')

    mm = _MENU_ANCHOR_RE.search(content)
    new_content = (content[:mm.start()] + _menu_block(mm.group('ind'))
                   + content[mm.start():])
    helpers = _LIKED_HELPER
    if len(searches) == 1:
        helpers = helpers + '\n' + _NEW_SEARCH_HELPER
        sm = _SEARCH_ANCHOR_RE.search(new_content)
        new_content = (new_content[:sm.start()] + _search_block(sm.group('ind'))
                       + new_content[sm.start():])
        # The intermediate screen rides on the same anchor being sound: it is
        # only useful once build() can refuse a cancelled search, or landing
        # back on it would immediately re-prompt.
        entries = _ENTRY_ANCHOR_RE.findall(new_content)
        if len(entries) != 1:
            _log('mdblist.py: search_mdbl_lists entry matched {0} times, '
                 'expected 1 -- shipping without the search screen'
                 .format(len(entries)), level='WARNING')
        else:
            helpers = helpers + '\n' + _SEARCH_SCREEN
            new_content = _ENTRY_ANCHOR_RE.sub(_entry_block, new_content, 1)
    new_content = _LABEL_ANCHOR_RE.sub(
        lambda m: m.group('line') + '\n' + _LABEL_LINE + '\n\n' + helpers,
        new_content, 1)
    if new_content == content:
        return 'unmatched'
    try:
        compile(new_content, path, 'exec')
    except Exception as e:
        _log('mdblist.py: patched content would not compile -- skipping '
             '({0})'.format(e), level='WARNING')
        return 'compile_failed'
    ok = 'repatched' if repatch else 'patched'
    return ok if _write(path, new_content) else 'write_failed'


def ensure_patched():
    """Add Like List / Unlike List to MDBList's list context menu, and the two
    API calls behind them. Idempotent, defensive, never raises.

    THE API HALF GOES FIRST, AND THE MENU HALF DEPENDS ON IT. These are two
    files, and a future POV release can change the shape of one and not the
    other -- which is exactly what happened to the favourites patcher. If the
    menu were patched while the API anchor missed, the entry would still appear
    and fire mode 'mdblist.mdbl_like_a_list' at a function that does not exist:
    entry.py resolves it with a bare getattr and Router does not suppress, so
    the user gets an uncaught AttributeError out of POV's plugin entry point
    rather than a failed action. Worse, it would be permanent -- the menu
    file's own marker blocks any retry of that half forever.

    A menu entry must never outlive its handler, so the menu is only touched
    once the API side is known good.
    """
    # 'repatched' belongs in this set as much as the other two: the handler is
    # present and current. Leaving it out is not theoretical -- it is what the
    # first cut of the revert did, and the upgrade test caught it as
    # menu=skipped_no_api on exactly the v2 devices this release exists for.
    a = _patch_api()
    if a in ('patched', 'repatched', 'unchanged'):
        m = _patch_menu()
    else:
        m = 'skipped_no_api'
        _log('menu left alone: the API half is {0}, and an entry without its '
             'handler crashes POV rather than failing politely'.format(a),
             level='WARNING')
    summary = 'api={0}, menu={1}'.format(a, m)
    if 'patched' in (a, m) or 'repatched' in (a, m):
        _log('MDBList like/unlike applied (' + summary + ')', level='INFO')
    return summary
