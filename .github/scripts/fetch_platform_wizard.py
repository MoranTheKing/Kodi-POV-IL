"""Use the published, verified Wizard for every fresh platform installer."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from urllib.request import urlopen
from zipfile import ZipFile
import xml.etree.ElementTree as ET

ADDON = 'plugin.program.kodipovilwizard'


def fetch(manifest, source_addon, destination, env_file):
    entry = json.loads(Path(manifest).read_text('utf-8'))['addons'][ADDON]
    version = entry['version']
    if not re.fullmatch(r'\d+(?:\.\d+)+', version):
        raise ValueError('invalid Wizard version')
    source = ET.parse(source_addon).getroot()
    if source.get('id') != ADDON or source.get('version') != version:
        raise ValueError('publish the current Wizard before building platform installers')
    if not entry['zip'].startswith('https://'):
        raise ValueError('Wizard download must use HTTPS')
    with urlopen(entry['zip'], timeout=120) as response:
        data = response.read()
    if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('published Wizard size/hash mismatch')
    root = ADDON + '/'
    with ZipFile(io.BytesIO(data)) as package:
        names = package.namelist()
        if len(set(names)) != len(names) or package.testzip():
            raise ValueError('invalid Wizard archive')
        for name in names:
            if not name.startswith(root) or '\\' in name or '..' in PurePosixPath(name).parts:
                raise ValueError('invalid Wizard archive member')
        xml = ET.fromstring(package.read(root + 'addon.xml'))
        if xml.get('id') != ADDON or xml.get('version') != version:
            raise ValueError('published Wizard identity/version mismatch')
        for name in ('modular_updater.py', 'fresh_install.py'):
            if root + 'resources/libs/' + name not in names:
                raise ValueError('published Wizard lacks modular installation')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (ADDON + '-' + version + '.zip')
    target.write_bytes(data)
    with Path(env_file).open('a', encoding='utf-8') as handle:
        handle.write('WIZARD_VERSION=' + version + '\n')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('manifest', 'source-addon', 'destination', 'env-file'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print('Verified platform Wizard:', fetch(args.manifest, args.source_addon,
                                            args.destination, args.env_file).name)
