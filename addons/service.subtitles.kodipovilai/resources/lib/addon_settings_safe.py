# Write another add-on's settings without ever moving a setting we did not
# name.
#
# WHY THIS EXISTS. Kodi's `xbmcaddon.Addon(other_id).setSetting(k, v)` is not
# a targeted write. It is:
#     load the whole of <other_id>'s settings into memory
#       -> change one value
#       -> RE-SERIALISE AND OVERWRITE THE ENTIRE settings.xml
# (xbmc/addons/Addon.cpp: UpdateSetting -> SaveSettings -> SettingsToXML).
# Everything the file contains makes that round trip, and anything the load
# leg drops or rejects is written back at its DEFAULT by the save leg --
# CAddonSettings::Load only warns ("failed to load value X for setting Y")
# and leaves the default in place when a stored value does not satisfy the
# definition's current constraints. A stored value can stop satisfying them
# without the user touching anything: the add-on updates and narrows a range
# or edits an <options> list, or the file was written behind Kodi's back and
# never re-read. So a single one-key write by US can silently reset a setting
# belonging to THEM -- and the user sees "the update reset my resolution".
#
# We cannot fix Kodi's round trip. We can make sure it is a no-op for
# everything that is not ours:
#
#   1. read <profile>/addon_data/<id>/settings.xml BEFORE we touch anything;
#   2. write only the keys we name, and only where the value really differs;
#   3. read the file again AFTER and compare;
#   4. any key that existed before, is not one of ours, and now reads
#      differently -> put the old value straight back, and log it loudly.
#
# Step 4 is the whole point. In the ordinary case it finds nothing and costs
# one file read. When it does find something, the user's setting is restored
# within the same startup instead of being lost, and the log names the key --
# which is also how we would learn that this happens at all.
#
# A key that appears only in the AFTER file is left alone: that is Kodi
# materialising a default that was previously implicit, which changes nothing
# the user would notice and is not ours to fight.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

try:
    import xbmcgui
except Exception:
    xbmcgui = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('addon_settings_safe: ' + msg, level=level)
    except Exception:
        pass


def _values_path(addon_id):
    """The add-on's STORED values -- not its definition."""
    if xbmcvfs is None:
        return ''
    try:
        p = xbmcvfs.translatePath(
            'special://profile/addon_data/' + addon_id + '/settings.xml')
    except Exception:
        return ''
    return p if os.path.isfile(p) else ''


def _read_values(path):
    """{id: text} for every <setting id="..."> in the stored values file.
    Returns None when the file cannot be read or parsed -- the caller then
    skips the comparison rather than acting on a half-picture."""
    if not path:
        return None
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(path).getroot()
    except Exception:
        return None
    out = {}
    for node in root.iter('setting'):
        key = node.get('id')
        if key:
            out[key] = node.text if node.text is not None else ''
    return out


def apply(addon_id, wanted, guard_property=None):
    """Set every (key, value) in `wanted` on `addon_id`, in that order,
    leaving every other setting exactly as it was.

    `wanted` is an ordered sequence of (key, value) pairs -- order matters
    when the target add-on reacts to its own settings (Umbrella blanks the
    external provider names whenever it sees the enable toggle off, so the
    toggle has to go last).

    `guard_property` is the home-window property the target add-on uses to
    mute its own settings monitor while it writes settings itself; when
    given we drive it the way the add-on does, so our writes do not make it
    run its change handler once per key.

    Returns (changed, restored, failed):
      changed -- the keys we actually wrote,
      restored -- the foreign keys we had to put back,
      failed  -- the keys we meant to write that did NOT end up at the wanted
                 value, whether the call raised or the value simply did not
                 stick.
    `failed` is the one callers must look at: a caller that records "already
    applied" for a key we never managed to write would never try again.
    Never raises."""
    if xbmcaddon is None:
        return [], [], [k for k, _ in wanted]
    try:
        addon = xbmcaddon.Addon(addon_id)
    except Exception:
        return [], [], [k for k, _ in wanted]

    path = _values_path(addon_id)
    before = _read_values(path)

    pending = []
    unreadable = []
    for key, value in wanted:
        try:
            current = addon.getSetting(key)
        except Exception:
            # Cannot even read it -> cannot claim it is where we want it.
            unreadable.append(key)
            continue
        if (current or '') != value:
            pending.append((key, value))
    if not pending:
        return [], [], unreadable

    win = None
    if guard_property and xbmcgui is not None:
        try:
            win = xbmcgui.Window(10000)
        except Exception:
            win = None

    changed = []
    last = len(pending)
    for idx, (key, value) in enumerate(pending, 1):
        if win is not None:
            # Mute the target's monitor for every write but the last, exactly
            # as its own bulk-write helper does, so it runs its change handler
            # once at the end instead of once per key.
            try:
                win.setProperty(guard_property,
                                'true' if idx == last else 'false')
            except Exception:
                pass
        try:
            addon.setSetting(key, value)
            changed.append(key)
        except Exception as e:
            _log('{0}: could not set {1}: {2}'.format(addon_id, key, e),
                 'WARNING')

    if win is not None:
        # Belt and braces: whatever happened in the loop, the target's monitor
        # must not be left muted. Leaving this at 'false' would silently stop
        # it reacting to the USER's next settings change, for the rest of the
        # session, which is a far worse bug than the one the mute avoids.
        try:
            win.setProperty(guard_property, 'true')
        except Exception:
            pass

    # A write that raised is a failure; so is a write that returned quietly
    # and did not stick (the target add-on can react to a setting by putting
    # it back). Read our own keys again and believe the file, not the call.
    failed = list(unreadable)
    for key, value in pending:
        try:
            if (addon.getSetting(key) or '') != value:
                failed.append(key)
        except Exception:
            failed.append(key)
    if failed:
        _log('{0}: {1} did not end up at the value we asked for'.format(
            addon_id, ', '.join(failed)), 'WARNING')

    restored = []
    if before is not None and changed:
        ours = set(k for k, _ in wanted)
        after = _read_values(path or _values_path(addon_id))
        if after is not None:
            for key, old in before.items():
                if key in ours:
                    continue
                if key in after and after[key] != old:
                    try:
                        addon.setSetting(key, old)
                        restored.append(key)
                    except Exception:
                        pass
            if restored:
                _log('{0}: Kodi\'s settings round trip moved {1} setting(s) '
                     'we never named ({2}) -- restored to what the user had'
                     .format(addon_id, len(restored), ', '.join(restored)),
                     'WARNING')
                # Say so out loud if a restore did NOT stick. One pass, never
                # a loop: something that reverts a value as fast as we write
                # it will not be beaten by writing it again, and the useful
                # thing at that point is a log line naming the setting.
                final = _read_values(path or _values_path(addon_id))
                if final is not None:
                    stuck = [k for k in restored
                             if final.get(k) != before.get(k)]
                    if stuck:
                        _log('{0}: could NOT restore {1} -- still reads {2}, '
                             'the user had {3}'.format(
                                 addon_id, ', '.join(stuck),
                                 ', '.join(str(final.get(k)) for k in stuck),
                                 ', '.join(str(before.get(k)) for k in stuck)),
                             'WARNING')
    return changed, restored, failed
