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
import urllib.parse

from . import kodi_utils


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
_ENGINE_DEFAULTS = {
    'language_hebrew': 'true',
    'language_english': 'true',
    'language_russian': 'false',
    'language_arab': 'false',
    'all_lang': 'false',
    'retry_search_with_all_langs': 'false',
    'auto_translate': 'false',
    'translate_p': '0',
    'max_search_time': '10',
    'subtitle_trans_cache': '15',
    'enable_autosub_notifications': 'true',
    'auto_fix_sub_punctuation': 'true',
    'auto_remove_hi_tags': 'false',
    'show_debug': 'false',
}


def ensure_engine_settings():
    """Populate any engine internal setting that is still empty with its
    intended default. MUST run before the engine is imported (general.py
    reads max_search_time at module load). Idempotent and cheap."""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('service.subtitles.kodipovilai')
    except Exception:
        return
    for k, v in _ENGINE_DEFAULTS.items():
        try:
            if (addon.getSetting(k) or '') == '':
                addon.setSetting(k, v)
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
    filepath = info.get('filepath') or ''
    try:
        file_original = os.path.basename(filepath) if filepath else (
            tvshow or title)
    except Exception:
        file_original = title

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
        'file_original_path': file_original or '',
        'Tagline': '',
        'Tagline_From_Fen': '',
        'VideoPlayer.Tagline': '',
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


def search(info):
    """Return a list of MoranSubs candidate dicts for the HEBREW
    subtitles the engine found (human first, machine-translated
    after). Empty list when the gate is off or anything fails.

    Each candidate matches translate.list_candidates' schema and
    carries a link of type 'engine' that resolve() routes back here
    for download. Non-Hebrew results are intentionally dropped --
    MoranSubs translates those via its own AI/pool path, not here.
    """
    if not enabled():
        return []
    try:
        return _search_inner(info)
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


def _search_inner(info):
    # Make sure the engine's internal settings have real values before the
    # engine module (and general.py) is imported -- otherwise int('') / empty
    # language flags break it. Safe to call every time.
    ensure_engine_settings()
    from resources.lib.subs_engine import engine

    video_data = build_video_data(info)
    kodi_utils.log('subs_engine_bridge: searching engine for '
                   + repr({k: video_data[k] for k in
                           ('imdb', 'title', 'season', 'episode',
                            'media_type')}),
                   level='INFO')

    f_result = engine.get_subtitles(video_data)
    if not f_result:
        return []
    sorted_subs = engine.sort_subtitles(f_result, video_data)

    human, machine = [], []
    seen = set()
    for t in sorted_subs:
        # tuple layout (sort_subtitles.append_subtitles):
        #  0 label  1 colored_label2  2 icon  3 thumb  4 url
        #  5 percent 6 sync  7 hearing_imp  8 filename  9 site_id
        try:
            url = t[4]
            percent = t[5]
            sync = t[6]
            hi = t[7]
            filename = t[8]
            site_id = t[9]
        except Exception:
            continue

        parsed = _parse_download_url(url)
        if not parsed:
            continue
        lang = parsed['language']
        # Keep only Hebrew (human + machine-translated). Everything
        # else (English, etc.) is left for MoranSubs's AI path.
        if lang == 'HebrewMachineTranslated':
            bucket = machine
            kind_tag = 'mt'
        elif lang == 'Hebrew' or 'Hebrew' in (t[0] or ''):
            bucket = human
            kind_tag = 'human'
        else:
            continue

        # De-dup identical picks (same source+filename).
        dedup_key = (parsed['source'], parsed['filename'])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        provider = _PROVIDER_LABEL.get(site_id, parsed['source'] or '?')
        try:
            pct = int(percent)
        except Exception:
            pct = 0
        label = '{0} · {1}%'.format(provider, pct)
        if kind_tag == 'mt':
            label = '[תרגום מכונה] ' + label
        if parsed['filename']:
            label = '{0}  —  {1}'.format(label, parsed['filename'])

        link = _encode_engine_link(parsed, hi)
        bucket.append({
            'filename': label,
            'language': 'he',
            'link': link,
            # Human subs sorted by real release-name match; show the
            # match% as the rating star bucket (5=best ... 1).
            'sync': 'true' if (kind_tag == 'human' and pct >= 90) else 'false',
            'rating': _rating_for(pct, kind_tag),
            'is_hi': (hi == 'true'),
            'is_hd': False,
            '_engine_kind': kind_tag,
        })

    kodi_utils.log('subs_engine_bridge: {0} human + {1} machine Hebrew '
                   'subs'.format(len(human), len(machine)), level='INFO')
    return human + machine


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


def _rating_for(pct, kind_tag):
    # Machine-translated Hebrew always ranks below any human sub.
    if kind_tag == 'mt':
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
        return None


def _download_inner(payload):
    source = payload.get('source') or ''
    download_data = payload.get('download_data') or {}
    language = payload.get('language') or 'Hebrew'
    filename = payload.get('filename') or 'subtitle'

    module = _provider_module(source)
    if module is None or not hasattr(module, 'download'):
        kodi_utils.log('subs_engine_bridge: no download() for source '
                       + str(source), level='WARNING')
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

    sub_file = module.download(download_data, sub_folder)
    if not sub_file or not os.path.isfile(sub_file):
        kodi_utils.log('subs_engine_bridge: download returned no file',
                       level='WARNING')
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

    return sub_file
