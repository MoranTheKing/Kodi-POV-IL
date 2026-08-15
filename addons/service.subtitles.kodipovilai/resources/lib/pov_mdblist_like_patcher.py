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

MARKER = '# AI_SUBS_MDBL_LIKE_v2'
# Detection is by FAMILY, not by exact version: a device carrying an older
# version must read as already-patched and be left alone, because injecting v2
# beside v1 would give the user two of each entry. (v1 never shipped, so this
# is insurance rather than migration.)
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
def mdbl_like_a_list(params):  ''' + MARKER + '''
	list_id = params['list_id']
	result = call_mdblist('lists/%s/like' % list_id, method='put')
	if result is None: return kodi_utils.notification(32574)
	mdbl_cache.clear_mdbl_list_data('liked_lists')
	try:
		from menus import mdblist as _ai_menu
		_ai_menu._ai_liked_ids_cache[0] = None
	except Exception: pass
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

def mdbl_unlike_a_list(params):  ''' + MARKER + '''
	list_id = params['list_id']
	result = call_mdblist('lists/%s/like' % list_id, method='delete')
	if result is None: return kodi_utils.notification(32574)
	mdbl_cache.clear_mdbl_list_data('liked_lists')
	try:
		from menus import mdblist as _ai_menu
		_ai_menu._ai_liked_ids_cache[0] = None
	except Exception: pass
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

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

_RUN = ("cm_append((%s, 'RunPlugin(%%s)' %% build_url("
        "{'mode': 'mdblist.mdbl_%s_a_list', 'list_id': list_id})))")

# The ids the user has already liked, read ONCE per plugin process.
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
    "_ai_liked_ids_cache = [None]  " + MARKER + "\n"
    "\n"
    "def _ai_liked_ids():  " + MARKER + "\n"
    "\tif _ai_liked_ids_cache[0] is None:\n"
    "\t\ttry:\n"
    "\t\t\t_ai_liked_ids_cache[0] = set(str(i.get('id')) for i in "
    "(mdblist_api.mdbl_get_lists('liked_lists') or []))\n"
    "\t\texcept Exception:\n"
    "\t\t\t_ai_liked_ids_cache[0] = set()\n"
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
        "%sif list_type == 'liked_lists' or str(list_id) in _ai_liked_ids():\n"
        "%s%s\n"
        "%selse:\n"
        "%s%s\n"
        % (ind, MARKER, inner, inner2, unlike, inner, inner2, like))


def _patch_api():
    path = _pov_path(API_REL_PATH)
    if not path:
        return 'no_file'
    content = _read(path)
    if content is None:
        return 'read_failed'
    if _MARKER_ANY in content:
        return 'unchanged'
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
    return 'patched' if _write(path, new_content) else 'write_failed'


def _patch_menu():
    path = _pov_path(MENU_REL_PATH)
    if not path:
        return 'no_file'
    content = _read(path)
    if content is None:
        return 'read_failed'
    if _MARKER_ANY in content:
        return 'unchanged'

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
    mm = _MENU_ANCHOR_RE.search(content)
    new_content = (content[:mm.start()] + _menu_block(mm.group('ind'))
                   + content[mm.start():])
    new_content = _LABEL_ANCHOR_RE.sub(
        lambda m: m.group('line') + '\n' + _LABEL_LINE + '\n\n' + _LIKED_HELPER,
        new_content, 1)
    if new_content == content:
        return 'unmatched'
    try:
        compile(new_content, path, 'exec')
    except Exception as e:
        _log('mdblist.py: patched content would not compile -- skipping '
             '({0})'.format(e), level='WARNING')
        return 'compile_failed'
    return 'patched' if _write(path, new_content) else 'write_failed'


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
    a = _patch_api()
    if a in ('patched', 'unchanged'):
        m = _patch_menu()
    else:
        m = 'skipped_no_api'
        _log('menu left alone: the API half is {0}, and an entry without its '
             'handler crashes POV rather than failing politely'.format(a),
             level='WARNING')
    summary = 'api={0}, menu={1}'.format(a, m)
    if a == 'patched' or m == 'patched':
        _log('MDBList like/unlike applied (' + summary + ')', level='INFO')
    return summary
