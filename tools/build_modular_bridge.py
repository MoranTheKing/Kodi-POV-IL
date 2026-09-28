"""Build a local quickfix bridge from reviewed modular addon directories.

The public legacy Wizard extracts quickfix ZIPs at special://home with
ignore=True. This bridge contains only three add-on trees and a migration
marker. It never ships userdata settings, skins, caches, or private handoffs.
Publishing the ZIP still requires the normal release gates and a new note.
"""

import argparse
import hashlib
import json
import os
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ADDON_IDS = (
    'plugin.program.kodipovilwizard',
    'plugin.program.orderfavourites-hebrew',
    'service.subtitles.kodipovilai',
)
MARKER = 'userdata/kodipovil.legacy_migration'


def build(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if output.is_relative_to(source):
        raise ValueError('bridge ZIP cannot be inside an addon source tree')
    files = []
    versions = {}
    for addon_id in ADDON_IDS:
        addon = source / addon_id
        xml_file = addon / 'addon.xml'
        data = ET.parse(xml_file).getroot()
        if data.get('id') != addon_id or not data.get('version'):
            raise ValueError('invalid addon.xml: ' + addon_id)
        versions[addon_id] = data.get('version')
        for path in addon.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            rel = path.relative_to(source).as_posix()
            files.append((path, 'addons/' + rel))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for path, member in sorted(files, key=lambda pair: pair[1]):
            info = zipfile.ZipInfo(member, (2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                        compresslevel=9)
        info = zipfile.ZipInfo(MARKER, (2024, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, 'legacy-quickfix-bridge\n')
    with zipfile.ZipFile(output) as zf:
        if zf.testzip() is not None:
            raise ValueError('bridge CRC check failed')
        members = set(zf.namelist())
        if MARKER not in members or any(
                'addons/' + addon_id + '/addon.xml' not in members
                for addon_id in ADDON_IDS):
            raise ValueError('bridge incomplete')
        if any(not (name.startswith('addons/' + ADDON_IDS[0] + '/') or
                    name.startswith('addons/' + ADDON_IDS[1] + '/') or
                    name.startswith('addons/' + ADDON_IDS[2] + '/') or
                    name == MARKER) for name in members):
            raise ValueError('unexpected bridge member')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {'sha256': digest, 'bytes': output.stat().st_size,
            'members': len(files) + 1, 'versions': versions}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', help='reviewed modular repository root')
    parser.add_argument('output', help='local ZIP path outside the public repo')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2))


if __name__ == '__main__':
    main()
