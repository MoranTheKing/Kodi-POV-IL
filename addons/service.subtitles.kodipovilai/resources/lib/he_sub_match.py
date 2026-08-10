# Hebrew-subtitle match score for POV's source-results window.
#
# Shows, under each source (before you pick it), how well an available Hebrew
# subtitle's release name matches that source's release -- i.e. how likely a
# ready Hebrew sub will sync to it. Computed against the community pool (AI +
# manual uploads). Cosmetic/advisory only.
#
# Self-contained on purpose: POV imports this by path from its own interpreter
# (like source_capture), so NO relative/package imports -- we do the pool
# /lookup over plain urllib here instead of importing pool.py. Every entry
# point is fully guarded; any failure yields an empty prefix so POV's source
# list is never affected.

import os
import re
import time
import json
import base64

try:
    import urllib.request as _req
    import urllib.parse as _parse
except Exception:
    _req = None
    _parse = None

POOL_URL = 'https://povil-subs-pool.moran200333.workers.dev'
_UA = 'KodiPOVIL-AISubs/he-match'
_ADDON_ID = 'service.subtitles.kodipovilai'

_TIMEOUT = 2.5
# Hard cap for the ONE synchronous pool lookup release_names() does on a cache
# miss (first entry to a title). Widened from 1.2s -> 2.5s so the shared % shows
# on the FIRST entry far more reliably (the 1.2s cap was timing out before the
# pool worker answered, so the badge only appeared on the 2nd/3rd entry once the
# background warm had filled the cache). Still ONE lookup per title (no extra
# Cloudflare reads); worst case the source window opens ~1.3s later on the first
# entry to a not-yet-cached title.
_FIRST_ENTRY_TIMEOUT = 3.5
# On a cache miss the source window WAITS this long (total) for the availability
# answer before it shows the list, so the Hebrew % is there on the FIRST entry
# rather than only after the background warm wins a race. Pool-HAVE titles return
# almost instantly (the pool answers in well under a second); only titles whose
# Hebrew lives on OpenSubtitles/Ktuvit pay most of this wait, while the in-service
# warm checks them. Kept to ~3s so the window never feels frozen.
_FIRST_ENTRY_WAIT = 3.2

# Engine (OpenSubtitles) availability is filled by a background RunScript into a
# shared cache file; we read it cheaply on every call so the badge fills in on
# the next source-window open without ever blocking POV.
_ENGINE_CACHE_FILE = (
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'he_avail_cache.json')
_ENGINE_TTL = 7 * 24 * 3600.0   # 7 days; used once HUMAN Hebrew has been found
# When NO human Hebrew exists yet (likely brand-new content), re-warm more often
# so a sub that appears shows up reasonably fast -- new releases get human Hebrew
# within ~24h, and a 7-day cache would hide it. Balanced at ~daily (was 8h) to
# cut repeat Worker /lookup traffic while still surfacing next-day Hebrew.
_AVAIL_TTL_NONE = 24 * 3600.0   # 24 hours
# Cross-process memo for _pool_lookup: coalesces repeated signed /lookup calls
# for the SAME title within a few seconds into ONE Worker request. (The POV
# source-window used to make its OWN unsigned peek here too, but that always
# 426'd and was removed; the signed background warm in availability() is now the
# only caller, and this memo still guards against it re-firing back-to-back.)
# Shares this file the same way the processes already share he_avail_cache.json.
_POOL_RAW_FILE = (
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'he_pool_raw.json')
_POOL_MEMO_TTL = 15.0
_FIRED = {}            # media_key -> last warm-fire ts (throttle re-fires)
_FIRE_RETRY = 120.0    # re-fire a warm at most once every 2 min per title

# Warm-request queue. prewarm()/release_names() drop a tiny JSON job here (a
# pure disk write in POV's process -- no network, no new interpreter); the
# long-lived MoranSubs service drains it within a fraction of a second and runs
# the full warm in its OWN addon context (all engine imports + the right API
# keys resolve there, but NOT inside POV's process). This replaced the old
# RunScript-per-warm: RunScript spins up a fresh Python interpreter (~3s to boot
# + re-import the addon), which was SLOWER than POV's ~2s scrape, so the badge
# only appeared on the 2nd/3rd entry. The queued in-service warm starts in ~0.4s
# and finishes inside the scrape window -> Hebrew % on the FIRST entry.
_WARM_QUEUE_DIR = (
    'special://profile/addon_data/service.subtitles.kodipovilai/he_warm_queue')
# Cap the concurrent pool/Wizdom/OpenSubtitles fetch so one hung source can't
# stall the fast first-entry store. Kept just under _FIRST_ENTRY_WAIT so the
# source window's wait reliably catches the phase-1 store. These usually answer
# in <2s anyway.
_WARM_FETCH_TIMEOUT = 3.0
# Serializes the SLOW live-Ktuvit top-up across warms so the one shared,
# rate-limited Ktuvit account is never hit by several titles at once.
_KT_LIVE_LOCK = None


def _kt_live_lock():
    global _KT_LIVE_LOCK
    if _KT_LIVE_LOCK is None:
        try:
            import threading
            _KT_LIVE_LOCK = threading.Lock()
        except Exception:
            return None
    return _KT_LIVE_LOCK


def _enabled():
    try:
        import xbmcaddon
        v = (xbmcaddon.Addon(_ADDON_ID).getSetting('show_subtitle_match')
             or '').strip().lower()
        return v != 'false'   # default ON when unset
    except Exception:
        return True


def _media_params(meta):
    """Pull {tmdb,imdb,type,season,episode} out of the player add-on's meta
    dict, defensively (only imdb_id/media_type/season/episode are guaranteed
    present).

    Serves POV *and* Umbrella. Umbrella's meta spells the same three fields
    `imdb`, `tmdb` and `mediatype` (no underscore) -- the first two were
    already covered by the alternates below, and `mediatype` is read here so
    Umbrella's type is taken from the field that states it rather than
    inferred from whether season/episode happen to be set. The inference still
    stands behind it and still gets the answer right, but a movie whose meta
    carries a stray season would have fooled it."""
    if not meta:
        return None
    g = meta.get
    imdb = str(g('imdb_id') or g('imdb') or '').strip()
    tmdb = str(g('tmdb_id') or g('tmdb') or '').strip()
    if not (imdb or tmdb):
        return None
    season = str(g('season') or g('custom_season') or '0').strip() or '0'
    episode = str(g('episode') or g('custom_episode') or '0').strip() or '0'
    mt = str(g('media_type') or g('mediatype') or '').strip().lower()
    is_ep = mt in ('episode', 'tvshow', 'tv', 'season') or (
        season not in ('', '0') and episode not in ('', '0'))
    return {
        'tmdb': tmdb, 'imdb': imdb,
        'type': 'episode' if is_ep else 'movie',
        'season': season if is_ep else '0',
        'episode': episode if is_ep else '0',
        'lang': 'he',
    }


def _media_key(p):
    return '{0}:{1}:{2}:{3}:{4}'.format(
        p['tmdb'] or p['imdb'], p['type'], p['season'], p['episode'], p['lang'])


WIZDOM_API_URL = 'https://wizdom.xyz/api/search?action=by_id'


def _pool_lookup(p):
    """One SIGNED /lookup call -> dict with the pool's Hebrew data for this media:
        {'names': [...],          pool-contributed Hebrew release names
         'embedded': [...],       releases flagged as carrying built-in Hebrew
         'ktuvit': [...],         Hebrew release names cached from Ktuvit
         'ktuvit_checked': <ts>}  when Ktuvit was last checked (0 = never)
    All keyed by release name so they match across debrid providers. Networked
    via pool._get (which signs the request and uses pool's fixed GET timeout).
    Runs only in MoranSubs's own service process (the signed background warm)."""
    out = {'names': [], 'embedded': [], 'ktuvit': [], 'sync_rel': [],
           'ktuvit_checked': 0.0, 'ktuvit_changed': 0.0, '_ok': False}
    try:
        # Route through pool._lookup_raw -- it SIGNS the request AND populates
        # pool.py's 90s in-process _LOOKUP_CACHE. Two wins:
        #  (1) SIGNED: the Worker REJECTS an unsigned/unversioned /lookup with
        #      HTTP 426 (poolAuth checks x-pov-v BEFORE the signature), so the old
        #      bare urllib call here always 426'd -- no data, wasted invocation.
        #  (2) SHARED CACHE: this background warm and autosub's pool.lookup() run
        #      in the SAME service process for one playback; going through
        #      _lookup_raw lets whichever fires first satisfy the other from
        #      pool.py's cache -- collapsing the near-guaranteed warm+autosub
        #      /lookup DUPLICATE into ONE Worker request (the dominant avoidable
        #      pool traffic per playback). _lookup_raw returns the FULL parsed
        #      /lookup dict (or {} on miss/error), same shape this code parses.
        # Runs ONLY in MoranSubs's own service process (the POV-side peek that
        # couldn't sign is gone), so `pool` imports cleanly. Fail-open on error.
        from resources.lib import pool as _pool
        data = _pool._lookup_raw(p) or {}
        if data.get('ok'):
            out['_ok'] = True   # a real, successful response (memoize-able)
            # Only HUMAN Hebrew counts as "there's a translation" here -- an AI
            # translation (kind='ai') can be generated for any source on demand,
            # so it must NOT make us treat a title as already-having-Hebrew (that
            # would stop us looking for real human subs on new content).
            out['names'] = [(_v.get('release') or '').strip()
                            for _v in (data.get('variants') or [])
                            if (_v.get('release') or '').strip()
                            and (_v.get('kind') or 'ai') != 'ai']
            out['embedded'] = [(_r or '').strip()
                               for _r in (data.get('embedded') or [])
                               if (_r or '').strip()]
            out['ktuvit'] = [(_r or '').strip()
                             for _r in (data.get('ktuvit') or [])
                             if (_r or '').strip()]
            # SubSync S3 badge: the normalized VIDEO releases the community
            # registry has CONFIRMED as carrying a synced Hebrew subtitle. The
            # /lookup `sync` map is keyed "<sub_hash>|<worker-normalized release>";
            # we keep only the release part of entries whose status is CONFIRMED
            # (the strongest, human-anchored signal), so the source screen can
            # show a "synced" tick on exactly those releases. Conservative on
            # purpose -- FIXABLE/auto verdicts are NOT surfaced as "synced".
            try:
                _sr = set()
                for _k, _v in (data.get('sync') or {}).items():
                    if (isinstance(_v, dict) and _v.get('st') == 'CONFIRMED'
                            and '|' in _k):
                        _rel = _k.split('|', 1)[1].strip()
                        if _rel:
                            _sr.add(_rel)
                out['sync_rel'] = sorted(_sr)
            except Exception:
                out['sync_rel'] = []
            try:
                out['ktuvit_checked'] = float(data.get('ktuvit_checked') or 0)
            except (TypeError, ValueError):
                out['ktuvit_checked'] = 0.0
            try:
                out['ktuvit_changed'] = float(data.get('ktuvit_changed') or 0)
            except (TypeError, ValueError):
                out['ktuvit_changed'] = 0.0
    except Exception:
        pass
    return out




def _pool_raw_path():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(_POOL_RAW_FILE)
    except Exception:
        return ''


def _pool_lookup_memo(p):
    """_pool_lookup() behind a short cross-process memo keyed by media, so a warm
    that re-fires for the same title within a few seconds costs ONE Worker
    /lookup, not several. Only a SUCCESSFUL response (_ok) is stashed, so a
    transient failure is never cached; any error along the way falls back to a
    direct _pool_lookup(). Same shared file model as he_avail_cache."""
    try:
        key = _media_key(p)
    except Exception:
        key = ''
    path = _pool_raw_path()
    now = time.time()
    if key and path:
        try:
            if os.path.isfile(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                ent = data.get(key)
                if ent and (now - float(ent.get('ts') or 0)) < _POOL_MEMO_TTL:
                    d = ent.get('data')
                    if isinstance(d, dict):
                        return d
        except Exception:
            pass
    out = _pool_lookup(p)
    if key and path and isinstance(out, dict) and out.get('_ok'):
        try:
            data = {}
            if os.path.isfile(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f) or {}
                except Exception:
                    data = {}
            data[key] = {'ts': now, 'data': out}
            if len(data) > 120:
                data = dict(sorted(data.items(),
                                   key=lambda kv: kv[1].get('ts', 0),
                                   reverse=True)[:120])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Unique per-writer temp name so POV's process and the service
            # process (or two warm threads) never truncate each other's
            # in-progress temp before os.replace -- mirrors the .tmp/.stmp split
            # _store_avail/_seed_from_pool already use for he_avail_cache.
            _suffix = str(os.getpid())
            try:
                import threading as _thr
                _suffix += '.' + str(_thr.get_ident())
            except Exception:
                pass
            tmp = path + '.ptmp.' + _suffix
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass
    return out


def _wizdom_release_names(p):
    """Hebrew release names from Wizdom's open API (no key, covers most
    content) -- so the source-screen % works even for titles that aren't in
    the community pool yet. Fully guarded."""
    try:
        imdb = (p.get('imdb') or '').strip()
        if not imdb.startswith('tt'):
            return []
        params = {'imdb': imdb}
        season = (p.get('season') or '').strip()
        episode = (p.get('episode') or '').strip()
        if p.get('type') == 'tv' or (season not in ('', '0')
                                     and episode not in ('', '0')):
            try:
                params['season'] = str(int(season or 0)).zfill(2)
                params['episode'] = str(int(episode or 0)).zfill(2)
            except Exception:
                pass
        req = _req.Request(
            WIZDOM_API_URL + '&' + _parse.urlencode(params),
            headers={'user-agent': _UA})
        raw = _req.urlopen(req, timeout=_TIMEOUT).read().decode('utf-8')
        data = json.loads(raw)
        out = []
        for item in (data or []):
            v = (item.get('versioname') or '').strip()
            if v:
                out.append(v)
        return out
    except Exception:
        return []


def _engine_cache_path():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(_ENGINE_CACHE_FILE)
    except Exception:
        return ''


def _cache_entry(key):
    """The shared he_avail cache entry for this media, or None when missing /
    stale. The background warm writes {ts, names, embedded}; this is a pure file
    read that NEVER networks (it runs inside POV's source-window build)."""
    try:
        path = _engine_cache_path()
        if not path or not os.path.isfile(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        ent = data.get(key)
        if not ent:
            return None
        # The warm picks the re-warm interval per title (short while the title is
        # still gaining Hebrew / has none yet, long once it's stable). Fall back
        # to the names-based rule for entries written before this field existed.
        try:
            ttl = float(ent.get('ttl') or 0)
        except (TypeError, ValueError):
            ttl = 0.0
        if ttl <= 0:
            ttl = _ENGINE_TTL if (ent.get('names')) else _AVAIL_TTL_NONE
        if (time.time() - float(ent.get('ts', 0))) > ttl:
            return None
        return ent
    except Exception:
        return None


def _cached_names(key):
    """All available Hebrew release names from the warm cache (pool + Wizdom +
    OpenSubtitles + Ktuvit-fallback), or None when not warmed / stale."""
    ent = _cache_entry(key)
    if ent is None:
        return None
    return [n for n in (ent.get('names') or []) if n]


def _cached_embedded(key):
    """Release names flagged as carrying a built-in Hebrew track (from the warm
    cache). [] when none / not warmed."""
    ent = _cache_entry(key)
    if ent is None:
        return []
    return [n for n in (ent.get('embedded') or []) if n]


def _meta_str(meta, keys):
    for k in keys:
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def _dbg(msg):
    """Log via xbmc directly so it works in EITHER process -- POV's source-scrape
    interpreter (where 'from resources.lib import kodi_utils' fails because only
    resources/lib is on sys.path) AND MoranSubs's own service. Timing diagnostics
    for the first-entry Hebrew-% warm."""
    try:
        import xbmc
        xbmc.log('[service.subtitles.kodipovilai] he_warm: ' + msg, xbmc.LOGINFO)
    except Exception:
        pass


def _warm_queue_dir():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(_WARM_QUEUE_DIR)
    except Exception:
        return ''


def _enqueue_warm(key, payload):
    """Drop a warm job on disk for the long-lived service to pick up. A tiny,
    atomic write -- no network, no new interpreter. Returns True on success so
    the caller can fall back to RunScript only when the queue is unwritable."""
    d = _warm_queue_dir()
    if not d:
        return False
    try:
        os.makedirs(d, exist_ok=True)
        # Sanitize the key into a filename (media keys are like "60625:episode:8:3:he").
        safe = re.sub(r'[^0-9A-Za-z]+', '_', key) or 'job'
        path = os.path.join(d, safe + '.json')
        # Skip if an identical, still-fresh job is already queued (belt-and-
        # braces on top of the in-process _FIRED throttle -- covers separate
        # POV plugin invocations that don't share _FIRED).
        try:
            if os.path.isfile(path) and (time.time() - os.path.getmtime(path)) < _FIRE_RETRY:
                _dbg('enqueue skip (fresh job already queued) ' + key)
                return True
        except OSError:
            pass
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
        _dbg('enqueued ' + key)
        return True
    except Exception as e:
        _dbg('enqueue FAILED ' + key + ': ' + repr(e))
        return False


def _fire_engine_warm(key, p, meta):
    """Kick MoranSubs's background availability warm for this title (pool +
    Wizdom + OpenSubtitles + Ktuvit -> shared cache the "HEB NN%" badge reads).
    Throttled per title so reopening the source window doesn't spam it.
    Non-blocking.

    Primary path: enqueue a disk job the long-lived service drains in ~0.4s and
    runs in its own addon context. Fallback: the old fire-and-forget RunScript
    (only when the queue can't be written) -- correct context but ~3s slower to
    start because it boots a fresh interpreter."""
    try:
        now = time.time()
        if (now - _FIRED.get(key, 0)) < _FIRE_RETRY:
            return
        _FIRED[key] = now
        payload = {
            'mk': key,
            'imdb': p.get('imdb', ''),
            'tmdb': p.get('tmdb', ''),
            'type': p.get('type', 'movie'),
            'season': p.get('season', '0'),
            'episode': p.get('episode', '0'),
            'title': _meta_str(meta, ('title', 'originaltitle',
                                      'OriginalTitle', 'label', 'name')),
            'tvshow': _meta_str(meta, ('tvshowtitle', 'showtitle',
                                       'TVShowTitle')),
            'year': str((meta.get('year') if meta else '') or ''),
        }
        if _enqueue_warm(key, payload):
            return
        # Queue unwritable -- fall back to the slower RunScript path.
        import xbmc
        blob = base64.b64encode(
            json.dumps(payload).encode('utf-8')).decode('ascii')
        xbmc.executebuiltin(
            'RunScript(service.subtitles.kodipovilai,'
            'action=he_avail,data={0})'.format(blob))
    except Exception:
        pass


def availability(p):
    """NETWORKED -- runs ONLY in the background warm (MoranSubs's own process),
    never in POV's source window. Returns a dict:
        {'names': [...],          pool + Wizdom Hebrew release names
         'embedded': [...],       releases flagged as carrying built-in Hebrew
         'ktuvit': [...],         Hebrew release names already cached on the pool
         'ktuvit_checked': <ts>}  when the pool last checked Ktuvit (0 = never)
    The warm adds OpenSubtitles on top, decides whether to refresh Ktuvit (only
    when the shared registry is missing/stale), and writes the merged result to
    the local speed cache."""
    pl = {}
    try:
        pl = _pool_lookup_memo(p)
    except Exception:
        pl = {}
    try:
        wiz = _wizdom_release_names(p)
    except Exception:
        wiz = []
    names, seen = [], set()
    for rel in list(pl.get('names') or []) + list(wiz):
        low = (rel or '').strip().lower()
        if low and low not in seen:
            seen.add(low)
            names.append(rel)
    return {
        'names': names,
        'embedded': list(pl.get('embedded') or []),
        'ktuvit': list(pl.get('ktuvit') or []),
        'sync_rel': list(pl.get('sync_rel') or []),
        'ktuvit_checked': pl.get('ktuvit_checked') or 0.0,
        'ktuvit_changed': pl.get('ktuvit_changed') or 0.0,
    }


def _worker_norm(s):
    """Mirror of pool.worker_norm_release()/the Worker's normRelease() -- the
    registry release keys are normalized this way, so a source row's release
    must be normalized identically before we test it against the CONFIRMED set.
    Kept inline (not imported from pool) so this module stays self-contained in
    POV's source-window interpreter, where only resources/lib is on sys.path."""
    s = str(s or '').lower()
    s = re.sub(r'\.(mkv|mp4|avi|srt)$', '', s)
    s = re.sub(r'[\s_+/\-]+', '.', s)
    s = re.sub(r'\.+', '.', s).strip('.')
    return s


def confirmed_releases(meta):
    """The set of worker-normalized VIDEO releases the community registry has
    CONFIRMED as carrying a synced Hebrew subtitle for this media. PURE cache
    read (the warm/first-entry lookup stashes it next to `names`); never
    networks -- safe to call inside POV's source-window build. set() when none
    / not warmed / disabled."""
    try:
        if not _enabled():
            return set()
        p = _media_params(meta)
        if not p:
            return set()
        ent = _cache_entry(_media_key(p))
        if ent is None:
            return set()
        return set(r for r in (ent.get('sync_rel') or []) if r)
    except Exception:
        return set()


def _warm_log(msg, level='INFO'):
    try:
        from resources.lib import kodi_utils
        kodi_utils.log('he_avail: ' + msg, level=level)
    except Exception:
        pass


def _store_avail(mk, names, embedded, ttl, sync_rel=None):
    """Write {mk: {ts, names, embedded, sync_rel, ttl}} into the shared he_avail
    cache the
    source window reads. Same file/format as default.py's _he_avail_store, so
    either warm path (in-service queue drain OR the RunScript fallback) fills the
    exact cache the badge reads. Atomic + size-bounded."""
    path = _engine_cache_path()
    if not path:
        return
    try:
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        # 'warm': 1 marks a FULL warm result (pool+Wizdom+OS+Ktuvit), so the
        # first-entry wait in release_names can tell it apart from a pool-only
        # seed (which _seed_from_pool writes without this flag) and keep waiting
        # for the real OS/Ktuvit answer instead of returning the seed early.
        #
        # UNION the embedded list with whatever is already cached instead of
        # overwriting it. A release carrying a built-in Hebrew track is an
        # immutable fact; merge_embedded() writes it LOCALLY the instant we
        # detect it at play, before the pool round-trip completes. If this warm
        # (whose `embedded` comes from the pool, which may not have that release
        # yet) overwrote the list, it would WIPE the just-detected flag -- so the
        # source the user just played loses its BUILT-IN badge while pool-sourced
        # ones keep theirs. Unioning preserves both.
        _existing_emb = [e for e in ((data.get(mk) or {}).get('embedded') or [])
                         if e]
        _emb_seen = set(e.lower() for e in _existing_emb)
        _merged_emb = list(_existing_emb)
        for _e in (embedded or []):
            if _e and _e.lower() not in _emb_seen:
                _emb_seen.add(_e.lower())
                _merged_emb.append(_e)
        # UNION sync_rel with what's cached, for the same reason as embedded: a
        # CONFIRMED synced release is a durable fact, and a later warm whose pool
        # response happens not to include it (throttle/miss) must not wipe the
        # tick from a release already known-synced.
        _existing_sr = [s for s in ((data.get(mk) or {}).get('sync_rel') or [])
                        if s]
        _sr_seen = set(_existing_sr)
        _merged_sr = list(_existing_sr)
        for _s in (sync_rel or []):
            if _s and _s not in _sr_seen:
                _sr_seen.add(_s)
                _merged_sr.append(_s)
        data[mk] = {'ts': time.time(), 'names': list(names),
                    'embedded': _merged_emb, 'sync_rel': _merged_sr,
                    'ttl': float(ttl or 0), 'warm': 1}
        if len(data) > 400:
            data = dict(sorted(data.items(),
                               key=lambda kv: kv[1].get('ts', 0),
                               reverse=True)[:400])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        _warm_log('store failed: {0}'.format(e), level='WARNING')


def run_warm(info):
    """Background availability warm for ONE title -- runs in MoranSubs's OWN addon
    context (the service queue drainer, or the RunScript fallback), never inside
    POV's process. Two phases so the source window's first-entry wait catches a
    FAST result instead of blocking on the slow one:

      PHASE 1 (fast, ~1-2s, stored before we return): community pool + Wizdom and
        OpenSubtitles fetched CONCURRENTLY, plus any Ktuvit release names ALREADY
        in the shared registry (free -- no live call). This covers the large
        majority of titles and is what the first-entry wait blocks for.

      PHASE 2 (slow, background, never blocks): only when the shared Ktuvit
        registry is missing/stale for this title, a LIVE Ktuvit lookup (login +
        search, ~3-6s) runs in a daemon thread, serialized across warms, and tops
        up the same cache entry + publishes to the shared registry so nobody else
        has to ask Ktuvit again. So Ktuvit's cost is paid once per title globally,
        off the critical path.

    `info` is the payload dict written by _fire_engine_warm. Fully guarded."""
    try:
        import threading
    except Exception:
        threading = None

    _t0 = time.time()
    mk = (info.get('mk') or '').strip()
    if not mk:
        return
    is_ep = (info.get('type') == 'episode')

    def _merge(dst, seen, items):
        added = 0
        for rel in items or []:
            low = (rel or '').strip().lower()
            if low and low not in seen:
                seen.add(low)
                dst.append(rel)
                added += 1
        return added

    _p = {
        'tmdb': info.get('tmdb', ''), 'imdb': info.get('imdb', ''),
        'type': 'episode' if is_ep else 'movie',
        'season': info.get('season', '0') if is_ep else '0',
        'episode': info.get('episode', '0') if is_ep else '0',
        'lang': 'he',
    }
    bridge_info = {
        'imdb_id': info.get('imdb', ''),
        'tmdb_id': info.get('tmdb', ''),
        'title': info.get('title', ''),
        'tvshow': info.get('tvshow', ''),
        'year': info.get('year', ''),
        'season': info.get('season', '') if is_ep else '',
        'episode': info.get('episode', '') if is_ep else '',
        'is_episode': is_ep,
    }

    # Results the two concurrent fetchers write into.
    box = {'av': None, 'os_names': [], 'vd': None}

    def _fetch_pool_wizdom():
        try:
            box['av'] = availability(_p)
        except Exception as e:
            _warm_log('pool/wizdom failed: {0}'.format(e), level='WARNING')

    def _fetch_opensubtitles():
        try:
            from resources.lib import subs_engine_bridge as bridge
            bridge.ensure_engine_settings()
            vd = bridge.build_video_data(bridge_info)
            box['vd'] = vd
            from resources.lib.subs_engine.sources import opensubtitles
            opensubtitles.global_var = []
            opensubtitles.get_subs(vd, True)  # all languages; we keep Hebrew
            names = []
            for d in (opensubtitles.global_var or []):
                lang = (d.get('label') or '').strip().lower()
                code = (d.get('thumbnailImage') or '').strip().lower()
                if lang == 'hebrew' or code in ('he', 'heb', 'iw'):
                    fn = (d.get('filename') or '').strip()
                    if fn:
                        names.append(fn)
            box['os_names'] = names
        except Exception as e:
            _warm_log('opensubtitles failed: {0}'.format(e), level='WARNING')

    # PHASE 1 -- pool+Wizdom and OpenSubtitles CONCURRENTLY, tight timeout.
    if threading is not None:
        t1 = threading.Thread(target=_fetch_pool_wizdom)
        t2 = threading.Thread(target=_fetch_opensubtitles)
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()
        t1.join(timeout=_WARM_FETCH_TIMEOUT)
        t2.join(timeout=_WARM_FETCH_TIMEOUT)
    else:
        _fetch_pool_wizdom()
        _fetch_opensubtitles()

    av = box['av'] or {}
    embedded = av.get('embedded') or []
    sync_rel = av.get('sync_rel') or []
    kt_pool_names = av.get('ktuvit') or []
    kt_checked = av.get('ktuvit_checked') or 0.0
    kt_changed = av.get('ktuvit_changed') or 0.0

    names, seen = [], set()
    _merge(names, seen, av.get('names') or [])
    _merge(names, seen, box['os_names'] or [])

    try:
        from resources.lib import kodi_utils as _ku
        ktuvit_ok = _ku.get_setting('he_match_ktuvit', 'true') != 'false'
    except Exception:
        ktuvit_ok = True
    _now = time.time()
    _KT_SHORT = 8 * 3600.0            # 8 hours while still active
    _KT_LONG = 30 * 24 * 3600.0       # 30 days once stable
    _KT_STABILIZE = 14 * 24 * 3600.0  # "active" window since last growth
    kt_active = (not kt_changed) or ((_now - float(kt_changed)) < _KT_STABILIZE)
    kt_fresh = bool(ktuvit_ok and kt_checked
                    and (_now - float(kt_checked)) < (_KT_SHORT if kt_active else _KT_LONG))
    if kt_fresh:
        _merge(names, seen, kt_pool_names)   # shared registry hit -- free, no call

    _LOCAL_SHORT = 24 * 3600.0        # no Hebrew yet -> re-check ~daily (was 8h)
    _LOCAL_MED = 2 * 24 * 3600.0      # HAS names but Ktuvit still "active"
    _LOCAL_LONG = 7 * 24 * 3600.0     # HAS names, Ktuvit stable

    def _pick_ttl(has_names):
        # A known-good availability answer is cached for a good while REGARDLESS
        # of Ktuvit-active state: the release names we already found don't vanish,
        # and `kt_active` only governs the live-Ktuvit RE-POLL decision above
        # (kt_fresh / _ktuvit_topup), NOT how long we may trust a positive result.
        # The old code returned the SHORT ttl for has-names whenever kt_active
        # (which defaults true for any recent title), so a popular title re-hit
        # the Worker /lookup every 8h for no reason -- the big repeat-lookup lever.
        # COUPLING (accepted): the live-Ktuvit top-up (_ktuvit_topup) only runs
        # INSIDE run_warm, which only fires on a local-cache MISS -- so extending
        # the has-names ttl also raises the floor on how often an "active" title
        # re-polls live Ktuvit (~8h -> ~48h). Fine: the badge is advisory only,
        # and the real fetch path (pool.lookup) keeps its own ~90s cache, so newly
        # added Hebrew is still found the instant the user actually searches.
        if not has_names:
            return _LOCAL_SHORT
        return _LOCAL_MED if (ktuvit_ok and kt_active) else _LOCAL_LONG

    # Store the fast result NOW -- this is what the first-entry wait blocks for.
    _store_avail(mk, names, embedded, _pick_ttl(bool(names)), sync_rel)
    _warm_log('phase1 stored {0} names ({1} embedded) for {2} in {3:.1f}s'.format(
        len(names), len(embedded), mk, time.time() - _t0))

    # PHASE 2 -- live Ktuvit only when the shared registry is stale/missing, in a
    # daemon thread so it NEVER blocks the drainer or the first-entry wait.
    if not (ktuvit_ok and not kt_fresh):
        return

    def _ktuvit_topup():
        try:
            lock = _kt_live_lock()
            if lock is not None:
                lock.acquire()
            try:
                vd = box['vd']
                if vd is None:
                    from resources.lib import subs_engine_bridge as bridge
                    bridge.ensure_engine_settings()
                    vd = bridge.build_video_data(bridge_info)
                if vd is None:
                    return
                from resources.lib.subs_engine.sources import ktuvit as _kt
                _kt.global_var = []
                _kt.get_subs(vd)
                kt_names = []
                for d in (_kt.global_var or []):
                    fn = (d.get('filename') or '').strip()
                    if fn:
                        kt_names.append(fn)
                added = _merge(names, seen, kt_names)
                try:
                    from resources.lib import pool as _pool
                    _pool.report_ktuvit({
                        'tmdb_id': info.get('tmdb', ''),
                        'imdb_id': info.get('imdb', ''),
                        'is_episode': is_ep,
                        'season': info.get('season', '0') if is_ep else '0',
                        'episode': info.get('episode', '0') if is_ep else '0',
                    }, kt_names)
                except Exception:
                    pass
                if added:
                    _store_avail(mk, names, embedded, _pick_ttl(bool(names)),
                                 sync_rel)
                _warm_log('ktuvit top-up added {0} names for {1} '
                          '(total {2}, took {3:.1f}s)'.format(
                              added, mk, len(names), time.time() - _t0))
            finally:
                if lock is not None:
                    lock.release()
        except Exception as e:
            _warm_log('ktuvit top-up failed: {0}'.format(e), level='WARNING')

    if threading is not None:
        threading.Thread(target=_ktuvit_topup, daemon=True).start()
    else:
        _ktuvit_topup()


def _seed_from_pool(key, pl):
    """Write the shared-pool result of the one-shot first-entry lookup into the
    local cache (names = pool-human + Ktuvit-registry, plus embedded flags), with
    a short TTL so the full background warm still refreshes it with Wizdom/OS
    shortly after. So the badge shows the SHARED data on the very first entry --
    on every device -- instead of only after that device's own warm."""
    try:
        names, seen = [], set()
        for rel in list(pl.get('names') or []) + list(pl.get('ktuvit') or []):
            low = (rel or '').strip().lower()
            if low and low not in seen:
                seen.add(low)
                names.append(rel)
        embedded = [r for r in (pl.get('embedded') or []) if r]
        sync_rel = [r for r in (pl.get('sync_rel') or []) if r]
        path = _engine_cache_path()
        if not path:
            return names
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        # Preserve any sync_rel a prior warm already cached (union), so this
        # short-TTL first-entry seed never wipes a known-synced tick.
        _prev_sr = [s for s in ((data.get(key) or {}).get('sync_rel') or []) if s]
        for _s in _prev_sr:
            if _s not in sync_rel:
                sync_rel.append(_s)
        data[key] = {'ts': time.time(), 'names': names,
                     'embedded': embedded, 'sync_rel': sync_rel,
                     'ttl': _AVAIL_TTL_NONE}
        if len(data) > 400:
            data = dict(sorted(data.items(),
                               key=lambda kv: kv[1].get('ts', 0),
                               reverse=True)[:400])
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + '.stmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass
        return names
    except Exception:
        return [n for n in (pl.get('names') or []) if n]


def release_names(meta):
    """Hebrew-subtitle release names available for this media. Normally a pure
    cache read (the background warm fills pool + Wizdom + OpenSubtitles + Ktuvit
    off the source list, so the old multi-second freeze is gone). On a cache
    MISS we also do ONE quick, tightly-capped /lookup to the SHARED pool so the
    badge shows the shared data on the FIRST entry -- on every device -- not just
    after that device's own warm. The full warm still runs in the background to
    add Wizdom/OS. [] when disabled / unknown."""
    try:
        if not _enabled():
            return []
        p = _media_params(meta)
        if not p:
            return []
        key = _media_key(p)
        names = _cached_names(key)
        if names is not None:
            return names
        # Cache miss. Kick the full in-service warm (pool+Wizdom+OS+Ktuvit),
        # which runs in MoranSubs's OWN process where it can SIGN the pool
        # /lookup. We no longer make a synchronous pool peek HERE: this POV
        # interpreter can't sign the request (no pool key), so that peek always
        # got HTTP 426 and returned nothing while still costing a Worker
        # invocation. Instead we wait briefly for the signed warm to land its
        # result (incl. pool names) in the shared cache -- identical first-entry
        # UX, one fewer wasted request per title.
        _fire_engine_warm(key, p, meta)
        deadline = time.time() + _FIRST_ENTRY_WAIT
        # Poll the shared cache the in-service warm writes; 'warm' marks its full
        # result so we don't return a half-filled entry by mistake.
        while time.time() < deadline:
            time.sleep(0.12)
            ent = _cache_entry(key)
            if ent is not None and ent.get('warm'):
                n = [x for x in (ent.get('names') or []) if x]
                _dbg('first-entry wait: warm landed for ' + key
                     + (' (%d names)' % len(n)))
                return n
        _dbg('first-entry wait: timed out (~%.1fs) for %s' % (_FIRST_ENTRY_WAIT, key))
        return []
    except Exception:
        return []


def prewarm(meta):
    """Kick the background availability warm EARLY -- called at the START of
    POV's source scrape (before get_sources), so the OpenSubtitles/Wizdom/Ktuvit
    warm runs CONCURRENTLY with the ~1.5-3s scrape and the cache is ready by the
    time the source dialog opens. That's what makes the Hebrew % show on the
    FIRST entry for titles whose subs live on OS/Ktuvit (not the shared pool),
    instead of only the 2nd/3rd. No network in THIS call (only fires the
    throttled fire-and-forget RunScript); no-op when disabled / already cached /
    no id."""
    try:
        if not _enabled():
            _dbg('prewarm skip (disabled)')
            return
        p = _media_params(meta)
        if not p:
            _dbg('prewarm skip (no media id in meta)')
            return
        key = _media_key(p)
        if _cached_names(key) is not None:
            _dbg('prewarm skip (already warm) ' + key)
            return  # already warm -- nothing to do
        _dbg('prewarm fired ' + key)
        _fire_engine_warm(key, p, meta)
    except Exception as e:
        _dbg('prewarm crashed: ' + repr(e))


def embedded_names(meta):
    """Release names flagged (by the community) as carrying a built-in Hebrew
    track, for THIS media. Pure cache read; [] when none / not warmed yet."""
    try:
        if not _enabled():
            return []
        p = _media_params(meta)
        if not p:
            return []
        _emb = _cached_embedded(_media_key(p))
        try:
            from resources.lib import kodi_utils as _ku
            _ku.log('embedded_names {0}: {1}'.format(_media_key(p), _emb),
                    level='INFO')
        except Exception:
            pass
        return _emb
    except Exception:
        return []


def merge_names(meta, names):
    """Write-through: UNION freshly-found Hebrew release names into the local
    availability cache. Called by the live search (auto-on-play / the subtitle
    picker) so the source-screen badge reflects what was ACTUALLY found, instead
    of lagging behind a possibly-staler background warm. This is what fixes "the
    picker shows a 33% Ktuvit sub but the poster badge says 25%": the moment the
    search sees that sub, its release is written here, so the badge picks it up.
    Union-only, so it never drops what the warm already found. Safe + atomic."""
    try:
        if not _enabled():
            return
        p = _media_params(meta)
        if not p:
            return
        clean = [(_n or '').strip() for _n in (names or []) if (_n or '').strip()]
        if not clean:
            return
        key = _media_key(p)
        path = _engine_cache_path()
        if not path:
            return
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        ent = data.get(key) or {}
        existing = [n for n in (ent.get('names') or []) if n]
        seen = set(n.lower() for n in existing)
        merged = list(existing)
        for n in clean:
            low = n.lower()
            if low not in seen:
                seen.add(low)
                merged.append(n)
        if merged == existing:
            return   # nothing new -- skip the write
        ent['names'] = merged
        ent['ts'] = time.time()
        ent.setdefault('embedded', ent.get('embedded') or [])
        # Keep it fresh-ish so the warm still refreshes from the network later.
        if not ent.get('ttl'):
            ent['ttl'] = _AVAIL_TTL_NONE
        data[key] = ent
        # Bound the file the same way the warm does (newest ~400 titles).
        if len(data) > 400:
            newest = sorted(data.items(),
                            key=lambda kv: kv[1].get('ts', 0),
                            reverse=True)[:400]
            data = dict(newest)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + '.wtmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass
    except Exception:
        pass


def merge_embedded(meta, releases):
    """Write-through: UNION release names carrying a BUILT-IN Hebrew track into
    the local availability cache's `embedded` list, so the source screen flags
    'HEB BUILT-IN 101%' IMMEDIATELY on this device -- instead of only after the
    next background warm re-reads the pool (which is what made a track detected
    at play vanish from the source list when you went back). Mirrors merge_names
    (which does this for external-sub names). pool.report_embedded still
    propagates it to every other device; this fixes the reporting device's own
    view lagging. Union-only, atomic, never raises."""
    try:
        if not _enabled():
            return
        p = _media_params(meta)
        if not p:
            return
        clean = [(_r or '').strip() for _r in (releases or []) if (_r or '').strip()]
        if not clean:
            return
        key = _media_key(p)
        path = _engine_cache_path()
        if not path:
            return
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        ent = data.get(key) or {}
        existing = [n for n in (ent.get('embedded') or []) if n]
        seen = set(n.lower() for n in existing)
        merged = list(existing)
        for n in clean:
            low = n.lower()
            if low not in seen:
                seen.add(low)
                merged.append(n)
        try:
            from resources.lib import kodi_utils as _ku
            _ku.log('merge_embedded {0}: existing={1} +{2} -> {3}'.format(
                key, existing, clean, merged), level='INFO')
        except Exception:
            pass
        if merged == existing:
            return   # nothing new -- skip the write
        ent['embedded'] = merged
        ent.setdefault('names', ent.get('names') or [])
        ent['ts'] = time.time()
        if not ent.get('ttl'):
            ent['ttl'] = _AVAIL_TTL_NONE
        data[key] = ent
        if len(data) > 400:
            newest = sorted(data.items(),
                            key=lambda kv: kv[1].get('ts', 0),
                            reverse=True)[:400]
            data = dict(newest)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + '.wtmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass
    except Exception:
        pass


def _tokens(s):
    # MUST mirror translate._match_pct so the source-screen badge and the
    # subtitle picker's % agree (the user saw 29% on the poster but 33% in the
    # picker for the same source -- because the two used different algorithms).
    s = re.sub(r'\.[a-z0-9]{2,4}$', '', s or '', flags=re.I)
    for ch in '_ +/-':
        s = s.replace(ch, '.')
    return [x.lower() for x in s.split('.') if x]


_RM = None
_RM_TRIED = False


def _release_match_mod():
    """release_match (the ONE structured scorer, SubSync S1), importable both
    in MoranSubs's own process AND in POV's interpreter where only
    resources/lib is on sys.path (so try the flat import too). None when
    unavailable -> difflib fallback keeps the badge working."""
    global _RM, _RM_TRIED
    if _RM_TRIED:
        return _RM
    _RM_TRIED = True
    try:
        from resources.lib import release_match as _m
        _RM = _m
    except Exception:
        try:
            import release_match as _m
            _RM = _m
        except Exception:
            _RM = None
    return _RM


def _score(src_release, sub_release):
    """Release-name match %, IDENTICAL to translate._match_pct (both delegate
    to release_match) so the badge on the source screen and the % shown in
    the subtitle picker are the same number for the same source + sub."""
    rm = _release_match_mod()
    if rm is not None:
        try:
            return rm.match_pct(src_release, sub_release)
        except Exception:
            pass
    import difflib
    a = _tokens(src_release)
    b = _tokens(sub_release)
    if not a or not b:
        return 0
    try:
        return int(round(difflib.SequenceMatcher(None, a, b).ratio() * 100))
    except Exception:
        return 0


def best_score(src_release, names):
    try:
        if not names or not src_release:
            return 0
        return max((_score(src_release, n) for n in names), default=0)
    except Exception:
        return 0


def label_prefix(src_release, names, embedded=None, alt_release='',
                 synced_releases=None):
    """A small coloured prefix for the START of the source's info line, or ''
    when there's no usable match.

    If this source's release matches one the community flagged as carrying a
    BUILT-IN Hebrew track, it gets a distinct top-priority green badge
    ('HEB BUILT-IN 101%') so everyone knows it already has Hebrew and is well
    worth picking. Otherwise a normal 'HEB <NN>%' match badge: green high /
    amber mid / red low.

    When `synced_releases` (the community-CONFIRMED set from confirmed_releases)
    contains THIS row's normalized release, the badge gains a trailing 'SYNC'
    tag and turns bright green -- "the community verified a synced Hebrew
    subtitle for this exact release". We use the ASCII word 'SYNC' rather than a
    check-mark glyph (U+2713): that glyph is MISSING from some skin fonts (NOX's
    among them) and renders as an empty tofu box -- plain ASCII letters render in
    every font on every skin. Kept LTR (no Hebrew) so it never triggers bidi
    reordering / clipping of the badge.

    Deliberately LTR-only (no Hebrew letters): a Hebrew word inline in the
    mostly-English info line triggers bidi reordering (it jumps to the end) and
    gets clipped when the line is full. An LTR badge stays at the start and
    always shows, since the line truncates from the end."""
    try:
        # Embedded Hebrew = best possible: it's already in the file. We treat a
        # high token overlap with a flagged release as a match (same scorer as
        # the % badge, threshold 80) so it survives small release-name diffs.
        # Score against BOTH the row's URLName (src_release) AND its name
        # (alt_release) and take the max: the flag is stored at play from the
        # 'name' field (via picked_release/_release_from) while the row is
        # displayed/scored by URLName, and POV makes those two fields differ --
        # so matching either identifier is what lets a just-played release light
        # up BUILT-IN instead of dropping to the % badge.
        if embedded and (src_release or alt_release):
            emb_best = max(best_score(src_release, embedded),
                           best_score(alt_release, embedded))
            if emb_best >= 40:
                try:
                    from resources.lib import kodi_utils as _ku
                    _ku.log('built-in check: emb_best={0} src={1!r} alt={2!r} '
                            'emb={3}'.format(emb_best, src_release, alt_release,
                                             embedded), level='INFO')
                except Exception:
                    pass
            if emb_best >= 80:
                return '[COLOR FF2ECC71][B]HEB BUILT-IN 101%[/B][/COLOR] | '
        # Community-CONFIRMED synced record for this exact release (strongest
        # signal: a human verified the Hebrew is in sync). Overrides the amber/
        # red name-match colour -- if the registry says this release has a synced
        # sub, it's the pick to make regardless of the name-similarity guess.
        synced = False
        try:
            if synced_releases:
                for _r in (src_release, alt_release):
                    if _r and _worker_norm(_r) in synced_releases:
                        synced = True
                        break
        except Exception:
            synced = False
        best = best_score(src_release, names)
        if best <= 0:
            # No name-match, but if the community confirmed THIS release is
            # synced, still surface it (a synced Hebrew sub exists for it).
            if synced:
                return '[COLOR FF2ECC71][B]HEB SYNC[/B][/COLOR] | '
            return ''
        if synced:
            return '[COLOR FF2ECC71][B]HEB {0}% SYNC[/B][/COLOR] | '.format(best)
        if best >= 66:
            color = 'FF49C46A'
        elif best >= 33:
            color = 'FFE0B23C'
        else:
            color = 'FFD0594F'
        return '[COLOR {0}][B]HEB {1}%[/B][/COLOR] | '.format(color, best)
    except Exception:
        return ''
