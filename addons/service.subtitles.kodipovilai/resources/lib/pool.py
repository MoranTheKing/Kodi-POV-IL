# Community AI-subtitle pool client (Kodi POV IL).
#
# Talks to the Cloudflare Worker that fronts the Telegram channel + KV index.
# Lets the add-on PULL Hebrew translations other users already made and PUSH
# the ones it makes. Everything here is best-effort and gated by two settings
# (pool_use / pool_share, both OFF by default): any failure degrades to "just
# translate locally", and the network calls never block playback.

import json
import os
import threading
import time

from resources.lib import kodi_utils

try:
    import urllib.request as _urlreq
    import urllib.parse as _urlparse
except ImportError:        # pragma: no cover
    _urlreq = None
    _urlparse = None

POOL_URL = 'https://povil-subs-pool.moran200333.workers.dev'
POOL_API_KEY = 'povil_x8FayxrUOAS9Qew1sFWzO6UgAnEAgJAG'

import hmac as _hmac
import hashlib as _hashlib

# Build-time pool credential (set during packaging). Fails closed if un-set.
# __POOL_KEY_BEGIN__
def _pool_key():
    return ''
# __POOL_KEY_END__


def _anon_id():
    """Stable anonymous per-install id (shared with telemetry)."""
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


def _addon_version():
    try:
        import xbmcaddon
        return xbmcaddon.Addon(
            'service.subtitles.kodipovilai').getAddonInfo('version') or ''
    except Exception:
        return ''


def sign_headers(method, path):
    """Return the request headers the Worker expects."""
    anon = _anon_id()
    try:
        msg = (method.upper() + '\n' + path + '\n' + anon).encode('utf-8')
        sig = _hmac.new(_pool_key().encode('utf-8'), msg,
                        _hashlib.sha256).hexdigest()
    except Exception:
        sig = ''
    return {'x-pov-sig': sig, 'x-pov-anon': anon, 'x-pov-v': _addon_version()}


def _post_headers(path):
    """Headers for a signed POST to `path`."""
    h = {'content-type': 'application/json', 'user-agent': _UA}
    h.update(sign_headers('POST', path))
    return h

# Cloudflare's browser-integrity check rejects plain urllib requests (HTTP
# 1010); a normal browser UA passes. Harmless for our own Worker.
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
_GET_TIMEOUT = 8
_POST_TIMEOUT = 25
# Seconds to wait between bulk-migration uploads. Each contribution is two
# channel messages (poster + document); Telegram allows ~20/min to a channel,
# so ~6s/contribution keeps the bulk run comfortably under the limit.
_BULK_THROTTLE_SEC = 6.0


def use_enabled():
    """Pull from the pool before translating? (default off)"""
    return kodi_utils.get_bool('pool_use', False)


def share_enabled():
    """Push fresh translations to the pool? (default off)"""
    return kodi_utils.get_bool('pool_share', False)


def _is_token_like(s):
    """A debrid URL / token / bare UUID is NOT a usable release name."""
    import re as _re
    s = (s or '').strip()
    low = s.lower()
    if not s:
        return True
    if 'token=' in low or '://' in low or '?' in low or '&' in low:
        return True
    if _re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                     r'[0-9a-f]{4}-[0-9a-f]{12}', low):
        return True
    if (len(s) >= 24 and '.' not in s and ' ' not in s
            and _re.fullmatch(r'[0-9a-f-]+', low)):
        return True
    return False


def _release_from(info):
    # Prefer real release names; never share a debrid URL/token as the release
    # (that's what produced the garbage "...?token=..." names in the pool).
    for key in ('release', 'filename', 'picked_release', 'tagline', 'label'):
        rel = (info.get(key) or '').strip()
        if rel and not _is_token_like(rel):
            return rel
    fp = info.get('filepath') or ''
    base = os.path.basename(fp)
    if '.' in base:
        base = base.rsplit('.', 1)[0]
    return '' if _is_token_like(base) else base


def _params(info):
    return {
        'tmdb': (info.get('tmdb_id') or '').strip(),
        'imdb': (info.get('imdb_id') or '').strip(),
        'type': 'episode' if info.get('is_episode') else 'movie',
        'season': str(info.get('season') or '0'),
        'episode': str(info.get('episode') or '0'),
        'lang': 'he',
    }


def _has_id(p):
    return bool(p.get('tmdb') or p.get('imdb'))


def _get(path, params):
    q = _urlparse.urlencode({k: v for k, v in params.items() if v})
    hdrs = {'user-agent': _UA}
    hdrs.update(sign_headers('GET', path))
    req = _urlreq.Request(POOL_URL + path + '?' + q, headers=hdrs)
    with _urlreq.urlopen(req, timeout=_GET_TIMEOUT) as r:
        return r.read()


def lookup(info):
    """Return a list of available Hebrew variants for this media, or []."""
    if _urlreq is None:
        return []
    p = _params(info)
    if not _has_id(p):
        return []
    try:
        data = json.loads(_get('/lookup', p).decode('utf-8'))
        return (data.get('variants') or []) if data.get('ok') else []
    except Exception as e:
        kodi_utils.log('pool lookup failed: {0}'.format(e), level='DEBUG')
        return []


def fetch(info, source_hash=None):
    """Return the .srt text for the exact source_hash (or newest if None),
    or None. With a hash, the Worker 404s when that exact variant is absent."""
    if _urlreq is None:
        return None
    p = _params(info)
    if not _has_id(p):
        return None
    if source_hash:
        p['hash'] = source_hash
    try:
        return _get('/sub', p).decode('utf-8')
    except Exception as e:
        kodi_utils.log('pool fetch failed: {0}'.format(e), level='DEBUG')
        return None


def _lookup_params_from_body(body):
    return {
        'tmdb': (body.get('tmdb_id') or '').strip(),
        'imdb': (body.get('imdb_id') or '').strip(),
        'type': body.get('type') or '',
        'season': str(body.get('season') or '0'),
        'episode': str(body.get('episode') or '0'),
        'lang': body.get('lang') or 'he',
    }


def _pool_has_hash(body, source_hash):
    """Cheap pre-check: is this exact source already in the pool? Reads the
    episode's variant list (each carries its source hash) and looks for a
    match. Lets the background uploader skip sending an SRT the server would
    only discard. Best-effort: any error returns False so we just upload."""
    if not source_hash:
        return False
    try:
        data = json.loads(
            _get('/lookup', _lookup_params_from_body(body)).decode('utf-8'))
        variants = (data.get('variants') or []) if data.get('ok') else []
        return any(v.get('hash') == source_hash for v in variants)
    except Exception:
        return False


def _post(body, marker_path=None):
    # Pre-check: if this exact source is already in the pool, skip the upload
    # entirely and just mark locally so we stop retrying. The server dedups by
    # source hash too, so this is purely to avoid sending an SRT that would be
    # discarded (and to suppress retries when another device already shared it).
    try:
        if _pool_has_hash(body, (body.get('source_hash') or '').strip()):
            if marker_path:
                mark_contributed(marker_path)
            return
    except Exception:
        pass
    try:
        req = _urlreq.Request(
            POOL_URL + '/contribute',
            data=json.dumps(body).encode('utf-8'),
            headers=_post_headers('/contribute'),
            method='POST')
        _urlreq.urlopen(req, timeout=_POST_TIMEOUT).read()
    except Exception as e:
        try:
            kodi_utils.log('pool contribute failed: {0}'.format(e), level='DEBUG')
        except Exception:
            pass
        return
    # Reached only on a successful POST: mark the file so we never re-upload
    # it. A failed upload leaves no marker, so it retries on the next watch.
    if marker_path:
        mark_contributed(marker_path)


def _build_body(info, source_hash, source_lang, srt_text,
                kind='ai', release_override=None):
    """Assemble the /contribute JSON body, or None if there's no usable id.

    `kind` is 'ai' for a machine translation or 'ktuvit' for a human Hebrew
    subtitle pulled from Ktuvit (a backup mirror so it survives Ktuvit going
    down, and loads instantly from the channel). `release_override`, when given,
    is used as the release name instead of deriving one from `info` -- the
    engine already knows the exact Ktuvit release filename."""
    p = _params(info)
    if not _has_id(p):
        return None
    # For episodes the pool/Telegram post wants the SERIES name, not the
    # episode title. Kodi's VideoPlayer.Title is the episode label (e.g. POV's
    # "2x08 The Hunters"), so prefer the show title for episodes -- otherwise
    # the post reads as the episode instead of the series. (The Worker still
    # overrides this with the localized TMDB name when it can resolve the id.)
    show = (info.get('tvshow') or '').strip()
    title = (show if (p['type'] == 'episode' and show)
             else (info.get('title') or '').strip())
    if release_override:
        rel = '' if _is_token_like(release_override) else release_override
    else:
        rel = _release_from(info)  # already filters token-like names
    return {
        'tmdb_id': p['tmdb'], 'imdb_id': p['imdb'], 'type': p['type'],
        'season': p['season'], 'episode': p['episode'], 'lang': 'he',
        'release': rel,
        'source_hash': source_hash or '',
        'source_lang': source_lang or 'en',
        'kind': kind or 'ai',
        'title': title,
        'year': str(info.get('year') or ''),
        'srt': srt_text,
    }


def contribute(info, source_hash, source_lang, srt_text, marker_path=None,
               kind='ai', release_override=None):
    """Fire-and-forget: share a fresh Hebrew translation. Runs on a daemon
    thread so it never delays handing the subtitle back to the player. If
    marker_path is given, the thread writes a ".shared" marker there once the
    upload succeeds."""
    if _urlreq is None or not srt_text:
        return
    body = _build_body(info, source_hash, source_lang, srt_text,
                       kind=kind, release_override=release_override)
    if body is None:
        return
    try:
        threading.Thread(target=_post, args=(body, marker_path),
                         daemon=True).start()
    except Exception:
        pass


# --- Duplicate-upload guard -------------------------------------------------
# Two layers protect against ever creating two identical subtitles in the pool:
#   1. SERVER: the Worker keys every variant by source_hash (the content hash
#      of the source SRT) and rejects a POST whose hash already exists for that
#      episode -- so a duplicate is impossible even if the client re-posts.
#   2. CLIENT: a tiny ".shared" sidecar next to each cached translation lets us
#      skip the network call entirely once we've contributed that file. The
#      marker lives in addon_data/cache, which a quick-update does NOT touch,
#      so it survives updates and we don't re-upload on every re-watch.
# The marker is only an optimisation; the server is the real guarantee.

def _marker_path(translated_path):
    return (translated_path + '.shared') if translated_path else None


def was_contributed(translated_path):
    m = _marker_path(translated_path)
    return bool(m and os.path.isfile(m))


def mark_contributed(translated_path):
    m = _marker_path(translated_path)
    if not m:
        return
    try:
        with open(m, 'w', encoding='utf-8') as f:
            f.write('1')
    except OSError:
        pass


# --- Embedded-Hebrew reporting -------------------------------------------
# When the add-on detects a built-in (muxed) Hebrew track in the source being
# played, it tells the pool "this RELEASE ships embedded Hebrew" so EVERYONE
# sees that source flagged on the source screen. Fully automatic (no user
# action), non-blocking, keyed by release name (provider-independent), and
# deduped locally so each release is reported at most once per device. NOT
# gated by pool_share -- it's a tiny advisory flag, not a subtitle upload --
# but can be turned off with `he_embedded_report`.

def _embedded_reported_path():
    try:
        import xbmcvfs
        base = xbmcvfs.translatePath(
            'special://profile/addon_data/service.subtitles.kodipovilai/')
        return os.path.join(base, 'embedded_reported.json')
    except Exception:
        return ''


def _embedded_already(key):
    p = _embedded_reported_path()
    if not p or not os.path.isfile(p):
        return False, p, []
    try:
        with open(p, 'r', encoding='utf-8') as f:
            lst = json.load(f) or []
        return (key in lst), p, lst
    except Exception:
        return False, p, []


def _embedded_mark(p, lst, key):
    try:
        lst.append(key)
        if len(lst) > 2000:
            lst = lst[-2000:]
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(lst, f)
        os.replace(tmp, p)
    except Exception:
        pass


def report_embedded(info):
    """Fire-and-forget: flag this media's CURRENT source release as carrying a
    built-in Hebrew track. Safe to call on every embedded-Hebrew detection --
    deduped locally and thrown onto a background thread so it never touches
    playback. No-op when disabled, when ids/release are missing, or on error."""
    try:
        if kodi_utils.get_setting('he_embedded_report', 'true') == 'false':
            return
        if _urlreq is None:
            return
        p = _params(info)
        if not _has_id(p):
            return
        rel = _release_from(info)
        if not rel or _is_token_like(rel):
            return
        key = '{0}:{1}:{2}:{3}:{4}'.format(
            p['tmdb'] or p['imdb'], p['type'], p['season'], p['episode'],
            rel.lower())
        already, path, lst = _embedded_already(key)
        if already:
            return
        body = {
            'tmdb_id': p['tmdb'], 'imdb_id': p['imdb'], 'type': p['type'],
            'season': p['season'], 'episode': p['episode'], 'release': rel,
        }

        def _run():
            try:
                req = _urlreq.Request(
                    POOL_URL + '/embedded',
                    data=json.dumps(body).encode('utf-8'),
                    headers=_post_headers('/embedded'),
                    method='POST')
                _urlreq.urlopen(req, timeout=_POST_TIMEOUT).read()
                # Mark locally only on a successful send, so a failed report
                # retries on the next watch.
                if path:
                    _embedded_mark(path, lst, key)
            except Exception as e:
                try:
                    kodi_utils.log('pool report_embedded failed: {0}'.format(e),
                                   level='DEBUG')
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def report_ktuvit(info, names):
    """Fire-and-forget: publish the Hebrew release names found on Ktuvit for this
    title to the SHARED pool registry, so every other user reads them back via
    /lookup and never has to hit the rate-limited shared Ktuvit account. Called
    by the background warm only when the registry was missing/stale (so Ktuvit
    is queried ~once per title globally). Non-blocking; no-op on missing id."""
    try:
        if _urlreq is None:
            return
        p = _params(info)
        if not _has_id(p):
            return
        clean = []
        seen = set()
        for n in (names or []):
            n = (n or '').strip()
            low = n.lower()
            if n and low not in seen:
                seen.add(low)
                clean.append(n)
        body = {
            'tmdb_id': p['tmdb'], 'imdb_id': p['imdb'], 'type': p['type'],
            'season': p['season'], 'episode': p['episode'],
            'names': clean,
        }

        def _run():
            try:
                req = _urlreq.Request(
                    POOL_URL + '/ktuvit',
                    data=json.dumps(body).encode('utf-8'),
                    headers=_post_headers('/ktuvit'),
                    method='POST')
                _urlreq.urlopen(req, timeout=_POST_TIMEOUT).read()
            except Exception as e:
                try:
                    kodi_utils.log('pool report_ktuvit failed: {0}'.format(e),
                                   level='DEBUG')
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


_CACHE_NAME_RE = None


def share_cache(progress_cb=None, should_cancel=None):
    """Bulk migration: contribute every Hebrew translation already in the local
    cache to the pool. Drives the "share my cached translations" settings
    action. Synchronous + one-at-a-time (the caller runs it on a thread), so it
    never spawns a swarm of uploads. Safe to run repeatedly: each file's
    ".shared" marker skips it once shared, and the Worker dedups by the Hebrew
    result hash, so nothing is ever uploaded or stored twice.

    Cached filenames look like <imdb>_S<season>E<episode>_<lang>_<digest>.he.srt
    -- we only have an IMDb id, so we resolve it to a TMDB id (when possible)
    so these key exactly like live uploads do. Returns
    (submitted, skipped, total)."""
    global _CACHE_NAME_RE
    if _urlreq is None or not share_enabled():
        return (0, 0, 0)
    import glob
    import re
    from . import cache as _cache
    try:
        from . import tmdb_helper as _tmdb
    except Exception:
        _tmdb = None
    if _CACHE_NAME_RE is None:
        _CACHE_NAME_RE = re.compile(
            r'^(?P<imdb>.+?)_S(?P<s>\d+)E(?P<e>\d+)_(?P<lang>[a-z]+)_'
            r'[0-9a-f]+\.he\.srt$')

    base = os.path.join(kodi_utils.cache_dir(), 'translated')
    try:
        files = glob.glob(os.path.join(base, '*.he.srt'))
    except Exception:
        files = []
    total = len(files)
    submitted = skipped = 0
    for i, fp in enumerate(files):
        if should_cancel is not None:
            try:
                if should_cancel():
                    break
            except Exception:
                pass
        if progress_cb is not None:
            try:
                progress_cb(i + 1, total)
            except Exception:
                pass
        if was_contributed(fp):
            skipped += 1
            continue
        m = _CACHE_NAME_RE.match(os.path.basename(fp))
        if not m:
            skipped += 1
            continue
        imdb = m.group('imdb')
        if imdb in ('', 'unknown'):
            skipped += 1
            continue
        season, episode, lang = m.group('s'), m.group('e'), m.group('lang')
        is_ep = not (season == '0' and episode == '0')
        text = _cache.load_text(fp)
        if not text:
            skipped += 1
            continue
        # Quality gate: don't bulk-share something that isn't really Hebrew
        # (a failed/empty translation left in cache). We have no source here to
        # compare entry counts, so this is the Hebrew-content check only.
        try:
            from . import srt as _srt
            if not _srt.looks_hebrew(text):
                skipped += 1
                continue
        except Exception:
            pass
        tmdb_id, title, year = '', '', ''
        if _tmdb is not None:
            try:
                tmdb_id = _tmdb.resolve_imdb_to_tmdb(imdb, is_ep) or ''
            except Exception:
                tmdb_id = ''
            try:
                title, year = _tmdb.title_and_year(
                    imdb_id=imdb, tmdb_id=(tmdb_id or None),
                    media_type=('tv' if is_ep else 'movie'))
            except Exception:
                title, year = '', ''
        info = {
            'tmdb_id': tmdb_id, 'imdb_id': imdb, 'is_episode': is_ep,
            'season': season, 'episode': episode,
            'title': title or '', 'year': year or '', 'filepath': '',
        }
        # Use the real source release recorded next to the cached file (written
        # at translation time), so this bulk upload tags it with a proper release
        # for match-% instead of falling back to a generic Title.Year.
        rel_override = None
        try:
            with open(fp + '.release', 'r', encoding='utf-8') as _rf:
                rel_override = (_rf.read().strip() or None)
        except OSError:
            rel_override = None
        body = _build_body(info, '', lang, text, release_override=rel_override)
        if body is None:
            skipped += 1
            continue
        # Synchronous post (we're already on a worker thread); the marker is
        # written by _post only on success, so a failure simply retries next run.
        _post(body, marker_path=fp)
        submitted += 1
        # Throttle so a large cache doesn't burst past Telegram's per-channel
        # rate limit (~20 msgs/min; each contribution is 2 messages). Sleep in
        # short slices so a cancel is still responsive.
        if i < total - 1:
            waited = 0.0
            while waited < _BULK_THROTTLE_SEC:
                if should_cancel is not None:
                    try:
                        if should_cancel():
                            break
                    except Exception:
                        pass
                time.sleep(0.5)
                waited += 0.5
    return (submitted, skipped, total)


def contribute_once(info, source_hash, source_lang, srt_text, marker_path=None,
                    kind='ai', release_override=None):
    """contribute(), but skip the upload if this file was already shared (per
    the local marker). The marker is written by the POST thread ONLY after a
    successful upload, so a transient failure retries on the next watch rather
    than being silently dropped. Once marked, repeated watches / quick-updates
    never re-upload. Even if the marker is lost, the Worker dedups by
    source_hash, so duplicates are impossible."""
    if marker_path and was_contributed(marker_path):
        return
    contribute(info, source_hash, source_lang, srt_text,
               marker_path=marker_path, kind=kind,
               release_override=release_override)


def contribute_ktuvit(info, srt_text, release='', marker_path=None):
    """Mirror a human Ktuvit Hebrew subtitle into the pool (kind='ktuvit').

    This is the Ktuvit backup channel: every Ktuvit sub a user downloads is
    pushed once to the same Telegram channel/Worker so it survives Ktuvit going
    offline and loads instantly from the channel afterwards. The content hash
    of the Hebrew SRT is the source hash, so the same release is never stored
    twice (server dedups by hash AND by result).

    Unlike the AI share (a fire-and-forget thread), this ENQUEUES the upload to
    a small on-disk queue and lets the long-lived service drain it (see
    drain()). That matters because the subtitle search runs in a short-lived
    invoker: the user is usually already watching -- or may stop/leave right
    after picking -- so a background thread can be torn down before it finishes.
    A queued job survives playback ending AND a Kodi restart, and the drainer
    throttles uploads so a burst never trips Telegram's bot rate limit. Gated by
    the caller on share_enabled(); enqueue is a fast local file write."""
    if _urlreq is None or not srt_text:
        return
    if marker_path and was_contributed(marker_path):
        return
    try:
        import hashlib
        sh = hashlib.sha1(
            srt_text.encode('utf-8', 'replace')).hexdigest()[:16]
    except Exception:
        sh = ''
    body = _build_body(info, sh, 'he', srt_text, kind='ktuvit',
                       release_override=(release or None))
    if body is None:
        return
    enqueue(body, marker_path=marker_path)


# --- Persistent, throttled upload queue -------------------------------------
# A contribution is QUEUED to disk the moment it's ready and uploaded later by
# the long-lived service (drain(), driven by service.py's monitor thread). This
# is what makes a shared subtitle reliable and rate-limit-safe:
#   * Durable: the job is a file under addon_data (which a quick-update never
#     touches), so it survives the user leaving the video and a Kodi restart --
#     a short-lived search invoker can't lose it.
#   * No burst: the drainer sends ONE contribution at a time with a throttle
#     (each contribution is two Telegram messages), so even a backlog stays well
#     under the bot's ~20 msgs/min channel limit.
#   * Self-healing: a failed upload stays queued and retries next pass; a
#     success (or a server dedup) removes it; permanently-bad jobs are dropped,
#     and anything stuck is aged out so the queue can't grow without bound.

_QUEUE_MAX_AGE_SEC = 14 * 24 * 3600

# Only one drain at a time per process: the service drainer thread AND an inline
# drain (e.g. right after the on-play harvest enqueues) can both call drain();
# this non-blocking lock lets whichever gets here first do the work while the
# other returns immediately -- so a job is never POSTed twice in one process.
_DRAIN_LOCK = threading.Lock()


def _queue_dir():
    try:
        d = os.path.join(kodi_utils.cache_dir(), 'pool_queue')
        if not os.path.isdir(d):
            os.makedirs(d)
        return d
    except Exception:
        return None


def _job_id(body):
    """Stable id from kind + source hash + media id, so the SAME subtitle is
    never queued twice (idempotent enqueue) even across re-watches."""
    import hashlib
    raw = '{0}|{1}|{2}:{3}:s{4}:e{5}'.format(
        body.get('kind') or 'ai',
        body.get('source_hash') or '',
        body.get('tmdb_id') or body.get('imdb_id') or '',
        body.get('type') or '',
        body.get('season') or '0',
        body.get('episode') or '0')
    return hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:24]


def enqueue(body, marker_path=None):
    """Persist a contribution as a queued job (fast local write). Idempotent.
    Then kick an immediate background drain so the upload happens right away --
    the same "upload as soon as it's ready" behaviour as the AI path's
    fire-and-forget post, instead of waiting for the service drainer's next
    pass. The drain lock serialises with the service thread and the per-send
    throttle still prevents a Telegram burst."""
    if not body:
        return
    d = _queue_dir()
    if not d:
        return
    try:
        path = os.path.join(d, _job_id(body) + '.json')
        if os.path.exists(path):
            try:
                kodi_utils.log('pool enqueue: already queued ({0} {1})'.format(
                    body.get('kind') or 'ai', body.get('release') or ''),
                    level='INFO')
            except Exception:
                pass
            return  # already queued
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'body': body, 'marker_path': marker_path or ''}, f)
        os.replace(tmp, path)
        try:
            kodi_utils.log('pool enqueue: queued {0} "{1}" (queue={2})'.format(
                body.get('kind') or 'ai', body.get('release') or '',
                queue_len()), level='INFO')
        except Exception:
            pass
        _kick_drain()
    except Exception as e:
        try:
            kodi_utils.log('pool enqueue failed: {0}'.format(e), level='WARNING')
        except Exception:
            pass


def _kick_drain():
    """Fire-and-forget an immediate drain on a daemon thread (best-effort)."""
    def _run():
        try:
            drain()
        except Exception:
            pass
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def queue_len():
    d = _queue_dir()
    if not d:
        return 0
    try:
        return sum(1 for fn in os.listdir(d) if fn.endswith('.json'))
    except Exception:
        return 0


def _post_sync(body):
    """Synchronous /contribute POST for the drainer. Returns one of:
      'ok'    -> stored, or already in the pool (server dedup): remove the job.
      'drop'  -> permanent client error (bad/invalid/unauthorized): remove it.
      'retry' -> transient failure (network / 429 / 5xx): keep for next pass.
    Never raises."""
    # Cheap pre-check: already in the pool -> done, no upload (= no TG message).
    try:
        if _pool_has_hash(body, (body.get('source_hash') or '').strip()):
            return 'ok'
    except Exception:
        pass
    try:
        req = _urlreq.Request(
            POOL_URL + '/contribute',
            data=json.dumps(body).encode('utf-8'),
            headers=_post_headers('/contribute'),
            method='POST')
        resp = _urlreq.urlopen(req, timeout=_POST_TIMEOUT).read()
        try:
            return 'ok' if json.loads(resp.decode('utf-8')).get('ok') else 'retry'
        except Exception:
            return 'ok'  # 2xx with an unparseable body -- assume stored
    except Exception as e:
        code = getattr(e, 'code', None)
        if code in (400, 401):           # invalid srt / unauthorized -> never ok
            try:
                kodi_utils.log('pool drop job (HTTP {0})'.format(code),
                               level='DEBUG')
            except Exception:
                pass
            return 'drop'
        try:                              # 429 / 5xx / network -> retry later
            kodi_utils.log('pool _post_sync retry: {0}'.format(e), level='DEBUG')
        except Exception:
            pass
        return 'retry'


def _sleep_cancellable(seconds, should_cancel):
    waited = 0.0
    while waited < seconds:
        if should_cancel is not None:
            try:
                if should_cancel():
                    return
            except Exception:
                pass
        time.sleep(0.5)
        waited += 0.5


def drain(throttle=None, should_cancel=None, max_sends=40):
    """Upload queued contributions one at a time with a throttle so a burst can
    never trip Telegram's bot rate limit. A failed upload stays queued for the
    next pass; a success (or server dedup) is removed. Returns (sent, remaining).
    `should_cancel` is an optional callable (e.g. monitor.abortRequested)."""
    if _urlreq is None:
        return (0, queue_len())
    d = _queue_dir()
    if not d:
        return (0, 0)
    # One drain at a time per process; a second concurrent caller just leaves.
    if not _DRAIN_LOCK.acquire(blocking=False):
        return (0, queue_len())
    try:
        if throttle is None:
            throttle = _BULK_THROTTLE_SEC
        try:
            files = [os.path.join(d, fn) for fn in os.listdir(d)
                     if fn.endswith('.json')]
        except Exception:
            return (0, 0)
        # Oldest first (FIFO) so nothing starves.
        files.sort(
            key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0))
        sent = dropped = failed = 0
        now = time.time()
        for fp in files:
            if should_cancel is not None:
                try:
                    if should_cancel():
                        break
                except Exception:
                    pass
            if sent >= max_sends:
                break
            # Age out jobs that can never resolve so the queue can't grow forever.
            try:
                if now - os.path.getmtime(fp) > _QUEUE_MAX_AGE_SEC:
                    os.remove(fp)
                    continue
            except OSError:
                pass
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    job = json.load(f)
            except Exception:
                try:
                    os.remove(fp)
                except OSError:
                    pass
                continue
            body = job.get('body') or {}
            marker_path = job.get('marker_path') or None
            status = _post_sync(body)
            if status == 'retry':
                # Server/network trouble -- stop now and retry the whole queue
                # later (don't hammer a struggling endpoint / burn the budget).
                failed += 1
                break
            if status == 'ok' and marker_path:
                mark_contributed(marker_path)
            try:
                os.remove(fp)
            except OSError:
                pass
            if status == 'ok':
                sent += 1
                # Throttle ONLY between real sends (each = a TG message pair).
                _sleep_cancellable(throttle, should_cancel)
            else:
                dropped += 1
        remaining = queue_len()
        if sent or dropped or failed:
            try:
                kodi_utils.log(
                    'pool drain: uploaded={0} dropped={1} failed={2} '
                    'remaining={3}'.format(sent, dropped, failed, remaining),
                    level='INFO')
            except Exception:
                pass
        return (sent, remaining)
    finally:
        _DRAIN_LOCK.release()


# --- Ktuvit harvest queue ---------------------------------------------------
# A SECOND queue, separate from the upload queue above. On every search,
# list_candidates drops a tiny job here for EVERY human Ktuvit subtitle it sees
# (just the media info + the engine download link) -- a fast local write, NO
# Ktuvit hit during playback. The long-lived service then downloads them from
# Ktuvit GENTLY (a couple at a time, throttled, retrying failures across
# sessions and days) and feeds each into the upload queue. This is what makes
# the backup eventually COMPLETE -- every release of a title ends up in the
# pool -- without hammering Ktuvit (which rate-/quota-limits downloads, the very
# reason a fast in-session grab only ever got a random subset) and without
# depending on the user staying on the video. The actual download lives in
# translate.py (which can import the engine); this module owns only the storage.

# Drop a harvest job after this many failed download attempts (Ktuvit removed
# it / permanently refuses), so a dead job can't retry forever.
_HARVEST_MAX_TRIES = 8


def _harvest_queue_dir():
    try:
        d = os.path.join(kodi_utils.cache_dir(), 'pool_harvest_queue')
        if not os.path.isdir(d):
            os.makedirs(d)
        return d
    except Exception:
        return None


def _harvest_job_id(info, payload):
    """Unique per (media + this exact Ktuvit subtitle), so the same release is
    queued once. The engine download_data carries Ktuvit's FilmID+SubtitleID."""
    import hashlib
    dd = payload.get('download_data') or {}
    raw = '{0}:{1}:s{2}:e{3}|{4}'.format(
        info.get('tmdb_id') or info.get('imdb_id') or '',
        'episode' if info.get('is_episode') else 'movie',
        info.get('season') or '0', info.get('episode') or '0',
        json.dumps(dd, sort_keys=True, ensure_ascii=False))
    return hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:24]


def enqueue_harvest(info, payload):
    """Queue ONE Ktuvit subtitle for background download+share. Fast, durable,
    idempotent, no network. Caller gates on share_enabled()."""
    if not info or not payload:
        return
    d = _harvest_queue_dir()
    if not d:
        return
    try:
        p = os.path.join(d, _harvest_job_id(info, payload) + '.json')
        if os.path.exists(p):
            return
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'info': info, 'payload': payload, 'tries': 0}, f)
        os.replace(tmp, p)
    except Exception as e:
        try:
            kodi_utils.log('harvest enqueue failed: {0}'.format(e),
                           level='DEBUG')
        except Exception:
            pass


def harvest_queue_len():
    d = _harvest_queue_dir()
    if not d:
        return 0
    try:
        return sum(1 for fn in os.listdir(d) if fn.endswith('.json'))
    except Exception:
        return 0


def harvest_jobs(limit=None):
    """NEWEST-first list of (path, job-dict). Newest-first so the title the user
    just played is mirrored before an older backlog (a big title's 20+ releases
    must not make a freshly-played movie wait behind them). Drops unreadable /
    aged-out jobs."""
    d = _harvest_queue_dir()
    if not d:
        return []
    try:
        files = [os.path.join(d, fn) for fn in os.listdir(d)
                 if fn.endswith('.json')]
    except Exception:
        return []
    files.sort(key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0),
               reverse=True)
    now = time.time()
    out = []
    for fp in files:
        try:
            if now - os.path.getmtime(fp) > _QUEUE_MAX_AGE_SEC:
                os.remove(fp)
                continue
        except OSError:
            pass
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                out.append((fp, json.load(f)))
        except Exception:
            try:
                os.remove(fp)
            except OSError:
                pass
        if limit and len(out) >= limit:
            break
    return out


def harvest_job_failed(fp, job):
    """Record a failed download attempt; drop the job once it's clearly dead."""
    try:
        tries = int(job.get('tries') or 0) + 1
    except Exception:
        tries = 1
    if tries >= _HARVEST_MAX_TRIES:
        remove_harvest_job(fp)
        return
    try:
        job['tries'] = tries
        tmp = fp + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(job, f)
        os.replace(tmp, fp)
    except Exception:
        pass


def remove_harvest_job(fp):
    try:
        os.remove(fp)
    except OSError:
        pass
