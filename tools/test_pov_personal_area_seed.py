"""Prove missing personal-area folders are restored without overwriting edits."""

import importlib.util
import os
import sqlite3
import tempfile


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
MODULE = os.path.join(
    ROOT, 'addons', 'service.subtitles.kodipovilai', 'resources', 'lib',
    'pov_navigator_patcher.py')
spec = importlib.util.spec_from_file_location('personal_seed_test', MODULE)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

FAIL = []


def check(label, condition, detail=''):
    print('{0:4} {1}{2}'.format(
        'ok' if condition else 'FAIL', label,
        (' -- ' + detail) if detail and not condition else ''))
    if not condition:
        FAIL.append(label)


with tempfile.TemporaryDirectory(prefix='pov-personal-seed-') as folder:
    db = os.path.join(folder, 'navigator.db')
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE navigator ('
        'list_name TEXT, list_type TEXT, list_contents TEXT)')
    conn.commit()
    conn.close()
    patcher._db_path = lambda: db
    patcher._mdblist_connected = lambda: False

    first = patcher.maybe_fix_personal_area_lists()
    check('both missing personal folders are seeded',
          set(first.values()) == {'seeded'}, str(first))
    conn = sqlite3.connect(db)
    rows = dict((name, (kind, contents)) for name, kind, contents in
                conn.execute('SELECT list_name,list_type,list_contents '
                             'FROM navigator'))
    check('movie folder has the current local/TMDB/Trakt/POV plan',
          rows.get(patcher.MOVIES_PA_NAME)
          == ('shortcut_folder', patcher.MOVIES_PA_V4))
    check('show folder has the current local/TMDB/Trakt/POV plan',
          rows.get(patcher.TVSHOWS_PA_NAME)
          == ('shortcut_folder', patcher.TVSHOWS_PA_V4))
    conn.close()

    second = patcher.maybe_fix_personal_area_lists()
    check('a second pass is idempotent',
          set(second.values()) == {'unchanged'}, str(second))

    conn = sqlite3.connect(db)
    conn.execute('UPDATE navigator SET list_contents=? WHERE list_name=?',
                 ('USER CUSTOM', patcher.MOVIES_PA_NAME))
    conn.execute('UPDATE navigator SET list_contents=? WHERE list_name=?',
                 (patcher.TVSHOWS_PA_V2, patcher.TVSHOWS_PA_NAME))
    conn.commit()
    conn.close()
    third = patcher.maybe_fix_personal_area_lists()
    conn = sqlite3.connect(db)
    current = dict(conn.execute(
        'SELECT list_name,list_contents FROM navigator'))
    conn.close()
    check('a user-customized movie folder is preserved',
          third[patcher.MOVIES_PA_NAME] == 'unchanged'
          and current[patcher.MOVIES_PA_NAME] == 'USER CUSTOM')
    check('a known old show folder is upgraded',
          third[patcher.TVSHOWS_PA_NAME] == 'fixed'
          and current[patcher.TVSHOWS_PA_NAME] == patcher.TVSHOWS_PA_V4)


if FAIL:
    print('\nFAILED: ' + ', '.join(FAIL))
    raise SystemExit(1)
print('\nAll POV personal-area seed checks passed.')
