"""Overlay a reviewed stage-1 bridge onto the last cumulative quickfix.

The old quickfix also carries skin, helper and media updates. Publishing the
small bridge alone would strand users who skipped an earlier quickfix. The
community-pool credential is present only in the last shipped archive; its
logic must match source exactly before the shipped bytes can be inherited.
"""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

SERVICE = 'addons/service.subtitles.kodipovilai/'
POOL = SERVICE + 'resources/lib/pool.py'
STAGED_WIZARD = SERVICE + 'resources/modular_wizard_stage1.zip'
REQUEST = 'userdata/kodipovil.modular_bridge_requested'
LEGACY = 'userdata/kodipovil.legacy_migration'
KEY_BLOCK = re.compile(rb'__POOL_KEY_BEGIN__.*?__POOL_KEY_END__', re.S)


def _without_key(data):
    if len(KEY_BLOCK.findall(data)) != 1:
        raise ValueError('pool credential markers are missing or ambiguous')
    return KEY_BLOCK.sub(b'', data)


def build(previous, bridge, output):
    previous, bridge, output = map(Path, (previous, bridge, output))
    if output.resolve() in (previous.resolve(), bridge.resolve()):
        raise ValueError('output overlaps an input')
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(bridge) as staged:
        if old.testzip() or staged.testzip():
            raise ValueError('input ZIP failed CRC validation')
        old_infos, bridge_infos = old.infolist(), staged.infolist()
        old_names = [info.filename for info in old_infos]
        bridge_names = [info.filename for info in bridge_infos]
        if len(old_names) != len(set(old_names)) or len(bridge_names) != len(set(bridge_names)):
            raise ValueError('duplicate ZIP member')
        if not all(name.startswith(SERVICE) or name in (REQUEST, LEGACY)
                   for name in bridge_names):
            raise ValueError('bridge contains a member outside its approved scope')
        if not {POOL, STAGED_WIZARD, REQUEST, LEGACY}.issubset(bridge_names):
            raise ValueError('incomplete stage-1 bridge')
        old_pool, source_pool = old.read(POOL), staged.read(POOL)
        if _without_key(old_pool) != _without_key(source_pool):
            raise ValueError('pool logic changed; refusing to inherit credential')
        if b'b64decode' not in KEY_BLOCK.search(old_pool).group():
            raise ValueError('previous quickfix has a pool placeholder')
        plan = json.loads(staged.read(REQUEST))
        if hashlib.sha256(staged.read(STAGED_WIZARD)).hexdigest() != plan.get('sha256'):
            raise ValueError('staged Wizard hash differs from migration plan')
        output.parent.mkdir(parents=True, exist_ok=True)
        bridge_by_name = {info.filename: info for info in bridge_infos}
        with zipfile.ZipFile(output, 'w') as result:
            for info in old_infos:
                name = info.filename
                if info.is_dir():
                    payload = b''
                elif name == POOL:
                    payload = old_pool
                elif name in bridge_by_name:
                    payload = staged.read(name)
                else:
                    payload = old.read(name)
                result.writestr(info, payload)
            for info in bridge_infos:
                if info.filename not in old_names:
                    result.writestr(info, staged.read(info))
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(bridge) as staged, \
            zipfile.ZipFile(output) as result:
        if result.testzip() or len(result.namelist()) != len(set(result.namelist())):
            raise ValueError('output ZIP failed CRC or duplicate validation')
        for info in old.infolist():
            name = info.filename
            expected = (old.read(name) if name == POOL or name not in staged.namelist()
                        else staged.read(name))
            if result.read(name) != expected:
                raise ValueError('output changed an unexpected member: ' + name)
        if result.read(POOL) != old.read(POOL):
            raise ValueError('community-pool credential changed')
        if result.read(REQUEST) != staged.read(REQUEST):
            raise ValueError('migration request missing')
    return {'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'bytes': output.stat().st_size, 'members': len(result.namelist())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('previous', type=Path)
    parser.add_argument('bridge', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.previous, args.bridge, args.output), indent=2))


if __name__ == '__main__':
    main()
