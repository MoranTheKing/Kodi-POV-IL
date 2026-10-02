#!/usr/bin/env python3
"""Build a minimal platform seed; full userdata is provisioned by the Wizard."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET

DEPENDENCIES = ('script.module.requests', 'script.module.six', 'script.module.certifi',
                'script.module.urllib3', 'script.module.chardet', 'script.module.idna')


def build(source, wizard, version, output):
    with ZipFile(wizard) as package:
        root = 'plugin.program.kodipovilwizard/'
        if ET.fromstring(package.read(root + 'addon.xml')).get('version') != version:
            raise ValueError('platform Wizard version mismatch')
        for required in ('resources/libs/modular_updater.py', 'resources/libs/fresh_install.py'):
            if root + required not in package.namelist():
                raise ValueError('platform Wizard lacks verified modular provisioning')
    prefixes = tuple('addons/' + aid + '/' for aid in DEPENDENCIES)
    with ZipFile(source) as source_zip, ZipFile(output, 'w', ZIP_DEFLATED) as target:
        for aid in DEPENDENCIES:
            xml = ET.fromstring(source_zip.read('addons/' + aid + '/addon.xml'))
            platform = xml.find("extension[@point='xbmc.addon.metadata']/platform")
            # Kodi treats an absent platform tag as all platforms.
            if platform is not None and (platform.text or '').strip() != 'all':
                raise ValueError('bootstrap dependency is platform-specific: ' + aid)
        for info in source_zip.infolist():
            if not info.filename.startswith(prefixes) or info.is_dir():
                continue
            if '..' in info.filename.split('/') or '\\' in info.filename:
                raise ValueError('invalid dependency ZIP member')
            if info.filename.lower().endswith(('.dll', '.so', '.pyd', '.dylib')):
                raise ValueError('native binary in pure-Python bootstrap dependency')
            target.writestr(info.filename, source_zip.read(info))
        target.writestr('userdata/guisettings.xml',
            '<settings version="2"><setting id="lookandfeel.skin">skin.estuary</setting></settings>')
        target.writestr('userdata/kodipovil.modular_install_started', '1\n')
    with ZipFile(output) as package:
        if package.testzip():
            raise ValueError('bootstrap CRC mismatch')
        if any(name.startswith('addons/plugin.video.') for name in package.namelist()):
            raise ValueError('legacy build leaked into platform bootstrap')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('source', 'wizard', 'version', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    build(args.source, args.wizard, args.version, args.output)
    print('Verified minimal platform bootstrap:', Path(args.output).name)
