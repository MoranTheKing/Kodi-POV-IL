#!/usr/bin/env python3
"""SubSync against the REAL helper modules of every shipped MoranSubs tree.

The remote-playback safety suite replaces kodi_utils with a stub, so it could
not notice that the modular package's kodi_utils had lost
release_conflicts_with_episode(). subsync.playing_release() swallowed the
resulting AttributeError and returned '' for every title: each delivery was
logged "playing release unavailable" and was never verified or corrected.

This test imports the real modules (only the xbmc* API is stubbed) and:
  * resolves a real release name through playing_release();
  * statically checks that every module.attribute used between the add-on's
    own modules actually exists in that module.

Run: python3 tools/test_subsync_real_imports.py
"""
import ast
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREES = [ROOT / 'service.subtitles.kodipovilai',
         ROOT / 'addons' / 'service.subtitles.kodipovilai']
FAILS = []


def check(desc, cond, extra=''):
    print(('  ok  - ' if cond else '  FAIL- ') + desc
          + ('' if cond or not extra else ' [' + extra + ']'))
    if not cond:
        FAILS.append(desc)


def module_names(tree_root):
    # Only resources/lib/*.py: "from resources.lib import srt" names that file,
    # never the unrelated subs_engine/srt.py or subs_engine/cache.py.
    names = {}
    for path in (tree_root / 'resources' / 'lib').glob('*.py'):
        try:
            body = ast.parse(path.read_text(encoding='utf-8')).body
        except SyntaxError:
            continue
        defined = set()
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    defined.add((alias.asname or alias.name).split('.')[0])
        names[path.stem] = defined
    return names


def missing_attributes(tree_root):
    defined = module_names(tree_root)
    problems = []
    files = list((tree_root / 'resources' / 'lib').glob('*.py'))
    files += [tree_root / 'service.py', tree_root / 'default.py']
    for path in files:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        aliases = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.module
                    and node.module.endswith('resources.lib')):
                for alias in node.names:
                    if alias.name in defined:
                        aliases[alias.asname or alias.name] = alias.name
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)):
                target = aliases.get(node.value.id)
                if (target and target != path.stem
                        and node.attr not in defined.get(target, ())):
                    problems.append('%s uses %s.%s' % (
                        path.name, target, node.attr))
    return sorted(set(problems))


def load_tree(tree_root):
    for name in ('xbmc', 'xbmcgui', 'xbmcaddon', 'xbmcvfs'):
        sys.modules.setdefault(name, types.ModuleType(name))
    for name in [m for m in sys.modules if m.startswith('resources')]:
        del sys.modules[name]
    sys.path.insert(0, str(tree_root))
    try:
        from resources.lib import subsync  # noqa: E402
        return subsync
    finally:
        sys.path.remove(str(tree_root))


for tree_root in TREES:
    label = os.path.relpath(tree_root, ROOT)
    print('== %s ==' % label)
    problems = missing_attributes(tree_root)
    check('no call into a missing module attribute', not problems,
          '; '.join(problems[:5]))
    subsync = load_tree(tree_root)
    info = {'picked_release':
            'The.Flash.2014.S01E01.720p.HDTV.X264-DIMENSION.mkv',
            'season': '1', 'episode': '1', 'is_episode': True}
    check('playing_release resolves a real release name',
          subsync.playing_release(info)
          == 'The.Flash.2014.S01E01.720p.HDTV.X264-DIMENSION.mkv',
          repr(subsync.playing_release(info)))
    stale = dict(info, picked_release=
                 'The.Flash.2014.S01E07.720p.HDTV.X264-DIMENSION.mkv',
                 label='The.Flash.2014.S01E01.1080p.WEB-DL.H.264-NTb')
    check('a stale other-episode name is skipped, not trusted',
          subsync.playing_release(stale)
          == 'The.Flash.2014.S01E01.1080p.WEB-DL.H.264-NTb',
          repr(subsync.playing_release(stale)))
    from resources.lib import kodi_utils as ku  # noqa: E402
    for name, conflicts in (
            ('the.flash.2014.201.hdtv-lol[ettv]', True),
            ('the.flash.2014.101.hdtv-lol', False),
            ('The.Flash.2x01.HDTV', True), ('The.Flash.1x01.HDTV', False),
            ('Movie.2014.720p.WEB-DL', False),
            ('Show.S01E01.1920x1080.mkv', False),
            ('Blade.Runner.2049.1080p', False)):
        check('episode guard %r -> %s' % (name, conflicts),
              ku.release_conflicts_with_episode(name, 1, 1) is conflicts)

print()
if FAILS:
    print('FAILED (%d):' % len(FAILS))
    for item in FAILS:
        print('  - ' + item)
    sys.exit(1)
print('ALL TESTS PASSED')
