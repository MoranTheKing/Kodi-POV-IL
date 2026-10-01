"""Two-boot, rollback-capable migration from legacy POV edits to clean POV.

Only code below ``addons/plugin.video.pov`` is replaced. Kodi's addon_data,
accounts and databases are deliberately outside that tree. The old subtitle
service must have its POV writers turned off on the *previous* Kodi process.
"""

import ast
import hashlib
import json
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from resources.libs import modular_host_migration as migration
from resources.libs.patch_engine import PatchEngine


PLAN_NAME = 'kodipovil.clean_pov_handoff.json'
SETTINGS_BACKUP = ('addon_data/plugin.program.kodipovilwizard/'
                   'migration-backups/plugin.video.pov-settings.xml')
_HEX = re.compile(r'^[0-9a-f]{64}$')


def _digest_tree(tree):
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(tree).rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts
                       and p.suffix not in ('.pyc', '.pyo')):
        rel = path.relative_to(tree).as_posix().encode('utf-8')
        digest.update(len(rel).to_bytes(4, 'big'))
        digest.update(rel)
        with open(path, 'rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def _identity(tree, version):
    try:
        root = ET.parse(str(Path(tree) / 'addon.xml')).getroot()
        return root.get('id') == migration.ADDON_ID and root.get('version') == version
    except (OSError, ET.ParseError):
        return False


def _patched_stage(stage):
    """Apply the actual active POV registry to a private tree before swap."""
    source = PatchEngine()
    entries = [entry for entry in source._raw_config
               if (entry.get('addon_id') or migration.ADDON_ID) == migration.ADDON_ID]
    stage = Path(stage)

    class StageEngine(PatchEngine):
        @staticmethod
        def _resolve_paths(addon_id, target_file):
            relative = Path(target_file)
            if (addon_id != migration.ADDON_ID or relative.is_absolute() or
                    '..' in relative.parts):
                raise ValueError('invalid staged POV target')
            return str(stage), str(stage / relative)

    engine = StageEngine(entries)
    normalized = engine._normalize_patches(entries)
    enabled = sum(1 for entry in normalized if entry['enabled'])
    stats = engine.run()
    if (any(stats.get(key) for key in ('legacy_host_deferred', 'anchor_missing',
                                      'missing', 'failed', 'malformed')) or
            sum(stats.get(key, 0) for key in ('applied', 'upgraded',
                                             'skipped_current', 'superseded')) != enabled):
        raise migration.MigrationError('staged POV patch validation failed: {}'.format(stats))
    for path in stage.rglob('*.py'):
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    return stats


def _plan_path(userdata):
    return Path(userdata) / PLAN_NAME


def _preserve_settings(userdata):
    """Keep a local copy for rollback; never put account data in a package."""
    source = Path(userdata) / 'addon_data/plugin.video.pov/settings.xml'
    backup = Path(userdata) / SETTINGS_BACKUP
    if not source.is_file() or backup.is_file():
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    temp = backup.with_name(backup.name + '.tmp')
    shutil.copy2(source, temp)
    os.replace(temp, backup)


def _restore_settings(userdata):
    backup = Path(userdata) / SETTINGS_BACKUP
    target = Path(userdata) / 'addon_data/plugin.video.pov/settings.xml'
    if backup.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + '.migration-restore')
        shutil.copy2(backup, temp)
        os.replace(temp, target)


def read_plan(userdata, host):
    path = _plan_path(userdata)
    try:
        if path.stat().st_size > 2048:
            return None
        plan = json.loads(path.read_text(encoding='utf-8'))
        now = int(time.time())
        stage = Path(host).absolute().parent.parent / plan['stage_name'] / migration.ADDON_ID
        if (plan.get('schema') != 1 or plan.get('addon_id') != migration.ADDON_ID or
                not isinstance(plan.get('version'), str) or
                not _HEX.fullmatch(str(plan.get('sha256'))) or
                not _HEX.fullmatch(str(plan.get('tree_digest'))) or
                not isinstance(plan.get('creator_pid'), int) or
                not isinstance(plan.get('was_enabled'), bool) or
                not isinstance(plan.get('created'), int) or
                not isinstance(plan.get('expires'), int) or
                plan['created'] > now + 300 or plan['expires'] < now or
                plan['expires'] > plan['created'] + 7 * 86400 or
                not re.fullmatch(r'\.plugin\.video\.pov-stage-[a-zA-Z0-9_-]+',
                                 str(plan.get('stage_name'))) or
                stage.parent.parent != Path(host).absolute().parent.parent):
            return None
        plan['stage'] = stage
        return plan
    except (OSError, ValueError, TypeError, KeyError):
        return None


def prepare(archive, host, userdata, version, sha256, service_addon):
    """Stage and patch official POV; request a restart before any live swap."""
    import xbmcaddon

    host = migration._host_path(host)
    if not Path(service_addon).is_file():
        raise migration.MigrationError('old service has no POV-off migration guard')
    existing = read_plan(userdata, host)
    if existing and existing['version'] == version and existing['sha256'] == sha256:
        if (existing['stage'].is_dir() and
                _digest_tree(existing['stage']) == existing['tree_digest']):
            return existing
    stage = migration.stage_clean_host(
        archive, host, sha256, version,
        lambda tree: _identity(tree, version))
    _patched_stage(stage)
    digest = _digest_tree(stage)
    _preserve_settings(userdata)
    details = _rpc('Addons.GetAddonDetails',
                   {'addonid': migration.ADDON_ID, 'properties': ['enabled']})
    was_enabled = bool(details['addon']['enabled'])
    setting = xbmcaddon.Addon('service.subtitles.kodipovilai')
    setting.setSetting('_pov_patching_off', 'true')
    if setting.getSetting('_pov_patching_off') != 'true':
        raise migration.MigrationError('old POV patcher could not be disabled')
    now = int(time.time())
    plan = {'schema': 1, 'addon_id': migration.ADDON_ID, 'version': version,
            'sha256': sha256, 'tree_digest': digest,
            'stage_name': stage.parent.name, 'creator_pid': os.getpid(),
            'was_enabled': was_enabled,
            'created': now, 'expires': now + 86400}
    path = _plan_path(userdata)
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'w', encoding='utf-8') as output:
        json.dump(plan, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)
    plan['stage'] = stage
    return plan


def _rpc(method, params):
    import xbmc

    reply = json.loads(xbmc.executeJSONRPC(json.dumps(
        {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    if 'error' in reply:
        raise migration.MigrationError('Kodi addon manager refused ' + method)
    return reply.get('result')


def complete(host, userdata):
    """On a later Kodi process, disable POV, swap code, validate or roll back."""
    import xbmc
    import xbmcaddon

    host = migration._host_path(host)
    plan = read_plan(userdata, host)
    recovered = migration.recover_unconfirmed(host)
    if plan and recovered in ('confirmed', 'restored', 'rolled_back', 'not_swapped'):
        if recovered == 'confirmed' and not _identity(host, plan['version']):
            raise migration.MigrationError(
                'confirmed POV host identity changed after activation')
        # Kodi may have died after the code swap but before re-enabling POV.
        # Complete the confirmed swap, or restore the old enabled state after
        # an interrupted one, before deciding whether another stage is needed.
        if plan['was_enabled']:
            if recovered != 'confirmed':
                _restore_settings(userdata)
            xbmc.executebuiltin('UpdateLocalAddons', True)
            details = _rpc('Addons.GetAddonDetails',
                           {'addonid': migration.ADDON_ID,
                            'properties': ['enabled']})
            if not details['addon']['enabled']:
                _rpc('Addons.SetAddonEnabled',
                     {'addonid': migration.ADDON_ID, 'enabled': True})
        if recovered == 'confirmed':
            # confirm_host already compared every staged byte immediately
            # after the swap. Other installed addons may legitimately patch
            # POV on the following boot (for example the private DirectSync
            # integration). Rechecking that historical digest now would
            # strand a completed migration with no staged tree left to use.
            _plan_path(userdata).unlink()
            return True
    if not plan or plan['creator_pid'] == os.getpid():
        return False
    if xbmc.getCondVisibility('Player.HasMedia'):
        return False
    if xbmcaddon.Addon('service.subtitles.kodipovilai').getSetting(
            '_pov_patching_off') != 'true':
        return False
    stage = plan['stage']
    if (not stage.is_dir() or not _identity(stage, plan['version']) or
            _digest_tree(stage) != plan['tree_digest']):
        raise migration.MigrationError('prepared POV tree changed after validation')
    addon_id = migration.ADDON_ID
    details = _rpc('Addons.GetAddonDetails',
                   {'addonid': addon_id, 'properties': ['enabled']})
    was_enabled = bool(details['addon']['enabled'])
    swapped = False
    try:
        if was_enabled:
            _rpc('Addons.SetAddonEnabled', {'addonid': addon_id, 'enabled': False})
        migration.activate_staged_host(stage, host)
        swapped = True
        migration.confirm_host(host, lambda tree: (
            _identity(tree, plan['version']) and
            _digest_tree(tree) == plan['tree_digest']))
        xbmc.executebuiltin('UpdateLocalAddons', True)
        if was_enabled:
            _rpc('Addons.SetAddonEnabled', {'addonid': addon_id, 'enabled': True})
        _plan_path(userdata).unlink()
        return True
    except Exception:
        if swapped:
            try:
                migration.rollback_host(host, allow_confirmed=True)
                _restore_settings(userdata)
                xbmc.executebuiltin('UpdateLocalAddons', True)
            except Exception:
                pass
        if was_enabled:
            try:
                _rpc('Addons.SetAddonEnabled', {'addonid': addon_id, 'enabled': True})
            except Exception:
                pass
        raise
