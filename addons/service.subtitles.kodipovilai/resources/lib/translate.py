# Orchestration: take a video metadata dict and a target language,
# return either a list of candidate subtitle entries (for the
# search dialog) or a final SRT path (for the download step).
#
# Source policy (we do NOT touch OpenSubtitles ourselves -- the
# user's existing subtitle addons (DarkSubs, OS-by-OS, etc.) handle
# all sourcing and have their own working quotas/keys, so we just
# read whatever they drop into Kodi's temp dir):
#
#   1. Hebrew SRT next to the video         -> hand it back as-is
#   2. Hebrew SRT in special://temp/         -> hand it back as-is
#   3. Source-lang SRT next to the video    -> translate to Hebrew
#   4. Source-lang SRT in special://temp/    -> translate to Hebrew
#                                              (lets the user grab
#                                              English from
#                                              DarkSubs/OS, then
#                                              come back to us)
#
# Two top-level entry points:
#   list_candidates(info)  -> [{title, language, link, ...}]
#   resolve(link, info)    -> path-to-srt-on-disk

import json
import os
import time
import urllib.parse

from . import cache
from . import gemini
from . import kodi_utils
from . import language_detect
from . import local_subs
from . import prompt
from . import srt
from . import tmdb_helper
from . import wyzie

# Iteration order = priority order. settings.xml exposes
# checkboxes -- we filter the disabled ones out at runtime.
ALL_SOURCE_LANGS = [
    ('en', 'src_english'),
    ('es', 'src_spanish'),
    ('de', 'src_german'),
    ('fr', 'src_french'),
    ('pt', 'src_portuguese'),
]


def _enabled_sources():
    return [code for code, key in ALL_SOURCE_LANGS
            if kodi_utils.get_bool(key, code in ('en', 'es'))]


def _encode_link(payload):
    return urllib.parse.quote(json.dumps(payload, ensure_ascii=False))


def _decode_link(link):
    try:
        return json.loads(urllib.parse.unquote(link))
    except (ValueError, TypeError):
        return None


def _lang_display(code):
    return {
        'en': 'English', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'pt': 'Portuguese', 'he': 'Hebrew',
    }.get(code, code or 'Unknown')


# ---- search ----------------------------------------------------------

def list_candidates(info):
    """Build the list Kodi's subtitle dialog will render.

    Returns a list of dicts with keys: filename, language, link,
    sync, rating. Empty list if nothing plausible is available.
    """
    filepath = info.get('filepath') or ''
    imdb_id = (info.get('imdb_id') or '').strip()
    season  = info.get('season') or ''
    episode = info.get('episode') or ''
    sources = _enabled_sources()

    # Collect candidate source files from the two filesystem
    # locations we look at. By-language dicts, so first match wins
    # per language.
    alongside = {}
    for path, lang in local_subs.find_alongside(filepath):
        if lang and lang not in alongside:
            alongside[lang] = path

    in_temp = {}
    for entry in local_subs.find_in_temp():
        lang = entry['lang']
        if not lang or lang in in_temp:
            continue
        # CRITICAL: never accept Hebrew from the temp dir as a
        # passthrough candidate. The file Kodi keeps there
        # (typically TempSubtitle.he.srt) is whatever was
        # selected last -- which means after translating movie
        # A, opening the subtitle dialog for movie B would
        # surface movie A's Hebrew SRT as if it were a match
        # for movie B. Only trust local files alongside the
        # video or fresh Wyzie hits for Hebrew passthrough.
        if lang == 'he':
            continue
        in_temp[lang] = entry['path']

    # Wyzie hits if the user has set their API key. Look up Hebrew
    # AND each source language in one round trip so we can offer
    # passthrough Hebrew if available, otherwise translate options.
    wyzie_by_lang = {}
    if wyzie.has_api_key() and imdb_id:
        wanted = ['he'] + [l for l in sources if l != 'he']
        try:
            hits = wyzie.search(
                imdb_id=imdb_id, season=season, episode=episode,
                languages=tuple(wanted),
            )
        except Exception as e:
            kodi_utils.log('wyzie search failed: {0}'.format(e),
                           level='WARNING')
            hits = []
        for h in hits:
            lang = h.get('language')
            if lang and lang not in wyzie_by_lang:
                wyzie_by_lang[lang] = h

    results = []

    # 1. Hebrew passthrough -- if there's already a Hebrew SRT we
    #    can hand to Kodi, no need to translate anything.
    have_hebrew = False
    if 'he' in alongside:
        have_hebrew = True
        results.append({
            'filename': os.path.basename(alongside['he']),
            'language': 'he',
            'link': _encode_link({
                'type': 'passthrough', 'path': alongside['he'],
            }),
            'sync': 'true',
            'rating': '5',
            'is_hi': False, 'is_hd': False,
        })
    elif 'he' in wyzie_by_lang:
        # Online Hebrew. Kodi will fetch it through us when picked.
        have_hebrew = True
        h = wyzie_by_lang['he']
        results.append({
            'filename': h.get('release') or h.get('name') or 'Hebrew',
            'language': 'he',
            'link': _encode_link({
                'type': 'wyzie_passthrough', 'url': h['url'],
            }),
            'sync': 'false',
            'rating': '4',
            'is_hi': h.get('hi', False),
            'is_hd': False,
        })

    skip_when_hebrew = kodi_utils.get_bool('skip_if_hebrew', True)
    if have_hebrew and skip_when_hebrew:
        return results

    # 2. For each enabled source language, surface ONE "translate
    #    this" entry. Priority order:
    #       (a) alongside file (local re-watch)
    #       (b) temp-dir file (loaded by another addon)
    #       (c) Wyzie online (single-click flow if user has key)
    seen_langs = set()
    for src_lang in sources:
        if src_lang in seen_langs:
            continue

        local_path = alongside.get(src_lang) or in_temp.get(src_lang)
        if local_path:
            seen_langs.add(src_lang)
            source_label = _lang_display(src_lang)
            source_origin = ('local file' if alongside.get(src_lang)
                             else 'loaded by another addon')
            results.append({
                'filename': 'AI Hebrew (translate {0} {1})'.format(
                    source_label, source_origin),
                'language': 'he',
                'link': _encode_link({
                    'type': 'ai',
                    'source_lang': src_lang,
                    'local_path': local_path,
                }),
                'sync': 'false',
                'rating': '4' if src_lang == 'en' else '3',
                'is_hi': False, 'is_hd': False,
            })
            continue

        wyzie_hit = wyzie_by_lang.get(src_lang)
        if wyzie_hit:
            seen_langs.add(src_lang)
            results.append({
                'filename': 'AI Hebrew (translate {0} via Wyzie)'.format(
                    _lang_display(src_lang)),
                'language': 'he',
                'link': _encode_link({
                    'type': 'ai',
                    'source_lang': src_lang,
                    'wyzie_url': wyzie_hit['url'],
                }),
                'sync': 'false',
                'rating': '4' if src_lang == 'en' else '3',
                'is_hi': False, 'is_hd': False,
            })

    return results


# ---- download / translate -------------------------------------------

def resolve(link, info, progress_cb=None):
    """Return a filesystem path to the SRT for the chosen link.

    For passthrough, hand back the existing file path. For ai
    entries, translate (or read from cache) and return the cached
    file's path. progress_cb, if provided, is called as
    progress_cb(chunk_index, total_chunks)."""
    payload = _decode_link(link)
    if not payload:
        return None

    kind = payload.get('type')

    imdb_id = (info.get('imdb_id') or '').strip()
    season  = info.get('season') or ''
    episode = info.get('episode') or ''

    if kind == 'passthrough':
        path = payload.get('path')
        if path and os.path.isfile(path):
            return path
        return None

    if kind == 'wyzie_passthrough':
        text = wyzie.download(payload.get('url'))
        if not text:
            return None
        out = os.path.join(kodi_utils.cache_dir(), 'wyzie_he.srt')
        try:
            with open(out, 'w', encoding='utf-8') as f:
                f.write(text)
            return out
        except OSError:
            return None

    if kind != 'ai':
        return None

    source_lang = payload.get('source_lang') or 'en'

    # Source identifier used in the cache key when imdb_id is
    # empty (typical for POV / plugin:// streams). Without this,
    # every cache-key collapses to 'unknown' and we'd serve the
    # first-ever translated movie for every subsequent one.
    local_source = payload.get('local_path')
    wyzie_url = payload.get('wyzie_url')
    source_id = wyzie_url or local_source or ''

    # Already translated this exact tuple? Return the cached file.
    translated = cache.translated_path(
        imdb_id, season, episode, source_lang, source_id=source_id)
    if os.path.isfile(translated):
        kodi_utils.log('Cache hit: ' + translated, level='INFO')
        try:
            now = time.time()
            os.utime(translated, (now, now))
        except OSError:
            pass
        return translated

    # Read the source SRT. Either we recorded a local path at list
    # time (alongside / temp dir) or a Wyzie download URL.
    src_text = None
    if local_source and os.path.isfile(local_source):
        try:
            with open(local_source, 'r', encoding='utf-8',
                      errors='replace') as f:
                src_text = f.read()
        except (IOError, OSError):
            src_text = None
    elif wyzie_url:
        src_text = wyzie.download(wyzie_url)
    if not src_text:
        kodi_utils.notify(
            'הקובץ של הכתוביות המקור לא נמצא. בחר שוב כתובית בשפת מקור '
            'ונסה שוב.',
            time_ms=8000,
        )
        return None

    # Strip hearing-impaired noise BEFORE translation. Source SRTs
    # often have things like "[breathing heavily]" / "(music plays)"
    # / "MABEL: ..." that aren't speech we want translated; they
    # just clutter the Hebrew output. Skipped if the cleaner ate
    # the entire file (it won't, but defend against it).
    cleaned = srt.strip_hi_annotations(src_text)
    if cleaned and srt.count_entries(cleaned) >= max(
            1, int(srt.count_entries(src_text) * 0.3)):
        src_text = cleaned

    # Up-front heads-up so the user understands the wait. The
    # progress dialog itself is a DialogProgressBG which sits in
    # the corner during video playback, easy to miss. Kodi has an
    # internal timeout on subtitle downloads and will likely show
    # its own "subtitle download failed" toast before we finish on
    # longer pieces -- the translation continues anyway and the
    # result is cached, so on the next subtitle-search the user
    # sees it as a cached entry and gets it instantly.
    kodi_utils.notify(
        'AI: מתחיל תרגום. יכול לקחת דקה-שתיים. '
        'התקדמות תופיע בפינה. אם Kodi יציג "הורדה נכשלה" '
        'באמצע - תתעלם, התרגום ממשיך וייושמר אוטומטית.',
        time_ms=10000,
    )

    # Sanity: if the source is actually Hebrew (mislabeled),
    # don't translate -- pass through.
    if language_detect.detect(src_text[:8000]) == 'he':
        cache.save_text(translated, src_text)
        return translated

    # Cast metadata (cached per-imdb).
    meta_path = cache.metadata_path(imdb_id) if imdb_id else None
    cast = None
    title = info.get('title') or ''
    year = info.get('year') or ''
    if meta_path:
        cached_meta = cache.load_json(meta_path)
        if cached_meta:
            cast = cached_meta.get('cast') or []
            title = cached_meta.get('title') or title
            year = cached_meta.get('year') or year
    if cast is None:
        try:
            cast = tmdb_helper.fetch_cast(
                imdb_id=imdb_id,
                media_type=('tv' if info.get('is_episode') else 'movie'),
                season=season, episode=episode,
            )
            t2, y2 = tmdb_helper.title_and_year(imdb_id=imdb_id)
            title = title or t2
            year = year or y2
            if meta_path:
                cache.save_json(meta_path, {
                    'cast': cast, 'title': title, 'year': year,
                })
        except Exception as e:
            kodi_utils.log('TMDB lookup failed: {0}'.format(e),
                           level='WARNING')
            cast = []

    # Prompt + chunk + translate via Gemini.
    api_key = kodi_utils.get_setting('api_key', '')
    if not api_key:
        kodi_utils.notify(kodi_utils.localised(33002))
        return None
    model = kodi_utils.get_setting('model', 'gemini-3.1-flash-lite') \
            or 'gemini-3.1-flash-lite'
    temperature = kodi_utils.get_float('temperature', 0.2)
    chunk_lines = kodi_utils.get_int('chunk_lines', 250)

    prompt_template = prompt.build(
        source_lang=source_lang,
        title=title,
        year=year,
        cast=cast,
        is_episode=info.get('is_episode', False),
        tvshow=info.get('tvshow', ''),
        season=season,
        episode=episode,
    )

    blocks = srt.parse_blocks(src_text)
    if not blocks:
        kodi_utils.log('Source SRT had no parseable blocks',
                       level='WARNING')
        return None

    chunks = list(srt.chunk_blocks(blocks, per_chunk=chunk_lines))
    total = len(chunks)

    # Backoff schedule for retryable Gemini failures (503 overload,
    # 500 / 502 / 504 transients). Google's published guidance is to
    # wait at least a few seconds before retrying these.
    OVERLOAD_BACKOFF = [5, 15, 30, 60, 120]  # seconds
    # Other transient (non-overload) Gemini errors get a shorter
    # schedule -- they're usually content / parse / safety issues,
    # not infrastructure.
    GENERIC_BACKOFF = [2, 5]

    # Per-chunk translator. Holds the inner retry loop. Returns the
    # raw Gemini response text, or raises a Stop-style exception
    # that the orchestrator below catches and converts into a
    # cancellation across all parallel chunks.
    class _AbortTranslation(Exception):
        def __init__(self, reason, user_msg):
            self.reason = reason
            self.user_msg = user_msg

    def _translate_one(idx, ch):
        # Recursive bisection on TruncatedResponse OR low-yield
        # response (Gemini sometimes skips entries silently --
        # observed in the first end-to-end test, a 5-minute gap
        # in the middle of a translated movie). Bisecting forces
        # the model to spend more attention per entry.
        if len(ch) > 1:
            try:
                response = _call_gemini(idx, ch)
            except gemini.TruncatedResponse as e:
                mid = len(ch) // 2
                kodi_utils.log(
                    'Chunk {0} truncated -- bisecting into {1} + {2}'
                    .format(idx, mid, len(ch) - mid),
                    level='WARNING')
                left = _translate_one(idx, ch[:mid])
                right = _translate_one(idx, ch[mid:])
                return left + '\n\n' + right

            # Yield check: did we get back roughly as many entries
            # as we asked for? Gemini sometimes drops entries
            # mid-chunk, leaving silent gaps in the final SRT.
            # Threshold 85% -- below that, bisect and re-do.
            got = len(srt.parse_blocks(response))
            expected = len(ch)
            if got < max(1, int(expected * 0.85)):
                mid = expected // 2
                kodi_utils.log(
                    'Chunk {0} low yield ({1}/{2} entries) -- '
                    'bisecting into {3} + {4}'.format(
                        idx, got, expected, mid, expected - mid),
                    level='WARNING')
                left = _translate_one(idx, ch[:mid])
                right = _translate_one(idx, ch[mid:])
                return left + '\n\n' + right

            return response
        # single-entry chunk that still truncates -- shouldn't
        # happen (one SRT entry is < 100 tokens), but if it does
        # we surface the partial text so the user sees something.
        try:
            return _call_gemini(idx, ch)
        except gemini.TruncatedResponse as e:
            kodi_utils.log(
                'Chunk {0} truncated even at size 1 -- '
                'returning partial'.format(idx),
                level='ERROR')
            return e.partial_text or ''

    def _call_gemini(idx, ch):
        body = '\n\n'.join(ch)
        full_prompt = (prompt_template
                       .replace('{entry_count}', str(len(ch)))
                       .replace('{chunk}', body))
        overload_attempts = 0
        generic_attempts = 0
        while True:
            try:
                return gemini.generate(
                    api_key=api_key,
                    model=model,
                    prompt=full_prompt,
                    temperature=temperature,
                )
            except gemini.QuotaExceeded:
                raise _AbortTranslation('quota',
                    kodi_utils.localised(33005))
            except gemini.InvalidKey as e:
                kodi_utils.log('InvalidKey: {0}'.format(e),
                               level='ERROR')
                raise _AbortTranslation('invalid_key',
                    kodi_utils.localised(33004, 'API key rejected'))
            except gemini.TruncatedResponse:
                # propagate up to _translate_one which will bisect
                raise
            except gemini.OverloadError as e:
                if overload_attempts < len(OVERLOAD_BACKOFF):
                    wait = OVERLOAD_BACKOFF[overload_attempts]
                    overload_attempts += 1
                    kodi_utils.log(
                        'Gemini overloaded chunk {0}/{1}, '
                        'retry {2}/{3} in {4}s'.format(
                            idx, total, overload_attempts,
                            len(OVERLOAD_BACKOFF), wait),
                        level='WARNING')
                    kodi_utils.notify(
                        'AI: Gemini עמוס. ניסיון {0}/{1} בעוד {2}ש'
                        .format(overload_attempts,
                                len(OVERLOAD_BACKOFF), wait),
                        time_ms=min(wait * 1000, 8000))
                    time.sleep(wait)
                    continue
                raise _AbortTranslation('overload',
                    'AI: Gemini עמוס מדי גם אחרי {0} ניסיונות. '
                    'תרגום נכשל ב-chunk {1}/{2}.'.format(
                        len(OVERLOAD_BACKOFF), idx, total))
            except gemini.GeminiError as e:
                if generic_attempts < len(GENERIC_BACKOFF):
                    wait = GENERIC_BACKOFF[generic_attempts]
                    generic_attempts += 1
                    kodi_utils.log(
                        'Gemini error chunk {0}/{1} attempt {2}: {3}'
                        .format(idx, total, generic_attempts, e),
                        level='WARNING')
                    time.sleep(wait)
                    continue
                raise _AbortTranslation('error',
                    kodi_utils.localised(33008, str(e)[:80]))

    # Parallel chunk dispatch. Gemini Flash Lite is 15 RPM, so 3
    # in flight at once is safe and turns a ~2-3 minute sequential
    # translation into ~30-60 seconds wall time. Users with the
    # paid tiers can crank this via `parallel_chunks` in the
    # advanced settings.
    parallel = max(1, min(8, kodi_utils.get_int('parallel_chunks', 3)))
    out_blocks_by_index = {}
    completed = 0
    abort_msg = None

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            future_to_idx = {
                pool.submit(_translate_one, i + 1, ch): i + 1
                for i, ch in enumerate(chunks)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    response = future.result()
                except _AbortTranslation as e:
                    abort_msg = e.user_msg
                    # Try to cancel pending futures; in-flight ones
                    # will run to completion but we ignore them.
                    for f in future_to_idx:
                        f.cancel()
                    break
                except Exception as e:
                    abort_msg = 'AI: שגיאה בלתי צפויה: {0}'.format(
                        str(e)[:80])
                    for f in future_to_idx:
                        f.cancel()
                    break
                out_blocks_by_index[idx] = srt.parse_blocks(response)
                completed += 1
                if progress_cb:
                    try:
                        progress_cb(completed, total)
                    except Exception:
                        pass
    except ImportError:
        # Older Python without concurrent.futures -- shouldn't
        # happen on Kodi 21 but bail safely.
        kodi_utils.notify('AI: שגיאה פנימית, התקן Python 3.6+',
                          time_ms=8000)
        return None

    if abort_msg:
        kodi_utils.notify(abort_msg, time_ms=12000)
        return None

    if completed != total:
        kodi_utils.notify(
            'AI: תרגום הסתיים חלקית ({0}/{1}). נסה שוב.'.format(
                completed, total),
            time_ms=10000)
        return None

    # Stitch in original order.
    out_blocks = []
    for i in sorted(out_blocks_by_index.keys()):
        out_blocks.extend(out_blocks_by_index[i])

    final = srt.stitch_blocks(out_blocks)
    cache.save_text(translated, final)
    kodi_utils.notify('AI: תרגום הסתיים בהצלחה ({0} chunks)'
                      .format(total), time_ms=4000)
    return translated
