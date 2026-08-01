# Teach POV to read the navigator rows it has always been shipped.
#
# Every row in navigator.db -- all eleven, on a fresh install -- is stored as a
# Python repr, so it carries single quotes:
#
#     [{'mode': 'myservices', 'name': '[B]חיבור שירותים[/B]', ...}]
#      ^ single quotes -- valid Python, not valid JSON
#
# POV 6.08.01 reads every one of them with json.loads
# (caches/__init__.py: jsloads), which raises on all eleven. Two read paths
# swallow that, each with its own visible symptom:
#
#   get_shortcut_folder_contents()  ->  `except: contents = []`
#       The folder renders with zero items. This is the "חיבור שירותים button
#       shows nothing" report, and also "חיפוש לפי שנה" and
#       "סרטים/סדרות - לפי רשתות" and both FENtastic personal areas.
#
#   get_list()  ->  `except: pass` -> returns None -> get_main_lists() calls
#       rebuild_database(), which overwrites the row with POV's own stock menu
#       via set_list() (json.dumps). The build's curated menu is replaced by
#       POV's default one, silently.
#
# Neither writes anything to the log. The folder is just empty and the menu is
# just POV's.
#
# THE FIX IS ON THE READ PATH, NOT IN THE DATABASE.
#
# The obvious repair -- rewrite the rows into JSON -- was written first and
# then thrown away, because it quietly breaks six other patchers in this
# add-on. pov_series_networks_reseed_patcher, pov_navigator_patcher (both the
# favourites-typo fix and the personal-area upgrade), pov_genre_folders_-
# reseed_patcher, pov_anime_hebrew_patcher, af3_home_patcher and
# standalone_cleanup all compare or substitute against repr-spelled literals.
# Converting the database makes every one of those comparisons miss: the
# reseeders stop recognising their own rows, the Hebrew anime renaming stops
# matching "'name': 'Anime'", and af3_home_patcher writes repr straight back.
# One of them (series-networks) even rewrites its row to repr on the very next
# step of the same startup, undoing the conversion permanently.
#
# Patching POV's two readers instead touches no data at all. Every row keeps
# the exact bytes it has today, so all six of those patchers keep working
# byte-for-byte, and POV can read the rows either way from now on.
#
# This is POV's own idea, incidentally: navigator_cache.rebuild_folders() does
# precisely this repr->JSON recovery. It is dead code -- nothing in 6.08.01
# calls it -- which is why the rows never healed.
#
# The injected helper uses ast.literal_eval, not POV's eval(): same result for
# a list of dicts, but it cannot execute anything.
#
# Marker-gated, compile()-checked, atomic, .pyc dropped. Safe no-op if POV is
# not installed or upstream changed these functions.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
NAV_CACHE_REL = 'resources/lib/caches/navigator_cache.py'
MARKER = '# AI_SUBS_POV_NAVREAD_v1'

# POV's file is tab-indented; every anchor below is verbatim from 6.08.01.

# Injected once, just above `class NavigatorCache`. Raising on a non-container
# keeps the callers' existing failure behaviour for anything unexpected --
# a bare string or number in list_contents is not a menu, and pretending it is
# would be worse than the empty folder.
_HELPER = (
    "def _ai_subs_literal(raw):\n"
    "\timport ast\n"
    "\tobj = ast.literal_eval(raw)\n"
    "\tif not isinstance(obj, (list, dict)): raise ValueError('not a menu')\n"
    "\treturn obj\n"
    "\n"
)
_HELPER_ANCHOR = "class NavigatorCache(BaseCache):"

# get_list: unchanged except that a json.loads failure now gets a second look.
# The no-row case (fetchone() returning None, so [0] raises TypeError) still
# returns None, which is what makes get_main_lists() rebuild -- that path is
# deliberately left alone.
_OLD_GET_LIST = (
    "\tdef get_list(self, list_name, list_type):\n"
    "\t\tcontents = None\n"
    "\t\ttry: contents = self.jsloads(self.dbcur.execute(GET_LIST, "
    "(list_name, list_type)).fetchone()[0])\n"
    "\t\texcept: pass\n"
    "\t\treturn contents"
)
_NEW_GET_LIST = (
    "\tdef get_list(self, list_name, list_type):\n"
    "\t\ttry: raw = self.dbcur.execute(GET_LIST, "
    "(list_name, list_type)).fetchone()[0]\n"
    "\t\texcept: return None\n"
    "\t\ttry: return self.jsloads(raw)\n"
    "\t\texcept: pass\n"
    "\t\ttry: return _ai_subs_literal(raw)\n"
    "\t\texcept: return None"
)

_OLD_FOLDER = (
    "\tdef get_shortcut_folder_contents(self, list_name):\n"
    "\t\ttry:\n"
    "\t\t\tcontents = self.dbcur.execute(GET_FOLDER_CONTENTS, "
    "(list_name, 'shortcut_folder')).fetchone()[0]\n"
    "\t\t\tcontents = self.jsloads(contents)\n"
    "\t\texcept: contents = []\n"
    "\t\treturn contents"
)
_NEW_FOLDER = (
    "\tdef get_shortcut_folder_contents(self, list_name):\n"
    "\t\ttry: raw = self.dbcur.execute(GET_FOLDER_CONTENTS, "
    "(list_name, 'shortcut_folder')).fetchone()[0]\n"
    "\t\texcept: return []\n"
    "\t\ttry: return self.jsloads(raw)\n"
    "\t\texcept: pass\n"
    "\t\ttry: return _ai_subs_literal(raw)\n"
    "\t\texcept: return []"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_navigator_read_patcher: ' + msg, level=level)
    except Exception:
        pass


def _nav_cache_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *NAV_CACHE_REL.split('/'))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'compile_failed' | 'read_failed' | 'write_failed'."""
    path = _nav_cache_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    # Both readers must be present. Patching only one would leave half the
    # menus readable and half not, which is harder to reason about than
    # leaving POV exactly as it is and saying so in the log.
    missing = [n for n, a in (('get_list', _OLD_GET_LIST),
                              ('get_shortcut_folder_contents', _OLD_FOLDER),
                              ('class NavigatorCache', _HELPER_ANCHOR))
               if a not in content]
    if missing:
        _log('navigator_cache.py does not look like 6.08.01 (no match for: '
             '{0}) -- leaving alone'.format(', '.join(missing)),
             level='WARNING')
        return 'unmatched'

    new_content = content.replace(_OLD_GET_LIST, _NEW_GET_LIST, 1)
    new_content = new_content.replace(_OLD_FOLDER, _NEW_FOLDER, 1)
    new_content = new_content.replace(
        _HELPER_ANCHOR, _HELPER + _HELPER_ANCHOR, 1)
    # Drop any superseded marker so an upgraded file carries exactly one.
    _prefix = MARKER.rsplit('_v', 1)[0]
    new_content = re.sub(r'[ \t]*' + re.escape(_prefix) + r'_v\d+\n', '',
                         new_content)
    new_content = new_content.replace('\n', '\n' + MARKER + '\n', 1)

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('navigator_cache.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    # Deliberately future tense. POV declares reuselanguageinvoker, so it has
    # already imported navigator_cache into a warm interpreter by the time this
    # runs, and nothing here cycles it: pov_reload.reload_if_patched() is called
    # earlier in main() than the repairs that arm it, so no POV source patch in
    # this add-on has ever taken effect in the session that applied it. That is
    # long-standing and left alone here rather than changed under a release --
    # and it costs nothing in practice, because the quick update that delivers
    # this restarts Kodi anyway.
    _log('POV will read the navigator rows it ships from the next start -- '
         'shortcut folders stop rendering empty and menus stop being replaced '
         'by POV defaults', level='INFO')
    return 'patched'
