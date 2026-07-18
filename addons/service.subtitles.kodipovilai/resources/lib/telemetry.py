# Anonymous, best-effort usage telemetry for AI translations -> the POV pool
# Worker. Owner-only dashboard lives at the Worker's /stats.
#
# Privacy: the ONLY identifier sent is a random per-install id (a uuid stored in
# a hidden setting). No account, no IP (beyond what any HTTPS request exposes to
# Cloudflare), no file paths. The payload is: anonymous id, add-on version,
# media type + title + season/episode/year, source language, the translation
# METHOD (ai_ar / ai_fallback / ai_plain), success, and a few diagnostics.
#
# --- Batching (to stay under Cloudflare's free 100k-requests/day cap) ----------
# One AI translation used to cost its OWN POST /ev on a daemon thread. Now events
# are QUEUED (persisted to a small file so they survive the short-lived subtitle
# process) and delivered WITHOUT a dedicated request in the common case:
#   * pool._post() drains the queue and PIGGYBACKS the events onto the
#     /contribute it already sends after a shared translation -> ZERO extra
#     requests, and the dashboard still sees them promptly.
#   * whatever isn't carried by a contribute (failures, pool-share off, dedup
#     short-circuits) is flushed in ONE batched POST /ev per _FLUSH_N events (or
#     when the oldest waits _FLUSH_AGE), so N translations cost 1 request, not N.
# Each event carries a client `ts` so the dashboard's time buckets stay accurate
# despite the delay (the Worker sanitises/clamps it). Fully guarded and
# fire-and-forget: telemetry NEVER blocks the translation and NEVER raises into
# the caller. If the Worker has no /ev yet, the POST just 404s and is ignored.
import json
import os
import threading
import time

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

ADDON_ID = 'service.subtitles.kodipovilai'

# Queue tuning. Small numbers: a real user makes a handful of translations, and
# the pool-share piggyback carries most events with no /ev at all.
_QUEUE_MAX = 200        # hard cap on queued events (drop OLDEST past this)
_FLUSH_N = 6            # flush a batched /ev once this many events are waiting
_FLUSH_AGE = 600        # ...or once the oldest has waited this long (seconds)
_BATCH_MAX = 40         # max events per POST (the Worker caps at 50 regardless)
PIGGYBACK_MAX = 20      # max events pool._post() attaches to one /contribute

_LOCK = threading.Lock()


def _addon_version():
    try:
        return xbmcaddon.Addon(ADDON_ID).getAddonInfo('version') or ''
    except Exception:
        return ''


def _anon_id():
    """A stable, anonymous per-install id. Created once and stored in a hidden
    setting. Read/written on the CALLING thread (Kodi setting writes off-thread
    are unreliable)."""
    try:
        from resources.lib import kodi_utils
        v = (kodi_utils.get_setting('_telemetry_id', '') or '').strip()
        if not v:
            import uuid
            v = uuid.uuid4().hex
            kodi_utils.set_setting('_telemetry_id', v)
        return v
    except Exception:
        return ''


# --- Persisted queue --------------------------------------------------------
# A JSON list of pending events in a file next to the add-on's other data, so a
# short-lived subtitle process doesn't lose an event before it's delivered. All
# read-modify-write is serialised by _LOCK; the write is atomic (temp + replace)
# so a crash mid-write can never corrupt the queue. Everything is fail-open.

def _qpath():
    try:
        from resources.lib import kodi_utils
        return os.path.join(kodi_utils.addon_profile_path(), 'ev_queue.json')
    except Exception:
        return None


def _load():
    try:
        p = _qpath()
        if not p or not os.path.isfile(p):
            return []
        with open(p, 'r') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(lst):
    try:
        p = _qpath()
        if not p:
            return
        tmp = p + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(lst, f)
        os.replace(tmp, p)
    except Exception:
        pass  # persistence is best-effort; a lost/duplicated event is harmless


def _enqueue(ev):
    with _LOCK:
        lst = _load()
        lst.append(ev)
        if len(lst) > _QUEUE_MAX:
            lst = lst[-_QUEUE_MAX:]          # keep the NEWEST, drop the oldest
        _save(lst)


def drain_batch(max_n):
    """Pop up to max_n oldest events off the queue (removing them) and return
    them. Called by pool._post() to piggyback telemetry onto a /contribute it is
    already sending. Returns [] on empty/error."""
    try:
        n = int(max_n)
    except Exception:
        return []
    if n <= 0:
        return []
    with _LOCK:
        lst = _load()
        if not lst:
            return []
        take = lst[:n]
        _save(lst[n:])
        return take


def restore(events):
    """Re-queue events whose delivery could not be confirmed (a transport error,
    NOT an HTTP response). Prepended so they keep their place near the front."""
    if not events:
        return
    with _LOCK:
        lst = list(events) + _load()
        if len(lst) > _QUEUE_MAX:
            lst = lst[-_QUEUE_MAX:]
        _save(lst)


# HTTP codes the Worker returns BEFORE recording (auth/version/precondition) or
# on an internal error -> the batch was NOT stored, so requeue it. Any other
# response (2xx, or an app-level 4xx from after the body was read) == stored.
_EV_REQUEUE_CODES = (401, 403, 426, 500, 503)


def _post_events(batch):
    """POST a batch of events to /ev. Delivered == a clean 2xx OR an HTTP response
    whose code is NOT an auth/version/precondition/server-error reject (the Worker
    reads the body and records the events before any of those app-level answers).
    An auth reject (esp. 426 for an out-of-date install), a 500, or a transport
    failure means the batch was NOT recorded -> restore it for next time."""
    try:
        import urllib.request
        from resources.lib import pool
        data = json.dumps({'events': batch}).encode('utf-8')
        headers = {'content-type': 'application/json',
                   'user-agent': 'Mozilla/5.0'}
        headers.update(pool.sign_headers('POST', '/ev'))
        req = urllib.request.Request(
            pool.POOL_URL + '/ev', data=data, headers=headers)
        urllib.request.urlopen(req, timeout=10).read()
        return  # clean 2xx -> delivered
    except Exception as e:
        code = getattr(e, 'code', None)  # HTTPError has .code; transport errors don't
        try:
            from urllib.error import HTTPError
            is_http = isinstance(e, HTTPError)
        except Exception:
            is_http = False
        delivered = is_http and code not in _EV_REQUEUE_CODES
        if not delivered:
            try:
                restore(batch)  # not recorded -> keep for next time
            except Exception:
                pass


def _maybe_flush():
    """If enough events are waiting (or the oldest has waited long enough), pop a
    batch and send it in ONE /ev on a daemon thread. Most events never reach here
    -- pool._post() carries them on a /contribute first."""
    batch = None
    try:
        with _LOCK:
            lst = _load()
            if not lst:
                return
            oldest_ts = 0
            try:
                oldest_ts = int(lst[0].get('ts') or 0)
            except Exception:
                oldest_ts = 0
            aged = oldest_ts and (int(time.time()) - oldest_ts) >= _FLUSH_AGE
            if len(lst) < _FLUSH_N and not aged:
                return
            batch = lst[:_BATCH_MAX]
            _save(lst[_BATCH_MAX:])
    except Exception:
        return
    if batch:
        try:
            threading.Thread(target=_post_events, args=(batch,),
                             daemon=True).start()
        except Exception:
            try:
                restore(batch)  # couldn't even start the thread -> requeue
            except Exception:
                pass


def report(event):
    """Record one usage event. Best-effort, non-blocking, never raises. The event
    is queued (and stamped with a client ts + this install's id/version); it ships
    later on the next /contribute piggyback or a batched /ev flush."""
    try:
        event = dict(event or {})
        event['anon'] = _anon_id()
        event['v'] = _addon_version()
        event['ts'] = int(time.time())
    except Exception:
        return
    try:
        _enqueue(event)
    except Exception:
        return
    try:
        _maybe_flush()
    except Exception:
        pass
