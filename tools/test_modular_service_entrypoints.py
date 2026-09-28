#!/usr/bin/env python3
"""Guard service startup work that must survive a modular migration.

This is a conservative call-site gate. Moving a callback to Wizard requires
replacing this check with a behavioural test for the new owner; merely leaving
the function's module on disk does not prove it runs on Kodi startup.
"""

import argparse
import ast
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'addons/service.subtitles.kodipovilai/service.py'
CRITICAL = frozenset((
    '_ensure_darksubs_enabled',
    '_maybe_patch_darksubs',
    '_maybe_patch_darksubs_download_sub',
    '_maybe_patch_darksubs_embedded_insert',
    '_maybe_patch_darksubs_opensubtitles',
    '_maybe_patch_pov_debrid_resolve',
    '_maybe_patch_pov_remember_source',
    '_maybe_patch_pov_subtitle_match',
))


def startup_calls(source):
    tree = ast.parse(source)
    main = next((node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == 'main'),
                None)
    if main is None:
        raise ValueError('service.py has no main()')
    return {node.func.id for node in ast.walk(main)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def main():
    # A parser returning a hard-coded baseline would certify a deleted path.
    if startup_calls('def main():\n    _ensure_darksubs_enabled()\n') != {
            '_ensure_darksubs_enabled'}:
        raise AssertionError('call-site parser failed its negative control')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT)
    parser.add_argument('--zip', type=Path)
    args = parser.parse_args()
    if args.zip:
        with zipfile.ZipFile(args.zip) as bundle:
            names = [name for name in bundle.namelist()
                     if name.endswith('/service.py') and name.count('/') == 1]
            if len(names) != 1:
                parser.error('ZIP must have exactly one top-level addon service.py')
            source = bundle.read(names[0]).decode('utf-8-sig')
    else:
        source = args.source.read_text(encoding='utf-8-sig')
    missing = CRITICAL - startup_calls(source)
    if missing:
        print('FAIL: startup behaviour lacks verified replacement for: '
              + ', '.join(sorted(missing)))
        return 1
    print('ok: all {} critical service startup calls remain'.format(len(CRITICAL)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
