#!/usr/bin/env python3
"""Offline upgrade/rollback drill using real POV trees copied to a temp dir.

This does not install anything in Kodi.  Both input trees are read-only.
"""

import argparse
import ast
import hashlib
import importlib.util
import shutil
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / 'wizard/source/plugin.program.kodipovilwizard/resources'
          / 'libs/modular_host_migration.py')
spec = importlib.util.spec_from_file_location('modular_host_migration', MODULE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def tree_digest(tree):
    """Hash file names and contents, so rollback checks more than addon.xml."""
    digest = hashlib.sha256()
    for file in sorted(p for p in tree.rglob('*') if p.is_file()):
        rel = file.relative_to(tree).as_posix().encode('utf-8')
        digest.update(len(rel).to_bytes(4, 'big'))
        digest.update(rel)
        with file.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def apply_candidate_patches(staged, candidate_wizard):
    """Run the candidate's actual patch engine on the staged tree only."""
    lib = candidate_wizard / 'resources/libs'
    engine_file = lib / 'patch_engine.py'
    registry_file = lib / 'patches/patches_config.py'
    registry_ast = ast.parse(registry_file.read_text(encoding='utf-8'))
    registry = None
    for node in registry_ast.body:
        if (isinstance(node, ast.Assign) and
                any(isinstance(target, ast.Name) and target.id == 'PATCH_CONFIG'
                    for target in node.targets)):
            registry = ast.literal_eval(node.value)
            break
    if not isinstance(registry, list):
        raise AssertionError('candidate PATCH_CONFIG is not a literal list')
    patches = [p for p in registry if p.get('addon_id') == migration.ADDON_ID
               and p.get('enabled', True)]
    if not patches:
        raise AssertionError('candidate has no active POV patches')

    xbmc = types.ModuleType('xbmc')
    xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = range(4)
    xbmcaddon = types.ModuleType('xbmcaddon')
    xbmcaddon.Addon = lambda: types.SimpleNamespace(getSetting=lambda _key: '')
    xbmcvfs = types.ModuleType('xbmcvfs')
    prefix = 'special://home/addons/plugin.video.pov'
    xbmcvfs.translatePath = lambda path: str(staged) + path[len(prefix):] if path.startswith(prefix) else path
    resources = types.ModuleType('resources')
    libs = types.ModuleType('resources.libs')
    common = types.ModuleType('resources.libs.common')
    logging = types.ModuleType('resources.libs.common.logging')
    logging.log = lambda *_args, **_kwargs: None
    common.logging = logging
    saved = {name: sys.modules.get(name) for name in
             ('xbmc', 'xbmcaddon', 'xbmcvfs', 'resources', 'resources.libs',
              'resources.libs.common', 'resources.libs.common.logging')}
    try:
        sys.modules.update({
            'xbmc': xbmc, 'xbmcaddon': xbmcaddon, 'xbmcvfs': xbmcvfs,
            'resources': resources, 'resources.libs': libs,
            'resources.libs.common': common,
            'resources.libs.common.logging': logging,
        })
        spec = importlib.util.spec_from_file_location('candidate_patch_engine', engine_file)
        engine_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine_module)
        stats = engine_module.PatchEngine(patches).run()
    finally:
        for name, prior in saved.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior
    if stats['applied'] != len(patches) or any(stats[key] for key in
                                              ('failed', 'anchor_missing',
                                               'missing', 'malformed')):
        raise AssertionError('candidate patch engine did not apply all POV patches: ' +
                             str(stats))
    for patch in patches:
        target = staged / patch['target_file']
        source = target.read_text(encoding='utf-8-sig')
        if patch['marker'] not in source:
            raise AssertionError('missing patch marker: ' + patch['id'])
        if target.suffix == '.py':
            ast.parse(source, filename=str(target))
    return len(patches)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean-tree', type=Path, required=True)
    parser.add_argument('--installed-tree', type=Path, required=True)
    parser.add_argument('--candidate-wizard', type=Path,
                        help='optional Menachem Wizard tree; run its 70 POV patches before swap')
    args = parser.parse_args()
    clean = args.clean_tree.resolve(strict=True)
    installed = args.installed_tree.resolve(strict=True)
    for tree in (clean, installed):
        if tree.name != migration.ADDON_ID or not tree.is_dir():
            parser.error('both trees must be plugin.video.pov directories')
        if ET.parse(tree / 'addon.xml').getroot().get('id') != migration.ADDON_ID:
            parser.error('both addon.xml files must identify POV')
    version = ET.parse(clean / 'addon.xml').getroot().get('version')
    old_digest = tree_digest(installed)
    clean_digest = tree_digest(clean)
    candidate = args.candidate_wizard.resolve(strict=True) if args.candidate_wizard else None

    with tempfile.TemporaryDirectory(prefix='modular-pov-drill-') as raw:
        root = Path(raw)
        addons = root / 'addons'
        addons.mkdir()
        host = addons / migration.ADDON_ID
        shutil.copytree(installed, host)
        userdata = root / 'userdata/addon_data/plugin.video.pov'
        userdata.mkdir(parents=True)
        settings = userdata / 'settings.xml'
        sentinel = b'<settings><setting id="test">retain-me</setting></settings>'
        settings.write_bytes(sentinel)
        archive = root / 'clean.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for file in clean.rglob('*'):
                if file.is_file():
                    bundle.write(file, migration.ADDON_ID + '/' +
                                 file.relative_to(clean).as_posix())
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        check = lambda path: tree_digest(path) == clean_digest
        staged = migration.stage_clean_host(
            archive, host, sha, version, check)
        if tree_digest(host) != old_digest:
            raise AssertionError('staging touched installed host')
        applied = apply_candidate_patches(staged, candidate) if candidate else 0
        staged_digest = tree_digest(staged)
        backup = migration.activate_staged_host(staged, host)
        if tree_digest(host) != staged_digest or tree_digest(backup) != old_digest:
            raise AssertionError('activation did not preserve both trees')
        migration.confirm_host(host, lambda path: tree_digest(path) == staged_digest)
        if migration.recover_unconfirmed(host) != 'confirmed':
            raise AssertionError('confirmed host was not stable')
        migration.rollback_host(host, allow_confirmed=True)
        if tree_digest(host) != old_digest or settings.read_bytes() != sentinel:
            raise AssertionError('rollback changed old host or user data')
    print('PASS: real-tree temp upgrade, confirmation, rollback, userdata')
    print('clean version: {}; old tree sha256: {}'.format(version, old_digest))
    if candidate:
        print('candidate POV patches applied and syntax-checked: {}'.format(applied))


if __name__ == '__main__':
    main()
