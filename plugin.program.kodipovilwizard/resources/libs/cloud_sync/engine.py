"""One round of the device-to-device sync, and the service loop that runs it (Wizard, cloud_sync).

A round: read POV's and Umbrella's lists (stores.py); find what changed on this device since the map it last saw
(records.changes); look at the viewer's file in Drive (5 units) and read it only when it changed since this device
last read it (200); merge; write to the lists what they lack; upload the map when this device added anything (50).

Kept on the device, in the Wizard's addon_data/cloud_sync (never in a log): tokens.json (the viewer's Drive
access), state.json (the file's id and checksum), base.json (the map this device last saw), remote.json (the map
the file held then). A lock file keeps two rounds from running at once (the service, and a "sync now" from the
settings tile run in another interpreter).
"""
import json
import os
import time

from . import records

LOCK_STALE_S = 180
FIND_EVERY_MS = 86400 * 1000        # once a day the file is looked for again: two devices may each have made one
FIRST_WAIT_S = 25           # after Kodi starts: its own services first
EVERY_S = 10 * 60           # a round this often while Kodi runs
AFTER_PLAYBACK_S = 30       # and this long after a playback ends (its place, its watched mark)


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _write_json(path, value):
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(value, handle, separators=(',', ':'))
    os.replace(temp, path)


class Folder(object):
    """The sync's files on this device."""

    def __init__(self, path):
        self.path = path

    def file(self, name):
        return os.path.join(self.path, name)

    def tokens(self):
        tokens = _read_json(self.file('tokens.json'), None)
        return tokens if isinstance(tokens, dict) and tokens.get('refresh_token') else None

    def save_tokens(self, tokens):
        os.makedirs(self.path, exist_ok=True)
        _write_json(self.file('tokens.json'), tokens)

    def disconnect(self):
        """This device only: its access, and what it knew of the file (the viewer's other devices stay connected)."""
        for name in ('tokens.json', 'state.json', 'base.json', 'remote.json', 'copied.json'):
            try:
                os.remove(self.file(name))
            except OSError:
                pass

    def state(self):
        state = _read_json(self.file('state.json'), {})
        return state if isinstance(state, dict) else {}

    def maps(self):
        return (records.clean(_read_json(self.file('base.json'), {})), records.clean(_read_json(self.file('remote.json'), {})))

    def save(self, state, base, remote):
        os.makedirs(self.path, exist_ok=True)
        _write_json(self.file('base.json'), base)
        _write_json(self.file('remote.json'), remote)
        _write_json(self.file('state.json'), state)

    def copied(self):
        """What the Trakt / MDBList copy last wrote into POV's watched.db (stores.mirror_pov)."""
        copied = _read_json(self.file('copied.json'), {})
        return copied if isinstance(copied, dict) else {}

    def save_copied(self, copied):
        os.makedirs(self.path, exist_ok=True)
        _write_json(self.file('copied.json'), copied)

    def lock(self, clock=time.time):
        """True when this round may run (no other round holds the lock, or the one that did is long gone)."""
        os.makedirs(self.path, exist_ok=True)
        path = self.file('round.lock')
        try:
            if clock() - os.path.getmtime(path) > LOCK_STALE_S:
                os.remove(path)
        except OSError:
            pass
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except OSError:
            return False

    def unlock(self):
        try:
            os.remove(self.file('round.lock'))
        except OSError:
            pass


def clean_copied(copied):
    from .records import KEY, clean_value
    return {key: clean_value(value) or {} for key, value in copied.items() if isinstance(key, str) and KEY.match(key)}


def sync_round(folder, stores, drive, now_ms):
    """One round. Returns {'put', 'removed', 'uploaded', 'records', 'skipped'} (counts); raises the Drive's errors."""
    state = folder.state()
    base, remote = folder.maps()
    if stores.pov_dir and stores.pov_indicators in (1, 2):
        from .stores import mirror_pov
        copied, _done = mirror_pov(stores.pov_dir, stores.pov_indicators, clean_copied(folder.copied()))
        folder.save_copied(copied)
    values, skipped = stores.read()
    local = records.changes(base, values, now_ms, stores.mine)
    local, held = records.hold_resets(base, local)
    file_id, found_at = state.get('file_id'), state.get('found', 0)
    meta, extra = (drive.look(file_id) if file_id else None), []
    if meta is None or now_ms - found_at > FIND_EVERY_MS:
        # the first round, a file the viewer deleted, and once a day: every file of the build's, the latest kept
        files = drive.find_all()
        meta, extra, found_at = (files[0] if files else None), files[1:], now_ms
        file_id = meta['id'] if meta else None
    md5 = meta.get('md5Checksum') if meta else None
    if file_id and md5 != state.get('md5'):
        remote = records.loads(drive.download(file_id))
    elif not file_id:
        remote = {}
    for other in extra:
        remote = records.merge(remote, records.loads(drive.download(other['id'])))
    remote, future = records.from_the_future(remote, now_ms)
    if not base and remote:
        local = records.first_connect(local, remote)
    merged = records.forget_old(records.merge(remote, local), now_ms)
    put, remove = records.to_apply(merged, values, stores.mine)
    if put or remove:
        stores.write(put, remove, values)
        values, _ = stores.read()
    uploaded = False
    if (merged != remote or extra or future) and (merged or file_id):
        meta = drive.upload(records.dumps(merged), file_id)
        file_id, md5, uploaded = meta.get('id', file_id), meta.get('md5Checksum'), True
    for other in extra:
        drive.delete(other['id'])
    # what the device could not take (an add-on's file it could not write) is left out of what it saw: it is asked
    # again next round, never taken for a removal
    seen = {key: rec for key, rec in merged.items() if rec.get('d') or key in values or not stores.mine(key)}
    folder.save({'file_id': file_id, 'md5': md5, 'last': now_ms, 'found': found_at}, seen, merged)
    return {'put': len(put), 'removed': len(remove), 'uploaded': uploaded, 'records': sum(1 for r in merged.values() if not r.get('d')),
            'skipped': skipped, 'held': held, 'merged_files': len(extra), 'future': future, 'unreadable': sorted(stores.broken)}


# ------------------------------------------------------------------ inside Kodi
def kodi_parts():
    """(folder, stores) of this Kodi profile."""
    import xbmc
    import xbmcaddon
    import xbmcvfs
    from .stores import Stores
    data = xbmcvfs.translatePath('special://profile/addon_data/')
    indicators = 0
    if xbmc.getCondVisibility('System.HasAddon(plugin.video.pov)'):
        try:
            # where POV keeps its watched marks: 0 itself, 1 Trakt, 2 MDBList (stores.mirror_pov)
            indicators = int(xbmcaddon.Addon('plugin.video.pov').getSetting('watched_indicators') or 0)
        except (RuntimeError, ValueError):
            indicators = 0
    return (Folder(os.path.join(data, 'plugin.program.kodipovilwizard', 'cloud_sync')),
            Stores(os.path.join(data, 'plugin.video.pov'), os.path.join(data, 'plugin.video.umbrella'), indicators))


def make_drive(folder):
    from . import config
    from .drive import Drive
    tokens = folder.tokens()
    if not tokens or not config.ready():
        return None
    return Drive(config.CLIENT_ID, config.CLIENT_SECRET, tokens, save=folder.save_tokens)


def run_once(log, why='round'):
    """A round, if this device is connected and no other round runs. The summary, or None."""
    import xbmcgui
    from .drive import Disconnected, DriveError
    folder, stores = kodi_parts()
    drive = make_drive(folder)
    if drive is None or not folder.lock():
        return None
    try:
        summary = sync_round(folder, stores, drive, int(time.time() * 1000))
    except Disconnected:
        log('the viewer\'s Google access ended: this device is no longer connected')
        folder.disconnect()
        return None
    except DriveError as exc:
        log('%s: Drive did not answer (%s)' % (why, exc.status))
        return None
    except Exception as exc:
        log('%s failed: %s' % (why, type(exc).__name__))
        return None
    finally:
        folder.unlock()
    units = sum(u for _m, u in drive.calls)
    log('%s: %d written here, %d removed here, %s, %d items, %d quota units' % (
        why, summary['put'], summary['removed'], 'uploaded' if summary['uploaded'] else 'nothing to upload', summary['records'], units))
    for name, count in summary['held'].items():
        log('%s: %s looked reset here (%d gone at once): filled again from the other devices, nothing removed' % (why, name, count))
    if summary['merged_files']:
        log('%s: %d more file(s) of the build in the viewer\'s Drive merged into one' % (why, summary['merged_files']))
    if summary['future']:
        log('%s: %d record(s) dated over a day ahead of this clock taken as made now' % (why, summary['future']))
    if summary['unreadable']:
        log('%s: left out, could not be read here: %s' % (why, ', '.join(summary['unreadable'])))
    if summary['put'] or summary['removed']:
        # the home's rows and POV's lists read their lists again
        xbmcgui.Window(10000).setProperty('povil.lists.t', str(int(time.time())))
    return summary


class Schedule(object):
    """When the next round runs. The owner, Nov 2026, on the quota: "a viewer who starts a few films a day ... and has
    five more devices at home -- isn't that a lot?" -- the expensive part is every other device reading each change.
    So: a round soon after start; one AFTER_PLAYBACK_S after a film or an episode ends (its place, its watched mark),
    never during one (POV keeps the place on the device every minute, and it is sent when the playback ends -- or,
    if Kodi was switched off mid-way, at its next start); every EVERY_S while someone uses the device; none while it
    stands idle (nobody touched the remote for IDLE_S), and one at once when someone comes back to it."""

    def __init__(self, now):
        self.due, self.urgent, self.away, self.trailer = now + FIRST_WAIT_S, True, False, False

    def started(self, trailer):
        self.trailer = trailer          # (the home's trailer is a playback too: its end sends nothing)

    def ended(self, now):
        if not self.trailer:
            # (not sooner: POV writes the place and the watched mark in the seconds after the stop)
            self.due, self.urgent = now + AFTER_PLAYBACK_S, True
        self.trailer = False

    def ready(self, now, idle, watching):
        """True when a round runs now."""
        if idle >= IDLE_S:
            self.away = True
        elif self.away and idle < 30:
            self.away = False
            self.due, self.urgent = min(self.due, now), True         # back at the device: its lists fresh now
        if now < self.due:
            return False
        if watching:
            self.due = now + 60
            return False
        urgent, self.urgent = self.urgent, False
        self.due = now + EVERY_S
        return urgent or not self.away


IDLE_S = 20 * 60


def watch():
    """The Wizard's start-up service runs this as one of its threads (see Schedule). Nothing at all while the device
    is not connected."""
    import xbmc
    import xbmcgui

    def log(text):
        xbmc.log('[POV IL sync] %s' % text, xbmc.LOGINFO)

    monitor = xbmc.Monitor()
    home = xbmcgui.Window(10000)
    schedule = Schedule(time.time())

    class Player(xbmc.Player):
        def onAVStarted(self):
            schedule.started(bool(home.getProperty('povil.tr.on')))

        def onPlayBackStopped(self):
            schedule.ended(time.time())

        def onPlayBackEnded(self):
            schedule.ended(time.time())

    player = Player()
    while not monitor.abortRequested():
        if monitor.waitForAbort(5):
            break
        watching = xbmc.getCondVisibility('Player.HasVideo') and not home.getProperty('povil.tr.on')
        if not schedule.ready(time.time(), xbmc.getGlobalIdleTime(), watching):
            continue
        folder, _stores = kodi_parts()
        if folder.tokens() is None:
            continue
        run_once(log)
    del player
