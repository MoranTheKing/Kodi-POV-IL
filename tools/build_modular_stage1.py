"""Build the first, private-only legacy-to-modular quickfix rehearsal ZIP.

Phase 1 keeps the public MoranSubs service and its repair calls, adding a
pinned on-disk Wizard bootstrap. It deliberately does not ship the modular
MoranSubs service or change the public manifest. Phase 2 is a separate OTA
operation and remains blocked by the other migration release gates.
"""

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


SERVICE_ID = 'service.subtitles.kodipovilai'
WIZARD_ID = 'plugin.program.kodipovilwizard'
STAGED_MEMBER = 'addons/' + SERVICE_ID + '/resources/modular_wizard_stage1.zip'
REQUEST_MEMBER = 'userdata/kodipovil.modular_bridge_requested'
LEGACY_MEMBER = 'userdata/kodipovil.legacy_migration'
FIXED_TIME = (2024, 1, 1, 0, 0, 0)


def _put(bundle, member, data):
    info = zipfile.ZipInfo(member, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    bundle.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9)


def build(legacy_service, wizard_zip, output):
    service = Path(legacy_service).resolve()
    wizard_zip = Path(wizard_zip).resolve()
    output = Path(output).resolve()
    if service.name != SERVICE_ID or not (service / 'addon.xml').is_file():
        raise ValueError('expected public MoranSubs service tree')
    if output.is_relative_to(service) or output == wizard_zip:
        raise ValueError('output overlaps an input')
    if not (service / 'resources/lib/modular_legacy_bootstrap.py').is_file():
        raise ValueError('missing reviewed legacy bootstrap')
    if not (service / 'resources/lib/wizard_self_healer.py').read_text(
            encoding='utf-8').count('modular_legacy_bootstrap'):
        raise ValueError('old Wizard healer would overwrite the modular one')
    service_xml = ET.parse(service / 'addon.xml').getroot()
    if service_xml.get('id') != SERVICE_ID:
        raise ValueError('invalid public MoranSubs identity')
    with zipfile.ZipFile(wizard_zip) as candidate:
        if candidate.testzip() is not None:
            raise ValueError('candidate Wizard CRC failed')
        xml = ET.fromstring(candidate.read(WIZARD_ID + '/addon.xml'))
        if xml.get('id') != WIZARD_ID or not xml.get('version'):
            raise ValueError('candidate Wizard identity/version mismatch')
        if tuple(int(part) for part in xml.get('version').split('.')) < (0, 4, 3):
            raise ValueError('candidate Wizard predates modular bootstrap')
        for needed in ('startup.py', 'resources/libs/wizard.py',
                       'resources/libs/modular_updater.py'):
            candidate.getinfo(WIZARD_ID + '/' + needed)
        version = xml.get('version')
    wizard_bytes = wizard_zip.read_bytes()
    digest = hashlib.sha256(wizard_bytes).hexdigest()
    plan = json.dumps({'sha256': digest, 'version': version},
                      sort_keys=True).encode('utf-8') + b'\n'
    files = sorted(path for path in service.rglob('*') if path.is_file()
                   and '__pycache__' not in path.parts
                   and path.suffix not in ('.pyc', '.pyo'))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w') as bundle:
        for path in files:
            member = 'addons/' + SERVICE_ID + '/' + path.relative_to(service).as_posix()
            if member == STAGED_MEMBER:
                continue
            _put(bundle, member, path.read_bytes())
        _put(bundle, STAGED_MEMBER, wizard_bytes)
        _put(bundle, REQUEST_MEMBER, plan)
        _put(bundle, LEGACY_MEMBER, b'legacy-quickfix-bridge\n')
    with zipfile.ZipFile(output) as bundle:
        names = bundle.namelist()
        if bundle.testzip() is not None or len(names) != len(set(names)):
            raise ValueError('stage-1 bridge ZIP failed CRC/duplicate check')
        if not all(name.startswith('addons/' + SERVICE_ID + '/') or
                   name in (REQUEST_MEMBER, LEGACY_MEMBER) for name in names):
            raise ValueError('stage-1 bridge contains an unexpected file')
    return {'wizard_version': version, 'wizard_sha256': digest,
            'bridge_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'bytes': output.stat().st_size, 'members': len(names)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('legacy_service')
    parser.add_argument('wizard_zip')
    parser.add_argument('output')
    args = parser.parse_args()
    print(json.dumps(build(args.legacy_service, args.wizard_zip, args.output),
                     indent=2))


if __name__ == '__main__':
    main()
