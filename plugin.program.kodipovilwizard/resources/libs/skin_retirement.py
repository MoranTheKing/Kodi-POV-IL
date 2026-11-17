"""A skin that left the build: move every profile off it and remove its files.

The skin named in RETIRED left the build with Wizard 0.5.0; Onyx is the
skin a new installation opens with. A device installed before that still has
the old skin on disk, and most have it as the active skin, since it was the
default. At each start (each profile's own start):

* Onyx is installed if it is not there (every installation carries the
  default skin: a new profile opens with it);
* once Onyx is on the device, the profiles that are not loaded have their
  saved skin rewritten on disk and are marked, so their own next start
  finishes the move (never before: a profile must not name a skin that is
  not installed);
* the loaded profile is moved through the Wizard's own Switch Skin -- never
  during playback, never before Onyx is on the device (no network: nothing
  changes, the next start tries again);
* once no profile names the old skin, its add-on folder, its downloaded
  package and its settings are deleted.

Never raises; every step is repeated at the next start until it is done.
"""
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET

import xbmc
import xbmcgui
import xbmcvfs

RETIRED = ('skin.povil.nox',)
DEFAULT = 'skin.povil.onyx'
# In a profile's folder: this profile was on a retired skin and its own start
# still has to activate the default one.
MARKER = 'kodipovil.skin_retired'
# Beside it: how many starts tried to switch the loaded profile and failed.
TRIES = MARKER + '.tries'
MAX_TRIES = 3
SKIN_MEMORY = os.path.join('addon_data', 'plugin.program.kodipovilwizard', 'host_watch_skin.json')
GUI_FILES = ('guisettings.xml', 'kodipovil.profile_gui_defaults.xml')
TITLE = 'Kodi POV IL'
MOVED_TEXT = ('הסקין שהיה פעיל אצלך הוסר מהבילד, ועברת לסקין Onyx.\n'
              'להחלפת סקין: לשונית הגדרות, ואז החלפת סקין.')


def _log(text, level=None):
    xbmc.log('[Skin retirement] ' + text, xbmc.LOGINFO if level is None else level)


def _atomic(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.povil-skin-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def saved_skin(profile, name='guisettings.xml'):
    """The skin a profile's settings file names; '' when unreadable."""
    try:
        row = ET.parse(os.path.join(profile, name)).getroot().find(
            ".//setting[@id='lookandfeel.skin']")
        return (row.text or '').strip() if row is not None else ''
    except (OSError, ET.ParseError):
        return ''


def rewrite_saved_skin(profile, name='guisettings.xml'):
    """Point a settings file that names a retired skin at the default one.
    Only for a file Kodi does not hold in memory. True when it was changed."""
    path = os.path.join(profile, name)
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError):
        return False
    row = tree.getroot().find(".//setting[@id='lookandfeel.skin']")
    if row is None or (row.text or '').strip() not in RETIRED:
        return False
    row.text = DEFAULT
    row.attrib.pop('default', None)
    _atomic(path, ET.tostring(tree.getroot(), encoding='utf-8', xml_declaration=True))
    return True


def profile_folders(master):
    """Every profile's folder, the master's first. Unreadable entries skipped."""
    master = os.path.realpath(master)
    folders = [master]
    try:
        from resources.libs import profile_store
        for profile in profile_store.registered_profiles(master):
            try:
                path = profile_store.profile_path(master, profile)
            except ValueError:
                continue
            if path not in folders and os.path.isdir(path):
                folders.append(path)
    except (OSError, ET.ParseError, ValueError):
        pass
    return folders


def rewrite_side_files(folder):
    """The two files beside a profile's settings that can bring a retired
    skin back: the kids profile's pending defaults (applied at its start)
    and the skin the host watcher remembers. Kodi holds neither in memory,
    so this is for the loaded profile too."""
    try:
        rewrite_saved_skin(folder, 'kodipovil.profile_gui_defaults.xml')
        memory = os.path.join(folder, SKIN_MEMORY)
        if os.path.isfile(memory):
            with open(memory) as handle:
                data = json.load(handle)
            if data.get('skin') in RETIRED:
                data['skin'] = DEFAULT
                _atomic(memory, json.dumps(data).encode('utf-8'))
    except (OSError, ValueError):
        pass


def prepare_unloaded(master, active):
    """Rewrite and mark every profile that is not loaded and names a retired
    skin. Only once the default skin is on the device. Returns how many
    were changed."""
    changed = 0
    active = os.path.realpath(active)
    for folder in profile_folders(master):
        if os.path.realpath(folder) == active:
            continue
        try:
            if rewrite_saved_skin(folder):
                with open(os.path.join(folder, MARKER), 'w') as handle:
                    handle.write(DEFAULT)
                changed += 1
        except OSError:
            continue
        rewrite_side_files(folder)
    return changed


def names_retired(master):
    """True while any profile's saved skin is a retired one."""
    return any(saved_skin(folder) in RETIRED for folder in profile_folders(master))


def remove_files(addons, master, packages=None):
    """Delete the retired skins' folders, packages and settings. Returns the
    paths removed. Only when no profile names them and none is loaded."""
    removed = []
    for ident in RETIRED:
        targets = [os.path.join(addons, ident)]
        targets += [os.path.join(folder, 'addon_data', ident) for folder in profile_folders(master)]
        for target in targets:
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
                if not os.path.exists(target):
                    removed.append(target)
        folder = packages or os.path.join(addons, 'packages')
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        for name in names:
            low = name.lower()
            short = ident.rsplit('.', 1)[-1]
            if low.startswith(ident + '-') or low in (short + '-modular.zip', short + '_skin_pack.zip'):
                try:
                    os.unlink(os.path.join(folder, name))
                    removed.append(os.path.join(folder, name))
                except OSError:
                    pass
    return removed


def _wait(monitor, condition, settle, limit, step=2):
    """True once condition() held for `settle` seconds; False when `limit`
    passed; None when Kodi is closing."""
    held = waited = 0
    while True:
        holds = condition()
        if holds and held >= settle:
            return True
        if waited >= limit:
            return False
        held = held + step if holds else 0
        if monitor.waitForAbort(step):
            return None
        waited += step


def _tries(active, add=0):
    path = os.path.join(active, TRIES)
    try:
        with open(path) as handle:
            count = int(handle.read().strip() or 0)
    except (OSError, ValueError):
        count = 0
    if add:
        count += add
        try:
            with open(path, 'w') as handle:
                handle.write(str(count))
        except OSError:
            pass
    return count


def move_loaded_profile(monitor, active):
    """Move the loaded profile to the default skin. True when it is on a
    skin of the build afterwards; False to try again at the next start;
    None when Kodi is closing."""
    marker = os.path.join(active, MARKER)
    on_retired = (xbmc.getSkinDir() in RETIRED or saved_skin(active) in RETIRED
                  or os.path.isfile(marker))
    if not on_retired:
        return True
    if _tries(active) >= MAX_TRIES:
        if xbmc.getSkinDir() not in RETIRED + ('skin.estuary',):
            # moved by hand since: nothing is owed any more
            for leftover in (marker, os.path.join(active, TRIES)):
                if os.path.isfile(leftover):
                    os.unlink(leftover)
            return True
        # a switch that keeps failing is not repeated (with its skin reload)
        # at every start; Switch Skin still moves the profile by hand
        _log('the move failed {0} times; left for Switch Skin'.format(MAX_TRIES), xbmc.LOGWARNING)
        return False
    window = xbmcgui.Window(10000)
    # After the start-up repairs (two writers of skin files), and never over a
    # video: Switch Skin refuses during playback. MoranSubs raises the flag;
    # without it (the add-on disabled) the move goes on after five minutes,
    # as the host watcher's own skin restore does.
    if _wait(monitor, lambda: bool(window.getProperty('kodipovil_startup_repairs_done')),
             0, 300) is None:
        return None
    quiet = _wait(monitor, lambda: not xbmc.getCondVisibility('Player.HasMedia'), 6, 6 * 3600)
    if quiet is not True:
        return quiet
    if os.path.isfile(marker) and xbmc.getSkinDir() not in RETIRED + ('skin.estuary',):
        # the profile chose another skin of the build since it was marked
        os.unlink(marker)
        return True
    from resources.libs import wizard, build_skin
    if not wizard.ensure_onyx_installed():
        _log('Onyx is not on the device yet; the move waits for the next start', xbmc.LOGWARNING)
        return False
    was = xbmc.getSkinDir()
    switched = build_skin.switch(DEFAULT)
    now = xbmc.getSkinDir()
    _log('profile moved from {0}: now on {1} (switch completed: {2})'.format(was, now, bool(switched)))
    if now != DEFAULT:
        _tries(active, add=1)
        return False
    for leftover in (marker, os.path.join(active, TRIES)):
        if os.path.isfile(leftover):
            os.unlink(leftover)
    rewrite_side_files(active)
    try:
        from resources.libs.patches import profile_age_guard
        if profile_age_guard.active_policy() is None and was in RETIRED:
            xbmcgui.Dialog().ok(TITLE, MOVED_TEXT)
    except Exception:
        pass
    return True


def run():
    try:
        monitor = xbmc.Monitor()
        master = os.path.realpath(xbmcvfs.translatePath('special://masterprofile/'))
        active = os.path.realpath(xbmcvfs.translatePath('special://profile/'))
        addons = xbmcvfs.translatePath('special://home/addons/')
        if not os.path.isfile(os.path.join(master, 'kodipovil.provisioned')):
            return
        on_disk = any(os.path.isdir(os.path.join(addons, ident)) for ident in RETIRED)
        if (not on_disk and not names_retired(master) and xbmc.getSkinDir() not in RETIRED
                and not os.path.isfile(os.path.join(active, MARKER))
                and os.path.isfile(os.path.join(addons, DEFAULT, 'addon.xml'))):
            return                                    # nothing left to do: the common start
        def have_default():
            return os.path.isfile(os.path.join(addons, DEFAULT, 'addon.xml'))

        moved = move_loaded_profile(monitor, active)
        if moved is None:
            return
        if not have_default():
            # a profile on another skin: the build's default skin is still
            # part of every installation
            from resources.libs import wizard
            if monitor.waitForAbort(20) or xbmc.getCondVisibility('Player.HasMedia'):
                return
            _log('default skin installed: {0}'.format(bool(wizard.ensure_onyx_installed())))
        if not have_default():
            return                                    # offline: nothing is rewritten or deleted
        changed = prepare_unloaded(master, active)
        if changed:
            _log('{0} unloaded profile(s) pointed at {1}'.format(changed, DEFAULT))
        if xbmc.getSkinDir() not in RETIRED:
            rewrite_side_files(active)
        if (moved and xbmc.getSkinDir() not in RETIRED and saved_skin(active) not in RETIRED
                and not names_retired(master)):
            removed = remove_files(addons, master)
            if removed:
                xbmc.executebuiltin('UpdateLocalAddons')
                _log('removed {0} item(s) of the retired skin'.format(len(removed)))
    except Exception as exc:
        _log('deferred: {0!r}'.format(exc), xbmc.LOGWARNING)
