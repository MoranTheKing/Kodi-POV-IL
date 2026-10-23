"""Repair hooks after Kodi updates a host during an existing session.

Idle polling only stats addon.xml. It does no network work and never replaces
an addon, restarts Kodi, or edits a playing video's code.
"""
import os
import hashlib
import json
import time

AF3_ID = 'skin.arctic.fuse.3'
# Kodi's own fallback when the configured skin cannot be loaded.
DEFAULT_SKIN = 'skin.estuary'
SKIN_MEMORY = 'host_watch_skin.json'
SKIN_STABLE_POLLS = 3          # 20-30 s on one skin with nothing updating
SKIN_REFRESH_SECONDS = 1800
_RESTORE_TRIED = set()         # AF3 signature rows a restore was attempted for

def af3_font_current(addons):
    """False when Arctic Fuse 3 is installed without the build's Hebrew font.

    Kodi replaces the whole skin folder on an update, Font.xml included, and
    the developer's fonts have no Hebrew: Kodi's own Hebrew (dates, "last
    login", menus) then shows as boxes, on the next login screen too (field
    report, 22 Oct 2026). MoranSubs' af3_home_patcher writes the NotoSans
    fontset."""
    if not os.path.isfile(os.path.join(addons, AF3_ID, 'addon.xml')):
        return True
    try:
        with open(os.path.join(addons, AF3_ID, '1080i', 'Font.xml'), 'rb') as handle:
            return b'NotoSans-Regular.ttf' in handle.read()
    except OSError:
        return False


def af3_hooks_current(addons):
    """False when Arctic Fuse 3's Home lacks the build's profile hooks.

    build_profiles.install_login_hooks puts the profile bootstrap (and the
    child-profile Home) into every build skin at start-up. When Kodi's
    start-up repository check replaces AF3 a few seconds later, and
    MoranSubs restores the font before this watch begins, the font check
    passes and the new Home ran without the hooks until the next restart
    (QA, 23 Oct 2026: AF3 3.4.6 -> 3.4.8)."""
    if not os.path.isfile(os.path.join(addons, AF3_ID, 'addon.xml')):
        return True
    try:
        with open(os.path.join(addons, AF3_ID, '1080i', 'Home.xml'), 'rb') as handle:
            return b'profile_bootstrap.py' in handle.read()
    except OSError:
        return False


def current_skin():
    try:
        import xbmc
        return xbmc.getSkinDir() or ''
    except Exception:
        return ''


def _skin_memory_path():
    import xbmcvfs
    return os.path.join(xbmcvfs.translatePath(
        'special://profile/addon_data/plugin.program.kodipovilwizard/'), SKIN_MEMORY)


def read_skin_memory():
    """(skin, seen_at) this profile was last seen on, settled; ('', 0) if none."""
    try:
        with open(_skin_memory_path(), 'r') as handle:
            data = json.load(handle)
        return str(data.get('skin') or ''), float(data.get('seen') or 0)
    except Exception:
        return '', 0.0


def remember_skin(skin, now=None):
    """Record the profile's skin (per profile). Called only for a skin seen
    settled -- never for Kodi's mid-update fallback -- and by the Wizard's
    own Switch Skin, which is a deliberate choice."""
    if not skin:
        return
    try:
        path = _skin_memory_path()
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        temporary = path + '.tmp'
        with open(temporary, 'w') as handle:
            json.dump({'skin': skin, 'seen': time.time() if now is None else now}, handle)
        os.replace(temporary, path)
    except Exception:
        pass


_MID_INSTALL_SINCE = []        # monotonic time AF3 was first seen unloaded
MID_INSTALL_MAX_SECONDS = 600


def af3_mid_install(addons):
    """True while Kodi has AF3 unloaded for an install: its files are on disk
    but Kodi does not know the add-on (CAddonInstallJob unloads it before the
    dependency installs and the unpack, and loads it again after the folder
    is replaced -- on a slow box that is minutes before addon.xml changes).
    Estuary seen then is Kodi's fallback, never the user's choice."""
    if not os.path.isfile(os.path.join(addons, AF3_ID, 'addon.xml')):
        return False
    try:
        import xbmc
        unloaded = not xbmc.getCondVisibility('System.HasAddon({})'.format(AF3_ID))
    except Exception:
        return False
    if not unloaded:
        del _MID_INSTALL_SINCE[:]
        return False
    # An AF3 Kodi never loads (broken or incompatible after a Kodi upgrade)
    # is not an install: after 10 minutes the profile's skin counts again.
    if not _MID_INSTALL_SINCE:
        _MID_INSTALL_SINCE.append(time.monotonic())
    return time.monotonic() - _MID_INSTALL_SINCE[0] < MID_INSTALL_MAX_SECONDS


def _quiet_for(monitor, condition, settle, limit, step=5):
    """True once condition() has held `settle` s in a row; False after
    `limit` s; None when Kodi closes."""
    held, waited = 0, 0
    while True:
        ok = condition()
        if ok and held >= settle:
            return True
        if waited >= limit:
            return False
        held = held + step if ok else 0
        if monitor.waitForAbort(step):
            return None
        waited += step


def af3_updated_since(seen):
    try:
        import xbmcvfs
        addons = xbmcvfs.translatePath('special://home/addons/')
        mtime = os.path.getmtime(os.path.join(addons, AF3_ID, 'addon.xml'))
        # A file time from the future (clock corrected later) is no update.
        return seen < mtime <= time.time()
    except Exception:
        return False


def restore_af3(previous_skin, af3_row, monitor=None, window=None):
    """Put a profile Kodi dropped to Estuary during an AF3 update back on AF3.

    QA (22 Oct 2026): Kodi unloads the active skin while it installs AF3; a
    ReloadSkin in that moment (AF3's own skinvariables, after updating itself)
    finds AF3 half-installed, Kodi loads Estuary and saves it as the user's
    skin. Only for a profile whose settled skin was AF3 and that is on
    Estuary now; once per AF3 update, never retried; through the Wizard's own
    Switch Skin (build_skin.switch: refuses during playback and for a blocked
    child profile, re-applies the child-profile hooks). None when there was
    nothing to do, else whether the switch succeeded."""
    import xbmc
    if previous_skin != AF3_ID or af3_row in _RESTORE_TRIED:
        return None
    # One evaluation per AF3 update: a later retry of this repair must not
    # override an Estuary the user picked in the meantime.
    _RESTORE_TRIED.add(af3_row)
    if current_skin() != DEFAULT_SKIN:
        return None
    if monitor is not None and window is not None:
        # The switch rebuilds AF3 through MoranSubs and reloads the skin: not
        # alongside MoranSubs' own start-up pass (two writers can tear the
        # skinvariables node files), and not in a gap between POV's autoplay
        # episodes -- 30 s with nothing playing at all.
        if _quiet_for(monitor, lambda: bool(window.getProperty('kodipovil_startup_repairs_done')),
                      0, 180) is None:
            return None
        if _quiet_for(monitor, lambda: not xbmc.getCondVisibility('Player.HasMedia'),
                      30, 6 * 3600) is not True:
            return None
        if current_skin() != DEFAULT_SKIN or read_skin_memory()[0] != AF3_ID:
            return None                      # the user moved on meanwhile
    try:
        from resources.libs import build_skin
        switched = build_skin.switch(AF3_ID)
    except Exception as exc:
        xbmc.log('[POV IL] Arctic Fuse 3 restore failed: {!r}'.format(exc), xbmc.LOGWARNING)
        switched = False
    restored = current_skin() == AF3_ID
    xbmc.log('[POV IL] Arctic Fuse 3 update left Kodi on {}; back on Arctic Fuse 3: {} '
             '(switch completed: {})'.format(DEFAULT_SKIN, restored, bool(switched)), xbmc.LOGINFO)
    return restored


def repair_af3(addons, window, monitor, previous_skin=None, af3_row=None):
    """Re-apply the build's edits to Arctic Fuse 3 after Kodi updated it.

    The update wipes two sets of them. The Wizard's own -- child-profile home
    gating, the profile bootstrap and the branded login screen -- are written
    again here (install_login_hooks reloads the skin itself when a child
    policy is active). MoranSubs' -- Hebrew font and strings, POV search,
    Discover and the subtitle dialog -- come from its repair_af3.py, which
    waits for MoranSubs' own start-up pass and for playback to end, then
    rebuilds and reloads the skin. Best effort: the next Kodi start applies
    both anyway, so a failure here is logged, never retried in a loop.
    Returns None when Kodi is closing."""
    import xbmc
    restore_af3(previous_skin, af3_row, monitor, window)
    try:
        from resources.libs import build_profiles
        build_profiles.install_login_hooks()
    except Exception as exc:
        xbmc.log('[POV IL] Arctic Fuse 3 profile hooks deferred: {!r}'.format(exc), xbmc.LOGWARNING)
    result = run_moransubs_repair(addons, window, monitor, 'repair_af3.py',
                                  'kodipovil.af3_repair.', wait=60, missing=True)
    xbmc.log('[POV IL] Arctic Fuse 3 update repair acknowledged={}'.format(result), xbmc.LOGINFO)
    return None if result is None else True


def repair_changed(addons, previous, current, window, monitor, previous_skin=None):
    import xbmc
    from resources.libs.patch_engine import PatchEngine
    old = dict((row[0], row[1:]) for row in previous)
    changed = [row[0] for row in current if old.get(row[0]) != row[1:]]
    # The patch engine has nothing for Arctic Fuse; an AF3 update alone does
    # not repeat the start-up pass on slow boxes.
    hooks = current[0][1] is not None and any(name != AF3_ID for name in changed)
    stats = PatchEngine().run() if hooks else {}
    healthy = not any(stats.get(key, 0) for key in
                      ('failed', 'missing', 'anchor_missing', 'malformed', 'legacy_host_deferred'))
    umbrella_changed = current[1][1] is not None and old.get(current[1][0]) != current[1][1:]
    if umbrella_changed:
        repaired = repair_umbrella(addons, window, monitor)
        if repaired is None:
            return False
        healthy = healthy and repaired
    if any(row[0] in ('skin.fentastic', 'script.fentastic.helper') and
           old.get(row[0]) != row[1:] for row in current):
        from resources.libs import fentastic_widgets
        fentastic_widgets.repair()
    af3 = [row for row in current if row[0] == AF3_ID and row[1] is not None
           and old.get(row[0]) != row[1:]]
    if af3:
        if repair_af3(addons, window, monitor, previous_skin, tuple(af3[0])) is None:
            return False
    xbmc.log('[POV IL] Host-update patch repair: {} acknowledged={}'.format(stats, healthy), xbmc.LOGINFO)
    return healthy

def repair_umbrella(addons, window, monitor):
    """Run MoranSubs' Umbrella patchers (its repair_hosts.py) and wait for
    their answer. True when every one reports a good state, False when not or
    no answer came within 20 s, None when Kodi is closing.

    Also used by the Wizard's version gate right after it installs a verified
    Umbrella: this watch takes its baseline after the start-up update check,
    so it never sees that change, and MoranSubs patched the old tree at start."""
    return run_moransubs_repair(addons, window, monitor, 'repair_hosts.py',
                                'kodipovil.host_repair.')


def run_moransubs_repair(addons, window, monitor, script_name, ack_prefix,
                         wait=20, missing=False):
    """RunScript one of MoranSubs' repair scripts and wait for its answer.
    `missing` is the result when that MoranSubs has no such script."""
    import xbmc
    import uuid
    ack = ack_prefix + uuid.uuid4().hex
    script = os.path.join(addons, 'service.subtitles.kodipovilai', script_name)
    if not os.path.isfile(script):
        return missing
    try:
        xbmc.executebuiltin('RunScript({}, {})'.format(script, ack))
        for _ in range(wait):
            result = window.getProperty(ack)
            if result:
                return json.loads(result).get('ok') is True
            if monitor.waitForAbort(1):
                return None
        return False
    except Exception:
        return False
    finally:
        window.clearProperty(ack)


def prebuild_lists():
    """Build one POV list ahead of its first visit while Kodi is idle (see
    pov_list_snapshot.prebuild_tick). Never fails the watch loop."""
    import sys
    import xbmc
    import xbmcvfs
    try:
        patches = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')
        if patches not in sys.path:
            sys.path.append(patches)
        import pov_list_snapshot
        pov_list_snapshot.prebuild_tick(xbmc)
    except Exception:
        pass


def resign_lists():
    """On Kodi's way out, after this session's last cache and sync writes:
    record the current file times of the most recent saved lists whose
    content did not change, so the first home rows of the next start are
    proven by file times alone. Files and SQLite only -- no GUI call (the
    GUI thread is waiting for this interpreter). Bounded to 1.5 s."""
    import sys
    import xbmcvfs
    try:
        patches = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')
        if patches not in sys.path:
            sys.path.append(patches)
        import pov_list_snapshot
        import xbmc
        pov_list_snapshot.DB_TIMEOUT = 0.3     # Kodi is closing: never wait on a lock
        done = pov_list_snapshot.resign(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'),
                                        limit=12, budget_s=1.5)
        xbmc.log('[POV IL snapshot] on exit: {} saved list(s) re-checked'.format(done), xbmc.LOGINFO)
    except Exception as error:
        try:
            import xbmc
            xbmc.log('[POV IL snapshot] on exit: re-check skipped ({})'.format(type(error).__name__), xbmc.LOGINFO)
        except Exception:
            pass


def warm_bytecode(addons, monitor):
    """Write .pyc files Kodi never writes itself (see pyc_warm); next pass time."""
    import xbmc
    started = time.monotonic()
    try:
        from resources.libs import pyc_warm
        player = xbmc.Player()
        compiled, current, failed = pyc_warm.warm(
            addons, should_stop=monitor.abortRequested,
            should_pause=player.isPlayingVideo,
            sleep=monitor.waitForAbort)
        xbmc.log('[POV IL] bytecode: {} compiled, {} current, {} skipped in {:.1f}s'.format(
            compiled, current, failed, time.monotonic() - started), xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[POV IL] bytecode pass failed: {!r}'.format(exc), xbmc.LOGWARNING)


def signature(addons):
    result = []
    for addon in ('plugin.video.pov', 'plugin.video.umbrella',
                  'skin.fentastic', 'script.fentastic.helper', AF3_ID):
        path = os.path.join(addons, addon, 'addon.xml')
        try:
            info = os.stat(path)
            result.append((addon, info.st_mtime_ns, info.st_size))
        except OSError:
            result.append((addon, None, None))
    return tuple(result)

def run():
    import xbmc
    import xbmcgui
    import xbmcvfs
    profile = os.path.normcase(os.path.realpath(xbmcvfs.translatePath('special://profile/')))
    prop = 'kodipovil.host_patch_watch.v2.' + hashlib.sha256(profile.encode('utf8')).hexdigest()
    window = xbmcgui.Window(10000)
    if window.getProperty(prop):
        return
    import uuid
    token = uuid.uuid4().hex
    window.setProperty(prop, token)
    monitor = xbmc.Monitor()
    addons = xbmcvfs.translatePath('special://home/addons/')
    previous = signature(addons)
    remembered, seen = read_skin_memory()
    fell_back = (remembered == AF3_ID and current_skin() == DEFAULT_SKIN and af3_updated_since(seen))
    if not af3_font_current(addons) or not af3_hooks_current(addons) or fell_back:
        # Kodi's start-up repository check updated AF3 alongside the build's
        # own start-up (QA: MoranSubs patched 3.4.4 a second before 3.4.6
        # replaced it) -- its files lack the font or the profile hooks, or
        # Kodi's fallback left a profile last seen on AF3 on Estuary. Treat AF3
        # as changed so the first settled poll repairs.
        previous = tuple((row[0], -1, -1) if row[0] == AF3_ID else row for row in previous)
    # A skin counts as the profile's only after SKIN_STABLE_POLLS polls with
    # nothing changing; any watched change starts the count again, so Kodi's
    # fallback during an AF3 install is never taken for a choice.
    skin_seen, skin_polls = '', 0
    pending = None
    retry_at = 0
    attempts = 0
    # Bytecode passes count idle 10 s polls: the first once start-up and the
    # home widgets have settled (~70 s), then about every 6 hours for Kodi's
    # own add-on updates, and soon after a host repair rewrote files.
    idle_polls, warm_after = 0, 6
    try:
        while not monitor.waitForAbort(10):
            current = signature(addons)
            if current == previous:
                pending = None
                attempts = 0
                idle_polls += 1
                skin = '' if af3_mid_install(addons) else current_skin()
                skin_polls = skin_polls + 1 if skin and skin == skin_seen else (1 if skin else 0)
                skin_seen = skin
                if skin and skin_polls >= SKIN_STABLE_POLLS and (
                        skin != remembered or time.time() - seen >= SKIN_REFRESH_SECONDS
                        or af3_updated_since(seen)):
                    remembered, seen = skin, time.time()
                    remember_skin(skin, seen)
                if idle_polls >= 3:
                    prebuild_lists()
                if idle_polls >= warm_after and not xbmc.Player().isPlayingVideo():
                    warm_bytecode(addons, monitor)
                    idle_polls, warm_after = 0, 6 * 360
                continue
            skin_seen, skin_polls = '', 0
            if xbmc.Player().isPlayingVideo():
                continue
            # Observe a stable install for two polls before touching it.
            if pending != current:
                pending = current
                attempts = 0
                retry_at = 0
                continue
            if time.monotonic() < retry_at:
                continue
            # A temporarily removed addon or partial write is not a completed update.
            removed = any(row[1] is None and previous[i][1] is not None
                          for i, row in enumerate(current))
            try:
                # The file, not this loop's copy: the Wizard's Switch Skin
                # writes it at once, and that choice must count right away.
                repaired = not removed and repair_changed(addons, previous, current, window, monitor,
                                                          previous_skin=read_skin_memory()[0] or remembered)
            except Exception:
                repaired = False
            if repaired and signature(addons) == current:
                previous = current
                pending = None
                attempts = 0
                # The host's files just changed: recompile them soon.
                idle_polls, warm_after = 0, min(warm_after, 3)
            else:
                attempts += 1
                # Fast recovery for a file lock, then bounded idle backoff for
                # an unsupported upstream change. Never mark failed work done.
                retry_at = time.monotonic() + (10 if attempts == 1 else 30 if attempts == 2 else 300)
                xbmc.log('[POV IL] Host-update repair pending; attempt {}'.format(attempts), xbmc.LOGWARNING)
    finally:
        if monitor.abortRequested():
            # Kodi's GUI thread waits for this interpreter during unload.
            # Window property getters acquire its GUI lock and can deadlock.
            # Queue cleanup without reading that lock; the key is profile-local.
            xbmc.executebuiltin('ClearProperty({},home)'.format(prop))
            resign_lists()
        elif window.getProperty(prop) == token:
            window.clearProperty(prop)
