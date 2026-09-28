"""One-time, fail-closed handoff from the public Wizard to the modular Wizard.

The first bridge quickfix contains this module and a pinned Wizard ZIP, but
does not replace Wizard files while the old quickfix interpreter is running.
This runs from MoranSubs on the following service start and keeps the old
Wizard tree as a rollback copy. It never touches userdata/addon_data.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile

try:
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
except ImportError:  # also exercised by filesystem-only regression tests
    xbmc = xbmcaddon = xbmcgui = xbmcvfs = None


WIZARD_ID = 'plugin.program.kodipovilwizard'
SERVICE_ID = 'service.subtitles.kodipovilai'
REQUEST = 'kodipovil.modular_bridge_requested'
READY = 'kodipovil.modular_bridge_ready'
ROLLBACK = '.kodipovil-wizard-stage1-rollback'
STAGED_ZIP = os.path.join('resources', 'modular_wizard_stage1.zip')
MAX_ZIP_BYTES = 25 * 1024 * 1024
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 1000
REQUIRED = ('addon.xml', 'startup.py', 'resources/libs/wizard.py',
            'resources/libs/modular_updater.py')


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path, parent):
    # realpath() can block inside Kodi's 32-bit Windows interpreter while it
    # resolves junctions on a widget-heavy boot. ZIP symlinks are forbidden
    # above, and these paths are built under a freshly created local folder.
    root = os.path.normcase(os.path.abspath(parent))
    target = os.path.normcase(os.path.abspath(path))
    return os.path.commonpath((root, target)) == root


def _validate_zip(path, expected_sha, expected_version):
    if not os.path.isfile(path) or os.path.getsize(path) > MAX_ZIP_BYTES:
        raise ValueError('missing or oversized staged Wizard ZIP')
    if _sha256(path) != expected_sha:
        raise ValueError('staged Wizard SHA-256 mismatch')
    prefix = WIZARD_ID + '/'
    with zipfile.ZipFile(path) as bundle:
        entries = bundle.infolist()
        if not entries or len(entries) > MAX_MEMBERS:
            raise ValueError('staged Wizard ZIP failed member-count check')
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError('duplicate staged Wizard path')
        if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
            raise ValueError('staged Wizard ZIP is too large when unpacked')
        for entry in entries:
            name = entry.filename
            parts = name.replace('\\', '/').split('/')
            checked_parts = parts[:-1] if entry.is_dir() else parts
            if (not name.startswith(prefix) or '\\' in name or ':' in name or
                    any(part in ('', '.', '..') for part in checked_parts) or
                    (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('unsafe staged Wizard path: ' + name)
        if bundle.testzip() is not None:
            raise ValueError('staged Wizard ZIP failed CRC check')
        for name in REQUIRED:
            if prefix + name not in names:
                raise ValueError('missing staged Wizard file: ' + name)
        # The ZIP is pinned by SHA-256 before this check. Reading only the
        # opening tag avoids ElementTree's slow first import in Kodi x86's
        # startup interpreter while still rejecting the wrong add-on/version.
        xml_text = bundle.read(prefix + 'addon.xml').decode('utf-8-sig')
        start = xml_text.find('<addon')
        opening = xml_text[start:].split('>', 1)[0] if start >= 0 else ''
        addon_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', opening)
        version = re.search(r'\bversion\s*=\s*["\']([^"\']+)["\']', opening)
        if (not addon_id or addon_id.group(1) != WIZARD_ID or
                not version or version.group(1) != expected_version):
            raise ValueError('staged Wizard identity/version mismatch')
    return entries


def _installed_matches(wizard_dir, archive_path, entries):
    """Verify every archived file before declaring an interrupted swap done."""
    if not os.path.isdir(wizard_dir):
        return False
    with zipfile.ZipFile(archive_path) as bundle:
        for entry in entries:
            if entry.is_dir():
                continue
            rel = entry.filename[len(WIZARD_ID) + 1:]
            target = os.path.join(wizard_dir, *rel.split('/'))
            if not _inside(target, wizard_dir) or not os.path.isfile(target):
                return False
            if os.path.getsize(target) != entry.file_size:
                return False
            with bundle.open(entry) as source, open(target, 'rb') as installed:
                while True:
                    expected = source.read(1024 * 1024)
                    if installed.read(1024 * 1024) != expected:
                        return False
                    if not expected:
                        break
    return True


def _restore_interrupted_swap(addons_root):
    """Restore the old Wizard if Kodi stopped between the two renames."""
    live = os.path.join(addons_root, WIZARD_ID)
    backup = os.path.join(addons_root, ROLLBACK)
    if os.path.lexists(live) or not os.path.isdir(backup):
        return False
    addon_xml = os.path.join(backup, 'addon.xml')
    if not os.path.isfile(addon_xml):
        raise ValueError('Wizard rollback tree has no addon.xml')
    with open(addon_xml, 'r', encoding='utf-8-sig') as stream:
        xml_start = stream.read(4096)
    if '<addon' not in xml_start:
        raise ValueError('Wizard rollback tree has no addon tag')
    opening = xml_start.split('<addon', 1)[1].split('>', 1)[0]
    addon_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', opening)
    if not addon_id or addon_id.group(1) != WIZARD_ID:
        raise ValueError('Wizard rollback identity mismatch')
    os.replace(backup, live)
    return True


def install_staged_wizard(archive_path, expected_sha, expected_version,
                          addons_root):
    """Stage, verify, swap, and retain a rollback tree on the same filesystem."""
    addons_root = os.path.abspath(addons_root)
    live = os.path.join(addons_root, WIZARD_ID)
    rollback = os.path.join(addons_root, ROLLBACK)
    if not _inside(live, addons_root):
        raise ValueError('Wizard destination escaped add-ons root')
    _restore_interrupted_swap(addons_root)
    entries = _validate_zip(archive_path, expected_sha, expected_version)
    if _installed_matches(live, archive_path, entries):
        return 'already_installed', rollback if os.path.isdir(rollback) else None
    if os.path.lexists(rollback):
        raise ValueError('previous Wizard rollback tree still present')

    temp_root = tempfile.mkdtemp(prefix='.kodipovil-wizard-stage-', dir=addons_root)
    staged = os.path.join(temp_root, WIZARD_ID)
    os.mkdir(staged)
    backup = None
    try:
        directories = set()
        for entry in entries:
            rel = entry.filename[len(WIZARD_ID) + 1:].rstrip('/')
            parent = rel if entry.is_dir() else os.path.dirname(rel)
            while parent:
                directories.add(parent)
                parent = os.path.dirname(parent)
        for rel in sorted(directories, key=lambda item: (item.count('/'), item)):
            target_dir = os.path.join(staged, *rel.split('/'))
            if not _inside(target_dir, staged):
                raise ValueError('staged directory escaped staging root')
            os.mkdir(target_dir)
        with zipfile.ZipFile(archive_path) as bundle:
            for entry in entries:
                if entry.is_dir():
                    continue
                rel = entry.filename[len(WIZARD_ID) + 1:]
                target = os.path.join(staged, *rel.split('/'))
                if not _inside(target, staged):
                    raise ValueError('staged file escaped staging directory')
                with bundle.open(entry) as source, open(target, 'wb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
        if not _installed_matches(staged, archive_path, entries):
            raise ValueError('staged Wizard copy did not verify')
        if os.path.lexists(live):
            backup = rollback
            os.replace(live, backup)
        try:
            os.replace(staged, live)
        except Exception:
            if backup is not None and not os.path.lexists(live):
                os.replace(backup, live)
            raise
        return 'installed', backup
    finally:
        if os.path.isdir(temp_root):
            shutil.rmtree(temp_root)


def ensure_bootstrapped():
    """Return ``not_requested`` or a bridge status; never invoke old healer."""
    if xbmcvfs is None or xbmcaddon is None:
        return 'not_requested'
    userdata = xbmcvfs.translatePath('special://home/userdata')
    request = os.path.join(userdata, REQUEST)
    ready = os.path.join(userdata, READY)
    marker = request if os.path.isfile(request) else ready
    if not os.path.isfile(marker):
        return 'not_requested'
    try:
        addons_root = xbmcvfs.translatePath('special://home/addons')
        _restore_interrupted_swap(addons_root)
        with open(marker, 'r', encoding='utf-8') as stream:
            plan = json.load(stream)
        expected_sha = plan['sha256']
        expected_version = plan['version']
        if (len(expected_sha) != 64 or
                any(ch not in '0123456789abcdef' for ch in expected_sha) or
                not expected_version):
            return 'invalid_plan'
        if marker == ready:
            # A completed installation is immutable from the bridge's point
            # of view. Local settings, later Wizard updates, or a QA-only URL
            # edit must never trigger a second self-replacement.
            addon_xml = os.path.join(addons_root, WIZARD_ID, 'addon.xml')
            if not os.path.isfile(addon_xml):
                return 'ready_wizard_missing'
            with open(addon_xml, 'r', encoding='utf-8-sig') as stream:
                xml_start = stream.read(4096)
            if '<addon' not in xml_start:
                return 'ready_identity_mismatch'
            opening = xml_start.split('<addon', 1)[1].split('>', 1)[0]
            addon_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', opening)
            version = re.search(r'\bversion\s*=\s*["\']([^"\']+)["\']', opening)
            if not addon_id or addon_id.group(1) != WIZARD_ID or not version:
                return 'ready_identity_mismatch'
            return ('ready' if version.group(1) == expected_version
                    else 'ready_version_changed')
        try:
            xbmcaddon.Addon(WIZARD_ID)
        except Exception:
            return 'wizard_not_installed'
        if 'deferred_pid' not in plan:
            # The old Wizard's quick_update() restarts this service before
            # its own interpreter has returned. Never rename Wizard files in
            # that same Kodi process. Require a genuine process restart.
            plan['deferred_pid'] = os.getpid()
            pending = request + '.tmp'
            with open(pending, 'w', encoding='utf-8') as stream:
                json.dump(plan, stream, sort_keys=True)
            os.replace(pending, request)
            return 'deferred_restart'
        if plan['deferred_pid'] == os.getpid():
            return 'deferred_restart'
        if xbmc is not None and xbmc.getCondVisibility('Player.HasMedia'):
            return 'deferred_playback'
        service_dir = xbmcvfs.translatePath(
            'special://home/addons/' + SERVICE_ID)
        staged_zip = os.path.join(service_dir, STAGED_ZIP)
        status, backup = install_staged_wizard(
            staged_zip, expected_sha, expected_version, addons_root)
        plan['backup'] = backup or plan.get('backup')
        ready_temp = ready + '.tmp'
        with open(ready_temp, 'w', encoding='utf-8') as stream:
            json.dump(plan, stream, sort_keys=True)
        os.replace(ready_temp, ready)
        if os.path.isfile(request):
            os.remove(request)
        if status == 'installed' and xbmcgui is not None:
            xbmcgui.Dialog().notification(
                'Kodi POV IL',
                'המעבר הוכן. יש לסגור את Kodi לחלוטין ולפתוח מחדש.',
                time=10000)
        return status
    except Exception as exc:
        if xbmc is not None:
            xbmc.log('[modular_legacy_bootstrap] ' + repr(exc), xbmc.LOGERROR)
        return 'failed'
