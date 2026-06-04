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


def _source_id_for_ai(payload):
    """Stable identifier for one source SRT, used as part of the
    cache key. Wyzie URLs are stable per SRT so we use them as-is.
    Local files get content-hashed because Kodi reuses temp paths
    like TempSubtitle.0.srt across movies -- the filename alone
    is NOT a reliable identifier. Returns '' if we can't compute
    one cheaply (caller will fall back to content-hash after the
    SRT is in memory)."""
    wyzie_url = payload.get('wyzie_url')
    if wyzie_url:
        return wyzie_url
    local_path = payload.get('local_path')
    if local_path and os.path.isfile(local_path):
        try:
            import hashlib as _hashlib
            h = _hashlib.sha1()
            with open(local_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()[:16]
        except (IOError, OSError):
            return ''
    return ''


def _reapply_rtl_fix_in_place(path):
    """Re-run srt.fix_rtl_punctuation() on a cached translation
    file. Catches up files that were cached before the current
    version's regex coverage was wired in. Idempotent: if the
    file is already clean, no write happens.

    Called on every cache hit in resolve() so a returning user
    benefits from the latest fix without having to clear cache or
    wait for the next service.py startup migration."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except OSError:
        return
    fixed = srt.fix_rtl_punctuation(content)
    if fixed == content:
        return
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(fixed)
        os.replace(tmp, path)
        kodi_utils.log(
            'RTL fix reapplied on cache hit: ' + path,
            level='INFO')
    except OSError:
        try: os.remove(tmp)
        except OSError: pass


# ---- search ----------------------------------------------------------

def list_candidates(info):
    """Build the list Kodi's subtitle dialog will render.

    Returns a list of dicts with keys: filename, language, link,
    sync, rating. Empty list if nothing plausible is available.
    """
    filepath = info.get('filepath') or ''
    imdb_id = (info.get('imdb_id') or '').strip()
    tmdb_id = (info.get('tmdb_id') or '').strip()
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
    # Accept either imdb_id (set by the library scraper) or tmdb_id
    # (set by POV / FENtastic plugin streams via UniqueId(tmdb)).
    wyzie_by_lang = {}
    wyzie_last_status = None  # for diagnostics in the empty-results branch
    wyzie_last_error = None
    if wyzie.has_api_key() and (imdb_id or tmdb_id):
        wanted = ['he'] + [l for l in sources if l != 'he']
        try:
            hits = wyzie.search(
                imdb_id=imdb_id or None,
                tmdb_id=tmdb_id or None,
                season=season, episode=episode,
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
        # Diagnostics: capture last HTTP status / error if the result
        # list exposes them (the new _SearchResult subclass does).
        wyzie_last_status = getattr(hits, 'last_http_status', None)
        wyzie_last_error = getattr(hits, 'last_error', None)
        kodi_utils.log(
            'Wyzie search: imdb={0} tmdb={1} -> {2} hits '
            '(last HTTP {3}, err {4}). per-lang: {5}'.format(
                imdb_id, tmdb_id, len(wyzie_by_lang),
                wyzie_last_status, wyzie_last_error,
                {k: 1 for k in wyzie_by_lang}),
            level='INFO')

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
    #    Built into a separate list so cache hits can be sorted to
    #    the top of the AI section (just under Hebrew passthrough).
    ai_entries = []
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
            ai_entries.append({
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
                '_payload': {'source_lang': src_lang,
                             'local_path': local_path},
            })
            continue

        wyzie_hit = wyzie_by_lang.get(src_lang)
        if wyzie_hit:
            seen_langs.add(src_lang)
            ai_entries.append({
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
                '_payload': {'source_lang': src_lang,
                             'wyzie_url': wyzie_hit['url']},
            })

    # Mark cached entries with a visible label and sort them to the
    # top of the AI section so a returning user picks the
    # already-translated copy first (instant) instead of re-paying
    # for translation by clicking a fresh source.
    for entry in ai_entries:
        payload = entry.pop('_payload', {})
        try:
            src_id = _source_id_for_ai(payload)
            if src_id:
                translated = cache.translated_path(
                    imdb_id, season, episode,
                    payload.get('source_lang') or 'en',
                    source_id=src_id)
                if os.path.isfile(translated):
                    entry['is_cached'] = True
                    entry['rating'] = '5'
                    entry['sync'] = 'true'
                    entry['filename'] = '[CACHE] ' + entry['filename']
        except Exception as e:
            kodi_utils.log('cache marker check failed: {0}'.format(e),
                           level='DEBUG')
    ai_entries.sort(key=lambda e: 0 if e.get('is_cached') else 1)
    results.extend(ai_entries)

    if not results:
        # Give the user a hint about why we have nothing -- the
        # "no subtitles found" toast from Kodi alone is
        # uninformative. Each reason is conditional so the message
        # only lists what's actually missing.
        reasons = []
        if not imdb_id and not tmdb_id:
            reasons.append('אין IMDB / TMDB id מהנגן')
        if not wyzie.has_api_key():
            reasons.append('לא הוגדר Wyzie API key')
        elif (imdb_id or tmdb_id) and not wyzie_by_lang:
            # Be specific about WHY Wyzie returned empty -- the
            # difference between "service down", "key rejected" and
            # "title genuinely not in their index" matters a lot
            # for the user trying to debug.
            if wyzie_last_status is None:
                reasons.append(
                    'Wyzie לא הגיב (timeout). Wyzie מקרטעת לאחרונה '
                    '(Cloudflare 522). זה אצלם, לא אצלך. אפשרות חלופית '
                    'מיידית: לחץ על כתובית באנגלית מ-All_Subs - התוסף '
                    'AI יתרגם אותה אוטומטית לעברית.')
            elif wyzie_last_status == 200:
                reasons.append(
                    'Wyzie החזיר 0 תוצאות לסרט הזה גם תחת קודי שפה '
                    'חלופיים (he/heb/iw). הסרט כנראה לא באינדקס שלהם.')
            elif wyzie_last_status in (401, 403):
                reasons.append(
                    'Wyzie API key נדחה ({0}). בדוק ב-"בדיקת חיבור '
                    'Wyzie".'.format(wyzie_last_status))
            elif wyzie_last_status == 429:
                reasons.append(
                    'חרגת ממכסת Wyzie היומית (1000 בקשות). המתן '
                    'עד מחר.')
            elif 500 <= wyzie_last_status < 600:
                reasons.append(
                    'Wyzie במצב תקלה (HTTP {0}). נסה שוב מאוחר '
                    'יותר.'.format(wyzie_last_status))
            else:
                reasons.append(
                    'Wyzie החזיר HTTP {0} ({1}). נסה "בדיקת חיבור '
                    'Wyzie".'.format(wyzie_last_status,
                                     wyzie_last_error or '?'))
        if not alongside and not in_temp:
            reasons.append('אין קבצי SRT ב-temp או ליד הסרט')
        msg = 'AI: אין מקור לתרגום ({0}). אפשרויות: 1) בחר ' \
              'כתובית באנגלית מתוסף אחר ופתח שוב חיפוש 2) הגדר ' \
              'Wyzie API key 3) חפש סרט שיש לו IMDB id'.format(
                ' / '.join(reasons) or 'לא ידוע')
        kodi_utils.notify(msg, time_ms=15000)
        kodi_utils.log('list_candidates returned empty: ' + repr(
            {'imdb_id': imdb_id, 'tmdb_id': tmdb_id,
             'has_wyzie_key': wyzie.has_api_key(),
             'alongside_count': len(alongside),
             'in_temp_count': len(in_temp),
             'wyzie_hits_count': len(wyzie_by_lang)}),
            level='WARNING')

    return results


# ---- download / translate -------------------------------------------

def resolve(link, info, progress_cb=None, progressive_cb=None):
    """Return a filesystem path to the SRT for the chosen link.

    For passthrough, hand back the existing file path. For ai
    entries, translate (or read from cache) and return the cached
    file's path. progress_cb, if provided, is called as
    progress_cb(chunk_index, total_chunks).

    progressive_cb, if provided, is an opt-in fast-first-chunk
    callback used by the DarkSubs auto_translate path to release the
    English fallback to Kodi immediately and then swap subtitles in
    flight as each Hebrew chunk lands. Signature:
        progressive_cb(phase, payload)
    where phase is one of:
        'first_ready'  payload={'fallback_text', 'source_id'}
        'chunk_ready'  payload={'completed','total','merged_text',
                                'source_id'}
        'done'         payload={'success', 'source_id'}
    Quality is unchanged: the final canonical Hebrew bytes written
    via cache.save_text() are byte-identical to today's output for
    the same source SRT; only the timing of delivery differs.
    A callback exception NEVER aborts the translation."""
    payload = _decode_link(link)
    if not payload:
        kodi_utils.log('resolve: bad link', level='ERROR')
        return None

    kind = payload.get('type')
    kodi_utils.log('resolve: kind={0}'.format(kind), level='INFO')

    imdb_id = (info.get('imdb_id') or '').strip()
    season  = info.get('season') or ''
    episode = info.get('episode') or ''

    if kind == 'passthrough':
        path = payload.get('path')
        kodi_utils.notify(
            'AI: כתובית קיימת (passthrough) - {0}'.format(
                os.path.basename(path) if path else '?'),
            time_ms=4000)
        if path and os.path.isfile(path):
            return path
        return None

    if kind == 'wyzie_passthrough':
        kodi_utils.notify(
            'AI: מוריד עברית מ-Wyzie ישירות (לא תרגום AI)',
            time_ms=4000)
        url = payload.get('url') or ''
        text = wyzie.download(url)
        if not text:
            kodi_utils.notify('AI: Wyzie download נכשל',
                              time_ms=8000)
            return None
        # Unique per Wyzie URL so different movies don't overwrite
        # each other in the cache dir, and so Kodi doesn't see the
        # same file path twice in a row and assume "same subtitle
        # as last play".
        import hashlib as _hashlib
        url_hash = _hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]
        out = os.path.join(kodi_utils.cache_dir(),
                           'wyzie_{0}.he.srt'.format(url_hash))
        try:
            with open(out, 'w', encoding='utf-8') as f:
                f.write(text)
            return out
        except OSError as e:
            kodi_utils.notify('AI: שמירה נכשלה - {0}'.format(e),
                              time_ms=8000)
            return None

    if kind != 'ai':
        kodi_utils.log('resolve: unknown kind ' + str(kind),
                       level='WARNING')
        return None

    source_lang = payload.get('source_lang') or 'en'

    local_source = payload.get('local_path')
    wyzie_url = payload.get('wyzie_url')

    # Two-tier cache strategy:
    #  1. EARLY lookup: Wyzie URL is stable per-SRT; local path is
    #     hashed by content (cheap because the file is small).
    #     This avoids a redundant Wyzie download / re-translation
    #     for entries the user already translated. Same key the
    #     [CACHE] marker in list_candidates uses.
    #  2. CONTENT-HASH lookup after the source is in memory: catches
    #     the rare case where two different Wyzie URLs / local
    #     paths point to byte-identical SRTs.
    early_source_id = _source_id_for_ai(payload)
    if early_source_id:
        translated = cache.translated_path(
            imdb_id, season, episode, source_lang,
            source_id=early_source_id)
        if os.path.isfile(translated):
            kodi_utils.log('Cache hit (early): ' + translated,
                           level='INFO')
            kodi_utils.notify(
                'AI: כתוביות מ-cache (תרגום קודם)',
                time_ms=4000)
            try:
                now = time.time()
                os.utime(translated, (now, now))
            except OSError:
                pass
            _reapply_rtl_fix_in_place(translated)
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
            'מקור הכתוביות לא נמצא — בחר שוב',
            time_ms=5000,
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

    # Content-hash lookup: only catches a hit when SOURCE bytes
    # match a previously translated SRT served from a different
    # url/path. Translation is saved to the early-source-id slot
    # (so list_candidates can pre-mark it as [CACHE]) and ALSO
    # to the content-hash slot so a future click of a different
    # url with identical content also hits cache.
    import hashlib as _hashlib
    content_id = _hashlib.sha1(
        src_text.encode('utf-8', errors='replace')).hexdigest()[:16]
    if content_id != early_source_id:
        translated_by_content = cache.translated_path(
            imdb_id, season, episode, source_lang,
            source_id=content_id)
        if os.path.isfile(translated_by_content):
            kodi_utils.log(
                'Cache hit (content): ' + translated_by_content,
                level='INFO')
            kodi_utils.notify(
                'AI: כתוביות מ-cache (זהה לתרגום קיים)',
                time_ms=4000)
            try:
                now = time.time()
                os.utime(translated_by_content, (now, now))
            except OSError:
                pass
            _reapply_rtl_fix_in_place(translated_by_content)
            return translated_by_content

    # No hit: settle on the early-source-id slot as the canonical
    # cache path for this translation; falls back to content_id
    # when we have no stable source_id at all.
    translated = cache.translated_path(
        imdb_id, season, episode, source_lang,
        source_id=(early_source_id or content_id))

    # Captured once and reused for ALL progressive callback emissions
    # so the caller can correlate first_ready/chunk_ready/done into a
    # single in-flight translation. Same value the cache key uses
    # above. Safe to evaluate here -- both ids are now stable.
    _progressive_source_id = early_source_id or content_id

    # Fast-first-chunk hand-off: release the English fallback to the
    # caller (e.g. DarkSubs) so Kodi can start showing SOMETHING in
    # seconds while we translate in the background. The bytes are
    # the POST-strip src_text -- the same source we'll feed to
    # Gemini -- so what the user sees onscreen matches what gets
    # translated. A buggy callback must not abort us.
    if progressive_cb is not None:
        try:
            progressive_cb('first_ready', {
                'fallback_text': src_text,
                'source_id': _progressive_source_id,
            })
        except Exception as e:
            kodi_utils.log(
                'progressive_cb first_ready raised: ' + str(e),
                level='WARNING')

    kodi_utils.log(
        'No cache hit. Starting translation. imdb={0} content_id={1} '
        'src_len={2}'.format(imdb_id, content_id, len(src_text)),
        level='INFO')

    # Up-front heads-up so the user understands the wait. The
    # progress dialog itself is a DialogProgressBG which sits in
    # the corner during video playback, easy to miss. Kodi has an
    # internal timeout on subtitle downloads and will likely show
    # its own "subtitle download failed" toast before we finish on
    # longer pieces -- the translation continues anyway and the
    # result is cached, so on the next subtitle-search the user
    # sees it as a cached entry and gets it instantly.
    # Kept VERY short on purpose -- Kodi's notification widget
    # scrolls anything past ~50 visible chars, and the scroll
    # direction in most skins is hardcoded LTR which makes a long
    # Hebrew message read "backwards" to the user. The 25/50/75 %
    # milestone toasts later replace the old "התקדמות תופיע בפינה"
    # explanation that used to bloat this kickoff line.
    kodi_utils.notify(
        'AI מתרגם (כדקה-שתיים). תתעלם משגיאות ביניים.',
        time_ms=8000,
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
    # Bumped cap (Oct 2026 -- minor characters were missing from
    # top-12). A cached cast with fewer than this many entries is
    # stale; treat as a cache miss so we re-fetch and store the
    # expanded list.
    MIN_CAST_FOR_CACHE = 20
    if meta_path:
        cached_meta = cache.load_json(meta_path)
        if cached_meta:
            cached_cast = cached_meta.get('cast') or []
            if len(cached_cast) >= MIN_CAST_FOR_CACHE:
                cast = cached_cast
                title = cached_meta.get('title') or title
                year = cached_meta.get('year') or year
            else:
                kodi_utils.log(
                    'Cached cast has only {0} entries -- refetching '
                    'for expanded coverage'.format(len(cached_cast)),
                    level='DEBUG')
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
    top_p = kodi_utils.get_float('top_p', 0.95)
    thinking_raw = (kodi_utils.get_setting('thinking_budget', 'disabled')
                    or 'disabled').strip().lower()
    thinking_level = None
    thinking_budget = None
    if thinking_raw in ('minimal', 'low', 'medium', 'high'):
        thinking_level = thinking_raw
    else:
        try:
            thinking_budget = int(thinking_raw)
        except (TypeError, ValueError):
            thinking_budget = 0
        if thinking_budget <= 0:
            thinking_budget = None
    if thinking_budget and model.lower().startswith('gemini-3.'):
        if thinking_budget <= 512:
            thinking_level = 'minimal'
        elif thinking_budget <= 768:
            thinking_level = 'low'
        elif thinking_budget <= 1024:
            thinking_level = 'medium'
        else:
            thinking_level = 'high'
        thinking_budget = None
    whole_subtitle_request = kodi_utils.get_bool(
        'whole_subtitle_request', False)
    max_output_tokens = 65535 if whole_subtitle_request else 16384
    gemini_timeout = 300 if whole_subtitle_request else None
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

    if whole_subtitle_request:
        chunks = [blocks]
        kodi_utils.notify(
            'AI: מתרגם את כל הכתוביות בפעימה אחת. זה יכול לקחת כמה דקות.',
            time_ms=7000)
    else:
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

    # Cross-chunk continuity. For chunk N, give the model the last
    # PREV_CONTEXT_LINES dialogue lines from chunk N-1's SOURCE so
    # the model has the same conversational thread it would have
    # had if everything ran in one giant chunk. Computed once
    # up-front (deterministic per index) so parallel chunk
    # dispatch still works -- no inter-chunk dependency.
    prev_context_lines = max(0, kodi_utils.get_int(
        'prev_context_lines', 5))
    prev_context_by_idx = {}
    if prev_context_lines > 0 and not whole_subtitle_request:
        for i in range(1, len(chunks)):
            prev_block_texts = []
            for block in chunks[i - 1][-prev_context_lines:]:
                t = srt.block_text_only(block)
                if t:
                    prev_block_texts.append(t)
            prev_context_by_idx[i] = prev_block_texts

    def _call_gemini(idx, ch):
        body = '\n\n'.join(ch)
        prev_ctx_block = prompt.build_prev_context_block(
            prev_context_by_idx.get(idx) or [])
        full_prompt = (prompt_template
                       .replace('{prev_context_block}', prev_ctx_block)
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
                    max_output_tokens=max_output_tokens,
                    top_p=top_p,
                    thinking_budget=thinking_budget,
                    thinking_level=thinking_level,
                    timeout=gemini_timeout or gemini.REQUEST_TIMEOUT,
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
    if whole_subtitle_request:
        parallel = 1
    else:
        parallel = max(1, min(8, kodi_utils.get_int(
            'parallel_chunks', 3)))
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
                if progressive_cb is not None:
                    try:
                        # Merge: Hebrew where done, source English
                        # where pending. Inline (not a srt.py helper)
                        # because this view is meaningful only here.
                        _merged_blocks = []
                        for _i, _ch in enumerate(chunks):
                            # chunks is 0-indexed; out_blocks_by_index
                            # is 1-indexed (idx = i + 1 above).
                            _key = _i + 1
                            if _key in out_blocks_by_index:
                                _merged_blocks.extend(
                                    out_blocks_by_index[_key])
                            else:
                                _merged_blocks.extend(_ch)
                        _merged_text = srt.fix_rtl_punctuation(
                            srt.stitch_blocks(_merged_blocks))
                        progressive_cb('chunk_ready', {
                            'completed': completed,
                            'total': total,
                            'merged_text': _merged_text,
                            'source_id': _progressive_source_id,
                        })
                    except Exception as e:
                        kodi_utils.log(
                            'progressive_cb chunk_ready raised: '
                            + str(e),
                            level='WARNING')
    except ImportError:
        # Older Python without concurrent.futures -- shouldn't
        # happen on Kodi 21 but bail safely.
        kodi_utils.notify('AI: שגיאה פנימית, התקן Python 3.6+',
                          time_ms=8000)
        return None

    if abort_msg:
        kodi_utils.notify(abort_msg, time_ms=12000)
        if progressive_cb is not None:
            try:
                progressive_cb('done', {
                    'success': False,
                    'source_id': _progressive_source_id,
                })
            except Exception as e:
                kodi_utils.log(
                    'progressive_cb done(abort) raised: ' + str(e),
                    level='WARNING')
        return None

    if completed != total:
        kodi_utils.notify(
            'AI: תרגום הסתיים חלקית ({0}/{1}). נסה שוב.'.format(
                completed, total),
            time_ms=10000)
        if progressive_cb is not None:
            try:
                progressive_cb('done', {
                    'success': False,
                    'source_id': _progressive_source_id,
                })
            except Exception as e:
                kodi_utils.log(
                    'progressive_cb done(partial) raised: ' + str(e),
                    level='WARNING')
        return None

    # Stitch in original order.
    out_blocks = []
    for i in sorted(out_blocks_by_index.keys()):
        out_blocks.extend(out_blocks_by_index[i])

    final = srt.stitch_blocks(out_blocks)
    # Defensive backstop for RTL punctuation: Gemini sometimes puts
    # punctuation at the logical start of a Hebrew line ("?שלום")
    # when it belongs at the logical end ("שלום?"). The prompt
    # instructs against this, but this post-processor catches any
    # slips so the final SRT renders correctly in Kodi.
    final = srt.fix_rtl_punctuation(final)
    cache.save_text(translated, final)
    # Also save under the content-hash slot when it differs from
    # the early-source-id slot. That way the same translation
    # answers a future lookup whether the user comes back via the
    # same URL/local path OR via a different source whose bytes
    # happen to match (e.g. a re-download of the same SRT from a
    # different Wyzie URL).
    if early_source_id and content_id and content_id != early_source_id:
        try:
            cache.save_text(
                cache.translated_path(
                    imdb_id, season, episode, source_lang,
                    source_id=content_id),
                final)
        except Exception as e:
            kodi_utils.log(
                'content-hash duplicate save failed: {0}'.format(e),
                level='DEBUG')
    # Append today's Gemini quota usage to the success toast, but
    # only if the user is on the tracked model (3.1 Flash Lite).
    # Wrapped so a quota-module bug can't drop the toast itself.
    quota_suffix = ''
    try:
        from . import gemini_quota
        if gemini_quota.is_tracked(model):
            quota_suffix = ' · ' + gemini_quota.format_status_short()
    except Exception:
        quota_suffix = ''
    kodi_utils.notify('AI: תרגום הסתיים בהצלחה ({0} chunks){1}'
                      .format(total, quota_suffix), time_ms=4000)
    if progressive_cb is not None:
        try:
            progressive_cb('done', {
                'success': True,
                'source_id': _progressive_source_id,
            })
        except Exception as e:
            kodi_utils.log(
                'progressive_cb done(success) raised: ' + str(e),
                level='WARNING')
    return translated
