#!/usr/bin/env python3
"""Rename Kodi's Android package in an apktool-decoded tree without smali rebuild.

Kodi is fragile when apktool disassembles/reassembles classes.dex: JNI
registration can crash during System.loadLibrary("kodi"). This script is for
decoded trees produced with `apktool d -s`, where classes*.dex are kept as raw
DEX files. It patches same-length package strings in place, fixes DEX checksums,
and updates decoded XML/YAML resources.

Usage:
    patch_apk_package_binary.py <decoded-dir> <old.pkg> <new.pkg>

The old and new package ids must have identical length, e.g.
org.xbmc.kodi -> org.xbmc.povi.
"""

import hashlib
import os
from pathlib import Path
import struct
import sys
import zlib


TEXT_SUFFIXES = {
    '.py', '.xml', '.yml', '.yaml', '.json', '.txt', '.properties', '.cfg',
}
BINARY_SUFFIXES = {
    '.so', '.arsc',
}


def forms(pkg):
    return {
        'dotted': pkg.encode('ascii'),
        'slash': pkg.replace('.', '/').encode('ascii'),
        'dash': pkg.replace('.', '-').encode('ascii'),
        'underscore': pkg.replace('.', '_').encode('ascii'),
    }


def replace_forms(data, old, new):
    changed = False
    for key, old_value in forms(old).items():
        new_value = forms(new)[key]
        if len(old_value) != len(new_value):
            raise SystemExit('ERROR: replacement length mismatch for ' + key)
        if old_value in data:
            data = data.replace(old_value, new_value)
            changed = True
    return data, changed


def patch_dex(path, old, new):
    data = bytearray(path.read_bytes())
    data, changed = replace_forms(data, old, new)
    if not changed:
        return False
    data[12:32] = hashlib.sha1(bytes(data[32:])).digest()
    data[8:12] = struct.pack(
        '<I', zlib.adler32(bytes(data[12:])) & 0xffffffff)
    path.write_bytes(data)
    return True


def patch_text(path, old, new):
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('utf-8', errors='ignore')
    new_text = text.replace(old, new)
    new_text = new_text.replace(old.replace('.', '/'), new.replace('.', '/'))
    new_text = new_text.replace(old.replace('.', '-'), new.replace('.', '-'))
    new_text = new_text.replace(
        old.replace('.', '_'), new.replace('.', '_'))
    if new_text == text:
        return False
    path.write_text(new_text, encoding='utf-8')
    return True


def patch_binary(path, old, new):
    data, changed = replace_forms(path.read_bytes(), old, new)
    if changed:
        path.write_bytes(data)
    return changed


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    root = Path(sys.argv[1])
    old = sys.argv[2]
    new = sys.argv[3]
    if len(old) != len(new):
        raise SystemExit(
            'ERROR: old/new package ids must be the same length '
            f'({len(old)} vs {len(new)})')
    if not root.is_dir():
        raise SystemExit('ERROR: decoded dir not found: ' + str(root))

    changed = []
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        rel = path.relative_to(root).as_posix()
        if path.name.startswith('classes') and suffix == '.dex':
            if patch_dex(path, old, new):
                changed.append(rel)
        elif suffix in TEXT_SUFFIXES:
            if patch_text(path, old, new):
                changed.append(rel)
        elif suffix in BINARY_SUFFIXES:
            if patch_binary(path, old, new):
                changed.append(rel)

    if not changed:
        raise SystemExit('ERROR: no package references were patched')
    print('patched package refs in {0} files:'.format(len(changed)))
    for rel in changed:
        print('  ' + rel)


if __name__ == '__main__':
    main()
