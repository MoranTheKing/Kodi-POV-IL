# -*- coding: utf-8 -*-
"""POV moves only to a version the build's patches were verified on.

WHY. Since Wizard 0.4.49 POV is registered to repository.kodifitzwell, so
Kodi installed every new POV the moment its developer published it. POV
6.10.16 (20 Oct 2026) restructured its tree; ten Wizard hooks lost their
anchors on devices before anyone had checked the release, and series lists
failed with a POV error for every user that night.

WHAT. Two halves:
  1. Kodi's own "auto-update off" rule (update_rules, rule 1 -- the same row
     the add-on information dialog writes) for plugin.video.pov. Kodi reads
     the rules when it starts, so it holds from the next start. MoranSubs'
     addon_autoupdate_repair clears only installer pins (rule 2), never this.
  2. The version the release automation verified (manifest
     pov_host_migration, moved by tools/auto_bump_pov_pin.py only after every
     enabled hook applies, idempotently) is installed by the Wizard itself
     from the build's own mirror, SHA-256 checked, and the hooks are applied
     to it at once.

A device never moves backwards, except when this very installation run put
POV on disk (`fresh` below): Kodi's native installer brings whatever the
repository publishes that day, and that POV has never run on this profile.
A "full install" over an existing device keeps its newer POV.

Kodi itself can open the hold for one session: it reads update_rules only at
start, and a POV updated by hand from the add-on browser has its rules
dropped by Kodi's installer; the gate writes the rule again on the next
check, and never moves the newer POV back.

Legacy devices (old MoranSubs edits in POV) get the hold too; the install
itself is left to the clean-host migration, which already installs exactly
this pinned version.
"""

import os

ADDON_ID = 'plugin.video.pov'
RULE_AUTO_UPDATE_OFF = 1


def version_key(value):
    parts = []
    for part in str(value or '').split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def decide(installed, pinned, fresh):
    """'install' or 'keep' for the installed POV against the verified pin."""
    if not installed or not pinned:
        return 'keep'
    if version_key(installed) < version_key(pinned):
        return 'install'
    if fresh and version_key(installed) > version_key(pinned):
        return 'install'
    return 'keep'


def ensure_hold(db_path, sqlite=None):
    """Add Kodi's auto-update-off rule for POV once. True when present."""
    if sqlite is None:
        import sqlite3 as sqlite
    if not db_path or not os.path.isfile(db_path):
        return False   # sqlite would create an empty database at this path
    conn = sqlite.connect(db_path, timeout=5)
    try:
        if conn.execute('SELECT 1 FROM update_rules WHERE addonID = ? AND updateRule = ?',
                        (ADDON_ID, RULE_AUTO_UPDATE_OFF)).fetchone():
            return True
        conn.execute('INSERT INTO update_rules (addonID, updateRule) VALUES (?, ?)',
                     (ADDON_ID, RULE_AUTO_UPDATE_OFF))
        conn.commit()
        return True
    finally:
        conn.close()


def pinned_entry(manifest):
    entry = (manifest or {}).get('pov_host_migration') or {}
    if not isinstance(entry, dict):
        return None
    version = str(entry.get('version') or '')
    sha256 = str(entry.get('sha256') or '').lower()
    if (entry.get('id') or ADDON_ID) != ADDON_ID or not version or len(sha256) != 64:
        return None
    if not str(entry.get('zip') or '').startswith('https://'):
        return None
    return entry


def sync(updater, manifest, fresh, config, log, db_path,
         legacy_host=None, install=None, register=None, repatch=None,
         install_allowed=True, recover=None):
    """Hold POV and move it to the verified version. Never raises.

    Returns 'installed <ver>', 'held', 'deferred', 'legacy', 'no_pin',
    'no_pov' or 'failed: <reason>'. Dependencies are injectable for tests.
    """
    try:
        entry = pinned_entry(manifest)
        if entry is None:
            return 'no_pin'
        # A power cut between the two directory renames of an earlier swap
        # leaves POV in the private backup; put it back before judging.
        try:
            if recover is None:
                from resources.libs import staged_addon_install
                recover = lambda: staged_addon_install.recover(
                    config.ADDONS, config.ADDONS, ADDON_ID)
            recover()
        except Exception as exc:
            log('[POV gate] recovery check: {0}'.format(exc))
        host = os.path.join(config.ADDONS, ADDON_ID)
        if not os.path.isfile(os.path.join(host, 'addon.xml')):
            return 'no_pov'
        try:
            if not ensure_hold(db_path):
                log('[POV gate] Kodi add-on database not found; no auto-update hold')
        except Exception as exc:
            log('[POV gate] could not add the auto-update hold: {0}'.format(exc))
        installed = updater.get_local_version(ADDON_ID)
        version = str(entry['version'])
        if decide(installed, version, fresh) != 'install':
            return 'held'
        if not install_allowed:
            return 'deferred'
        # Only now: normalizing the whole patch registry is slow on x86 boxes,
        # and the common case above never needs it.
        if legacy_host is None:
            from resources.libs.patch_engine import PatchEngine
            legacy_host = lambda: PatchEngine().legacy_pov_host_present()
        if legacy_host():
            return 'legacy'
        sha256 = str(entry['sha256']).lower()
        ota = os.path.join(config.ADDON_DATA, config.ADDON_ID, 'ota-packages')
        os.makedirs(ota, exist_ok=True)
        package = os.path.join(ota, ADDON_ID + '-verified.zip')
        try:
            updater._download_background_zip(entry['zip'], package, entry)
            if install is None:
                from resources.libs import staged_addon_install
                install = lambda path: staged_addon_install.install(
                    path, config.ADDONS, ADDON_ID, version, sha256)
            install(package)
        finally:
            try:
                os.remove(package)
            except OSError:
                pass
        if register is None:
            def register():
                from resources.libs import db
                import xbmc
                db.addon_database([ADDON_ID], 1, True)
                xbmc.executebuiltin('UpdateLocalAddons')
        register()
        if repatch is None:
            def repatch():
                from resources.libs.patch_engine import PatchEngine
                return PatchEngine().run()
        stats = repatch() or {}
        log('[POV gate] POV {0} -> verified {1}; hooks: {2}'.format(installed, version, stats))
        bad = {k: stats.get(k) for k in ('anchor_missing', 'failed', 'malformed') if stats.get(k)}
        if bad:
            return 'installed {0} with hook problems {1}'.format(version, bad)
        return 'installed {0}'.format(version)
    except Exception as exc:
        log('[POV gate] verified POV install failed: {0}'.format(exc))
        return 'failed: {0}'.format(exc)
