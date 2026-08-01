# Rewrite POV's navigator shortcut folders from Python repr into real JSON.
#
# Every shortcut folder in the build comes up EMPTY -- "חיבור שירותים",
# "חיפוש לפי שנה", "סרטים/סדרות - לפי רשתות", and both FENtastic personal
# areas. Seven folders, one cause.
#
# POV reads a folder's contents with json.loads (caches/__init__.jsloads), and
# these rows were written with Python's repr instead, so they carry single
# quotes:
#
#     [{'mode': 'myservices', 'name': '[B]חיבור שירותים[/B]', ...}]
#      ^ single quotes -- valid Python, not valid JSON
#
# json.loads raises, navigator.py's `except: contents = []` swallows it, and
# the folder renders with zero items. No error reaches the log; the folder just
# looks empty, which is why this read as "the button does nothing".
#
# The conversion is literal: parse with ast.literal_eval, re-serialise with
# json.dumps. Same data, a spelling POV can read. Nothing is invented, nothing
# is dropped, and a row that is already valid JSON is left untouched.
#
# Deliberately conservative, because this is the file the user's whole menu
# structure lives in:
#   * a row that will not literal_eval is left exactly as it is
#   * a row whose round-trip does not compare equal is left exactly as it is
#   * the whole update runs in one transaction, so a failure part-way leaves
#     the database as it was
#   * a backup copy is written first, once, before anything is changed

import ast
import json
import os
import shutil
import sqlite3

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
DB_RELATIVE = 'navigator.db'
FLAG = '_pov_navigator_json_v1'
SELECT = "SELECT list_name, list_type, list_contents FROM navigator"
UPDATE = ("UPDATE navigator SET list_contents=? "
          "WHERE list_name=? AND list_type=?")


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_navigator_json_patcher: ' + msg, level=level)
    except Exception:
        pass


def _db_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://profile/addon_data/{0}/'.format(POV_ADDON_ID))
    except Exception:
        return ''
    p = os.path.join(base, DB_RELATIVE)
    return p if os.path.isfile(p) else ''


def _already_done():
    if kodi_utils is None:
        return False
    try:
        return kodi_utils.get_setting(FLAG, '') == 'done'
    except Exception:
        return False


def _mark_done():
    if kodi_utils is None:
        return
    try:
        kodi_utils.set_setting(FLAG, 'done')
    except Exception:
        pass


def _to_json(raw):
    """A JSON spelling of `raw`, or None to leave the row alone.

    None is returned for anything this cannot vouch for: text that is already
    JSON (nothing to do), text that is not a Python literal at all, and text
    whose JSON round-trip does not reproduce the original object. The last one
    matters -- it is what rules out silently changing a value's meaning.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        json.loads(raw)
        return None                      # already readable by POV
    except Exception:
        pass
    try:
        obj = ast.literal_eval(raw)
    except Exception:
        return None                      # not a Python literal either
    if not isinstance(obj, (list, dict)):
        return None
    try:
        out = json.dumps(obj, ensure_ascii=False)
        if json.loads(out) != obj:
            return None                  # round-trip changed it
    except Exception:
        return None
    return out


def ensure_patched():
    """Returns 'already' | 'no_db' | 'unchanged' | 'converted:N' | 'failed'."""
    if _already_done():
        return 'already'
    path = _db_path()
    if not path:
        return 'no_db'
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=5000')
        cur = conn.cursor()
        rows = cur.execute(SELECT).fetchall()
        pending = []
        for name, ltype, raw in rows:
            fixed = _to_json(raw)
            if fixed is not None:
                pending.append((fixed, name, ltype))
        if not pending:
            _mark_done()
            return 'unchanged'
        # One backup, before the first write, so there is always a way back.
        try:
            backup = path + '.prejson'
            if not os.path.exists(backup):
                shutil.copyfile(path, backup)
        except OSError as e:
            _log('could not write a backup, not touching the database: '
                 '{0}'.format(e), level='WARNING')
            return 'failed'
        cur.execute('BEGIN IMMEDIATE')
        try:
            for args in pending:
                cur.execute(UPDATE, args)
            cur.execute('COMMIT')
        except Exception:
            try:
                cur.execute('ROLLBACK')
            except Exception:
                pass
            raise
        _log('converted {0} navigator row(s) from Python repr to JSON -- POV '
             'reads these with json.loads, so they were rendering as empty '
             'folders: {1}'.format(
                 len(pending), ', '.join(a[1] for a in pending)[:220]),
             level='WARNING')
        _mark_done()
        return 'converted:{0}'.format(len(pending))
    except Exception as e:
        _log('failed: {0}'.format(e), level='WARNING')
        return 'failed'
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
