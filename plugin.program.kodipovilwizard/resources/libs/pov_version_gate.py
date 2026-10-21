# -*- coding: utf-8 -*-
"""POV and Umbrella move only to a version the build's patches were verified on.

WHY. Since Wizard 0.4.49 POV is registered to repository.kodifitzwell, so
Kodi installed every new POV the moment its developer published it. POV
6.10.16 (20 Oct 2026) restructured its tree; ten Wizard hooks lost their
anchors on devices before anyone had checked the release, and series lists
failed with a POV error for every user that night. Umbrella carries the
kids-profile hooks and follows repository.umbrella the same way (Wizard
0.4.68), so it gets the same gate.

WHAT. Two halves, per add-on in TARGETS:
  1. Kodi's own "auto-update off" rule (update_rules, rule 1 -- the same row
     the add-on information dialog writes). Kodi reads the rules when it
     starts, so it holds from the next start. MoranSubs'
     addon_autoupdate_repair clears only installer pins (rule 2), never this.
  2. The version the release automation verified (manifest
     pov_host_migration / umbrella_pin, moved by tools/auto_bump_pov_pin.py
     only after every enabled hook applies, idempotently) is installed by the
     Wizard itself from the build's own mirror, SHA-256 checked, and the
     hooks are applied to it at once.

A device never moves backwards, except when this very installation run put
the add-on on disk (`fresh` below): Kodi's native installer brings whatever
the repository publishes that day, and that copy has never run on this
profile. A "full install" over an existing device keeps its newer copy.

Kodi itself can open the hold for one session: it reads update_rules only at
start, and an add-on updated by hand from the add-on browser has its rules
dropped by Kodi's installer; the gate writes the rule again on the next
check, and never moves the newer copy back.

Legacy POV devices (old MoranSubs edits in POV) get the hold too; the install
itself is left to the clean-host migration, which already installs exactly
the pinned POV.
"""

import io
import os
import re
import zipfile

ADDON_ID = 'plugin.video.pov'
RULE_AUTO_UPDATE_OFF = 1
# add-on id -> (manifest key, log label)
TARGETS = {
    'plugin.video.pov': ('pov_host_migration', 'POV'),
    'plugin.video.umbrella': ('umbrella_pin', 'Umbrella'),
}


def version_key(value):
    parts = []
    for part in str(value or '').split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def decide(installed, pinned, fresh):
    """'install' or 'keep' for the installed add-on against the verified pin."""
    if not installed or not pinned:
        return 'keep'
    if version_key(installed) < version_key(pinned):
        return 'install'
    if fresh and version_key(installed) > version_key(pinned):
        return 'install'
    return 'keep'


def ensure_hold(db_path, sqlite=None, addon_id=ADDON_ID):
    """Add Kodi's auto-update-off rule for the add-on once. True when present."""
    if sqlite is None:
        import sqlite3 as sqlite
    if not db_path or not os.path.isfile(db_path):
        return False   # sqlite would create an empty database at this path
    conn = sqlite.connect(db_path, timeout=5)
    try:
        if conn.execute('SELECT 1 FROM update_rules WHERE addonID = ? AND updateRule = ?',
                        (addon_id, RULE_AUTO_UPDATE_OFF)).fetchone():
            return True
        conn.execute('INSERT INTO update_rules (addonID, updateRule) VALUES (?, ?)',
                     (addon_id, RULE_AUTO_UPDATE_OFF))
        conn.commit()
        return True
    finally:
        conn.close()


def pinned_entry(manifest, addon_id=ADDON_ID):
    entry = (manifest or {}).get(TARGETS[addon_id][0]) or {}
    if not isinstance(entry, dict):
        return None
    version = str(entry.get('version') or '')
    sha256 = str(entry.get('sha256') or '').lower()
    if (entry.get('id') or addon_id) != addon_id or not version or len(sha256) != 64:
        return None
    if not str(entry.get('zip') or '').startswith('https://'):
        return None
    return entry


def unmet_requirements(package, local_version, addon_id):
    """[(dependency, required version)] this package needs and the device has older.

    Only a dependency installed under home/addons with a known, lower version
    counts: Kodi's own modules (xbmc.*) and system add-ons are not visible
    here, and a package that cannot be read is left to the SHA-checked
    install to refuse."""
    try:
        with open(package, 'rb') as source:
            with zipfile.ZipFile(io.BytesIO(source.read())) as archive:
                head = archive.read(addon_id + '/addon.xml').decode('utf-8', 'replace')
    except Exception:
        return []
    unmet = []
    for tag in re.findall(r'<import\b[^>]*>', head):
        attrs = dict(re.findall(r'\b(addon|version|optional)\s*=\s*"([^"]*)"', tag))
        dep, needed = attrs.get('addon', ''), attrs.get('version', '')
        if (not dep or not needed or dep.startswith('xbmc.') or
                attrs.get('optional', '').lower() == 'true'):
            continue
        have = local_version(dep)
        if have and version_key(have) < version_key(needed):
            unmet.append((dep, needed))
    return unmet


def user_disabled(db_path, addon_id, sqlite=None):
    """True when Kodi's add-on database marks the add-on disabled."""
    if sqlite is None:
        import sqlite3 as sqlite
    if not db_path or not os.path.isfile(db_path):
        return False
    conn = sqlite.connect(db_path, timeout=5)
    try:
        row = conn.execute('SELECT enabled FROM installed WHERE addonID = ?', (addon_id,)).fetchone()
        return bool(row) and row[0] == 0
    finally:
        conn.close()


def _waiting_marker(ota, addon_id):
    return os.path.join(ota, addon_id + '-waiting.json')


def still_waiting(ota, addon_id, sha256, local_version):
    """True while the pin last found waiting on a dependency is unchanged and
    so is every dependency it waited on: no ~11 MB download on every start."""
    import json
    try:
        with open(_waiting_marker(ota, addon_id), 'r') as source:
            seen = json.load(source)
    except Exception:
        return False
    if seen.get('sha256') != sha256:
        return False
    return all(local_version(dep) == have for dep, have in (seen.get('local') or {}).items())


def sync(updater, manifest, fresh, config, log, db_path,
         legacy_host=None, install=None, register=None, repatch=None,
         install_allowed=True, recover=None, addon_id=ADDON_ID, moransubs_repair=None):
    """Hold the add-on and move it to the verified version. Never raises.

    Returns 'installed <ver>', 'held', 'deferred', 'legacy', 'no_pin',
    'no_pov' / 'not_installed' (POV / Umbrella absent), 'disabled' (turned off
    by the user: left alone), 'needs <dep> <ver>' or 'failed: <reason>'.
    Dependencies are injectable for tests.
    """
    label = TARGETS.get(addon_id, ('', addon_id))[1]
    try:
        entry = pinned_entry(manifest, addon_id)
        if entry is None:
            return 'no_pin'
        # A power cut between the two directory renames of an earlier swap
        # leaves the add-on in the private backup; put it back before judging.
        try:
            if recover is None:
                from resources.libs import staged_addon_install
                recover = lambda: staged_addon_install.recover(
                    config.ADDONS, config.ADDONS, addon_id)
            recover()
        except Exception as exc:
            log('[{0} gate] recovery check: {1}'.format(label, exc))
        host = os.path.join(config.ADDONS, addon_id)
        if not os.path.isfile(os.path.join(host, 'addon.xml')):
            return 'no_pov' if addon_id == ADDON_ID else 'not_installed'
        try:
            if not ensure_hold(db_path, addon_id=addon_id):
                log('[{0} gate] Kodi add-on database not found; no auto-update hold'.format(label))
        except Exception as exc:
            log('[{0} gate] could not add the auto-update hold: {1}'.format(label, exc))
        installed = updater.get_local_version(addon_id)
        version = str(entry['version'])
        if decide(installed, version, fresh) != 'install':
            return 'held'
        if not install_allowed:
            return 'deferred'
        try:
            # Registering the new copy enables it; an Umbrella the user switched
            # off stays as it is (held, never replaced). POV is switched off
            # briefly by MoranSubs' own reload cycles; it keeps 0.4.67's path.
            if addon_id != ADDON_ID and user_disabled(db_path, addon_id):
                return 'disabled'
        except Exception as exc:
            log('[{0} gate] could not read the enabled state: {1}'.format(label, exc))
        if addon_id == 'plugin.video.pov':
            # Only now: normalizing the whole patch registry is slow on x86
            # boxes, and the common case above never needs it.
            if legacy_host is None:
                from resources.libs.patch_engine import PatchEngine
                legacy_host = lambda: PatchEngine().legacy_pov_host_present()
            if legacy_host():
                return 'legacy'
        sha256 = str(entry['sha256']).lower()
        ota = os.path.join(config.ADDON_DATA, config.ADDON_ID, 'ota-packages')
        os.makedirs(ota, exist_ok=True)
        package = os.path.join(ota, addon_id + '-verified.zip')
        if still_waiting(ota, addon_id, sha256, updater.get_local_version):
            return 'needs (unchanged)'
        try:
            updater._download_background_zip(entry['zip'], package, entry)
            unmet = unmet_requirements(package, updater.get_local_version, addon_id)
            if unmet:
                # Kodi would keep the add-on disabled; the dependency updates
                # from its own repository and the next check installs.
                import json
                with open(_waiting_marker(ota, addon_id), 'w') as out:
                    json.dump({'sha256': sha256, 'local': {
                        dep: updater.get_local_version(dep) for dep, _ in unmet}}, out)
                return 'needs ' + ', '.join('{0} {1}'.format(*dep) for dep in unmet)
            try:
                os.remove(_waiting_marker(ota, addon_id))
            except OSError:
                pass
            if install is None:
                from resources.libs import staged_addon_install
                install = lambda path: staged_addon_install.install(
                    path, config.ADDONS, addon_id, version, sha256)
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
                db.addon_database([addon_id], 1, True)
                xbmc.executebuiltin('UpdateLocalAddons')
        register()
        if repatch is None:
            def repatch():
                from resources.libs.patch_engine import PatchEngine
                return PatchEngine().run()
        stats = repatch() or {}
        log('[{0} gate] {0} {1} -> verified {2}; hooks: {3}'.format(label, installed, version, stats))
        if addon_id == 'plugin.video.umbrella':
            # MoranSubs patched the old tree when Kodi started (Hebrew menus,
            # subtitle match, sources); patch the new one now, not next start.
            try:
                if moransubs_repair is None:
                    def moransubs_repair():
                        import xbmc
                        import xbmcgui
                        from resources.libs.host_patch_watch import repair_umbrella
                        return repair_umbrella(config.ADDONS, xbmcgui.Window(10000), xbmc.Monitor())
                log('[{0} gate] MoranSubs Umbrella patchers: {1}'.format(label, moransubs_repair()))
            except Exception as exc:
                log('[{0} gate] MoranSubs Umbrella patchers: {1}'.format(label, exc))
        bad = {k: stats.get(k) for k in ('anchor_missing', 'failed', 'malformed') if stats.get(k)}
        if bad:
            return 'installed {0} with hook problems {1}'.format(version, bad)
        return 'installed {0}'.format(version)
    except Exception as exc:
        log('[{0} gate] verified {0} install failed: {1}'.format(label, exc))
        return 'failed: {0}'.format(exc)
