# SPDX-License-Identifier: GPL-3.0-or-later (additional terms: LICENSE.txt)
"""The gender proofread asked again later, from the service (0.3.75).

Since 0.3.75 the proofread asks gemini-3.7-flash only (gender_proofread.MODELS).
3.7 is busy much of the day -- the field's answers came mostly 20:00-23:00
Israel time -- and a translation made on play is seldom opened again, so a
proofread that found it busy used to be lost. Such a translation waits here
instead; the service (translate.gp_later_tick) asks 3.7 again for one of them
at a time, spaced out: a 503 counts toward the day's 20 requests, so the queue
spends at most DAILY_CAP of them a day, GAP apart, each translation further
apart every time (FIRST_WAIT, doubling up to BACKOFF_MAX), for EXPIRE.

Bookkeeping only (no Kodi, no network): one JSON file,
{'entries': [...], 'day': quota day, 'sent': requests that day, 'last': time
of the last one}. An entry: 'path' (the Hebrew file to correct), 'marker'
(where its proofread markers hang), 'src' (a copy of the subtitle it was
translated from), 'copies' (other files holding the same translation),
'info' (the title), 'share' (where the pool keeps it, or None), 'ref_hash'
(the pooled variant's hash, for the Hebrew-reference rule), 'added',
'next', 'tries'.

The add-on's plugin interpreters add and the service takes, so every change
is a short load-change-save under a lock file (update); never across a
request."""
import contextlib
import json
import os
import threading
import time

# The first ask again: an hour after the proofread that found 3.7 busy.
FIRST_WAIT = 3600
# Each ask again doubles the wait, up to this.
BACKOFF_MAX = 8 * 3600
# Between any two requests the queue sends.
GAP = 30 * 60
# Requests the queue sends a quota day (of about 20 a day for 3.7 on a free
# key; the viewer's own proofreads keep the rest).
DAILY_CAP = 6
# A translation waits this long at most.
EXPIRE = 3 * 86400
# The oldest go first past this many.
MAX_ENTRIES = 20
# A proofread in-progress marker this fresh: an attempt for the same
# translation may be running now. The background job (proofread_later's)
# marks once at its start and can run 30 minutes of busy rounds plus one
# request of up to 15 minutes; a margin on top.
FRESH_TRY = 50 * 60
# A lock file older than this was left by a process that died.
LOCK_STALE = 30


def _empty():
    return {'entries': [], 'day': '', 'sent': 0, 'last': 0}


def load(path, today=None):
    """The queue's state: an empty one when there is no file. A file that
    cannot be parsed is moved aside (.bad) and the state that replaces it
    counts today's requests as spent -- an unknown count must not hand out
    six more (`today`: the quota day). Raises OSError when the file is there
    and cannot be read."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read()
    except FileNotFoundError:
        return _empty()
    try:
        state = json.loads(raw)
        if not (isinstance(state, dict) and isinstance(state.get('entries'), list)):
            raise ValueError('not a queue')
        state['entries'] = [e for e in state['entries']
                            if isinstance(e, dict) and e.get('marker') and e.get('path')]
        return state
    except Exception:
        try:
            os.replace(path, path + '.bad')
        except OSError:
            pass
        state = _empty()
        state.update(day=today or '', sent=DAILY_CAP, last=time.time(), recovered=True)
        return state


def save(path, state):
    """Written whole and swapped in, so a reader never sees half a file; a
    temporary name of its own per writer; the swap retried while another
    process (a virus scanner) holds the file."""
    state.pop('recovered', None)
    tmp = '{0}.{1}.{2}.tmp'.format(path, os.getpid(), threading.get_ident())
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 5:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.2)


@contextlib.contextmanager
def locked(path, wait=5.0):
    """The queue's lock (an exclusive lock file beside it), waited for up to
    `wait` seconds; TimeoutError when another holder keeps it. A stale lock
    is renamed away before it goes, so of two waiters only one breaks it; on
    Windows a lock file still being deleted refuses with PermissionError, a
    wait like any other."""
    lock = path + '.lock'
    end = time.time() + wait
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):
            try:
                if time.time() - os.path.getmtime(lock) > LOCK_STALE:
                    gone = '{0}.{1}.{2}.stale'.format(lock, os.getpid(), threading.get_ident())
                    os.rename(lock, gone)
                    os.remove(gone)
                    continue
            except OSError:
                pass
            if time.time() > end:
                raise TimeoutError('the proofread queue is locked')
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def update(path, change, today=None):
    """Under the lock: load, `change(state)` -> (result, changed), save when
    it changed (or the file had to be recovered). Returns the result."""
    with locked(path):
        state = load(path, today)
        result, changed = change(state)
        if changed or state.get('recovered'):
            save(path, state)
        return result


def find(state, marker):
    return next((e for e in state.get('entries') or [] if e.get('marker') == marker), None)


def add(state, entry, now=None):
    """Queue `entry` (one per marker: a newer one replaces it, its first wait
    from now). Returns the entries pushed out by MAX_ENTRIES."""
    now = time.time() if now is None else now
    entry = dict(entry, added=now, next=now + FIRST_WAIT, tries=0)
    entries = [e for e in state.get('entries') or [] if e.get('marker') != entry['marker']]
    entries.append(entry)
    entries.sort(key=lambda e: e.get('added') or 0)
    dropped = entries[:-MAX_ENTRIES] if len(entries) > MAX_ENTRIES else []
    state['entries'] = entries[len(dropped):]
    return dropped


def remove(state, marker):
    """Takes the entry out; returns it (None when it was not there)."""
    entry = find(state, marker)
    if entry is not None:
        state['entries'] = [e for e in state['entries'] if e is not entry]
    return entry


def prune(state, now, alive):
    """Drops the entries past EXPIRE or no longer `alive(entry)`; returns them."""
    keep, dropped = [], []
    for e in state.get('entries') or []:
        try:
            ok = now - (e.get('added') or 0) < EXPIRE and alive(e)
        except Exception:
            ok = False
        (keep if ok else dropped).append(e)
    state['entries'] = keep
    return dropped


def _day(state, today):
    if state.get('day') != today:
        state['day'], state['sent'] = today, 0


def can_send(state, now, today):
    """Today's DAILY_CAP not spent and the last request GAP behind."""
    _day(state, today)
    return (state.get('sent') or 0) < DAILY_CAP and now - (state.get('last') or 0) >= GAP


def due(state, now, today):
    """The entry to ask for now: the one waiting longest past its time, when
    can_send; else None."""
    if not can_send(state, now, today):
        return None
    ready = [e for e in state.get('entries') or [] if (e.get('next') or 0) <= now]
    return min(ready, key=lambda e: e.get('next') or 0) if ready else None


def hold(entry, now, secs=GAP):
    """Not before `secs` from now (an attempt for it running elsewhere)."""
    entry['next'] = max(entry.get('next') or 0, now + secs)


def note_sent(state, now, today):
    """A request goes out: it counts toward today's cap and the gap."""
    _day(state, today)
    state['sent'] = (state.get('sent') or 0) + 1
    state['last'] = now


def claim(state, entry, now, today):
    """About to ask for `entry`. The request counts now -- Google counts it
    when it is sent, and a crash, an update or a failed save mid-request must
    not let the next one through early -- and the entry waits as if it found
    no answer (retry_later's time) until the outcome says otherwise."""
    note_sent(state, now, today)
    entry['next'] = max(entry.get('next') or 0,
                        now + min(FIRST_WAIT * (2 ** ((entry.get('tries') or 0) + 1)), BACKOFF_MAX))


def refund(state, today):
    """Nothing went out after all (claim counted one)."""
    if state.get('day') == today and (state.get('sent') or 0) > 0:
        state['sent'] -= 1


def retry_later(entry, now):
    """No answer again: the next ask further off (doubling, BACKOFF_MAX)."""
    entry['tries'] = (entry.get('tries') or 0) + 1
    entry['next'] = now + min(FIRST_WAIT * (2 ** entry['tries']), BACKOFF_MAX)
