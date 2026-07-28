# Bridge between MoranSubs and the vendored DarkSubs fetch engine
# (resources/lib/subs_engine). Phase B2 of the unification.
#
# The whole module is GATED behind the `use_builtin_engine` setting
# (default OFF). When the gate is off every public entry point returns
# an empty/neutral result WITHOUT importing the engine at all, so the
# default behavior of the addon is exactly as before -- DarkSubs keeps
# running as its own addon and nothing here executes.
#
# When the gate is on, MoranSubs searches the human subtitle sources
# itself (Ktuvit, Wizdom, OpenSubtitles, ...) via the vendored engine,
# and surfaces the found HEBREW subtitles in the normal subtitle list.
# Translation of non-Hebrew sources is still done by MoranSubs's own
# AI/pool path (translate.py) -- the engine's own machine-translate
# (auto_translate) stays OFF; this bridge never invokes it.
#
# Design rules:
#   * Lazy imports only. The engine is imported inside functions, never
#     at module load, so importing this module is free and safe even on
#     a clean repo install where subs_engine is excluded.
#   * Every public function is wrapped so a failure degrades to "no
#     engine results" instead of breaking the subtitle dialog.

import json
import os
import re
import time
import urllib.parse

from . import kodi_utils


# Tokens that mark a string as a real release name (vs a clean title or a
# debrid token). Used to pick the best release name for sync-% matching.
_REL_PATTERNS = (
    r'(?:19|20)\d{2}',
    r'(?:360|480|576|720|1080|2160)p',
    r'web.?dl|webrip|web|bluray|blu.?ray|brrip|bdrip|hdtv|hdrip|dvdrip|remux|hdcam',
    r'x26[45]|h\.?26[45]|hevc|avc|xvid|10bit',
    r'aac|ac3|e?ac.?3|dts|ddp?5|atmos|dd\+|truehd|multi',
    r'-[a-z0-9]{2,}$',
)


def _release_score(s):
    """Heuristic: how much a string looks like a scene/web release name."""
    if not s:
        return 0
    s2 = s.lower()
    sc = sum(1 for p in _REL_PATTERNS if re.search(p, s2))
    if s2.count('.') >= 3 or s2.count(' ') >= 3:
        sc += 1
    return sc


def _detect_release_name(info):
    """Pick the best available release name for sync-% matching. The player
    filepath is often a tokenized debrid URL, while the real release name
    lives in the ListItem path / label / tagline -- so we score every
    candidate and take the most release-like one."""
    cands = []
    # POV's captured pick is the most reliable release name -- prefer it.
    pr = (info.get('picked_release') or '').strip()
    if pr:
        cands.append(pr)
    for key in ('filepath', 'li_filename'):
        v = (info.get(key) or '').strip()
        if v:
            try:
                cands.append(os.path.basename(v.rstrip('/')) or v)
            except Exception:
                cands.append(v)
    for key in ('label', 'tagline', 'title'):
        v = (info.get(key) or '').strip()
        if v:
            cands.append(v)
    best, best_score = '', -1
    for c in cands:
        sc = _release_score(c)
        # tie-break: prefer the longer (more specific) string
        if sc > best_score or (sc == best_score and len(c) > len(best)):
            best, best_score = c, sc
    return best


def _release_ready(info):
    """True once a REAL release name is available (not just the show/movie
    title). The sync-% is computed from the release name; right after an
    auto-advance to the next episode the real release (POV's picked_release,
    the ListItem path, or the tagline) lags the title by a moment, during
    which every match is 0%. We use this to (a) make autosub wait for the
    release before its pre-search and (b) refuse to cache a search done before
    the release settled -- which is why users previously had to exit + re-enter
    the subtitle list to get correct percentages."""
    if (info.get('picked_release') or '').strip():
        return True
    if (info.get('li_filename') or '').strip():
        return True
    if (info.get('tagline') or '').strip():
        return True
    fp = (info.get('filepath') or '').strip()
    # A real local file path is itself the release name; a stream / debrid
    # token URL is not, so for those we wait for one of the fields above.
    if fp and '://' not in fp:
        return True
    return False


def enabled():
    """Master gate. False => this whole module is inert."""
    try:
        return kodi_utils.get_bool('use_builtin_engine', False)
    except Exception:
        return False


# Defaults for the engine's internal settings. These are declared in
# settings.xml as hidden label-control entries (so they don't render as
# stray toggles), but Kodi does NOT auto-apply a <default> to a label
# control -- getSetting() comes back ''. The engine then crashes on
# int('') at import and, even past that, reads every language flag as ''
# (== 'true' is False) so Hebrew search is silently disabled. So we write
# these values ourselves before the engine is ever imported. Only keys
# with a non-empty intended default are listed (empty-default keys like
# other_lang / the OS_* credentials are correct as '').
# all_lang=true makes the global providers (OpenSubtitles, Subscene,
# SubSource, YIFY) return EVERY language, not just Hebrew+English -- this is
# why DarkSubs returned far more results in more languages. We match that.
_ENGINE_DEFAULTS = {
    'language_hebrew': 'true',
    'language_english': 'true',
    'language_russian': 'false',
    'language_arab': 'false',
    'all_lang': 'true',
    'retry_search_with_all_langs': 'true',
    'auto_translate': 'false',
    'translate_p': '0',
    # max_search_time is NOT here on purpose: it's a user-facing setting now
    # (Settings > engine), so we must never force-overwrite the user's choice.
    'subtitle_trans_cache': '15',
    'enable_autosub_notifications': 'true',
    'auto_fix_sub_punctuation': 'true',
    'auto_remove_hi_tags': 'false',
    'show_debug': 'false',
    # Telegram channel is mostly low-quality machine translations and needs a
    # per-user login -> OFF by default (force it off once via the version bump).
    'telegram': 'false',
}

# Bump when _ENGINE_DEFAULTS changes so the new values are force-applied to
# installs that already have the old values written.
_ENGINE_DEFAULTS_VERSION = '4'


def ensure_engine_settings():
    """Populate the engine's internal settings. MUST run before the engine is
    imported (general.py reads max_search_time at module load). Writes empty
    settings always; force-rewrites everything once when the defaults version
    changes (so existing installs pick up new defaults like all_lang)."""
    try:
        from resources.lib import kodi_utils
        addon = kodi_utils.addon()
    except Exception:
        return
    try:
        force = (addon.getSetting('_engine_defaults_v') or '') \
            != _ENGINE_DEFAULTS_VERSION
    except Exception:
        force = False
    for k, v in _ENGINE_DEFAULTS.items():
        try:
            if force or (addon.getSetting(k) or '') == '':
                addon.setSetting(k, v)
        except Exception:
            pass
    if force:
        try:
            addon.setSetting('_engine_defaults_v', _ENGINE_DEFAULTS_VERSION)
        except Exception:
            pass



# ---- video_data construction ---------------------------------------

def build_video_data(info):
    """Map MoranSubs's current_video_info() dict to the `video_data`
    dict the vendored engine + its providers expect.

    The engine and providers read a wide set of keys (some via
    bracket access that would KeyError if missing), so we populate
    every key the vendored code touches with a safe default.
    """
    imdb = (info.get('imdb_id') or '').strip()
    # Providers expect the bare tt-id form; normalize if a plain
    # numeric id slipped through (some skins report it without 'tt').
    if imdb and not imdb.startswith('tt') and imdb.isdigit():
        imdb = 'tt' + imdb

    is_episode = bool(info.get('is_episode')
                      or (info.get('tvshow') and info.get('episode')))
    media_type = 'tv' if is_episode else 'movie'

    title = (info.get('title') or '').strip()
    tvshow = (info.get('tvshow') or '').strip()

    # Release name used by sort_subtitles to compute the sync %. The player
    # filepath is often a tokenized debrid URL, so we score every candidate
    # (filepath, ListItem path, label, tagline, title) and feed the most
    # release-like one into BOTH file_original_path and Tagline. This is why
    # our %s were far lower than DarkSubs' -- we were matching a token.
    release = _detect_release_name(info) or tvshow or title

    vd = {
        'imdb': imdb,
        'IMDBNumber': imdb,
        'imdb_UniqueID': imdb,
        'tmdb': (info.get('tmdb_id') or '').strip(),
        'title': title,
        'OriginalTitle': title,
        'TVShowTitle': tvshow,
        'year': info.get('year') or '',
        'season': info.get('season') or '',
        'episode': info.get('episode') or '',
        'media_type': media_type,
        'media_type_ListItem.DBTYPE': media_type,
        'media_type_videoInfoTag': media_type,
        'file_original_path': release or '',
        'Tagline': release or '',
        'Tagline_From_Fen': release or '',
        'VideoPlayer.Tagline': release or '',
        'mpaa': '',
        'is_local_media_playing': 'false',
        'state': '',
    }
    return vd


# ---- provider module lookup ----------------------------------------

# site_id (from sort_subtitles) -> provider source name used in the
# download URL's source= param. We resolve the provider module by the
# source name parsed from the URL, so this map is only a fallback.
_SOURCE_MODULES = (
    'ktuvit', 'wizdom', 'telegram', 'opensubtitles',
    'yify', 'subsource', 'subscene', 'bsplayer',
)


def _provider_module(source):
    """Return the already-imported vendored provider module for a
    given source name (e.g. 'wizdom'). Returns None if unknown.

    We import the package's source modules directly rather than
    relying on the engine's __import__(source)+sys.path dance (which
    assumed DarkSubs's resources/sources layout that doesn't exist
    inside MoranSubs)."""
    if source not in _SOURCE_MODULES:
        return None
    try:
        mod = __import__(
            'resources.lib.subs_engine.sources.' + source,
            fromlist=[source])
        return mod
    except Exception as e:
        kodi_utils.log('subs_engine_bridge: provider import failed '
                       '({0}): {1}'.format(source, e), level='WARNING')
        return None


# ---- search ---------------------------------------------------------

def _parse_download_url(url):
    """Pull the source / language / filename / download_data params
    out of a provider's plugin:// download URL. Returns a dict or
    None if the URL isn't parseable."""
    try:
        q = urllib.parse.urlparse(url).query
        params = dict(urllib.parse.parse_qsl(q, keep_blank_values=True))
    except Exception:
        return None
    source = params.get('source', '')
    if not source:
        return None
    dd_raw = params.get('download_data', '')
    download_data = {}
    if dd_raw:
        try:
            download_data = json.loads(dd_raw)
        except Exception:
            download_data = {}
    # Some providers (wizdom) also pass id= / filename= alongside the
    # JSON blob; fold them in so download() has everything.
    for k in ('id', 'filename', 'language'):
        if k in params and k not in download_data:
            download_data.setdefault(k, params[k])
    return {
        'source': source,
        'language': params.get('language', ''),
        'filename': params.get('filename', '') or download_data.get(
            'filename', ''),
        'download_data': download_data,
    }


def search(info, modal_progress=True):
    """Return MoranSubs candidate dicts for the subtitles the engine
    found. Empty list when the gate is off or anything fails.

    modal_progress: show the DarkSubs-style modal progress dialog while
    searching (manual "Download Subtitles" flow). The auto-on-play path
    passes False -- it shows its own non-modal banner instead.

    Each candidate matches translate.list_candidates' schema, carries a
    link of type 'engine' that resolve() routes back here for download,
    and is tagged with '_engine_kind' in {'human_he','mt_he','other'} so
    list_candidates can order them (Hebrew first, other languages last).
    """
    if not enabled():
        return []
    # The sync-% is computed against the release name. Right after an
    # auto-advance to the next episode the player metadata is still
    # transitioning, so the release name is briefly empty and every match
    # comes back 0%. We must NOT cache such a transient result -- otherwise
    # the 0%-list sticks for 24h and the user has to exit + re-enter the
    # subtitle list to get a fresh (correct) search. So the result cache is
    # only consulted/written once a real release name is available.
    cacheable = _release_ready(info)
    # Result cache: a repeat open of the same title returns instantly
    # instead of re-running every provider (this is a big part of why
    # DarkSubs feels faster -- it caches its sorted results for 24h).
    if cacheable:
        cached = _cache_get(info)
        # Only a NON-EMPTY cached result counts as a hit. An empty cached list
        # is treated as a miss so we re-search -- this also lets devices that
        # already have a poisoned empty entry recover immediately instead of
        # waiting 24h for it to expire.
        if cached:
            return cached
    try:
        out = _search_inner(info, modal_progress=modal_progress)
        # NEVER cache an empty / failed search. A transient timeout, rate-limit
        # (429) or network hiccup returns [] -- caching that would hide every
        # source for 24h (the user sees only the community pool). DarkSubs's
        # cache does the same: it returns an empty result without storing it.
        if cacheable and out:
            _cache_put(info, out)
        return out
    except Exception as e:
        kodi_utils.log('subs_engine_bridge.search failed: {0}'.format(e),
                       level='WARNING')
        # The engine is experimental and the user explicitly turned it on,
        # so make a failure visible instead of silently showing nothing.
        try:
            kodi_utils.notify('מנוע מקורות: שגיאה — {0}'.format(
                str(e)[:80]), time_ms=5000)
        except Exception:
            pass
        return []


# ---- result cache (per media, short TTL) ----------------------------

_CACHE_TTL = 24 * 3600  # seconds (matches DarkSubs's 24h search-result cache)


def _cache_key(info):
    mid = (info.get('imdb_id') or info.get('tmdb_id') or '').strip()
    if not mid:
        return None
    # Include a signature of the ENABLED sources so toggling a source (e.g.
    # turning Ktuvit off) invalidates old cached results instead of serving
    # 6h-stale results that still contain the now-disabled source.
    sig = ''
    try:
        from resources.lib import kodi_utils
        a = kodi_utils.addon()
        for s in ('ktuvit', 'wizdom', 'telegram', 'opensubtitles',
                  'yify', 'subsource', 'subscene', 'bsplayer', 'all_lang'):
            sig += '1' if (a.getSetting(s) or '') == 'true' else '0'
    except Exception:
        sig = ''
    return '{0}_s{1}_e{2}_{3}'.format(
        mid, info.get('season') or '0', info.get('episode') or '0', sig)


def _cache_dir():
    try:
        import xbmcvfs
        from resources.lib import kodi_utils
        base = xbmcvfs.translatePath(
            kodi_utils.addon().getAddonInfo('profile'))
        d = os.path.join(base, 'engine_cache')
        if not os.path.isdir(d):
            os.makedirs(d)
        return d
    except Exception:
        return None


def _cache_get(info):
    key = _cache_key(info)
    d = _cache_dir()
    if not key or not d:
        return None
    p = os.path.join(d, key + '.json')
    try:
        if not os.path.isfile(p):
            return None
        if time.time() - os.path.getmtime(p) > _CACHE_TTL:
            return None
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cache_put(info, candidates):
    key = _cache_key(info)
    d = _cache_dir()
    if not key or not d:
        return
    p = os.path.join(d, key + '.json')
    try:
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(candidates, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def _search_inner(info, modal_progress=True):
    # Make sure the engine's internal settings have real values before the
    # engine module (and general.py) is imported -- otherwise int('') / empty
    # language flags break it. Safe to call every time.
    ensure_engine_settings()
    from resources.lib.subs_engine import engine, general

    video_data = build_video_data(info)
    kodi_utils.log('subs_engine_bridge: searching engine for '
                   + repr({k: video_data[k] for k in
                           ('imdb', 'title', 'season', 'episode',
                            'media_type')}),
                   level='INFO')

    # Show the same live per-provider progress dialog DarkSubs shows while
    # the providers run (manual flow only). general.show_results reads
    # general.show_msg (which c_get_subtitles updates with per-source counts)
    # until we set 'END'. Heavily guarded: any failure must not affect search.
    import threading
    progress_thread = None
    if modal_progress:
        try:
            general.break_all = False
            general.with_dp = True
            general.show_msg = 'MoranSubs — מחפש כתוביות'
            progress_thread = threading.Thread(
                target=general.show_results, args=(True,))
            progress_thread.daemon = True
            progress_thread.start()
        except Exception:
            progress_thread = None

    try:
        f_result = engine.get_subtitles(video_data)
        sorted_subs = engine.sort_subtitles(f_result, video_data) \
            if f_result else []
    finally:
        # Close the progress dialog (show_results exits on 'END').
        try:
            general.show_msg = 'END'
        except Exception:
            pass

    if not sorted_subs:
        return []

    out = []
    seen = set()
    for t in sorted_subs:
        # tuple layout (sort_subtitles.append_subtitles):
        #  0 label  1 colored_label2  2 icon  3 thumb  4 url
        #  5 percent 6 sync  7 hearing_imp  8 filename  9 site_id
        try:
            url = t[4]
            percent = t[5]
            hi = t[7]
            site_id = t[9]
            thumb_code = (t[3] or '').strip().lower()  # provider ISO 639-1
        except Exception:
            continue

        parsed = _parse_download_url(url)
        if not parsed:
            continue
        lang = parsed['language']
        label0 = t[0] or ''
        # The provider already computed a proper ISO 639-1 code in the tuple's
        # thumbnail field (via xbmc.convertLanguage) -- use it so Kodi shows
        # the right flag. Normalize a few common non-standard codes.
        code = _LANG_NORMALIZE.get(thumb_code, thumb_code)
        # Machine/AI-translated flag carried by the provider (currently the
        # OpenSubtitles source sets download_data['mt']; it requests MT subs
        # from the API but the flag used to be dropped, letting an MT Hebrew
        # sub masquerade as human). Old cached results simply lack the key ->
        # False, same behavior as before.
        is_mt = ((parsed['download_data'] or {}).get('mt') == 'true')
        # Classify. Hebrew (human / machine) first, everything else after.
        if (lang == 'HebrewMachineTranslated'
                or 'HebrewMachineTranslated' in label0
                or (is_mt and (code in ('he', 'iw', 'heb')
                               or lang == 'Hebrew' or 'Hebrew' in label0))):
            kind = 'mt_he'
            code = 'he'
        elif (code in ('he', 'iw', 'heb') or lang == 'Hebrew'
              or 'Hebrew' in label0):
            kind = 'human_he'
            code = 'he'
        else:
            kind = 'other'
            if not code:
                code = _LANG_CODES.get(lang, (lang[:2].lower() if lang else 'und'))

        # De-dup identical picks (same source + filename + language).
        dedup_key = (parsed['source'], parsed['filename'], code)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        provider = _PROVIDER_LABEL.get(site_id, parsed['source'] or '?')
        try:
            pct = int(percent)
        except Exception:
            pct = 0
        label = '{0} · {1}%'.format(provider, pct)
        if kind == 'mt_he':
            label = '[תרגום מכונה] ' + label
        # Always show a language tag so the user knows the language even when
        # Kodi can't render a flag for the code.
        if kind == 'other' and code:
            label = '[{0}] {1}'.format(code.upper(), label)
        if parsed['filename']:
            label = '{0}  —  {1}'.format(label, parsed['filename'])

        out.append({
            'filename': label,
            'language': code or 'und',
            'link': _encode_engine_link(parsed, hi),
            'sync': 'true' if (kind == 'human_he' and pct >= 90) else 'false',
            'rating': _rating_for(pct, kind),
            'is_hi': (hi == 'true'),
            'is_hd': False,
            '_engine_kind': kind,
            '_pct': pct,
            # Machine/AI-translated (any language). The gender-reference oracle
            # rejects these outright -- an MT sub in ANY language is a poisoned
            # gender oracle (MT defaults to masculine).
            '_is_mt': is_mt,
        })

    kodi_utils.log('subs_engine_bridge: {0} engine results'.format(len(out)),
                   level='INFO')
    return out


def _wait_for_subtitle_streams(player, max_tenths=25):
    """Poll the player's subtitle-stream list until it populates. The
    demuxer often hasn't exposed embedded streams yet right after playback
    starts (the search dialog opens at ~00:00:02), so an immediate read
    returns []. Mirrors DarkSubs's wait_for_video_and_return_subs_list but
    capped shorter to stay responsive. Returns the stream list."""
    import xbmc
    subs = []
    once = True
    vidtime_pre = 0
    for _ in range(max_tenths):
        try:
            subs = player.getAvailableSubtitleStreams() or []
            if subs:
                return subs
            vidtime = player.getTime()
            if vidtime > 0:
                if once:
                    vidtime_pre = vidtime
                    once = False
                elif vidtime_pre != vidtime:
                    # Time advanced and still no streams -> none coming.
                    break
        except Exception:
            pass
        xbmc.sleep(100)
    return subs


# --- Embedded-stream snapshot (taken at PLAYBACK START) ----------------------
# Kodi's getAvailableSubtitleStreams() returns BOTH the file's embedded streams
# AND any EXTERNAL sub that's since been loaded (including one WE loaded -- e.g.
# an AI translation). Polling it live each time the picker opens therefore
# misreads our own external sub as an "embedded Hebrew 101%" entry, which then
# pins the picker on that sub. The fix: snapshot the stream list ONCE at play
# start (before anything external is loaded) and offer embedded entries only
# from that snapshot. Embedded streams keep their (low) indices even after Kodi
# appends externals, so the snapshot index stays valid at select time.
#
# CRITICAL: the snapshot is taken in the SERVICE process (auto-on-play) but read
# in the SUBTITLE-DIALOG process (default.py) -- two separate Python instances,
# so a module global wouldn't be visible across them. Store it on a Kodi WINDOW
# PROPERTY (Window(10000)), which every add-on process shares.
_SNAP_PROP = 'povil.embedded_snap'


def _snap_get():
    try:
        import xbmcgui
        raw = xbmcgui.Window(10000).getProperty(_SNAP_PROP)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _snap_set(key, streams):
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty(
            _SNAP_PROP,
            json.dumps({'key': key, 'streams': list(streams or [])},
                       ensure_ascii=False))
    except Exception:
        pass


def _stream_key(info):
    """A stable id for the currently-playing item (same across the dialog opens
    of one playback). Prefer the player's own file over the info dict."""
    try:
        import xbmc
        f = (xbmc.Player().getPlayingFile() or '').strip()
    except Exception:
        f = ''
    return f or ((info or {}).get('filepath') or (info or {}).get('title') or '')


def have_playback_snapshot(info=None):
    """True when the file playing RIGHT NOW already has a real (non-empty)
    play-start snapshot. Lets a caller skip an expensive stream poll it does not
    need. An EMPTY snapshot deliberately reads as False -- it means "captured
    nothing yet", so a retry is still wanted (see note_playback_streams)."""
    try:
        snap = _snap_get()
        return bool(snap and snap.get('key') == _stream_key(info)
                    and snap.get('streams'))
    except Exception:
        return False


def note_playback_streams(info, streams=None):
    """Snapshot the embedded/local subtitle streams at PLAY START, before any
    external sub is loaded. Call ONCE per file, as early as possible. `streams`
    may be passed if the caller already polled them (auto-on-play does).
    Stored on a window property so the subtitle-dialog process can read it."""
    try:
        import xbmc
        player = xbmc.Player()
        if not player.isPlayingVideo():
            return
        key = _stream_key(info)
        cur = _snap_get()
        # Only a NON-EMPTY snapshot is final. An empty one is provisional: the
        # demuxer may simply not have enumerated the tracks yet, and a caller
        # whose poll timed out first must not be able to latch [] and discard a
        # real list that arrives afterwards -- that would silently reproduce the
        # "no embedded rows" bug through a different door. A file that genuinely
        # has no subtitle streams just gets rewritten as [] each time, which
        # costs one window-property write and changes nothing downstream.
        if cur and cur.get('key') == key and cur.get('streams'):
            return  # already captured for this file
        if streams is None:
            streams = _wait_for_subtitle_streams(player)
        _snap_set(key, streams)
        kodi_utils.log('embedded baseline ({0} stream(s)): {1}'.format(
            len(streams or []), list(streams or [])), level='INFO')
        # If this source ships a built-in Hebrew track, tell the pool so the
        # source screen flags it "BUILT-IN 100%" for everyone. Automatic,
        # deduped + backgrounded inside pool.report_embedded; never blocks.
        try:
            def _is_he_label(n):
                low = (n or '').strip().lower()
                if not low:
                    return False
                if _LANG_NORMALIZE.get(low, low[:2]) == 'he':
                    return True
                # Descriptive labels a code/2-char lookup misses:
                # "Hebrew", "Hebrew SDH", "Forced Hebrew", or Hebrew script.
                if 'hebrew' in low:
                    return True
                return any('֐' <= ch <= 'ת' for ch in (n or ''))
            has_he = any(_is_he_label(n) for n in (streams or []))
            _rel = ''
            if has_he:
                from resources.lib import pool
                _rel = pool._release_from(info)
                pool.report_embedded(info)
                try:
                    from resources.lib import he_sub_match as _hsm
                    if _rel:
                        _hsm.merge_embedded(info, [_rel])
                except Exception:
                    pass
            # Diagnostic (once per play): shows WHY a source did/didn't get the
            # BUILT-IN flag -- whether Hebrew was detected, the release we stored,
            # and which field it came from. Makes a release-name mismatch vs the
            # source row, or an empty release, visible in a single line.
            try:
                kodi_utils.log(
                    'embedded-report he={0} rel={1!r} ids(tmdb={2!r} imdb={3!r} '
                    's={4!r} e={5!r} mt={6!r} isep={7}) (picked={8!r} li={9!r} '
                    'fp={10!r})'.format(
                        has_he, _rel, info.get('tmdb_id', ''),
                        info.get('imdb_id', ''), info.get('season', ''),
                        info.get('episode', ''), info.get('media_type', ''),
                        info.get('is_episode', ''), info.get('picked_release', ''),
                        info.get('li_filename', ''), info.get('filepath', '')),
                    level='INFO')
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        pass


def _wait_for_snapshot(key, timeout=3.0):
    """Bounded wait for the play-start snapshot to be populated for `key`.

    On the FIRST play, the subtitle dialog / autosub search can fire before the
    service process finished capturing the snapshot (note_playback_streams waits
    for the embedded streams to enumerate). Without this, the embedded-Hebrew
    101% entry only appeared from the SECOND open onward. We poll the same
    play-start snapshot -- never the live stream list -- so there is still no
    risk of misreading an external sub as embedded. Returns the snapshot dict or
    None."""
    try:
        import xbmc
        player = xbmc.Player()
        monitor = xbmc.Monitor()
        elapsed = 0.0
        provisional = None
        while elapsed < timeout:
            if not player.isPlayingVideo():
                return provisional
            snap = _snap_get()
            if snap and snap.get('key') == key:
                if snap.get('streams'):
                    return snap
                # Empty means "captured nothing YET" (see note_playback_streams):
                # keep waiting for a real list rather than accepting it, but
                # remember it so a file that truly has no streams still resolves
                # instead of blocking the dialog for the full timeout twice.
                if snap.get('streams') is not None:
                    provisional = snap
            if monitor.waitForAbort(0.2):
                return provisional
            elapsed += 0.2
        return provisional
    except Exception:
        return None


def embedded_candidates(info):
    """Offer the file's EMBEDDED / local subtitle streams (mirroring DarkSubs's
    [LOC] entries): Hebrew at the top as 101%, other languages as selectable
    "[מובנה] XX" entries. Uses the play-start snapshot (see above) so an
    external sub we loaded -- e.g. an AI translation -- can NEVER be mistaken
    for an embedded stream. With no snapshot (e.g. autosub off, or the dialog
    opened before play start was captured) it offers nothing rather than risk a
    misread."""
    if not enabled():
        return []
    key = _stream_key(info)
    snap = _snap_get()
    if not snap or snap.get('key') != key:
        # First-play race: the play-start snapshot is captured in the service
        # process and may not be ready when the dialog opens. Wait briefly for
        # it so the embedded-Hebrew 101% entry shows on the FIRST open too.
        snap = _wait_for_snapshot(key)
        if not snap or snap.get('key') != key:
            return []
    streams = snap.get('streams')
    if not streams:
        return []
    # Built-in Hebrew here too -> flag the release for everyone (deduped,
    # backgrounded). Covers users who open the picker with autosub off.
    try:
        if any((_LANG_NORMALIZE.get((n or '').strip().lower(),
                                    (n or '').strip().lower()[:2]) == 'he')
               for n in streams):
            from resources.lib import pool
            pool.report_embedded(info)
            try:
                from resources.lib import he_sub_match as _hsm
                _rel = pool._release_from(info)
                if _rel:
                    _hsm.merge_embedded(info, [_rel])
            except Exception:
                pass
    except Exception:
        pass
    out = []
    for idx, name in enumerate(streams):
        n = (name or '').strip().lower()
        if not n:
            continue
        code = _LANG_NORMALIZE.get(n, n[:2] if len(n) >= 2 else n)
        if code == 'he':
            out.append({
                'filename': 'תרגום מובנה בעברית · 101%',
                'language': 'he',
                'link': urllib.parse.quote(json.dumps({
                    'type': 'engine', 'embedded': True,
                    'stream_index': idx, 'lang': 'he',
                }, ensure_ascii=False)),
                'sync': 'true', 'rating': '5',
                'is_hi': False, 'is_hd': False,
                '_engine_kind': 'embedded_he', '_pct': 101,
            })
        else:
            out.append({
                'filename': '[מובנה] {0}'.format(code.upper()),
                'language': code or 'und',
                'link': urllib.parse.quote(json.dumps({
                    'type': 'engine', 'embedded': True,
                    'stream_index': idx, 'lang': code,
                }, ensure_ascii=False)),
                'sync': 'false', 'rating': '3',
                'is_hi': False, 'is_hd': False,
                '_engine_kind': 'embedded_other', '_pct': 0,
            })
    return out


# Language-name -> ISO code for the buckets sort_subtitles produces by
# language name (the "other languages" path). Only the common ones; an
# unknown name falls back to its first two letters.
_LANG_CODES = {
    'Hebrew': 'he', 'English': 'en', 'Arabic': 'ar', 'Russian': 'ru',
    'Spanish': 'es', 'French': 'fr', 'German': 'de', 'Portuguese': 'pt',
    'Italian': 'it', 'Turkish': 'tr', 'Polish': 'pl', 'Dutch': 'nl',
}

# Fix common non-ISO-639-1 codes some providers emit so Kodi shows a flag.
_LANG_NORMALIZE = {
    'gr': 'el', 'gre': 'el', 'ell': 'el', 'greek': 'el',
    'sp': 'es', 'spa': 'es', 'spanish': 'es',
    'per': 'fa', 'fas': 'fa', 'far': 'fa', 'persian': 'fa',
    'iw': 'he', 'heb': 'he', 'hebrew': 'he',
    'eng': 'en', 'english': 'en',
    'ara': 'ar', 'arabic': 'ar',
    'rus': 'ru', 'russian': 'ru',
    'fre': 'fr', 'fra': 'fr', 'french': 'fr',
    'ger': 'de', 'deu': 'de', 'german': 'de',
    'dut': 'nl', 'nld': 'nl', 'por': 'pt', 'ita': 'it',
    'tur': 'tr', 'pol': 'pl', 'chi': 'zh', 'zho': 'zh',
}


_PROVIDER_LABEL = {
    '[Ktuvit]': 'Ktuvit',
    '[Wizdom]': 'Wizdom',
    '[Telegram]': 'Telegram',
    '[OpenSubtitles]': 'OpenSubtitles',
    '[YIFY]': 'YIFY',
    '[SubSource]': 'SubSource',
    '[Subscene]': 'Subscene',
    '[BSPlayer]': 'BSPlayer',
}


def _rating_for(pct, kind):
    # Machine-translated Hebrew always ranks below any human sub.
    if kind == 'mt_he':
        return '2'
    if pct >= 90:
        return '5'
    if pct >= 66:
        return '4'
    if pct >= 33:
        return '3'
    return '2'


def _encode_engine_link(parsed, hi):
    payload = {
        'type': 'engine',
        'source': parsed['source'],
        'language': parsed['language'],
        'filename': parsed['filename'],
        'download_data': parsed['download_data'],
        'hi': hi,
    }
    return urllib.parse.quote(json.dumps(payload, ensure_ascii=False))


# ---- download -------------------------------------------------------

_SUB_EXTS = ('.srt', '.ssa', '.ass', '.sub', '.smi', '.vtt', '.txt')

# Persistent downloaded-file cache, one-to-one with DarkSubs's "Cached_subs"
# folder. A subtitle the user already picked once is served straight from disk
# on the next pick of the SAME source+language+filename -- no network round
# trip -- which is the single biggest reason re-picking in DarkSubs is instant.
# Set by _download_inner on each call: True when the subtitle was served from
# the persistent Cached_subs folder (no network fetch). The auto-on-play overlay
# reads it to show "(נטענה מהקאש)", exactly like DarkSubs's cache note.
LAST_DOWNLOAD_FROM_CACHE = False

_CACHED_SUBS_DIRNAME = 'Cached_subs_v2'
# Do NOT bump/delete this cache for the RTL compatibility repair. Existing
# Ktuvit files may already carry a ".shared" marker, and throwing them away
# would cause needless provider fetches plus pool de-dup lookups. Old v2 bytes
# stay immutable; playback gets a separate locally-rendered copy instead.
# DarkSubs caches every download keyed {source}_{language}_{filename}{ext} and
# wipes the whole folder once it exceeds this many files (its
# "subtitle_trans_cache" setting). We keep the same count-based prune.
_CACHED_SUBS_MAX = 200
_CACHED_SUBS_EXTS = ('.srt', '.idx', '.sup', '.sub', '.str', '.ass', '.ssa',
                     '.smi', '.vtt', '.txt')


def _cached_subs_dir():
    try:
        import xbmcvfs
        from resources.lib import kodi_utils
        base = xbmcvfs.translatePath(
            kodi_utils.addon().getAddonInfo('profile'))
        d = os.path.join(base, _CACHED_SUBS_DIRNAME)
        if not os.path.isdir(d):
            os.makedirs(d)
        return d
    except Exception:
        return None


def _cached_subs_max():
    # Honour DarkSubs's subtitle_trans_cache setting if present, else default.
    try:
        v = int(kodi_utils.get_setting('subtitle_trans_cache', '') or 0)
        if v > 0:
            return v
    except Exception:
        pass
    return _CACHED_SUBS_MAX


def _cached_subs_keybase(cache_dir, source, language, filename):
    """The DarkSubs cache stem: <dir>/<source>_<language>_<filename>. Filename
    components are sanitised so a provider's title can't escape the folder or
    break the path; the value is still stable per pick, so a repeat pick hits
    the same stem."""
    def _safe(s):
        s = str(s or '')
        out = []
        for ch in s:
            if ch.isalnum() or ch in (' ', '.', '-', '_', '(', ')', '[', ']'):
                out.append(ch)
            else:
                out.append('_')
        return ''.join(out).strip() or '_'
    stem = '{0}_{1}_{2}'.format(_safe(source), _safe(language),
                                _safe(filename))
    return os.path.join(cache_dir, stem)


def _cached_subs_lookup(keybase):
    """Return an existing cached file for this stem (any known ext), or None."""
    for ext in _CACHED_SUBS_EXTS:
        p = keybase + ext
        try:
            if os.path.isfile(p):
                return p
        except Exception:
            pass
    return None


def _cached_subs_prune(cache_dir):
    """Match DarkSubs: once the folder exceeds the cap, wipe it wholesale (a
    simple, predictable bound that never blocks a download)."""
    try:
        names = os.listdir(cache_dir)
    except Exception:
        return
    source_names = [
        n for n in names
        if os.path.splitext(n)[1].lower() in _CACHED_SUBS_EXTS
        and '.povil-rtl.' not in n
    ]
    if len(source_names) <= _cached_subs_max():
        return
    for n in names:
        try:
            os.remove(os.path.join(cache_dir, n))
        except Exception:
            pass


def _cached_subs_store(keybase, sub_file):
    """Copy a freshly-downloaded subtitle into the cache (if not already there),
    preserving its extension -- exactly like DarkSubs's shutil.copy."""
    try:
        import shutil
        ext = os.path.splitext(sub_file)[1] or '.srt'
        dest = keybase + ext
        if not os.path.exists(dest):
            shutil.copy(sub_file, dest)
        return dest
    except Exception as e:
        kodi_utils.log('subs_engine_bridge: cache store skipped: {0}'
                       .format(e), level='DEBUG')
        return None


# Only plain timed-text formats can be passed through srt.fix_rtl_punctuation
# line-by-line. ASS/SSA and MicroDVD SUB carry timing/style fields on the SAME
# line as the dialogue; wrapping the full line would corrupt their syntax.
_RTL_PLAIN_TEXT_EXTS = ('.srt', '.vtt')
_RTL_DISPLAY_TOKEN = '.povil-rtl'
_LOGICAL_SOURCE_MARKER = '.logical-v1'


def source_path_for_delivery(path):
    """Map our private display-copy path back to the immutable source file.

    Pool hashing/sharing must always read and mark the source, never the copy
    carrying playback-only BiDi controls. Falls back to the input path.
    """
    try:
        root, ext = os.path.splitext(path or '')
        if root.endswith(_RTL_DISPLAY_TOKEN):
            source = root[:-len(_RTL_DISPLAY_TOKEN)] + ext
            if os.path.isfile(source):
                return source
    except Exception:
        pass
    return path


def is_logical_source(path):
    try:
        return os.path.isfile(path + _LOGICAL_SOURCE_MARKER)
    except Exception:
        return False


def _mark_logical_source(path):
    """Mark a freshly downloaded file as pristine logical-order text.

    Existing unmarked v2 entries are known to predate this change and may carry
    the vendored engine's physical punctuation reversal. The tiny local marker
    prevents that compatibility inverse from being applied to new downloads.
    It causes no network traffic and is never uploaded.
    """
    try:
        marker = path + _LOGICAL_SOURCE_MARKER
        if not os.path.exists(marker):
            with open(marker, 'w', encoding='ascii') as f:
                f.write('1')
    except Exception:
        pass


def _render_hebrew_rtl_copy(sub_file, legacy_engine=False):
    """Return a playback-only RTL copy while leaving ``sub_file`` untouched.

    The source bytes, source hash and ".shared" marker remain stable, so this
    repair cannot re-upload existing pool subtitles. Unsupported structured
    formats are deliberately returned verbatim rather than risking their
    timing/style syntax. Fail-open on every error.

    ``legacy_engine`` reverses only the old engine's known punctuation shapes;
    fresh logical downloads pass False.

    Deliberately does NOT run srt.clamp_cue_durations, unlike every other place
    the RTL fix is applied. That clamp exists for a failure this path cannot
    have: our own model mistyping a timecode it was told to copy verbatim.
    These bytes come from Ktuvit / OpenSubtitles / Wizdom and never touch
    Gemini, their timing is treated as MORE trustworthy elsewhere in the add-on
    (subsync uses a foreign-language human sub as the oracle it corrects AI
    timing against), and real-world third-party SRT formatting is far more
    varied than Gemini's output -- so silently re-timing it is a risk taken for
    no matching benefit. If a stuck-cue report ever arrives against an engine
    download, this is the considered decision to revisit, not an oversight.
    """
    try:
        if os.path.splitext(sub_file or '')[1].lower() \
                not in _RTL_PLAIN_TEXT_EXTS:
            return sub_file
        with open(sub_file, 'rb') as f:
            raw = f.read()
        # extract_sub.convert_to_utf normalizes engine downloads first. Decode
        # strictly here so an unexpected binary/legacy file is never rewritten
        # with replacement characters.
        text = raw.decode('utf-8-sig')
        from resources.lib import srt
        fixed = srt.fix_rtl_punctuation(
            text, legacy_engine=legacy_engine)
        if fixed == text:
            return sub_file
        root, ext = os.path.splitext(sub_file)
        out = root + _RTL_DISPLAY_TOKEN + ext
        tmp = out + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8', newline='') as f:
                f.write(fixed)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, out)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        return out
    except Exception as e:
        kodi_utils.log('subs_engine_bridge: RTL display copy skipped: {0}'
                       .format(e), level='DEBUG')
        return sub_file


def _ensure_utf8(path):
    """Rewrite `path` as UTF-8 if it is not already valid UTF-8. Returns True
    when the file was converted.

    The engine normalises encodings in extract_sub.convert_to_utf -- but ONLY
    for files it pulled out of an archive. Ktuvit sometimes serves the .srt
    directly rather than zipped; ZipFile() then raises, extract() falls back to
    `return archive_file`, and the RAW bytes (cp1255, the legacy Israeli Hebrew
    encoding) are used as-is.

    Nothing downstream survives that. Every consumer reads the file as UTF-8
    with errors='replace', so each Hebrew letter becomes U+FFFD -- which is in
    none of the letter ranges the code counts. The pool's quality gate sees a
    subtitle with no Hebrew and drops it before uploading (a Ktuvit sub that
    should have been mirrored for everyone silently never arrives), and subsync
    sees one dialogue cue instead of hundreds and cannot verify the timing.
    Both were observed in the field on Rick and Morty S01E09, where the pool
    ended up with nothing while the same flow had mirrored four variants of
    S01E01 -- the difference being that those came zipped.

    Deliberately conservative: a file that already decodes as UTF-8 is not
    touched at all, so its bytes, its source hash and its ".shared" marker stay
    exactly as they were and this can never trigger a re-upload of anything
    already in the pool. Fail-open on every error."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return False
    try:
        raw.decode('utf-8-sig')
        return False                 # already UTF-8 -- leave it completely alone
    except (UnicodeDecodeError, LookupError):
        pass
    try:
        text = raw.decode('cp1255')  # also decodes iso-8859-8 Hebrew correctly
    except (UnicodeDecodeError, LookupError):
        kodi_utils.log('subs_engine_bridge: {0} is neither UTF-8 nor cp1255 -- '
                       'left as-is'.format(os.path.basename(path)),
                       level='WARNING')
        return False
    tmp = path + '.utf8tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        kodi_utils.log('subs_engine_bridge: UTF-8 rewrite failed for {0}: {1}'
                       .format(os.path.basename(path), e), level='WARNING')
        return False
    kodi_utils.log('subs_engine_bridge: converted {0} from cp1255 to UTF-8 '
                   '(a provider served it unzipped, so the engine never '
                   'normalised it)'.format(os.path.basename(path)),
                   level='INFO')
    return True


def _looks_like_subtitle(path):
    """True if the file is a plausible subtitle: not an HTML/zip blob (some
    providers hand back the error page or un-extracted archive when a download
    actually failed). Accepts by known extension OR by content sniff -- some
    providers quote the Content-Disposition filename ("name.srt") so the
    on-disk extension comes out mangled even though the bytes are a real SRT."""
    try:
        with open(path, 'rb') as f:
            head = f.read(2048)
        if not head.strip():
            return False
        if head[:2] == b'PK':          # zip
            return False
        low = head.lstrip().lower()
        if low.startswith((b'<!doctype', b'<html', b'<?xml', b'<head')):
            return False
        ext = os.path.splitext(path)[1].lower().strip('"\'')
        if ext in _SUB_EXTS:
            return True
        # Mangled / missing extension: accept if the CONTENT looks like a
        # subtitle (srt/vtt cue arrow, ass/ssa header, microdvd frame braces).
        if (b'-->' in head or b'[script info]' in low
                or b'dialogue:' in low or head.lstrip()[:1] == b'{'):
            return True
        return False
    except Exception:
        return True  # if unsure, don't block a possibly-good file


def select_embedded(stream_index, lang=None):
    """Switch Kodi to the chosen EMBEDDED subtitle stream. The index comes from
    the play-start snapshot, where only true embedded streams existed; Kodi
    appends external subs at HIGHER indices, so this index still points at the
    embedded stream. Use it directly. Only if it's out of range do we re-find
    the first stream of the requested language (lowest index = the embedded
    one), never an external appended later."""
    try:
        import xbmc
        p = xbmc.Player()
        try:
            streams = p.getAvailableSubtitleStreams() or []
        except Exception:
            streams = []
        target = int(stream_index)
        if target < 0 or (streams and target >= len(streams)):
            want = (lang or 'he').lower()
            target = next(
                (i for i, name in enumerate(streams)
                 if _LANG_NORMALIZE.get((name or '').strip().lower(),
                                        (name or '').strip().lower()[:2]) == want),
                int(stream_index))
        p.setSubtitleStream(target)
        p.showSubtitles(True)
        kodi_utils.log('subs_engine_bridge.select_embedded: set stream {0}'
                       .format(target), level='INFO')
        return True
    except Exception as e:
        kodi_utils.log('subs_engine_bridge.select_embedded failed: {0}'
                       .format(e), level='WARNING')
        return False


def download(payload, for_delivery=True):
    """Resolve an 'engine' link to a Hebrew SRT path on disk. Returns
    the path or None. Called from translate.resolve().

    ``for_delivery=False`` returns the immutable canonical/cache source for
    hashing, pool sharing and language/timing analysis. The default returns a
    separate RTL-rendered copy for a Hebrew SRT/VTT. Neither path performs any
    Worker request by itself.
    """
    if not enabled():
        return None
    try:
        return _download_inner(payload, for_delivery=for_delivery)
    except Exception as e:
        kodi_utils.log('subs_engine_bridge.download failed ({0}): {1}'.format(
            (payload.get('source') or '?'), e), level='ERROR')
        # Log only -- no user popup. This fired on every failed provider download,
        # including background/secondary Ktuvit fetches the server "refuses"
        # (raising "Ktuvit refused the file...") while the subtitle the user
        # actually picked loads fine -- which spammed a popup on every playback.
        # The exact reason is in the ERROR log above for diagnosis.
        return None


def _download_inner(payload, for_delivery=True):
    global LAST_DOWNLOAD_FROM_CACHE
    LAST_DOWNLOAD_FROM_CACHE = False
    source = payload.get('source') or ''
    download_data = payload.get('download_data') or {}
    language = payload.get('language') or 'Hebrew'
    filename = payload.get('filename') or 'subtitle'

    # Make sure the engine's internal settings exist before any provider /
    # general.py runs. search() does this, but a download can be the FIRST
    # engine call in a fresh process (e.g. straight after a quick update, or an
    # auto-on-play), and the providers + general.py read these settings -- an
    # empty value used to break the read. Cheap + idempotent.
    try:
        ensure_engine_settings()
    except Exception:
        pass

    module = _provider_module(source)
    if module is None or not hasattr(module, 'download'):
        kodi_utils.log('subs_engine_bridge: no download() for source '
                       + str(source), level='WARNING')
        # Log only (logged above) -- no user popup; this fired during background
        # resolution too and was just playback noise.
        return None

    from resources.lib.subs_engine import general

    # Embedded-stream selection (download_data['url'] is an int index)
    # is a DarkSubs feature handled elsewhere; the bridge only deals
    # with downloadable file subs.
    try:
        int(download_data.get('url', ''))
        kodi_utils.log('subs_engine_bridge: embedded-stream pick not '
                       'handled by bridge', level='INFO')
        return None
    except (ValueError, TypeError):
        pass

    sub_folder = general.MySubFolder
    # Clear the shared download folder before EVERY fetch. It is one persistent
    # dir reused by every source/title, and extract() picks a subtitle file out of
    # it -- so a leftover from a previous, unrelated download (a different title,
    # or an English file from another source) could be handed back mislabeled.
    # rmtree+recreate mirrors the reference engine.download_sub, which the bridge
    # dropped when it added the Cached_subs disk cache (the Wizdom regression:
    # wrong-title / English-as-Hebrew / unsynced subtitles).
    try:
        import shutil as _shutil
        _shutil.rmtree(sub_folder, ignore_errors=True)
    except Exception:
        pass
    try:
        os.makedirs(sub_folder)
    except OSError:
        pass

    # DarkSubs-style downloaded-file cache: if this exact subtitle (same
    # source + language + filename) was fetched before, serve it from disk
    # and skip the network download entirely -- this is what makes re-picking
    # a subtitle instant. The cached file was already validated + punctuation-
    # fixed when it was first stored, so we return it straight away.
    cache_dir = _cached_subs_dir()
    keybase = None
    if cache_dir:
        try:
            _cached_subs_prune(cache_dir)
            keybase = _cached_subs_keybase(cache_dir, source, language,
                                           filename)
            hit = _cached_subs_lookup(keybase)
            if hit:
                kodi_utils.log('subs_engine_bridge: cached file hit ({0})'
                               .format(os.path.basename(hit)), level='INFO')
                # (LAST_DOWNLOAD_FROM_CACHE is already declared global at the
                # top of this function -- re-declaring it here is a SyntaxError.)
                LAST_DOWNLOAD_FROM_CACHE = True
                # A cache entry stored before this normalisation existed can
                # still be cp1255. Heal it in place, or the same device keeps
                # serving the same unreadable copy for as long as the entry
                # lives -- and keeps failing to mirror it to the pool.
                _ensure_utf8(hit)
                if (for_delivery
                        and kodi_utils.get_bool(
                            'auto_fix_sub_punctuation', True)
                        and 'Hebrew' in language):
                    # Every shipped v2 entry without the local format marker
                    # predates the single RTL owner and may carry the old
                    # engine's reversed dash/ellipsis shapes. Render a copy;
                    # never mutate/delete the cache source or its share marker.
                    return _render_hebrew_rtl_copy(
                        hit, legacy_engine=not is_logical_source(hit))
                return hit
        except Exception as e:
            kodi_utils.log('subs_engine_bridge: cache lookup skipped: {0}'
                           .format(e), level='DEBUG')
            keybase = None

    sub_file = module.download(download_data, sub_folder)
    if not sub_file or not os.path.isfile(sub_file):
        kodi_utils.log('subs_engine_bridge: download returned no file '
                       '(source={0}, got={1})'.format(source, sub_file),
                       level='WARNING')
        # Log only -- no user popup. This fires for a single failed provider
        # download (e.g. a background/secondary Ktuvit fetch) while the sub the
        # user actually picked works fine; a popup here just spams playback.
        return None

    # Validate it's an actual subtitle, not an HTML error page / un-extracted
    # archive a provider handed back on a failed download (e.g. YIFY 403).
    # Otherwise Kodi tries to load garbage and shows "download failed".
    if not _looks_like_subtitle(sub_file):
        kodi_utils.log('subs_engine_bridge: downloaded file is not a valid '
                       'subtitle ({0})'.format(os.path.basename(sub_file)),
                       level='WARNING')
        # Log only -- no user popup. A provider (often Ktuvit, when rate-limited)
        # occasionally hands back an HTML/empty blob for ONE result; the user's
        # actual subtitle still loads, so the repeated popup was pure noise.
        return None

    # Normalise the encoding BEFORE the pristine copy is taken, so the stored
    # source -- the one the pool hashes, uploads and marks as shared, and the
    # one subsync reads -- is the UTF-8 text everything downstream assumes.
    _ensure_utf8(sub_file)

    # Store the validated PRISTINE provider file before any playback rendering.
    # This preserves one stable source hash for pool de-dup and sharing.
    source_file = sub_file
    if keybase:
        cached = _cached_subs_store(keybase, sub_file)
        if cached:
            source_file = cached
    _mark_logical_source(source_file)

    # The old vendored fixer is intentionally gone. One canonical MoranSubs
    # processor owns Hebrew playback, on a disposable local copy only.
    if (for_delivery
            and kodi_utils.get_bool('auto_fix_sub_punctuation', True)
            and 'Hebrew' in language):
        return _render_hebrew_rtl_copy(source_file, legacy_engine=False)
    return source_file
