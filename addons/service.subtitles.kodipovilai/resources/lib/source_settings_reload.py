# -*- coding: utf-8 -*-
"""Reload repaired Umbrella/Coco settings without risking active playback.

Kodi reads an add-on's profile settings into its CAddon object. Replacing a
malformed XML file repairs the disk, but an add-on already constructed during
this startup can keep the old defaults until it is reconstructed. POV has its
own mature idle-safe cycle. This module provides the smaller companion cycle
needed by Umbrella and CocoScrapers.

Only add-ons that were enabled before the cycle are touched. A crash-safe
record is written before the first disable; a later service start uses that
record to re-enable only add-ons this module could have left off. If Kodi never
becomes safely idle, nothing is disabled and the valid file takes effect at
the next normal Kodi start.
"""

from __future__ import unicode_literals

import json
import os
import threading

try:
    import xbmc
except Exception:
    xbmc = None

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils, pov_reload
except Exception:
    kodi_utils = None
    pov_reload = None


UMBRELLA_ID = 'plugin.video.umbrella'
COCO_ID = 'script.module.cocoscrapers'
_ALLOWED = (UMBRELLA_ID, COCO_ID)
_DISABLE_ORDER = (UMBRELLA_ID, COCO_ID)
_ENABLE_ORDER = (COCO_ID, UMBRELLA_ID)
_RECORD_SPECIAL = (
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'source-settings-cycle.json')

_pending = set()
_scheduled = False
_lock = threading.Lock()


def _log(message, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('source_settings_reload: ' + message, level=level)
    except Exception:
        pass


def _record_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(_RECORD_SPECIAL)
    except Exception:
        return ''


def _read_record():
    path = _record_path()
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        requested = data.get('addon_ids') if isinstance(data, dict) else []
        return [addon_id for addon_id in _ENABLE_ORDER
                if addon_id in (requested or [])]
    except Exception:
        # An unreadable record is not authority to enable arbitrary add-ons.
        return []


def _write_record(addon_ids):
    path = _record_path()
    wanted = [addon_id for addon_id in _DISABLE_ORDER
              if addon_id in set(addon_ids or ())]
    if not path or not wanted:
        return False
    directory = os.path.dirname(path) or '.'
    temp = path + '.tmp'
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump({'addon_ids': wanted}, handle, sort_keys=True)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        os.replace(temp, path)
        return _read_record() == [addon_id for addon_id in _ENABLE_ORDER
                                  if addon_id in wanted]
    except Exception:
        try:
            os.remove(temp)
        except Exception:
            pass
        return False


def _clear_record():
    path = _record_path()
    if not path:
        return False
    try:
        if os.path.isfile(path):
            os.remove(path)
        return not os.path.exists(path)
    except Exception:
        return False


def _is_enabled(addon_id):
    if xbmc is None or addon_id not in _ALLOWED:
        return None
    payload = json.dumps({
        'jsonrpc': '2.0', 'id': 1,
        'method': 'Addons.GetAddonDetails',
        'params': {'addonid': addon_id, 'properties': ['enabled']},
    })
    try:
        data = json.loads(xbmc.executeJSONRPC(payload) or '{}')
        addon = (data.get('result') or {}).get('addon') or {}
        return bool(addon.get('enabled')) if 'enabled' in addon else None
    except Exception:
        return None


def _set_enabled(addon_id, enabled):
    if xbmc is None or addon_id not in _ALLOWED:
        return False
    payload = json.dumps({
        'jsonrpc': '2.0', 'id': 1,
        'method': 'Addons.SetAddonEnabled',
        'params': {'addonid': addon_id, 'enabled': bool(enabled)},
    })
    try:
        reply = xbmc.executeJSONRPC(payload) or ''
        return '"result"' in reply and '"error"' not in reply
    except Exception:
        return False


def _sleep(milliseconds):
    try:
        xbmc.sleep(milliseconds)
    except Exception:
        pass


def _wait_for_state(addon_id, expected, attempts=8):
    """Require Kodi to report the requested state; RPC success is not proof."""
    for _attempt in range(attempts):
        if _is_enabled(addon_id) is expected:
            return True
        _sleep(250)
    return _is_enabled(addon_id) is expected


def _restore_enabled(addon_ids):
    """Best-effort restore, returning True only after every ID reads enabled."""
    wanted = [addon_id for addon_id in _ENABLE_ORDER
              if addon_id in set(addon_ids or ())]
    for _attempt in range(8):
        missing = [addon_id for addon_id in wanted
                   if _is_enabled(addon_id) is not True]
        if not missing:
            return True
        for addon_id in missing:
            _set_enabled(addon_id, True)
        _sleep(500)
    return all(_is_enabled(addon_id) is True for addon_id in wanted)


def heal_interrupted_cycle():
    """Re-enable only add-ons named by a record written by this module."""
    recorded = _read_record()
    if not recorded:
        return True
    restored = _restore_enabled(recorded)
    if restored:
        if not _clear_record():
            _log('recovered enabled add-ons but could not clear cycle record',
                 level='WARNING')
            return False
        _log('completed an interrupted source-settings reload', level='INFO')
        return True
    _log('could not complete an interrupted source-settings reload; record '
         'kept for the next start', level='WARNING')
    return False


def note_repaired(addon_ids):
    """Remember which directly repaired settings files need reconstruction."""
    with _lock:
        for addon_id in addon_ids or ():
            if addon_id == UMBRELLA_ID:
                _pending.add(UMBRELLA_ID)
            elif addon_id == COCO_ID:
                # Umbrella imports and consumes Coco's settings. If it is
                # enabled, reconstruct it after Coco as part of the same gap.
                _pending.add(COCO_ID)
                _pending.add(UMBRELLA_ID)


def _safe_to_cycle():
    if xbmc is None or pov_reload is None:
        return False
    try:
        # The POV repair may have armed its own cycle immediately before this
        # one. Wait until its unavailable window is over, then use the same
        # home/media/dialog/idle gate already field-hardened for source UI.
        if not pov_reload.wait_until_settled(timeout=240):
            return False
        if not pov_reload._wait_until_idle(timeout=180):
            return False
        return (not xbmc.getCondVisibility('Player.HasMedia')
                and not xbmc.getCondVisibility('Container.IsUpdating')
                and not pov_reload._dialog_up())
    except Exception:
        return False


def _run_cycle(requested):
    if not heal_interrupted_cycle():
        return False
    if not _safe_to_cycle():
        _log('screen did not become safely idle; repaired settings will load '
             'on the next Kodi start', level='INFO')
        return False

    # Query at the last possible point. False is an explicit user state and is
    # never changed; None means Kodi cannot prove the add-on is available.
    enabled = [addon_id for addon_id in _DISABLE_ORDER
               if addon_id in requested and _is_enabled(addon_id) is True]
    if not enabled:
        return True
    if not _write_record(enabled):
        _log('could not record the cycle; no add-on was disabled',
             level='WARNING')
        return False

    disabled = []
    try:
        for addon_id in _DISABLE_ORDER:
            if addon_id not in enabled:
                continue
            if not _set_enabled(addon_id, False):
                _log('{0} refused the disable; restoring the already changed '
                     'add-ons'.format(addon_id), level='WARNING')
                return False
            if not _wait_for_state(addon_id, False):
                _log('{0} never reached the disabled state; not claiming a '
                     'settings reload'.format(addon_id), level='WARNING')
                return False
            disabled.append(addon_id)
        _sleep(1200)
        restored = _restore_enabled(enabled)
        if restored and _clear_record():
            _log('reloaded repaired settings for {0}'.format(
                ', '.join(enabled)), level='INFO')
            return True
        _log('one or more source add-ons did not come back; recovery record '
             'kept for the next start', level='WARNING')
        return False
    finally:
        # Covers a refused later disable, an exception, or a normal enable
        # failure. The record stays unless every original add-on is verified
        # enabled, so a process kill cannot strand one off silently.
        if _restore_enabled(enabled):
            _clear_record()


def _deferred_cycle(requested):
    try:
        _run_cycle(requested)
    except Exception as exc:
        _log('reload failed: {0}'.format(exc), level='WARNING')
        heal_interrupted_cycle()


def reload_if_repaired():
    """Schedule at most one background reload for this service process."""
    global _scheduled
    with _lock:
        if _scheduled or not _pending or xbmc is None:
            return False
        requested = set(_pending)
        _scheduled = True
    try:
        threading.Thread(target=_deferred_cycle, args=(requested,),
                         daemon=True).start()
        return True
    except Exception as exc:
        with _lock:
            _scheduled = False
        _log('could not start reload worker: {0}'.format(exc),
             level='WARNING')
        return False
