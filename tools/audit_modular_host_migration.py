#!/usr/bin/env python3
"""Offline upgrade/rollback drill using real POV trees copied to a temp dir.

This does not install anything in Kodi.  Both input trees are read-only.
"""

import argparse
import hashlib
import importlib.util
import shutil
import tempfile
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean-tree', type=Path, required=True)
    parser.add_argument('--installed-tree', type=Path, required=True)
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
        backup = migration.activate_staged_host(staged, host)
        if not check(host) or tree_digest(backup) != old_digest:
            raise AssertionError('activation did not preserve both trees')
        migration.confirm_host(host, check)
        if migration.recover_unconfirmed(host) != 'confirmed':
            raise AssertionError('confirmed host was not stable')
        migration.rollback_host(host, allow_confirmed=True)
        if tree_digest(host) != old_digest or settings.read_bytes() != sentinel:
            raise AssertionError('rollback changed old host or user data')
    print('PASS: real-tree temp upgrade, confirmation, rollback, userdata')
    print('clean version: {}; old tree sha256: {}'.format(version, old_digest))


if __name__ == '__main__':
    main()
