# -*- coding: utf-8 -*-
"""POV debrid notification settings compatibility patch.

The build provides its own Hebrew/icon-aware premium-status toasts. POV's
upstream expiry service is English/generic and would duplicate the same
event, so we disable only that generic service and keep using POV's own
settings as the user-facing configuration surface.
"""

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from resources.lib import kodi_utils


POV_ADDON = 'plugin.video.pov'
SETTINGS_REL = os.path.join('resources', 'settings.xml')
SERVICE_REL = os.path.join('resources', 'lib', 'service.py')
MARKER = '# KODI_POV_IL_DEBRID_STATUS_HANDLED_BY_AI_ADDON'


def _path(rel):
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                POV_ADDON, rel.replace(os.sep, '/')))
    except Exception:
        return ''


def _read(path):
    with open(path, 'rb') as f:
        raw = f.read()
    return raw.decode('utf-8', errors='replace')


def _write_if_changed(path, text):
    old = _read(path)
    if old == text:
        return False
    tmp = path + '.aitmp'
    with open(tmp, 'wb') as f:
        f.write(text.encode('utf-8'))
    os.replace(tmp, path)
    return True


def _patch_settings():
    path = _path(SETTINGS_REL)
    if not path or not os.path.isfile(path):
        return False
    text = _read(path)
    new = text
    for sid in ('rd.expires', 'tb.expires', 'pm.expires', 'ad.expires'):
        pattern = (r'(<setting\b[^>]*id="' + re.escape(sid) +
                   r'"[^>]*\brange=")0,1,7("[^>]*/>)')
        new = re.sub(pattern, r'\g<1>0,1,365\2', new)
    return _write_if_changed(path, new)


def _patch_service():
    path = _path(SERVICE_REL)
    if not path or not os.path.isfile(path):
        return False
    text = _read(path)
    if MARKER in text:
        return False

    pattern = re.compile(
        r'(def\s+premAccntNotification\s*\(\s*\)\s*:\s*\r?\n)',
        re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return False

    eol = '\r\n' if '\r\n' in text[:8192] else '\n'
    insert = (
        '\t{0}{1}'
        '\ttry: logger("POV", "Debrid expiry notification handled by Kodi POV IL AI addon"){1}'
        '\texcept: pass{1}'
        '\treturn{1}'
    ).format(MARKER, eol)
    new = text[:match.end()] + insert + text[match.end():]
    return _write_if_changed(path, new)


def ensure_patched():
    changed = False
    try:
        changed = _patch_settings() or changed
    except Exception as exc:
        kodi_utils.log('pov_debrid_status_patcher settings failed: {0}'
                       .format(exc), level='WARNING')
    try:
        changed = _patch_service() or changed
    except Exception as exc:
        kodi_utils.log('pov_debrid_status_patcher service failed: {0}'
                       .format(exc), level='WARNING')
    return 'patched' if changed else 'already_patched'
