# Orchestration: take a video metadata dict and a target language,
# return either a list of candidate subtitle entries (for the search
# dialog) or a final SRT path (for the download step).
#
# Two top-level entry points:
#   list_candidates(info)  -> [{title, language, link, ...}]
#   resolve(link, info)    -> path-to-srt-on-disk
#
# `link` is an opaque token we round-trip through Kodi -- it
# encodes whether to translate (and from which source) or just
# pass through an existing OS sub.

import json
import os
import time
import urllib.parse

from . import cache
from . import gemini
from . import kodi_utils
from . import language_detect
from . import opensubs
from . import prompt
from . import srt
from . import tmdb_helper

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


# ---- search ----------------------------------------------------------

def list_candidates(info):
    """Build the list Kodi's subtitle dialog will render.

    Returns a list of dicts with keys: filename, language,
    language_name, link, sync, rating. Empty list if nothing
    plausible is available.

    Policy: if real Hebrew subs exist and skip_if_hebrew is on,
    those float to the top; the AI entry still appears too so the
    user can override if they want, but ranks lower.
    """
    imdb_id = (info.get('imdb_id') or '').strip()
    season  = info.get('season') or ''
    episode = info.get('episode') or ''
    title   = info.get('title') or ''
    year    = info.get('year') or ''

    results = []

    # 1. Look for existing Hebrew subs first. If found AND
    #    skip_if_hebrew is on, we won't translate -- but we still
    #    list them in the dialog (Kodi will fetch them, not us).
    have_hebrew = False
    if imdb_id:
        try:
            hebrew_hits = opensubs.search(
                imdb_id=imdb_id, season=season, episode=episode,
                languages=('he',))
        except Exception as e:
            kodi_utils.log('OpenSubtitles he search failed: {0}'.format(e),
                           level='WARNING')
            hebrew_hits = []
        for h in hebrew_hits[:5]:
            have_hebrew = True
            results.append({
                'filename': h.get('release') or h.get('filename') or 'Hebrew',
                'language': 'he',
                'link': _encode_link({'type': 'os_passthrough',
                                      'file_id': h.get('file_id'),
                                      'language': 'he'}),
                'sync': 'true' if (h.get('fps') or 0) else 'false',
                'rating': str(min(5, max(0, int(h.get('download_count', 0) // 5000)))),
                'is_hi': h.get('hi', False),
                'is_hd': h.get('hd', False),
            })

    skip_when_hebrew = kodi_utils.get_bool('skip_if_hebrew', True)
    if have_hebrew and skip_when_hebrew:
        # Done -- no AI entry needed.
        return results

    # 2. For each source language we have enabled, see if OS has a
    #    sub for this title in that language; if yes, add an AI
    #    entry that means "translate this".
    sources = _enabled_sources()
    seen_langs = set()
    for src_lang in sources:
        if not imdb_id:
            # Without an IMDB id we can't reliably search OS for
            # the right title. Surface a single "AI from en" entry
            # using local files only -- it'll resolve at download
            # time using info dict alone.
            if 'en' not in seen_langs:
                seen_langs.add('en')
                results.append({
                    'filename': 'AI Hebrew (translated from English)',
                    'language': 'he',
                    'link': _encode_link({'type': 'ai',
                                          'source_lang': 'en'}),
                    'sync': 'false',
                    'rating': '3',
                    'is_hi': False, 'is_hd': False,
                })
            continue

        try:
            src_hits = opensubs.search(
                imdb_id=imdb_id, season=season, episode=episode,
                languages=(src_lang,))
        except Exception as e:
            kodi_utils.log('OS {0} search failed: {1}'.format(src_lang, e),
                           level='WARNING')
            src_hits = []

        if not src_hits:
            continue
        if src_lang in seen_langs:
            continue
        seen_langs.add(src_lang)
        top = src_hits[0]
        results.append({
            'filename': 'AI Hebrew (translated from {0})'.format(
                _lang_display(src_lang)),
            'language': 'he',
            'link': _encode_link({'type': 'ai',
                                  'source_lang': src_lang,
                                  'file_id': top.get('file_id')}),
            'sync': 'false',
            'rating': '4' if src_lang == 'en' else '3',
            'is_hi': False, 'is_hd': False,
        })

    return results


def _lang_display(code):
    return {
        'en': 'English', 'es': 'Spanish', 'fr': 'French',
        'de': 'German', 'pt': 'Portuguese',
    }.get(code, code or 'Unknown')


# ---- download / translate -------------------------------------------

def resolve(link, info, progress_cb=None):
    """Return a filesystem path to the SRT for the chosen link.

    For os_passthrough, we just download the OS file and return its
    path. For ai entries, we translate (or read from cache) and
    return the cached file's path.
    progress_cb, if provided, is called as progress_cb(stage, pct).
    """
    payload = _decode_link(link)
    if not payload:
        return None

    kind = payload.get('type')

    imdb_id = (info.get('imdb_id') or '').strip()
    season  = info.get('season') or ''
    episode = info.get('episode') or ''

    if kind == 'os_passthrough':
        text = opensubs.download(payload.get('file_id'))
        if not text:
            return None
        out = os.path.join(kodi_utils.cache_dir(), 'pass_he.srt')
        try:
            with open(out, 'w', encoding='utf-8') as f:
                f.write(text)
            return out
        except OSError:
            return None

    if kind != 'ai':
        return None

    source_lang = payload.get('source_lang') or 'en'

    # Already translated this exact tuple? Hand back the cached file.
    translated = cache.translated_path(imdb_id, season, episode, source_lang)
    if os.path.isfile(translated):
        kodi_utils.log('Cache hit: ' + translated, level='INFO')
        # Touch atime so eviction tracks usage.
        try:
            now = time.time()
            os.utime(translated, (now, now))
        except OSError:
            pass
        return translated

    # Fetch / cache the source SRT.
    src_path = cache.source_path(imdb_id, season, episode, source_lang)
    src_text = cache.load_text(src_path)
    if not src_text:
        file_id = payload.get('file_id')
        if not file_id:
            # No file_id (happens when called from no-imdb path).
            # Re-query OS now that we have time.
            hits = opensubs.search(imdb_id=imdb_id, season=season,
                                   episode=episode, languages=(source_lang,))
            if not hits:
                return None
            file_id = hits[0].get('file_id')
        src_text = opensubs.download(file_id)
        if not src_text:
            return None
        cache.save_text(src_path, src_text)

    # Sanity: if the source happens to be Hebrew (mislabelled),
    # don't translate it again -- just return it as the result.
    if language_detect.detect(src_text[:8000]) == 'he':
        cache.save_text(translated, src_text)
        return translated

    # Fetch cast metadata (cached).
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

    # Build the prompt template + chunk + call the API.
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
        kodi_utils.log('Source SRT had no parseable blocks', level='WARNING')
        return None

    chunks = list(srt.chunk_blocks(blocks, per_chunk=chunk_lines))
    total = len(chunks)
    out_blocks = []

    for i, ch in enumerate(chunks, start=1):
        if progress_cb:
            try:
                progress_cb(i, total)
            except Exception:
                pass
        body = '\n\n'.join(ch)
        full_prompt = prompt_template.replace('{chunk}', body)
        last_err = None
        for attempt in range(2):
            try:
                response = gemini.generate(
                    api_key=api_key,
                    model=model,
                    prompt=full_prompt,
                    temperature=temperature,
                )
                out_blocks.extend(srt.parse_blocks(response))
                last_err = None
                break
            except gemini.QuotaExceeded:
                kodi_utils.notify(kodi_utils.localised(33005))
                return None
            except gemini.InvalidKey as e:
                kodi_utils.notify(kodi_utils.localised(33004,
                    'API key rejected'))
                kodi_utils.log('InvalidKey: {0}'.format(e), level='ERROR')
                return None
            except gemini.GeminiError as e:
                last_err = e
                kodi_utils.log('Gemini error chunk {0}/{1} attempt {2}: {3}'
                               .format(i, total, attempt + 1, e),
                               level='WARNING')
                time.sleep(2 * (attempt + 1))
                continue
        if last_err is not None:
            kodi_utils.notify(kodi_utils.localised(33008, str(last_err)[:80]))
            return None

    final = srt.stitch_blocks(out_blocks)
    cache.save_text(translated, final)
    return translated
