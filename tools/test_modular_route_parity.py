#!/usr/bin/env python3
"""Protect the public MoranSubs RunScript/plugin action contract in migrations.

These are the 29 actions accepted by release 666's default.py.  A modular
rewrite may move their implementation, but existing Kodi favourites and skin
buttons still invoke this addon's action= route.  Deleting a route therefore
requires a separately verified migration of every caller; do not silently
accept a smaller dispatcher because the module itself imports successfully.
"""

import argparse
import ast
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'addons/service.subtitles.kodipovilai/default.py'
REQUIRED = frozenset((
    'bg_translate_picker', 'choose_subs', 'clear_cache', 'connect_gemini',
    'connect_mdblist', 'connect_telegram', 'darksubs_status',
    'debrid_notice_settings', 'download', 'engine_test', 'he_avail',
    'logout_telegram', 'manualsearch', 'mdblist_mirror_umbrella',
    'open_aistudio', 'open_pov_settings', 'open_tmdb_notice',
    'pool_share_cache', 'pool_share_cache_run', 'purge_temp',
    'remember_source_status', 'search', 'search_provider',
    'show_gemini_usage', 'telegram_test', 'test_connection', 'tonight',
    'torbox_status', 'translate_file',
))


def accepted_actions(source):
    tree = ast.parse(source)
    main = next((node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == 'main'),
                None)
    if main is None:
        raise ValueError('default.py has no main() dispatcher')
    actions = set()
    for node in ast.walk(main):
        if (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)
                and isinstance(node.left, ast.Name) and node.left.id == 'action'
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Constant)
                and isinstance(node.comparators[0].value, str)):
            actions.add(node.comparators[0].value)
    return actions


def main():
    # A broken parser that always returns the baseline must not certify a
    # rewritten dispatcher.  This tiny negative control runs on every check.
    if accepted_actions("def main():\n    if action == 'search':\n        pass\n") != {'search'}:
        raise AssertionError('route parser failed its negative control')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ADDON)
    parser.add_argument('--zip', type=Path)
    args = parser.parse_args()
    if args.zip:
        with zipfile.ZipFile(args.zip) as bundle:
            names = [name for name in bundle.namelist()
                     if name.endswith('/default.py') and name.count('/') == 1]
            if len(names) != 1:
                parser.error('ZIP must have exactly one top-level addon default.py')
            source = bundle.read(names[0]).decode('utf-8-sig')
    else:
        source = args.source.read_text(encoding='utf-8-sig')
    actual = accepted_actions(source)
    missing = REQUIRED - actual
    if missing:
        print('FAIL: missing release-666 action routes: ' + ', '.join(sorted(missing)))
        return 1
    print('ok: all {} release-666 action routes remain'.format(len(REQUIRED)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
