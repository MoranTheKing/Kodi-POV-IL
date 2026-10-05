"""Preserve the cumulative quickfix, refreshing only the migration handoff.

The legacy updater extracts at special://home, so do not replace the running
Wizard. Stage the verified current release for a real process restart instead.
"""

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

SERVICE = 'addons/service.subtitles.kodipovilai/'
STAGED = SERVICE + 'resources/modular_wizard_stage1.zip'
REQUEST = 'userdata/kodipovil.modular_bridge_requested'
REPAIRS = ('modular_legacy_bootstrap.py', 'pov_navigator_read_patcher.py')


def build(previous, wizard, output, previous_sha, wizard_sha, repairs=None):
    previous, wizard, output = map(Path, (previous, wizard, output))
    repairs = Path(repairs or Path(__file__).parent / 'legacy_bridge')
    if output.resolve() in (previous.resolve(), wizard.resolve()):
        raise ValueError('output overlaps an input')
    for path, digest in ((previous, previous_sha), (wizard, wizard_sha)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('input SHA-256 mismatch: ' + path.name)
    wizard_bytes = wizard.read_bytes()
    with zipfile.ZipFile(wizard) as package:
        if package.testzip():
            raise ValueError('Wizard CRC failure')
        xml = ET.fromstring(package.read('plugin.program.kodipovilwizard/addon.xml'))
        if xml.get('id') != 'plugin.program.kodipovilwizard':
            raise ValueError('Wizard identity mismatch')
        version = xml.get('version')
        if tuple(map(int, version.split('.'))) < (0, 4, 31):
            raise ValueError('Wizard predates the current recovery release')
        for name in ('startup.py', 'resources/libs/modular_updater.py',
                     'resources/libs/patches/pov_nav_read_fix.py'):
            package.getinfo('plugin.program.kodipovilwizard/' + name)
    replacements = {STAGED: wizard_bytes, REQUEST: (json.dumps(
        {'version': version, 'sha256': wizard_sha}, sort_keys=True) + '\n').encode()}
    for name in REPAIRS:
        payload = (repairs / name).read_bytes()
        compile(payload, name, 'exec')
        replacements[SERVICE + 'resources/lib/' + name] = payload
    with zipfile.ZipFile(previous) as old:
        names = old.namelist()
        if old.testzip() or len(names) != len(set(names)):
            raise ValueError('previous quickfix CRC/duplicate failure')
        if not set(replacements).issubset(names):
            raise ValueError('previous quickfix is not a stage-1 bridge')
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w') as result:
            for info in old.infolist():
                result.writestr(info, replacements.get(info.filename, old.read(info)))
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(output) as result:
        if result.testzip() or result.namelist() != old.namelist():
            raise ValueError('output CRC/member set mismatch')
        for name in names:
            if result.read(name) != replacements.get(name, old.read(name)):
                raise ValueError('unexpected changed payload: ' + name)
    return dict(version=version, wizard_sha256=wizard_sha,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                bytes=output.stat().st_size, members=len(names),
                changed=sorted(replacements))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('previous', 'wizard', 'output', 'previous_sha', 'wizard_sha'):
        parser.add_argument(name)
    args = parser.parse_args()
    print(json.dumps(build(**vars(args)), indent=2))
