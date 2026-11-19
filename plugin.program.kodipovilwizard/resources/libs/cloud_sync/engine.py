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
        for name in ('tokens.json', 'state.json', 'base.json', 'remote.json'):
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


def sync_round(folder, stores, drive, now_ms):
    """One round. Returns {'put', 'removed', 'uploaded', 'records', 'skipped'} (counts); raises the Drive's errors."""
    state = folder.state()
    base, remote = folder.maps()
    values, skipped = stores.read()
    local = records.changes(base, values, now_ms, stores.mine)
    file_id, md5 = state.get('file_id'), None
    meta = drive.look(file_id) if file_id else None
    if meta is None:
        meta = drive.find()
        file_id = meta['id'] if meta else None
    md5 = meta.get('md5Checksum') if meta else None
    if file_id and md5 != state.get('md5'):
        remote = records.loads(drive.download(file_id))
    elif not file_id:
        remote = {}
    merged = records.forget_old(records.merge(remote, local), now_ms)
    put, remove = records.to_apply(merged, values, stores.mine)
    if put or remove:
        stores.write(put, remove, values)
        values, _ = stores.read()
    uploaded = False
    if merged != remote and (merged or file_id):
        meta = drive.upload(records.dumps(merged), file_id)
        file_id, md5, uploaded = meta.get('id', file_id), meta.get('md5Checksum'), True
    # what the device could not take (an add-on's file it could not write) is left out of what it saw: it is asked
    # again next round, never taken for a removal
    seen = {key: rec for key, rec in merged.items() if rec.get('d') or key in values or not stores.mine(key)}
    folder.save({'file_id': file_id, 'md5': md5, 'last': now_ms}, seen, merged)
    return {'put': len(put), 'removed': len(remove), 'uploaded': uploaded, 'records': sum(1 for r in merged.values() if not r.get('d')),
            'skipped': skipped}


# ------------------------------------------------------------------ inside Kodi
def kodi_parts():
    """(folder, stores) of this Kodi profile."""
    import xbmcvfs
    from .stores import Stores
    data = xbmcvfs.translatePath('special://profile/addon_data/')
    return (Folder(os.path.join(data, 'plugin.program.kodipovilwizard', 'cloud_sync')),
            Stores(os.path.join(data, 'plugin.video.pov'), os.path.join(data, 'plugin.video.umbrella')))


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
    if summary['put'] or summary['removed']:
        # the home's rows and POV's lists read their lists again
        xbmcgui.Window(10000).setProperty('povil.lists.t', str(int(time.time())))
    return summary


def watch():
    """The Wizard's start-up service runs this as one of its threads: a round soon after start, every EVERY_S, and
    AFTER_PLAYBACK_S after a playback ends. Nothing at all while the device is not connected."""
    import xbmc

    def log(text):
        xbmc.log('[POV IL sync] %s' % text, xbmc.LOGINFO)

    monitor = xbmc.Monitor()
    due = [time.time() + FIRST_WAIT_S]

    class Player(xbmc.Player):
        def onPlayBackStopped(self):
            due[0] = min(due[0], time.time() + AFTER_PLAYBACK_S)

        def onPlayBackEnded(self):
            self.onPlayBackStopped()

    player = Player()
    while not monitor.abortRequested():
        if monitor.waitForAbort(5):
            break
        if time.time() < due[0]:
            continue
        due[0] = time.time() + EVERY_S
        folder, _stores = kodi_parts()
        if folder.tokens() is None:
            continue
        run_once(log)
    del player
