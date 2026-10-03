"""Replace an add-on only after its ZIP has been fully extracted and checked.

Used for the MoranSubs transition on existing installations.  The staging and
backup directories live in the Wizard's data area, on the same filesystem as
the installed add-on.  A crash between the two directory renames is repaired
on the next update check before version comparison.
"""

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import sys
import time
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path


_WINDOWS_DEVICE = re.compile(
    r'^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', re.I)


class NativeExtractionTimeout(IOError):
    pass


REQUEST_NAME = 'kodipovil.modular_service_handoff.json'
ACK_NAME = 'kodipovil.modular_service_handoff_ack.json'


def _handoff_paths(userdata):
    root = Path(userdata)
    return root / REQUEST_NAME, root / ACK_NAME


def read_handoff(userdata):
    request, ack = _handoff_paths(userdata)
    try:
        if request.stat().st_size > 2048:
            return None, None
        plan = json.loads(request.read_text(encoding='utf-8'))
        now = int(time.time())
        if (plan.get('schema') != 1 or
                plan.get('addon_id') != 'service.subtitles.kodipovilai' or
                not re.fullmatch(r'[0-9a-f]{32}', str(plan.get('token'))) or
                not re.fullmatch(r'[0-9a-f]{64}', str(plan.get('sha256'))) or
                not isinstance(plan.get('version'), str) or
                not isinstance(plan.get('created'), int) or
                not isinstance(plan.get('expires'), int) or
                plan['created'] > now + 300 or plan['expires'] < now or
                plan['expires'] > plan['created'] + 7 * 86400):
            return None, None
        response = None
        if ack.is_file() and ack.stat().st_size <= 1024:
            response = json.loads(ack.read_text(encoding='utf-8'))
            if (response.get('schema') != 1 or
                    response.get('token') != plan['token'] or
                    not isinstance(response.get('acked'), int) or
                    response['acked'] < plan['created'] or
                    response['acked'] > now + 300):
                response = None
        return plan, response
    except (OSError, ValueError, TypeError):
        return None, None


def request_handoff(userdata, version, sha256):
    """Ask the installed service to yield only on a later Kodi process."""
    plan, _ack = read_handoff(userdata)
    if plan and plan['version'] == version and plan['sha256'] == sha256:
        return plan
    request, ack = _handoff_paths(userdata)
    try:
        ack.unlink()
    except OSError:
        pass
    now = int(time.time())
    plan = {'schema': 1, 'addon_id': 'service.subtitles.kodipovilai',
            'token': secrets.token_hex(16), 'version': version,
            'sha256': sha256, 'creator_pid': os.getpid(),
            'created': now, 'expires': now + 86400}
    temp = request.with_name(request.name + '.tmp')
    with open(temp, 'w', encoding='utf-8') as output:
        json.dump(plan, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, request)
    return plan


def clear_handoff(userdata):
    for path in _handoff_paths(userdata):
        try:
            path.unlink()
        except OSError:
            pass


def _paths(addons_dir, package_path, addon_id):
    if (not isinstance(addon_id, str) or
            not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{1,100}', addon_id)):
        raise ValueError('invalid add-on id')
    addons = Path(addons_dir).resolve()
    package = Path(package_path).resolve()
    # Keep the temporary root short. Kodi on Windows still encounters MAX_PATH
    # in Python's os.mkdir for long subtitle-engine members; placing it under
    # addon_data/ota-packages adds ~100 characters and fails before the swap.
    # This sibling of addons is outside Kodi's add-on scanner and on its volume.
    stage_area = addons.parent
    if os.path.splitdrive(str(addons))[0].lower() != os.path.splitdrive(str(package))[0].lower():
        raise ValueError('staging and add-ons must be on the same volume')
    if addon_id == 'service.subtitles.kodipovilai':
        stem = '.kodipovil-ms'
    else:
        stem = '.kodipovil-' + hashlib.sha256(addon_id.encode('utf-8')).hexdigest()[:12]
    return addons / addon_id, stage_area / (stem + '-new'), stage_area / (stem + '-backup')


def _ready_path(stage):
    # Every staged add-on needs its own receipt. Sharing the MoranSubs name
    # lets a later skin/plugin update erase its prepared handoff on restart.
    return stage.parent / (stage.name[:-4] + '-ready.json')


def _read_ready(stage, addon_id):
    try:
        path = _ready_path(stage)
        if path.stat().st_size > 1024:
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        if (data.get('schema') == 1 and
                data.get('addon_id') == addon_id and
                isinstance(data.get('version'), str) and
                isinstance(data.get('files'), int) and
                isinstance(data.get('sha256'), str) and
                isinstance(data.get('created'), int)):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_ready(stage, addon_id, version, sha256, files):
    path = _ready_path(stage)
    temp = path.with_name(path.name + '.tmp')
    data = {'schema': 1, 'addon_id': addon_id,
            'version': version, 'sha256': sha256, 'files': files,
            'created': int(time.time())}
    with open(temp, 'w', encoding='utf-8') as output:
        json.dump(data, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def recover(addons_dir, package_path, addon_id):
    """Complete or roll back an interrupted directory swap, without deletion of live data."""
    target, stage, backup = _paths(addons_dir, package_path, addon_id)
    extract_root = stage.parent / '.kodipovil-ms-extract' if addon_id == 'service.subtitles.kodipovilai' else None
    if extract_root is not None and extract_root.exists():
        if extract_root.is_symlink():
            raise ValueError('symlinked extraction root')
        shutil.rmtree(str(extract_root))
    if backup.exists():
        if not target.exists():
            os.replace(str(backup), str(target))
        elif (target / 'addon.xml').is_file():
            shutil.rmtree(str(backup))
        else:
            raise RuntimeError('installed add-on lacks addon.xml; keeping backup')
    ready = _read_ready(stage, addon_id)
    if stage.exists() and ready and int(time.time()) - ready['created'] < 7 * 86400:
        return
    if stage.exists():
        shutil.rmtree(str(stage))
    try:
        _ready_path(stage).unlink()
    except OSError:
        pass


def _extract_kodi(zip_path, stage, addon_id, expected_files):
    """Use Kodi's own C++ Extract builtin, verified on Windows x86 QA."""
    try:
        import xbmc
    except ImportError:
        return False
    # The builtin parses comma-separated arguments, so unusual profile paths
    # fall back to the safe Python reader instead of changing their meaning.
    if any(char in str(path) for path in (zip_path, stage) for char in ',)('):
        return False
    root = stage.parent / '.kodipovil-ms-extract'
    if root.exists():
        if root.is_symlink():
            raise ValueError('symlinked extraction root')
        shutil.rmtree(str(root))
    root.mkdir()
    command = 'Extract({},{})'.format(zip_path, root)
    xbmc.executebuiltin(command, True)
    extracted = root / addon_id
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if extracted.is_dir() and sum(
                len(names) for _base, _dirs, names in os.walk(extracted)) == expected_files:
            os.replace(str(extracted), str(stage))
            shutil.rmtree(str(root))
            return True
        time.sleep(0.1)
    # A delayed Kodi extraction might still be writing. Leave the private
    # root for recovery on the next boot rather than deleting under it.
    raise NativeExtractionTimeout('Kodi ZIP extraction did not complete')


def _activate(target, stage, backup):
    if target.exists():
        os.replace(str(target), str(backup))
    try:
        os.replace(str(stage), str(target))
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(str(backup), str(target))
        raise
    if backup.exists():
        shutil.rmtree(str(backup))
    try:
        _ready_path(stage).unlink()
    except OSError:
        pass


def prepared_matches(addons_dir, addon_id, version, sha256):
    _target, stage, _backup = _paths(addons_dir, addons_dir, addon_id)
    ready = _read_ready(stage, addon_id)
    return bool(stage.is_dir() and ready and ready['version'] == version and
                ready['sha256'] == str(sha256).lower() and
                (stage / 'addon.xml').is_file())


def claim_restart_notice(addons_dir, addon_id, version, sha256):
    """Persist one notice in the existing prepared-package receipt.

    A renewed/cleared handoff request must not repeat the same package's toast.
    No extra user cache file or network request is needed.
    """
    _target, stage, _backup = _paths(addons_dir, addons_dir, addon_id)
    ready = _read_ready(stage, addon_id)
    if (not ready or ready['version'] != version or
            ready['sha256'] != str(sha256).lower() or
            ready.get('restart_notified') is True):
        return False
    ready['restart_notified'] = True
    path = _ready_path(stage)
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'w', encoding='utf-8') as output:
        json.dump(ready, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(str(temp), str(path))
    return True


def activate_prepared(addons_dir, addon_id, expected_version, expected_sha256):
    """Activate only a complete previously verified package after service yield."""
    target, stage, backup = _paths(addons_dir, addons_dir, addon_id)
    ready = _read_ready(stage, addon_id)
    if (not ready or ready['version'] != expected_version or
            ready['sha256'] != str(expected_sha256).lower() or
            not stage.is_dir()):
        raise ValueError('no matching prepared MoranSubs package')
    xml = stage / 'addon.xml'
    root = ET.parse(str(xml)).getroot()
    if (root.get('id') != addon_id or root.get('version') != expected_version or
            sum(len(names) for _root, _dirs, names in os.walk(stage)) != ready['files']):
        raise ValueError('prepared MoranSubs package failed identity/count check')
    _activate(target, stage, backup)
    return ready['files']


def install(zip_path, addons_dir, addon_id, expected_version, expected_sha256,
            defer_swap=False):
    target, stage, backup = _paths(addons_dir, zip_path, addon_id)
    recover(addons_dir, zip_path, addon_id)
    ready = _read_ready(stage, addon_id)
    if (ready and stage.is_dir() and ready['version'] == expected_version and
            ready['sha256'] == str(expected_sha256).lower()):
        if defer_swap:
            return ready['files']
        return activate_prepared(addons_dir, addon_id, expected_version,
                                 expected_sha256)
    if stage.exists():
        shutil.rmtree(str(stage))
    try:
        _ready_path(stage).unlink()
    except OSError:
        pass
    if Path(zip_path).stat().st_size > 25 * 1024 * 1024:
        raise ValueError('add-on ZIP exceeds compressed size limit')
    # Kodi's 32-bit Windows Python repeatedly stalled while ZipFile sought
    # between members on the package file. The service ZIP is bounded at
    # 25 MB; one read avoids those per-member file seeks.
    payload = Path(zip_path).read_bytes()
    if hashlib.sha256(payload).hexdigest() != str(expected_sha256).lower():
        raise ValueError('add-on ZIP SHA-256 mismatch')
    total = 0
    files = 0
    seen = set()
    created_dirs = {stage}
    prepared = False
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = []
            for info in archive.infolist():
                parts = info.filename.split('/')
                if (len(parts) < 2 or parts[0] != addon_id or
                        any(part in ('', '.', '..') for part in parts[1:-1]) or
                        '\\' in info.filename or info.filename.startswith('/') or
                        ':' in info.filename or info.flag_bits & 1 or
                        any(part.endswith((' ', '.')) or _WINDOWS_DEVICE.match(part)
                            or any(ord(char) < 32 for char in part)
                            for part in parts if part) or
                        ((info.external_attr >> 16) & 0o170000) not in
                        (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError('unsafe add-on ZIP member: ' + info.filename)
                if info.is_dir():
                    continue
                rel = parts[1:]
                if not rel[-1] or any(part in ('', '.', '..') for part in rel):
                    raise ValueError('unsafe add-on ZIP filename: ' + info.filename)
                key = '/'.join(rel).casefold()
                if key in seen:
                    raise ValueError('duplicate add-on ZIP member: ' + info.filename)
                seen.add(key)
                total += info.file_size
                files += 1
                if (info.file_size > 16 * 1024 * 1024 or
                        total > 30 * 1024 * 1024 or files > 2000):
                    raise ValueError('add-on ZIP exceeds safety limits')
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('unsupported add-on ZIP compression')
                members.append((info, rel))
            native = (addon_id == 'service.subtitles.kodipovilai' and
                      _extract_kodi(zip_path, stage, addon_id, files))
            if not native:
                stage.mkdir(parents=True, exist_ok=False)
            for info, rel in members:
                if native:
                    continue
                destination = stage.joinpath(*rel)
                parent = destination.parent
                if parent not in created_dirs:
                    parent.mkdir(parents=True, exist_ok=True)
                    while parent not in created_dirs:
                        created_dirs.add(parent)
                        parent = parent.parent
                # Work from the pinned in-memory archive. Kodi x86's
                # ZipExtFile._update_crc stalled on arbitrary small members;
                # deflate each member directly without repeated seeks/reads.
                offset = info.header_offset
                if (payload[offset:offset + 4] != b'PK\x03\x04' or
                        int.from_bytes(payload[offset + 8:offset + 10], 'little') !=
                        info.compress_type):
                    raise ValueError('invalid local ZIP header')
                name_len = int.from_bytes(payload[offset + 26:offset + 28], 'little')
                extra_len = int.from_bytes(payload[offset + 28:offset + 30], 'little')
                start = offset + 30 + name_len + extra_len
                end = start + info.compress_size
                if (offset + 30 > len(payload) or end > len(payload) or
                        payload[offset + 30:offset + 30 + name_len] !=
                        info.filename.encode('utf-8')):
                    raise ValueError('ZIP local entry differs from central directory')
                raw = payload[start:end]
                data = (raw if info.compress_type == zipfile.ZIP_STORED
                        else zlib.decompress(raw, -15))
                if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
                    raise ValueError('ZIP member size or CRC mismatch: ' + info.filename)
                with open(destination, 'xb') as output:
                    written = output.write(data)
                if written != info.file_size:
                    raise IOError('short add-on ZIP member: ' + info.filename)
            if native and sum(len(names) for _root, _dirs, names in os.walk(stage)) != files:
                raise IOError('native ZIP extraction omitted add-on files')
        addon_xml = stage / 'addon.xml'
        if not addon_xml.is_file():
            raise ValueError('add-on ZIP lacks addon.xml')
        root = ET.parse(str(addon_xml)).getroot()
        if root.get('id') != addon_id or root.get('version') != expected_version:
            raise ValueError('add-on identity or version mismatch')
        _write_ready(stage, addon_id, expected_version, str(expected_sha256).lower(), files)
        prepared = True
        if defer_swap:
            return files
        _activate(target, stage, backup)
        return files
    finally:
        # A timed-out helper may still have a tar child writing. Keep this
        # private staging tree for recovery on next boot rather than deleting
        # under an active writer.
        if (stage.exists() and not prepared and
                sys.exc_info()[0] is not NativeExtractionTimeout):
            shutil.rmtree(str(stage))
