"""Keep Kodi's add-on package cache from filling a small device, and say so in
Hebrew when the device is nearly full anyway.

Field log, 24 Oct 2026 (LG webOS TV): "No space left on device". The
MoranSubs and Wizard updates and the Arctic Fuse 3 update all failed, Kodi's
own database reported "disk is full", and POV answered every search with no
results. Kodi keeps the zip of every version it installs in addons/packages:
the QA Kodi had 820 MB there, six Arctic Fuse 3 zips alone about 360 MB.

At start-up, before the update check, this keeps per add-on only the newest
zip and the one of the installed version, and drops our own update downloads
an interrupted run left behind. If free space is still low, a Hebrew
notification says where to free more -- once a day, or at once when a Wizard
update fails for lack of space.

A trade-off, on purpose: Kodi lists the zips in addons/packages as rollback
versions (its own pruning keeps two per add-on). Here only the installed and
the newest stay; older versions come from the repository, if it still has
them. A build whose versions are set by the Wizard's manifest needs the room
more than the rollback.
"""
import os
import re
import shutil
import time

import xbmc
import xbmcgui

from resources.libs.common import logging
from resources.libs.common.config import CONFIG

_ZIP = re.compile(r'^(?P<id>[A-Za-z0-9._]+(?:-[A-Za-z][A-Za-z0-9._]*)*)'
                  r'-(?P<ver>\d[0-9A-Za-z.+~_-]*)\.zip$')
_ADDON_VERSION = re.compile(r'<addon\b[^>]*?\bversion="([^"]+)"', re.S)
_STALE_DOWNLOAD_S = 3600
LOW_BYTES = 200 * 1024 * 1024
_WARN_SETTING = 'storage_low_warned'
_WARN_EVERY_S = 24 * 3600
_warned_this_session = []


def _version_key(version):
    """'3.4.10' > '3.4.8', '1.2.1' > '1.2.0a'; numbers before letters."""
    return [(0, int(p)) if p.isdigit() else (1, p.lower())
            for p in re.findall(r'\d+|[A-Za-z]+', version or '')]


def _installed_version(addons_dir, addon_id):
    try:
        with open(os.path.join(addons_dir, addon_id, 'addon.xml'),
                  encoding='utf-8', errors='replace') as f:
            match = _ADDON_VERSION.search(f.read(4096))
        return match.group(1) if match else None
    except (OSError, ValueError):
        return None


def prune_packages(packages_dir, addons_dir, now=None):
    """Delete old add-on zips; return (files removed, bytes freed).

    Kept per add-on: the newest version, and the installed version's zip (a
    newer one may be an update that failed to unpack). A zip written in the
    last hour is never touched: Kodi's own repository update can be writing
    it right now, and our version order is not Kodi's in every corner
    ("1.0.0~beta1"). A name that is not "<add-on id>-<version>.zip" is left
    alone, except our own "<id>_update.zip" downloads once they are an hour
    old."""
    now = time.time() if now is None else now
    try:
        names = os.listdir(packages_dir)
    except OSError:
        return 0, 0
    groups = {}
    doomed = []
    for name in names:
        path = os.path.join(packages_dir, name)
        if not os.path.isfile(path):
            continue
        match = _ZIP.match(name)
        if match:
            groups.setdefault(match.group('id'), []).append(
                (match.group('ver'), path))
        elif name.endswith('_update.zip'):
            try:
                if now - os.path.getmtime(path) > _STALE_DOWNLOAD_S:
                    doomed.append(path)
            except OSError:
                pass
    for addon_id, versions in groups.items():
        if len(versions) < 2:
            continue
        versions.sort(key=lambda item: _version_key(item[0]))
        keep = {versions[-1][1]}
        installed = _installed_version(addons_dir, addon_id)
        keep.update(path for ver, path in versions if ver == installed)
        doomed.extend(path for _ver, path in versions
                      if path not in keep and not _recent(path, now))
    removed = freed = 0
    for path in doomed:
        try:
            size = os.path.getsize(path)
            os.remove(path)
            removed += 1
            freed += size
        except OSError:
            pass
    return removed, freed


def _recent(path, now):
    try:
        return now - os.path.getmtime(path) <= _STALE_DOWNLOAD_S
    except OSError:
        return True


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except (OSError, AttributeError, ValueError):
        return None


def _megabytes(count):
    return int(round(count / (1024.0 * 1024.0)))


def warn(free=None, force=False):
    """The Hebrew notice; once a day, or now when an update just failed.

    At start-up a dialog: a notification is one scrolling line in the build's
    skins, and this one has to be read. Three lines, each short enough not to
    wrap: the build's OK dialog cuts a fourth line in half (QA Kodi). After a
    failed update -- which may run while something plays -- a short
    notification only. Only the dialog sets the daily stamp: a toast after
    every failed start would otherwise keep the dialog, which says what to
    do, from ever coming back."""
    if force and _warned_this_session:
        return False
    if not force:
        try:
            last = float(CONFIG.get_setting(_WARN_SETTING) or 0)
        except (TypeError, ValueError):
            last = 0.0
        now = time.time()
        if 0 <= now - last < _WARN_EVERY_S:      # a future stamp: clock was off
            return False
        try:
            if xbmc.Player().isPlaying():           # not over a film; next start
                return False
        except Exception:
            pass
    try:
        if force:
            xbmcgui.Dialog().notification(
                CONFIG.ADDONTITLE, 'העדכון נכשל: אין מקום פנוי במכשיר', time=8000)
        else:
            left = ' (נשארו {0}MB)'.format(_megabytes(free)) if free is not None else ''
            xbmcgui.Dialog().ok(
                CONFIG.ADDONTITLE,
                'כמעט אין מקום פנוי במכשיר{0}.\n'
                'כשאין מקום, עדכונים נכשלים ו-POV עלול להחזיר "אין תוצאות".\n'
                'לפינוי מקום: בוויזארד, תחזוקה, Cleaning Tools ואז Clear Packages.'.format(left))
    except Exception:
        return False
    _warned_this_session.append(True)
    if not force:
        CONFIG.set_setting(_WARN_SETTING, str(int(time.time())))
    return True


def run_at_startup():
    removed, freed = prune_packages(CONFIG.PACKAGES, CONFIG.ADDONS)
    if removed:
        logging.log('[Storage] removed {0} old add-on package(s), {1} MB freed'
                    .format(removed, _megabytes(freed)), level=xbmc.LOGINFO)
    free = free_bytes(CONFIG.HOME)
    if free is not None and free < LOW_BYTES:
        logging.log('[Storage] only {0} MB free on the device'.format(
            _megabytes(free)), level=xbmc.LOGWARNING)
        warn(free)
    return removed, freed, free


def note_failure(exc):
    """Called where an update failed: out of space -> the notice now."""
    if getattr(exc, 'errno', None) == 28 or 'No space left' in str(exc):
        warn(free_bytes(CONFIG.HOME), force=True)
        return True
    return False
