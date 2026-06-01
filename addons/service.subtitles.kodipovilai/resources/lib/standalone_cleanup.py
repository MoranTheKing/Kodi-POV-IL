# Conservative cleanup for standalone installs of service.subtitles.kodipovilai.
#
# Older versions of the subtitle service also ran build-level patchers on
# startup. That was correct inside the managed Kodi POV IL build, but wrong
# for users who installed only the AI subtitle addon on top of their own POV
# setup. This module reverses only exact navigator.db rows that match the
# build patcher's known output. Unknown/user-customized data is left alone.

try:
    import sqlite3
except Exception:
    sqlite3 = None

try:
    from resources.lib import pov_navigator_patcher
except Exception:
    pov_navigator_patcher = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('standalone_cleanup: ' + msg, level=level)
    except Exception:
        pass


def _db_path():
    if pov_navigator_patcher is None:
        return ''
    try:
        return pov_navigator_patcher._db_path()
    except Exception:
        return ''


def ensure_cleaned():
    if sqlite3 is None or pov_navigator_patcher is None:
        return 'unavailable'
    path = _db_path()
    if not path:
        return 'no_db'

    targets = (
        (
            pov_navigator_patcher.MOVIES_PA_NAME,
            (
                pov_navigator_patcher.MOVIES_PA_V2,
                pov_navigator_patcher.MOVIES_PA_V3,
            ),
            pov_navigator_patcher.MOVIES_PA_V1,
        ),
        (
            pov_navigator_patcher.TVSHOWS_PA_NAME,
            (
                pov_navigator_patcher.TVSHOWS_PA_V2,
                pov_navigator_patcher.TVSHOWS_PA_V3,
            ),
            pov_navigator_patcher.TVSHOWS_PA_V1,
        ),
    )

    restored = []
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=2.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()
        for row_name, build_versions, standalone_value in targets:
            try:
                cur.execute(
                    'SELECT list_contents FROM navigator WHERE list_name=?',
                    (row_name,))
                row = cur.fetchone()
            except sqlite3.DatabaseError:
                continue
            if not row:
                continue
            current = row[0] or ''
            if current not in build_versions:
                continue
            try:
                cur.execute('BEGIN IMMEDIATE')
                cur.execute(
                    'UPDATE navigator SET list_contents=? WHERE list_name=?',
                    (standalone_value, row_name))
                cur.execute('COMMIT')
                restored.append(row_name)
            except Exception:
                try:
                    cur.execute('ROLLBACK')
                except Exception:
                    pass
                _log('failed restoring row: {0}'.format(row_name), 'WARNING')
    except sqlite3.OperationalError as e:
        _log('DB locked or unreadable: {0}'.format(e), 'WARNING')
        return 'failed'
    except Exception as e:
        _log(str(e), 'WARNING')
        return 'failed'
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if restored:
        return 'restored:{0}'.format(len(restored))
    return 'already_done'
