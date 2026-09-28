"""Fail-closed, offline POV host swap for a future modular migration.

This module is intentionally not wired into the running Wizard.  The caller
must supply a known SHA-256 and version for an official clean POV ZIP, plus a
health check for the staged files and one after activation.  Addon data lives
outside the code directory and is never read or modified here.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ADDON_ID = 'plugin.video.pov'
JOURNAL_NAME = '.plugin.video.pov-modular-migration.json'
STAGE_PREFIX = '.plugin.video.pov-stage-'
BACKUP_PREFIX = '.plugin.video.pov-backup-'
FAILED_PREFIX = '.plugin.video.pov-failed-'
MAX_FILES = 12000
MAX_UNCOMPRESSED = 256 * 1024 * 1024
_SAFE_SUFFIX = re.compile(r'^[0-9a-f]{32}$')
_WINDOWS_DEVICE = re.compile(r'^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', re.I)


class MigrationError(Exception):
    pass


def _host_path(path):
    host = Path(path).absolute()
    if host.name != ADDON_ID or not host.parent.is_dir():
        raise MigrationError('host must be an existing addons/plugin.video.pov path')
    if host.is_symlink() or host.parent.is_symlink():
        raise MigrationError('symlinked host paths are not supported')
    return host


def _digest(path):
    sha = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def _validated_members(bundle, expected_version):
    files = []
    seen = set()
    total = 0
    prefix = ADDON_ID + '/'
    for member in bundle.infolist():
        raw = member.filename
        if '\\' in raw:
            raise MigrationError('ZIP contains a noncanonical path separator')
        name = raw.replace('\\', '/')
        if not name.startswith(prefix) or raw.startswith(('/', '\\')) or ':' in name:
            raise MigrationError('ZIP contains a path outside the POV addon')
        parts = name.split('/')
        if any(part in ('', '.', '..') for part in parts[:-1]) or (
                not member.is_dir() and parts[-1] in ('', '.', '..')):
            raise MigrationError('ZIP contains an unsafe path')
        if any((part.endswith((' ', '.')) or _WINDOWS_DEVICE.match(part)
                or any(ord(char) < 32 for char in part))
               for part in parts if part):
            raise MigrationError('ZIP contains a Windows-unsafe path')
        mode = (member.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK or (mode and mode not in (stat.S_IFREG, stat.S_IFDIR)):
            raise MigrationError('ZIP contains a special file')
        if member.flag_bits & 1:
            raise MigrationError('encrypted ZIP members are unsupported')
        if member.is_dir():
            continue
        folded = name.casefold()
        if folded in seen:
            raise MigrationError('ZIP contains duplicate paths')
        seen.add(folded)
        files.append((member, parts[1:]))
        total += member.file_size
        if len(files) > MAX_FILES or total > MAX_UNCOMPRESSED:
            raise MigrationError('POV ZIP exceeds the migration size limit')
    addon_xml = prefix + 'addon.xml'
    if addon_xml.casefold() not in seen:
        raise MigrationError('POV ZIP has no addon.xml')
    try:
        root = ET.fromstring(bundle.read(addon_xml))
    except (ET.ParseError, KeyError, zipfile.BadZipFile) as exc:
        raise MigrationError('invalid POV addon.xml: {}'.format(exc))
    if root.get('id') != ADDON_ID or root.get('version') != expected_version:
        raise MigrationError('POV ZIP identity/version mismatch')
    bad_crc = bundle.testzip()
    if bad_crc:
        raise MigrationError('POV ZIP CRC failure')
    return files


def stage_clean_host(archive, host_path, expected_sha256, expected_version,
                     health_check):
    """Extract a verified clean host beside an installed host; never switch it.

    Returns the staged addon path.  The caller must retain it until activation
    or remove the temporary stage after deciding not to migrate.
    """
    host = _host_path(host_path)
    if not host.is_dir():
        raise MigrationError('installed POV addon is missing')
    if not callable(health_check):
        raise MigrationError('a staged-host health check is required')
    expected = str(expected_sha256).lower()
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise MigrationError('expected SHA-256 must be 64 hex characters')
    archive = Path(archive)
    if _digest(archive) != expected:
        raise MigrationError('POV ZIP SHA-256 mismatch')
    with zipfile.ZipFile(archive) as bundle:
        files = _validated_members(bundle, expected_version)
        stage_root = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=str(host.parent)))
        staged = stage_root / ADDON_ID
        try:
            staged.mkdir()
            for member, parts in files:
                dest = staged.joinpath(*parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, open(dest, 'wb') as target:
                    shutil.copyfileobj(source, target)
            if not health_check(staged):
                raise MigrationError('staged POV health check failed')
            return staged
        except Exception:
            # This directory was just created by mkdtemp under the validated
            # addons parent.  Refuse cleanup if that invariant changed.
            if stage_root.parent == host.parent and stage_root.name.startswith(STAGE_PREFIX):
                shutil.rmtree(stage_root)
            raise


def _journal_path(host):
    return host.parent / JOURNAL_NAME


def _write_journal(path, state, suffix):
    payload = {'schema': 1, 'addon_id': ADDON_ID, 'state': state,
               'suffix': suffix}
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'w', encoding='utf-8') as target:
        json.dump(payload, target, sort_keys=True)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temp, path)


def _read_journal(host):
    path = _journal_path(host)
    try:
        with open(path, 'r', encoding='utf-8') as source:
            data = json.load(source)
    except (OSError, ValueError) as exc:
        raise MigrationError('migration journal unavailable: {}'.format(exc))
    if (data.get('schema') != 1 or data.get('addon_id') != ADDON_ID
            or data.get('state') not in ('prepared', 'old_moved',
                                         'pending_validation', 'confirmed',
                                         'rollback_in_progress', 'rolled_back')
            or not _SAFE_SUFFIX.fullmatch(str(data.get('suffix', '')))):
        raise MigrationError('invalid migration journal')
    return data


def activate_staged_host(staged_path, host_path):
    """Swap staged code for installed code and retain the old tree as backup.

    The new code remains *pending_validation* until confirm_host() runs a
    separate post-switch health check.  Never call during live playback.
    """
    host = _host_path(host_path)
    staged = Path(staged_path).absolute()
    if (not host.is_dir() or staged.name != ADDON_ID or not staged.is_dir()
            or staged.is_symlink() or staged.parent.parent != host.parent
            or not staged.parent.name.startswith(STAGE_PREFIX)):
        raise MigrationError('invalid staged or installed POV tree')
    journal = _journal_path(host)
    if journal.exists():
        previous = _read_journal(host)
        previous_backup = host.parent / (BACKUP_PREFIX + previous['suffix'])
        if previous['state'] != 'rolled_back' or previous_backup.exists():
            raise MigrationError('a POV migration journal already exists')
        history = journal.with_name(journal.name + '.history-' + previous['suffix'])
        if history.exists():
            raise MigrationError('POV migration history already exists')
        os.replace(journal, history)
    suffix = uuid.uuid4().hex
    backup = host.parent / (BACKUP_PREFIX + suffix)
    _write_journal(journal, 'prepared', suffix)
    try:
        os.replace(host, backup)
        _write_journal(journal, 'old_moved', suffix)
        os.replace(staged, host)
        _write_journal(journal, 'pending_validation', suffix)
    except Exception:
        # A process crash between renames is handled by rollback_host() on
        # the next boot.  For ordinary exceptions, restore immediately.
        if backup.is_dir():
            try:
                rollback_host(host)
            except Exception:
                pass
        elif host.is_dir():
            try:
                _write_journal(journal, 'rolled_back', suffix)
            except Exception:
                pass
        raise
    return backup


def rollback_host(host_path, allow_confirmed=False):
    """Restore the saved addon tree; quarantine the new tree.

    A confirmed migration requires an explicit allow_confirmed=True call;
    automatic recovery must never undo a validated update by accident.
    """
    host = _host_path(host_path)
    data = _read_journal(host)
    if data['state'] == 'confirmed' and not allow_confirmed:
        raise MigrationError('confirmed migration requires explicit rollback')
    backup = host.parent / (BACKUP_PREFIX + data['suffix'])
    if not backup.is_dir() or backup.is_symlink():
        raise MigrationError('POV backup missing; refusing destructive rollback')
    failed = host.parent / (FAILED_PREFIX + data['suffix'])
    if host.exists() and failed.exists():
        raise MigrationError('failed-host quarantine already exists')
    _write_journal(_journal_path(host), 'rollback_in_progress', data['suffix'])
    if host.exists():
        os.replace(host, failed)
    os.replace(backup, host)
    _write_journal(_journal_path(host), 'rolled_back', data['suffix'])
    return host


def confirm_host(host_path, health_check):
    """Confirm only after the caller's independent post-switch health check."""
    host = _host_path(host_path)
    data = _read_journal(host)
    if data['state'] != 'pending_validation' or not callable(health_check):
        raise MigrationError('POV migration is not pending validation')
    try:
        healthy = bool(health_check(host))
    except Exception:
        healthy = False
    if not healthy:
        rollback_host(host)
        raise MigrationError('post-switch POV health check failed; old host restored')
    _write_journal(_journal_path(host), 'confirmed', data['suffix'])
    return host.parent / (BACKUP_PREFIX + data['suffix'])


def recover_unconfirmed(host_path):
    """Restore interrupted swaps before POV can start from a half-updated tree.

    This must run before loading POV code.  A confirmed migration is left
    untouched; an unconfirmed new tree is moved to quarantine, never deleted.
    """
    host = _host_path(host_path)
    journal = _journal_path(host)
    if not journal.exists():
        return 'no_journal'
    data = _read_journal(host)
    if data['state'] in ('confirmed', 'rolled_back'):
        return data['state']
    backup = host.parent / (BACKUP_PREFIX + data['suffix'])
    if data['state'] == 'prepared' and not backup.exists() and host.is_dir():
        _write_journal(journal, 'rolled_back', data['suffix'])
        return 'not_swapped'
    if data['state'] == 'rollback_in_progress' and not backup.exists() and host.is_dir():
        # Recovery may have crashed after restoring the backup but before
        # writing the final journal.  This state was written before rollback.
        _write_journal(journal, 'rolled_back', data['suffix'])
        return 'restored'
    rollback_host(host)
    return 'restored'
