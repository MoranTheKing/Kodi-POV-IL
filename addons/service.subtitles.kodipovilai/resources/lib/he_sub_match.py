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

# Engine (OpenSubtitles) availability is filled by a background RunScript into a
# shared cache file; we read it cheaply on every call so the badge fills in on
# the next source-window open without ever blocking POV.
_ENGINE_CACHE_FILE = (
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'he_avail_cache.json')
_ENGINE_TTL = 7 * 24 * 3600.0   # 7 days; used once HUMAN Hebrew has been found
# When NO human Hebrew exists yet (likely brand-new content), re-warm MUCH more
# often so a sub that appears within hours shows up fast for everyone -- new
# releases get human Hebrew within ~24h, and a 7-day cache would hide it.
_AVAIL_TTL_NONE = 8 * 3600.0    # 8 hours
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


def _enabled():
    try:
        import xbmcaddon
        v = (xbmcaddon.Addon(_ADDON_ID).getSetting('show_subtitle_match')
             or '').strip().lower()
        return v != 'false'   # default ON when unset
    except Exception:
        return True


def _media_params(meta):
    """Pull {tmdb,imdb,type,season,episode} out of POV's meta dict, defensively
    (only imdb_id/media_type/season/episode are guaranteed present)."""
    if not meta:
        return None
    g = meta.get
    imdb = str(g('imdb_id') or g('imdb') or '').strip()
    tmdb = str(g('tmdb_id') or g('tmdb') or '').strip()
    if not (imdb or tmdb):
        return None
    season = str(g('season') or g('custom_season') or '0').strip() or '0'
    episode = str(g('episode') or g('custom_episode') or '0').strip() or '0'
    mt = str(g('media_type') or '').strip().lower()
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


def _pool_lookup(p, timeout=None):
    """One /lookup call -> dict with the pool's Hebrew data for this media:
        {'names': [...],          pool-contributed Hebrew release names
         'embedded': [...],       releases flagged as carrying built-in Hebrew
         'ktuvit': [...],         Hebrew release names cached from Ktuvit
         'ktuvit_checked': <ts>}  when Ktuvit was last checked (0 = never)
    All keyed by release name so they match across debrid providers. Networked.
    `timeout` overrides the default (the source window uses a tight cap for its
    one allowed synchronous first-entry call)."""
    out = {'names': [], 'embedded': [], 'ktuvit': [],
           'ktuvit_checked': 0.0, 'ktuvit_changed': 0.0}
    try:
        q = _parse.urlencode({k: v for k, v in p.items() if v})
        req = _req.Request(POOL_URL + '/lookup?' + q,
                           headers={'user-agent': _UA})
        raw = _req.urlopen(req, timeout=(timeout or _TIMEOUT)).read().decode('utf-8')
        data = json.loads(raw)
        if data.get('ok'):
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
        pl = _pool_lookup(p)
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
        'ktuvit_checked': pl.get('ktuvit_checked') or 0.0,
        'ktuvit_changed': pl.get('ktuvit_changed') or 0.0,
    }


def _warm_log(msg, level='INFO'):
    try:
        from resources.lib import kodi_utils
        kodi_utils.log('he_avail: ' + msg, level=level)
    except Exception:
        pass


def _store_avail(mk, names, embedded, ttl):
    """Write {mk: {ts, names, embedded, ttl}} into the shared he_avail cache the
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
        data[mk] = {'ts': time.time(), 'names': list(names),
                    'embedded': list(embedded or []), 'ttl': float(ttl or 0)}
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
    """Full background availability warm for ONE title -- runs in MoranSubs's
    OWN addon context (the service queue drainer, or the RunScript fallback),
    never inside POV's process. Gathers every Hebrew-availability source and
    writes the merged result to the shared cache the badge reads next open:
      * community pool + Wizdom, and OpenSubtitles -- fetched CONCURRENTLY so the
        warm finishes inside POV's ~2s scrape window (that's what makes the % show
        on the FIRST entry, not the 2nd/3rd);
      * the pool's embedded-Hebrew flags -> the "BUILT-IN" badge;
      * Ktuvit -- ONLY via the shared registry / as a gated fallback, at most
        ~once per title globally, so the one shared account is never hammered.
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
        for rel in items or []:
            low = (rel or '').strip().lower()
            if low and low not in seen:
                seen.add(low)
                dst.append(rel)

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

    # 1+2) Pool+Wizdom and OpenSubtitles CONCURRENTLY (the slow part).
    if threading is not None:
        t1 = threading.Thread(target=_fetch_pool_wizdom)
        t2 = threading.Thread(target=_fetch_opensubtitles)
        t1.start()
        t2.start()
        t1.join(timeout=8.0)
        t2.join(timeout=8.0)
    else:
        _fetch_pool_wizdom()
        _fetch_opensubtitles()

    av = box['av'] or {}
    embedded = av.get('embedded') or []
    kt_pool_names = av.get('ktuvit') or []
    kt_checked = av.get('ktuvit_checked') or 0.0
    kt_changed = av.get('ktuvit_changed') or 0.0

    names, seen = [], set()
    _merge(names, seen, av.get('names') or [])
    _merge(names, seen, box['os_names'] or [])

    # 3) Ktuvit via the SHARED registry -- at most ~once per title globally.
    #    Re-check often while a title is still GAINING Hebrew, back off once
    #    stable. Gated by `he_match_ktuvit`. Needs the OpenSubtitles video data.
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
    if ktuvit_ok:
        _kt_ttl = _KT_SHORT if kt_active else _KT_LONG
        fresh = kt_checked and (_now - float(kt_checked)) < _kt_ttl
        if fresh:
            _merge(names, seen, kt_pool_names)   # shared cache hit -- no call
        else:
            vd = box['vd']
            if vd is None:
                try:
                    from resources.lib import subs_engine_bridge as bridge
                    bridge.ensure_engine_settings()
                    vd = bridge.build_video_data(bridge_info)
                except Exception:
                    vd = None
            if vd is not None:
                try:
                    from resources.lib.subs_engine.sources import ktuvit as _kt
                    _kt.global_var = []
                    _kt.get_subs(vd)
                    kt_names = []
                    for d in (_kt.global_var or []):
                        fn = (d.get('filename') or '').strip()
                        if fn:
                            kt_names.append(fn)
                    _merge(names, seen, kt_names)
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
                except Exception as e:
                    _warm_log('ktuvit check failed: {0}'.format(e),
                              level='WARNING')

    _LOCAL_SHORT = 8 * 3600.0
    _LOCAL_LONG = 7 * 24 * 3600.0
    if not names:
        local_ttl = _LOCAL_SHORT
    elif ktuvit_ok and kt_active:
        local_ttl = _LOCAL_SHORT
    else:
        local_ttl = _LOCAL_LONG
    _store_avail(mk, names, embedded, local_ttl)
    _warm_log('stored {0} Hebrew release names ({1} embedded) for {2} '
              '(ttl={3}h, warm took {4:.1f}s)'.format(
                  len(names), len(embedded), mk, int(local_ttl / 3600),
                  time.time() - _t0))


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
        data[key] = {'ts': time.time(), 'names': names,
                     'embedded': embedded, 'ttl': _AVAIL_TTL_NONE}
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
        # Cache miss. Kick the full background warm (Wizdom/OS/Ktuvit-live)...
        _fire_engine_warm(key, p, meta)
        # ...and do ONE quick shared-pool lookup so the first entry isn't blank.
        # Tight timeout so the source window can never stall more than ~1s.
        try:
            pl = _pool_lookup(p, timeout=_FIRST_ENTRY_TIMEOUT)
            return _seed_from_pool(key, pl)
        except Exception:
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
        return _cached_embedded(_media_key(p))
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


def _tokens(s):
    # MUST mirror translate._match_pct so the source-screen badge and the
    # subtitle picker's % agree (the user saw 29% on the poster but 33% in the
    # picker for the same source -- because the two used different algorithms).
    s = re.sub(r'\.[a-z0-9]{2,4}$', '', s or '', flags=re.I)
    for ch in '_ +/-':
        s = s.replace(ch, '.')
    return [x.lower() for x in s.split('.') if x]


def _score(src_release, sub_release):
    """Release-name match %, IDENTICAL to translate._match_pct (difflib token
    sequence ratio) so the badge on the source screen and the % shown in the
    subtitle picker are the same number for the same source + sub."""
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


def label_prefix(src_release, names, embedded=None):
    """A small coloured prefix for the START of the source's info line, or ''
    when there's no usable match.

    If this source's release matches one the community flagged as carrying a
    BUILT-IN Hebrew track, it gets a distinct top-priority green badge
    ('HEB BUILT-IN 101%') so everyone knows it already has Hebrew and is well
    worth picking. Otherwise a normal 'HEB <NN>%' match badge: green high /
    amber mid / red low.

    Deliberately LTR-only (no Hebrew letters): a Hebrew word inline in the
    mostly-English info line triggers bidi reordering (it jumps to the end) and
    gets clipped when the line is full. An LTR badge stays at the start and
    always shows, since the line truncates from the end."""
    try:
        # Embedded Hebrew = best possible: it's already in the file. We treat a
        # high token overlap with a flagged release as a match (same scorer as
        # the % badge, threshold 80) so it survives small release-name diffs.
        if embedded and src_release:
            emb_best = best_score(src_release, embedded)
            if emb_best >= 80:
                return '[COLOR FF2ECC71][B]HEB BUILT-IN 101%[/B][/COLOR] | '
        best = best_score(src_release, names)
        if best <= 0:
            return ''
        if best >= 66:
            color = 'FF49C46A'
        elif best >= 33:
            color = 'FFE0B23C'
        else:
            color = 'FFD0594F'
        return '[COLOR {0}][B]HEB {1}%[/B][/COLOR] | '.format(color, best)
    except Exception:
        return ''
