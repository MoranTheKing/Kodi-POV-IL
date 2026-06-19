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
    'max_search_time': '15',
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
_ENGINE_DEFAULTS_VERSION = '3'


def ensure_engine_settings():
    """Populate the engine's internal settings. MUST run before the engine is
    imported (general.py reads max_search_time at module load). Writes empty
    settings always; force-rewrites everything once when the defaults version
    changes (so existing installs pick up new defaults like all_lang)."""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('service.subtitles.kodipovilai')
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
        if cached is not None:
            return cached
    try:
        out = _search_inner(info, modal_progress=modal_progress)
        if cacheable:
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
        import xbmcaddon
        a = xbmcaddon.Addon('service.subtitles.kodipovilai')
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
        import xbmcaddon
        base = xbmcvfs.translatePath(
            xbmcaddon.Addon('service.subtitles.kodipovilai')
            .getAddonInfo('profile'))
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
        # Classify. Hebrew (human / machine) first, everything else after.
        if lang == 'HebrewMachineTranslated' or 'HebrewMachineTranslated' in label0:
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


def embedded_candidates(info):
    """Detect an embedded Hebrew subtitle stream in the currently-playing file
    and offer it at the very top, mirroring DarkSubs's "[LOC] 101%" entry.
    Selecting it switches Kodi's subtitle stream (no file) -- default.py then
    closes the dialog the way DarkSubs does so Kodi shows no error."""
    if not enabled():
        return []
    try:
        import xbmc
        player = xbmc.Player()
        if not player.isPlayingVideo():
            return []
        streams = _wait_for_subtitle_streams(player)
    except Exception:
        return []
    out = []
    for idx, name in enumerate(streams or []):
        n = (name or '').strip().lower()
        # Match the EMBEDDED Hebrew stream exactly like DarkSubs does (== 'heb').
        # Embedded container streams report the 3-letter code 'heb'; an EXTERNAL
        # Hebrew sub (e.g. one we already loaded from OpenSubtitles) reports 'he'
        # or 'Hebrew' -- so a broad match would wrongly target the external sub
        # and "switch to nothing". Only offer a true embedded 'heb' stream.
        if n == 'heb':
            out.append({
                'filename': 'תרגום מובנה בעברית · 101%',
                'language': 'he',
                'link': urllib.parse.quote(json.dumps({
                    'type': 'engine', 'embedded': True,
                    'stream_index': idx,
                }, ensure_ascii=False)),
                'sync': 'true',
                'rating': '5',
                'is_hi': False, 'is_hd': False,
                '_engine_kind': 'embedded_he',
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

_CACHED_SUBS_DIRNAME = 'Cached_subs'
# DarkSubs caches every download keyed {source}_{language}_{filename}{ext} and
# wipes the whole folder once it exceeds this many files (its
# "subtitle_trans_cache" setting). We keep the same count-based prune.
_CACHED_SUBS_MAX = 200
_CACHED_SUBS_EXTS = ('.srt', '.idx', '.sup', '.sub', '.str', '.ass', '.ssa',
                     '.smi', '.vtt', '.txt')


def _cached_subs_dir():
    try:
        import xbmcvfs
        import xbmcaddon
        base = xbmcvfs.translatePath(
            xbmcaddon.Addon('service.subtitles.kodipovilai')
            .getAddonInfo('profile'))
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
    if len(names) <= _cached_subs_max():
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


def select_embedded(stream_index):
    """Switch Kodi to the embedded HEBREW subtitle stream. We RE-FIND the Hebrew
    stream right now rather than trusting the index captured when the dialog
    opened: by download time the stream list can have shifted (Kodi/our own
    external subs got added), so a stale index points at the wrong stream and
    "shows nothing". Mirrors DarkSubs's get_embedded_sub_index(subs,'heb') at
    apply time. Falls back to the captured index if no Hebrew stream is found."""
    try:
        import xbmc
        p = xbmc.Player()
        try:
            streams = p.getAvailableSubtitleStreams() or []
        except Exception:
            streams = []
        # DarkSubs matches the embedded stream by EXACTLY 'heb' (get_embedded_
        # sub_index(subs,'heb')). External Hebrew subs report 'he'/'Hebrew', so
        # matching 'heb' picks the real embedded stream and not an external one.
        target = None
        for i, name in enumerate(streams):
            if (name or '').strip().lower() == 'heb':
                target = i
                break
        if target is None:
            target = int(stream_index)
        p.setSubtitleStream(target)
        p.showSubtitles(True)
        kodi_utils.log('subs_engine_bridge.select_embedded: set stream {0}'
                       .format(target), level='INFO')
        return True
    except Exception as e:
        kodi_utils.log('subs_engine_bridge.select_embedded failed: {0}'
                       .format(e), level='WARNING')
        return False


def download(payload):
    """Resolve an 'engine' link to a Hebrew SRT path on disk. Returns
    the path or None. Called from translate.resolve()."""
    if not enabled():
        return None
    try:
        return _download_inner(payload)
    except Exception as e:
        kodi_utils.log('subs_engine_bridge.download failed: {0}'.format(e),
                       level='ERROR')
        # Surface the real reason instead of Kodi's generic "download failed",
        # so a problem is reportable without digging through the log.
        try:
            kodi_utils.notify('הורדה נכשלה ({0}): {1}'.format(
                (payload.get('source') or '?'), str(e)[:90]), time_ms=6000)
        except Exception:
            pass
        return None


def _download_inner(payload):
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
        try:
            kodi_utils.notify('מקור לא נתמך להורדה: {0}'.format(source or '?'),
                              time_ms=6000)
        except Exception:
            pass
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
    try:
        if not os.path.exists(sub_folder):
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
                global LAST_DOWNLOAD_FROM_CACHE
                LAST_DOWNLOAD_FROM_CACHE = True
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
        try:
            kodi_utils.notify('השרת לא החזיר קובץ כתובית ({0})'.format(source),
                              time_ms=6000)
        except Exception:
            pass
        return None

    # Validate it's an actual subtitle, not an HTML error page / un-extracted
    # archive a provider handed back on a failed download (e.g. YIFY 403).
    # Otherwise Kodi tries to load garbage and shows "download failed".
    if not _looks_like_subtitle(sub_file):
        kodi_utils.log('subs_engine_bridge: downloaded file is not a valid '
                       'subtitle ({0})'.format(os.path.basename(sub_file)),
                       level='WARNING')
        try:
            kodi_utils.notify('הקובץ שהתקבל אינו כתובית תקינה ({0})'.format(
                source), time_ms=6000)
        except Exception:
            pass
        return None

    # Optional Hebrew punctuation fix, mirroring engine.download_sub.
    try:
        if kodi_utils.get_bool('auto_fix_sub_punctuation', True) \
                and 'Hebrew' in language:
            from resources.lib.subs_engine import engine as _eng
            fixed = _eng.fix_sub_punctuation_and_write(sub_file)
            if fixed:
                sub_file = fixed
    except Exception as e:
        kodi_utils.log('subs_engine_bridge: punct fix skipped: {0}'
                       .format(e), level='DEBUG')

    # Store the validated, punctuation-fixed file in the persistent cache so
    # the next pick of the same subtitle is served from disk (see above).
    if keybase:
        _cached_subs_store(keybase, sub_file)

    return sub_file
