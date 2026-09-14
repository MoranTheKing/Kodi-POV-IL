# -*- coding: utf-8 -*-
"""Recover a torn add-on ``settings.xml`` without losing the user's values.

Kodi logs this exact line only when TinyXML cannot load the stored values file::

    CAddon[plugin.video.pov]: failed to load addon settings from .../settings.xml

When that happens ``getSetting()`` returns the add-on defaults.  For POV that
makes an authorised debrid look disconnected, and its source window reports
"No External Scrapers Enabled" before returning "No Results".  Account Manager
cannot repair the state either: Kodi refuses to save settings while the values
file is unloaded.

This module keeps a parse-checked last-known-good copy of the three settings
files which participate in a source search (POV, Umbrella and CocoScrapers).
On a torn file it first preserves the bad bytes, then restores the exact good
copy.  On the first incident, before a good copy exists, it salvages every
complete, individually valid ``<setting>`` element and writes a new document.
The write is validated and moved into place atomically.  Values are never put
in the log.

If Account Manager has an AllDebrid token, a recovered POV/Umbrella document is
also given that canonical token before it is installed.  A separate sync pass
repairs the ordinary (well-formed) case where Account Manager has the token but
one target missed the propagation.  This mirrors Account Manager's own policy:
the central account is the source of truth.
"""

from __future__ import unicode_literals

import hashlib
import os
import re
import threading
import time
import xml.etree.ElementTree as ET

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

try:
    import xbmcgui
except Exception:
    xbmcgui = None

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import addon_presence, addon_settings_safe, kodi_utils
except Exception:
    addon_presence = None
    addon_settings_safe = None
    kodi_utils = None


OUR_ADDON_ID = 'service.subtitles.kodipovilai'
ACCOUNT_MANAGER_ID = 'script.module.acctmgr'

# id, profile settings path, last-good filename
TARGETS = (
    ('plugin.video.pov',
     'special://profile/addon_data/plugin.video.pov/settings.xml',
     'plugin.video.pov.xml'),
    ('plugin.video.umbrella',
     'special://profile/addon_data/plugin.video.umbrella/settings.xml',
     'plugin.video.umbrella.xml'),
    ('script.module.cocoscrapers',
     'special://profile/addon_data/script.module.cocoscrapers/settings.xml',
     'script.module.cocoscrapers.xml'),
)

_SETTING_RE = re.compile(
    r'<setting\b[^>]*(?:/>|>.*?</setting\s*>)', re.IGNORECASE | re.DOTALL)
_MAX_SETTINGS_BYTES = 4 * 1024 * 1024


def _log(message, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('addon_settings_integrity: ' + message, level=level)
    except Exception:
        pass


def _translate(path):
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(path)
    except Exception:
        return ''


def _backup_dir():
    return _translate(
        'special://profile/addon_data/%s/settings-last-good/' % OUR_ADDON_ID)


def _parse(raw):
    if not raw or len(raw) > _MAX_SETTINGS_BYTES:
        return None
    try:
        root = ET.fromstring(raw)
    except Exception:
        return None
    return root if root.tag == 'settings' else None


def _read(path):
    try:
        with open(path, 'rb') as handle:
            return handle.read(_MAX_SETTINGS_BYTES + 1)
    except Exception:
        return None


def _atomic_write(path, raw, expected_current=None):
    """Validate beside ``path`` and atomically install it.

    ``None`` means a compare-before-install check saw another writer change
    the destination. ``False`` is an I/O/validation failure, and ``True`` is a
    completed replace. The comparison cannot be a cross-process lock (Kodi's
    writers do not participate in one), but putting it immediately before the
    atomic rename closes the meaningful write window without ever overwriting
    a change that already landed.
    """
    if _parse(raw) is None:
        return False
    directory = os.path.dirname(path) or '.'
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
    except Exception:
        return False
    temp = '%s.%d.%d.aitmp' % (
        path, os.getpid(), threading.current_thread().ident or 0)
    try:
        with open(temp, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        if _parse(_read(temp)) is None:
            raise ValueError('temporary settings file did not parse')
        if expected_current is not None and _read(path) != expected_current:
            try:
                os.remove(temp)
            except Exception:
                pass
            return None
        os.replace(temp, path)
        return _parse(_read(path)) is not None
    except Exception:
        try:
            os.remove(temp)
        except Exception:
            pass
        return False


def _copy_if_changed(path, raw):
    current = _read(path)
    if current == raw:
        return True
    return _atomic_write(path, raw)


def _sanitise_lexical_sections(text):
    """Remove comments and escape CDATA while respecting their boundaries.

    This must be one left-to-right scan. Doing comments and CDATA as separate
    passes is order-dependent: a comment may contain the literal ``<![CDATA[``
    and CDATA may contain the literal ``<!--``. The first delimiter that is
    actual markup owns everything through its matching close, so delimiter
    text inside that region has no structural meaning.

    Complete CDATA bodies are escaped so a literal ``<setting>`` remains the
    outer setting's text instead of becoming a phantom node. A torn comment or
    CDATA ends salvage at its opener because no later close can be trusted to
    be real markup in that lexical state.
    """
    out = []
    pos = 0
    while True:
        comment = text.find('<!--', pos)
        cdata = text.find('<![CDATA[', pos)
        starts = [index for index in (comment, cdata) if index >= 0]
        if not starts:
            out.append(text[pos:])
            return ''.join(out)
        start = min(starts)
        out.append(text[pos:start])
        if start == comment:
            end = text.find('-->', start + 4)
            if end < 0:
                return ''.join(out)
            pos = end + 3
            continue
        end = text.find(']]>', start + 9)
        if end < 0:
            return ''.join(out)
        body = text[start + 9:end]
        out.append(body.replace('&', '&amp;').replace('<', '&lt;')
                   .replace('>', '&gt;'))
        pos = end + 3


def _salvage(raw):
    """Build a valid root from complete, valid setting elements in ``raw``."""
    try:
        text = raw.decode('utf-8-sig', 'replace')
    except Exception:
        text = ''
    text = _sanitise_lexical_sections(text)
    root = ET.Element('settings', {'version': '2'})
    if text is None:
        return root, 0

    # Last occurrence wins, matching a normal settings map.  Assignment to an
    # existing dict key retains its first position, which keeps the recovered
    # file stable without making duplicate ids survive.
    found = {}
    order = []
    for match in _SETTING_RE.finditer(text):
        try:
            node = ET.fromstring(match.group(0))
        except Exception:
            continue
        setting_id = node.get('id')
        if not setting_id or node.tag != 'setting':
            continue
        if setting_id not in found:
            order.append(setting_id)
        found[setting_id] = node
    for setting_id in order:
        root.append(found[setting_id])
    return root, len(found)


def _setting_node(root, setting_id):
    for node in root.iter('setting'):
        if node.get('id') == setting_id:
            return node
    return None


def _set_value(root, setting_id, value, replace=True):
    node = _setting_node(root, setting_id)
    if node is None:
        node = ET.SubElement(root, 'setting', {'id': setting_id})
    elif not replace and (node.text or '').strip():
        return False
    node.text = value or ''
    node.attrib.pop('default', None)
    return True


def _account_manager_alldebrid():
    """Return ``(username, token)`` without ever logging either value."""
    addon = None
    try:
        if addon_presence is not None:
            addon = addon_presence.addon(ACCOUNT_MANAGER_ID)
        elif xbmcaddon is not None:
            addon = xbmcaddon.Addon(ACCOUNT_MANAGER_ID)
    except Exception:
        addon = None
    if addon is None:
        return '', ''
    try:
        username = (addon.getSetting('alldebrid.username') or '').strip()
        token = (addon.getSetting('alldebrid.token') or '').strip()
    except Exception:
        return '', ''
    return username, token


def _merge_alldebrid(root, addon_id, account):
    username, token = account
    if not token:
        return False
    if addon_id == 'plugin.video.pov':
        _set_value(root, 'ad.account_id', username)
        _set_value(root, 'ad.token', token)
        _set_value(root, 'ad.enabled', 'true', replace=False)
        # A missing value is a torn/rebuilt profile, not a user opting out.
        _set_value(root, 'ad.torrent.enabled', 'true', replace=False)
        return True
    if addon_id == 'plugin.video.umbrella':
        _set_value(root, 'alldebridusername', username)
        _set_value(root, 'alldebridtoken', token)
        _set_value(root, 'alldebrid.enable', 'true', replace=False)
        return True
    return False


def _serialise(root):
    root.set('version', root.get('version') or '2')
    try:
        ET.indent(root, space='    ')
    except Exception:
        pass
    return ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n'


def _preserve_corrupt(path, raw):
    digest = hashlib.sha256(raw).hexdigest()[:12]
    backup = '%s.corrupt-%s.bak' % (path, digest)
    if os.path.isfile(backup):
        return True
    # The backup intentionally is not XML-validated: its whole purpose is to
    # preserve the exact malformed bytes for a future forensic recovery.
    temp = '%s.%d.%d.tmp' % (
        backup, os.getpid(), threading.current_thread().ident or 0)
    try:
        with open(temp, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        os.replace(temp, backup)
        return True
    except Exception:
        try:
            os.remove(temp)
        except Exception:
            pass
        return False


def repair_file(path, last_good_path, addon_id, account=('', ''), pause=None):
    """Repair one settings file and return a small, value-free result dict."""
    raw = _read(path)
    if raw is None:
        return {'status': 'no_file', 'addon': addon_id, 'salvaged': 0,
                'account_restored': False}
    if len(raw) > _MAX_SETTINGS_BYTES:
        # _read deliberately stops after MAX+1. Replacing this file would mean
        # our forensic backup was not exact and bytes after the cap were lost.
        # A real add-on values file is measured in kilobytes; an oversized one
        # needs inspection, not an automatic partial recovery.
        return {'status': 'too_large', 'addon': addon_id, 'salvaged': 0,
                'account_restored': False}

    root = _parse(raw)
    if root is not None:
        snapshot_ok = (not last_good_path
                       or _copy_if_changed(last_good_path, raw))
        return {'status': ('healthy' if snapshot_ok
                           else 'healthy_snapshot_failed'),
                'addon': addon_id, 'salvaged': 0,
                'account_restored': False}

    # Do not mistake an in-progress whole-file writer for corruption.  Invalid
    # bytes have to remain byte-identical across two reads before we touch them.
    try:
        (pause or time.sleep)(0.20)
    except Exception:
        pass
    again = _read(path)
    if again is None or again != raw:
        return {'status': 'changing', 'addon': addon_id, 'salvaged': 0,
                'account_restored': False}

    if not _preserve_corrupt(path, raw):
        return {'status': 'backup_failed', 'addon': addon_id, 'salvaged': 0,
                'account_restored': False}

    source = 'salvage'
    good = _read(last_good_path) if last_good_path else None
    root = _parse(good)
    if root is not None:
        source = 'last_good'
        salvaged = len(list(root.iter('setting')))
    else:
        root, salvaged = _salvage(raw)

    account_restored = _merge_alldebrid(root, addon_id, account)
    repaired = _serialise(root)
    installed = _atomic_write(path, repaired, expected_current=raw)
    if installed is None:
        return {'status': 'changed_before_install', 'addon': addon_id,
                'salvaged': salvaged,
                'account_restored': account_restored}
    if not installed:
        return {'status': 'write_failed', 'addon': addon_id,
                'salvaged': salvaged,
                'account_restored': account_restored}
    if last_good_path:
        _copy_if_changed(last_good_path, repaired)
    return {'status': 'repaired_' + source, 'addon': addon_id,
            'salvaged': salvaged,
            'account_restored': account_restored}


def ensure_integrity(pause=None):
    """Check all source-stack settings files.  Never raises or exposes values."""
    results = []
    backup_dir = _backup_dir()
    if backup_dir:
        try:
            if not os.path.isdir(backup_dir):
                os.makedirs(backup_dir)
        except Exception:
            backup_dir = ''
    account = _account_manager_alldebrid()
    for addon_id, special_path, backup_name in TARGETS:
        path = _translate(special_path)
        if not path or not os.path.isfile(path):
            continue
        last_good = os.path.join(backup_dir, backup_name) if backup_dir else ''
        try:
            results.append(repair_file(path, last_good, addon_id,
                                       account=account, pause=pause))
        except Exception as exc:
            _log('{0}: integrity check failed: {1}'.format(addon_id, exc),
                 level='WARNING')
            results.append({'status': 'error', 'addon': addon_id,
                            'salvaged': 0, 'account_restored': False})
    return results


def sync_alldebrid_from_account_manager(skip_addons=()):
    """Repair a missed Account Manager propagation on otherwise healthy XML.

    Only a target whose token differs from Account Manager is written.  That is
    the same decision Account Manager's own ``debrid_ad`` sync makes.  The
    helper preserves every unrelated setting around those writes.
    """
    if addon_settings_safe is None:
        return []
    username, token = _account_manager_alldebrid()
    if not token:
        return []
    results = []
    skip_addons = set(skip_addons or ())
    wanted_by_addon = (
        ('plugin.video.pov', 'ad.token', 'ad.enabled', (
            ('ad.account_id', username), ('ad.token', token))),
        ('plugin.video.umbrella', 'alldebridtoken', 'alldebrid.enable', (
            ('alldebridusername', username), ('alldebridtoken', token))),
    )
    for addon_id, token_key, enabled_key, base_wanted in wanted_by_addon:
        # A file repaired behind Kodi's back is valid on disk but the CAddon
        # object still holds the defaults from its failed first load. Calling
        # setSetting in that state cannot save (SettingsLoaded is false) and
        # can misleadingly read back the in-memory value. The repair already
        # merged Account Manager's token directly; let the scheduled add-on
        # reload, or the next Kodi start, consume that file before any API
        # write touches this target.
        if addon_id in skip_addons:
            continue
        addon = None
        try:
            addon = addon_presence.addon(addon_id) if addon_presence else None
            if addon is None:
                continue
            current = (addon.getSetting(token_key) or '').strip()
        except Exception:
            continue
        if current == token:
            continue
        wanted = list(base_wanted)
        # Credentials may need refreshing while the service itself is
        # deliberately disabled. Only a missing switch gets the functional
        # default; an explicit false survives the sync.
        try:
            service_enabled = (addon.getSetting(enabled_key) or '').strip()
        except Exception:
            service_enabled = ''
        if not service_enabled:
            wanted.append((enabled_key, 'true'))
        if addon_id == 'plugin.video.pov':
            # Account Manager itself does not touch this per-service switch.
            # A completely missing value means a newly rebuilt profile and
            # needs an enabled torrent service to be useful.  An explicit
            # false is the user's choice and must survive a credential sync.
            try:
                torrent_enabled = (
                    addon.getSetting('ad.torrent.enabled') or '').strip()
            except Exception:
                torrent_enabled = ''
            if not torrent_enabled:
                wanted.append(('ad.torrent.enabled', 'true'))
        changed, _restored, failed = addon_settings_safe.apply(
            addon_id, tuple(wanted),
            guard_property=('umbrella.updateSettings'
                            if addon_id == 'plugin.video.umbrella' else None))
        results.append({'addon': addon_id, 'changed': bool(changed),
                        'failed': bool(failed)})
        if changed and addon_id == 'plugin.video.pov' and xbmcgui is not None:
            try:
                xbmcgui.Window(10000).clearProperty('pov_settings')
            except Exception:
                pass
    return results
