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

# Community subtitle pool (optional, gated by settings, OFF by default).
# Imported defensively: a problem here must never break translation.
try:
    from . import pool
except Exception:
    pool = None

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


def _looks_like_token(s):
    """True if a string is a debrid URL / token / bare UUID rather than a real
    subtitle release name (used to hide garbage pool 'release' names)."""
    import re as _re
    s = (s or '').strip()
    if not s:
        return False
    low = s.lower()
    if 'token=' in low or '://' in low or '?' in low or '&' in low:
        return True
    # bare UUID, e.g. 499157df-d49d-4c1b-96f9-920866a2354a
    if _re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                     r'[0-9a-f]{4}-[0-9a-f]{12}', low):
        return True
    # long hex blob with no spaces/dots (a hash, not a release name)
    if (len(s) >= 24 and '.' not in s and ' ' not in s
            and _re.fullmatch(r'[0-9a-f-]+', low)):
        return True
    return False


def _match_pct(video_name, sub_name):
    """Release-name match %, same idea as the engine's sort_subtitles
    (token-list similarity). Used to show a sync % on community-pool
    entries the way human sources show one."""
    import re as _re
    import difflib as _dl

    def toks(s):
        s = _re.sub(r'\.[a-z0-9]{2,4}$', '', s or '', flags=_re.I)
        for ch in '_ +/-':
            s = s.replace(ch, '.')
        return [x.lower() for x in s.split('.') if x]

    a, b = toks(video_name), toks(sub_name)
    if not a or not b:
        return 0
    try:
        return int(round(_dl.SequenceMatcher(None, a, b).ratio() * 100))
    except Exception:
        return 0


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
    cache key. Local files get content-hashed because Kodi reuses
    temp paths like TempSubtitle.0.srt across movies -- the filename
    alone is NOT a reliable identifier. Returns '' if we can't
    compute one cheaply (caller will fall back to content-hash after
    the SRT is in memory)."""
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

def _mark_current(results):
    """Mark the currently-applied subtitle with '» נוכחית' and float it to the
    top (mirrors DarkSubs's 'כתובית נוכחית'). Matched by candidate link."""
    try:
        cur = kodi_utils.get_current_subtitle()
        if not cur:
            return results
        for i, c in enumerate(results):
            if c.get('link') == cur:
                c['filename'] = '» נוכחית · ' + (c.get('filename') or '')
                c['rating'] = '5'
                results.insert(0, results.pop(i))
                break
    except Exception:
        pass
    return results


def _finalize(info, results):
    """Write-through the real Hebrew releases this live search found into the
    source-screen badge cache (so the poster % matches the picker), then apply
    the 'currently applied' marking. Every list_candidates return goes through
    here."""
    try:
        he_names = []
        for c in results:
            if c.get('language') != 'he':
                continue
            pl = _decode_link(c.get('link') or '') or {}
            t = pl.get('type')
            # Real downloadable Hebrew releases only -- skip embedded streams
            # and the synthetic "AI translate" / "current" display entries.
            if t in ('passthrough', 'pool', 'engine') and not pl.get('embedded'):
                nm = (c.get('filename') or '').strip()
                if nm and not _looks_like_token(nm) and '» נוכחית' not in nm \
                        and not nm.startswith('תרגום'):
                    he_names.append(nm)
        if he_names:
            from . import he_sub_match
            he_sub_match.merge_names(info, he_names)
    except Exception:
        pass
    return _mark_current(results)


# How gently to pull queued Ktuvit subs from Ktuvit on each background pass.
# A few per pass, spaced out, so we never hammer Ktuvit's rate/quota limits
# (the thing that made a fast in-session grab miss most releases). On-device
# logs show downloads at this rate succeed (failed=0), and a failure just stays
# queued and retries, so it's safe to keep the pool filling at a useful pace.
_HARVEST_PER_PASS = 3
_HARVEST_DOWNLOAD_THROTTLE = 6.0


def process_harvest_queue(should_cancel=None):
    """Download a couple of queued Ktuvit subs and feed them into the upload
    queue. Gentle (few per pass, throttled) + retrying (a failed download stays
    queued and is retried on a later pass / day, until it succeeds or is
    declared dead). Runs on the long-lived service. Returns how many were fed to
    the upload queue."""
    if pool is None:
        return 0
    try:
        if not pool.share_enabled():
            return 0
    except Exception:
        return 0
    jobs = pool.harvest_jobs()
    if not jobs:
        return 0
    try:
        from . import subs_engine_bridge
        if not subs_engine_bridge.enabled():
            return 0
    except Exception:
        return 0

    import re as _re

    def _norm(s):
        return _re.sub(r'[^a-z0-9]', '', (s or '').lower())

    pooled_cache = {}

    def _pooled_for(info):
        key = '{0}:{1}:{2}'.format(
            info.get('tmdb_id') or info.get('imdb_id') or '',
            info.get('season') or '0', info.get('episode') or '0')
        if key not in pooled_cache:
            s = set()
            try:
                for v in pool.lookup(info):
                    if (v.get('kind') or 'ai') == 'ktuvit':
                        r = (v.get('release') or '').strip()
                        if r:
                            s.add(_norm(r))
            except Exception:
                pass
            pooled_cache[key] = s
        return pooled_cache[key]

    fed = downloaded = 0
    for fp, job in jobs:
        if downloaded >= _HARVEST_PER_PASS:
            break
        if should_cancel is not None:
            try:
                if should_cancel():
                    break
            except Exception:
                pass
        info = job.get('info') or {}
        payload = job.get('payload') or {}
        rel = payload.get('filename') or ''
        # Already shared by anyone? then this job is done -- no Ktuvit hit.
        if rel and _norm(rel) in _pooled_for(info):
            pool.remove_harvest_job(fp)
            continue
        try:
            path = subs_engine_bridge.download(payload)
        except Exception as e:
            kodi_utils.log('ktuvit harvest: download failed "{0}": {1}'.format(
                rel, str(e)[:120]), level='INFO')
            pool.harvest_job_failed(fp, job)
            downloaded += 1
            _sleep_harvest(should_cancel)
            continue
        downloaded += 1
        if not path or not os.path.isfile(path):
            pool.harvest_job_failed(fp, job)
            _sleep_harvest(should_cancel)
            continue
        if pool.was_contributed(path):
            pool.remove_harvest_job(fp)
            continue
        text = ''
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            text = ''
        if text:
            try:
                pool.contribute_ktuvit(info, text, release=rel,
                                       marker_path=path)
                fed += 1
            except Exception:
                pass
        pool.remove_harvest_job(fp)
        _sleep_harvest(should_cancel)
    if fed:
        kodi_utils.log('ktuvit harvest: fed {0} sub(s) to the upload queue '
                       '({1} left)'.format(fed, pool.harvest_queue_len()),
                       level='INFO')
    return fed


def _sleep_harvest(should_cancel):
    waited = 0.0
    while waited < _HARVEST_DOWNLOAD_THROTTLE:
        if should_cancel is not None:
            try:
                if should_cancel():
                    return
            except Exception:
                pass
        time.sleep(0.5)
        waited += 0.5


def list_candidates(info, modal_progress=True):
    """Build the list Kodi's subtitle dialog will render.

    Returns a list of dicts with keys: filename, language, link,
    sync, rating. Empty list if nothing plausible is available.
    """
    # Respect the user's preferred subtitle language. If they've set it to
    # a specific non-Hebrew language (e.g. English) we are the wrong addon
    # for the job -- offer nothing and let DarkSubs / other providers serve
    # that language. Conservative: only skips when we can positively tell
    # Hebrew is not wanted (see kodi_utils.hebrew_subtitle_wanted).
    if not kodi_utils.hebrew_subtitle_wanted():
        kodi_utils.log(
            'list_candidates: preferred subtitle language is not Hebrew; '
            'offering no AI entries', level='INFO')
        return []

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
        # for movie B. Only trust local files alongside the video
        # for Hebrew passthrough.
        if lang == 'he':
            continue
        in_temp[lang] = entry['path']

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

    # Built-in sources engine (Phase B, gated by use_builtin_engine,
    # default OFF). When on, MoranSubs searches the subtitle sources
    # itself so it can stand in for DarkSubs: embedded Hebrew, human
    # Hebrew, machine-translated Hebrew, and other languages (English
    # etc.). When the gate is off the bridge returns [] without importing
    # the engine, so this block is a no-op.
    engine_human, engine_mt, engine_other, engine_embedded = [], [], [], []
    _engine_on = False
    try:
        from . import subs_engine_bridge
        _engine_on = subs_engine_bridge.enabled()
    except Exception as e:
        kodi_utils.log('engine import/enabled() failed: {0}'.format(e),
                       level='WARNING')
    kodi_utils.log('engine gate: enabled={0}'.format(_engine_on), level='INFO')
    if _engine_on:
        # Embedded-stream detection and the provider search are INDEPENDENT --
        # run them in SEPARATE try blocks so a failure in one (e.g. the player
        # stream probe) can NEVER stop the other. Previously a single exception
        # in embedded_candidates aborted the whole block and the provider search
        # never ran, leaving only the community pool. Failures are logged at
        # WARNING (not DEBUG) so they're visible without a debug log.
        try:
            engine_embedded = subs_engine_bridge.embedded_candidates(info)
        except Exception as e:
            kodi_utils.log('engine embedded_candidates failed: {0}'.format(e),
                           level='WARNING')
        try:
            for c in subs_engine_bridge.search(info,
                                               modal_progress=modal_progress):
                k = c.get('_engine_kind', 'human_he')
                if k == 'human_he':
                    engine_human.append(c)
                elif k == 'mt_he':
                    engine_mt.append(c)
                else:
                    engine_other.append(c)
        except Exception as e:
            kodi_utils.log('engine search failed: {0}'.format(e),
                           level='WARNING')

        # Queue EVERY human Ktuvit result for the background harvest, so the
        # whole title's set ends up in the pool over time -- not just the one
        # the user picks. Just a fast local write per sub (no Ktuvit hit here);
        # the long-lived service downloads + uploads them gently. Gated by
        # pool_share; runs on auto-on-play AND a manual "download subtitles".
        try:
            if pool is not None and pool.share_enabled():
                _kt = 0
                for c in engine_human:
                    pl = _decode_link(c.get('link') or '') or {}
                    if (pl.get('type') == 'engine' and not pl.get('embedded')
                            and (pl.get('source') or '').strip().lower()
                            == 'ktuvit'
                            and 'Hebrew' in (pl.get('language') or '')
                            and 'MachineTranslated' not in (
                                pl.get('language') or '')):
                        pool.enqueue_harvest(info, pl)
                        _kt += 1
                if _kt:
                    kodi_utils.log('ktuvit harvest: queued {0} release(s) for '
                                   'background mirroring'.format(_kt),
                                   level='INFO')
        except Exception as e:
            kodi_utils.log('ktuvit harvest enqueue failed: {0}'.format(e),
                           level='WARNING')

    # Language display order (the user's requested grouping): Hebrew first
    # (handled above as its own groups), then English, Spanish, then the other
    # AI-source languages MoranSubs can translate from (German/French/
    # Portuguese), then everything else. Used to sort + group the raw foreign
    # subs AND to decide which languages get an "AI translate to Hebrew" entry.
    _AI_SOURCE_ORDER = {'en': 0, 'es': 1, 'de': 2, 'fr': 3, 'pt': 4}

    def _lang_rank(code):
        return _AI_SOURCE_ORDER.get(code, 50)

    def _clean(c):
        c.pop('_engine_kind', None)
        c.pop('_pct', None)
        return c

    # Embedded Hebrew (101%) goes to the very top -- above even a local
    # passthrough -- mirroring DarkSubs's [LOC] entry. Embedded FOREIGN streams
    # (e.g. built-in French/English) are NOT Hebrew, so they must rank BELOW all
    # the Hebrew options, not above them -- they're held back and appended after
    # the foreign section.
    embedded_foreign = []
    if engine_embedded:
        emb_he = [c for c in engine_embedded if c.get('language') == 'he']
        embedded_foreign = [c for c in engine_embedded
                            if c.get('language') != 'he']
        if emb_he:
            # Only an embedded HEBREW stream means "Hebrew already exists"; an
            # embedded English (or other) [מובנה] entry must NOT suppress the
            # AI-translate options.
            have_hebrew = True
            results[:0] = [_clean(c) for c in emb_he]

    # Community pool. ONE network lookup returns both kinds of shared Hebrew:
    #   - 'ktuvit': a HUMAN Ktuvit subtitle mirrored to the pool. It loads
    #               INSTANTLY from the channel and never hits Ktuvit, so when a
    #               release exists BOTH live (from the engine) and in the pool we
    #               show the POOL copy and hide the slow live one -- exactly what
    #               you asked: no need for the live Ktuvit when the pool has it.
    #               Labelled "כתובית · מאגר" so it's clearly the pool (a live one
    #               is labelled "Ktuvit"). Human, so it ranks above the AI pool.
    #   - 'ai':     a machine AI translation other users shared.
    # One lookup keeps the request count identical to the AI-only pool.
    _pool_variants = []
    _video_ref = ''
    if pool is not None and pool.use_enabled():
        _video_ref = (info.get('picked_release') or info.get('tagline')
                      or info.get('label') or os.path.basename(filepath)
                      or info.get('title') or '')
        try:
            _pool_variants = pool.lookup(info)
        except Exception:
            _pool_variants = []

    def _norm_rel(s):
        import re as _re_nr
        return _re_nr.sub(r'[^a-z0-9]', '', (s or '').lower())

    def _pool_release(v):
        r = (v.get('release') or '').strip()
        # Reject debrid URL / token "releases" stored by older shares.
        return '' if (r and _looks_like_token(r)) else r

    # Map normalised release -> the pooled Ktuvit copy, so we can swap a live
    # Ktuvit result for its faster pool twin.
    _ktuvit_pool_by_rel = {}
    for v in _pool_variants:
        if (v.get('kind') or 'ai') == 'ktuvit':
            r = _pool_release(v)
            if r:
                _ktuvit_pool_by_rel.setdefault(_norm_rel(r), v)

    def _pool_entry(v, release):
        pct = _match_pct(_video_ref, release) if release else 0
        if release and pct > 0:
            label = 'כתובית · מאגר · {0}%  —  {1}'.format(pct, release)
        elif release:
            label = 'כתובית · מאגר  —  {0}'.format(release)
        else:
            label = 'כתובית · מאגר'
        return {
            'filename': label, 'language': 'he',
            'link': _encode_link({'type': 'pool', 'hash': v.get('hash')}),
            'sync': 'false', 'rating': '5', 'is_hi': False, 'is_hd': False,
        }

    # Engine human Hebrew, in the engine's own match-% order. For a LIVE Ktuvit
    # result that's ALSO in the pool, emit the POOL copy in its place (instant +
    # no Ktuvit hit), keeping the position so the %-ordering is preserved. Other
    # human results (Wizdom, not-yet-pooled Ktuvit) render as-is.
    _used_pool_rels = set()
    for c in engine_human:
        have_hebrew = True
        pl = _decode_link(c.get('link') or '') or {}
        is_ktuvit = (pl.get('type') == 'engine'
                     and (pl.get('source') or '').strip().lower() == 'ktuvit')
        fn = c.get('filename') or ''
        rel_norm = _norm_rel(fn.split('—')[-1].strip() if '—' in fn else '')
        if is_ktuvit and rel_norm and rel_norm in _ktuvit_pool_by_rel:
            v = _ktuvit_pool_by_rel[rel_norm]
            results.append(_pool_entry(v, _pool_release(v)))
            _used_pool_rels.add(rel_norm)
        else:
            results.append(_clean(c))

    # Pooled Ktuvit releases the live engine did NOT return this time (e.g.
    # Ktuvit is slow/down) -- still available, instant, human.
    for rel_norm, v in _ktuvit_pool_by_rel.items():
        if rel_norm in _used_pool_rels:
            continue
        have_hebrew = True
        results.append(_pool_entry(v, _pool_release(v)))

    # AI pool (machine translations) -- below all the human Ktuvit entries.
    for v in _pool_variants:
        if (v.get('kind') or 'ai') == 'ktuvit':
            continue
        have_hebrew = True
        release = _pool_release(v)
        pct = _match_pct(_video_ref, release) if release else 0
        # Only show a % when we actually have a meaningful match (a 0% almost
        # always means we couldn't read the video's release name, not a real
        # zero -- showing "0%" is misleading).
        if release and pct > 0:
            label = 'תרגום AI · מאגר קהילתי · {0}%  —  {1}'.format(pct, release)
        elif release:
            label = 'תרגום AI · מאגר קהילתי  —  {0}'.format(release)
        else:
            label = 'תרגום AI · מאגר קהילתי'
        results.append({
            'filename': label,
            'language': 'he',
            'link': _encode_link({'type': 'pool', 'hash': v.get('hash')}),
            'sync': 'false', 'rating': '5',
            'is_hi': False, 'is_hd': False,
        })

    # Machine-translated Hebrew from the engine.
    for c in engine_mt:
        have_hebrew = True
        results.append(_clean(c))

    # Foreign-language engine results. With AI translation ON (default) each
    # becomes a single "translate to Hebrew" action (pick it -> get Hebrew,
    # like DarkSubs auto_translate). With translation_mode = 'none' (the user
    # opted out of AI) we hand back the RAW foreign sub instead -- no AI is
    # ever invoked. Grouped/ordered by source language (en, es, de, fr, pt,
    # then the rest); within a language, best match % first.
    ai_translation_on = (kodi_utils.get_setting('translation_mode', 'ai')
                         or 'ai') != 'none'
    # Group BOTH the foreign AI-translate sources AND the embedded (built-in)
    # foreign streams by language, then emit language by language (en, es, de,
    # fr, pt, then the rest). Within each language the EMBEDDED track comes
    # FIRST (top of that language's group), then the rest by best match %. So
    # built-in subtitles head their own language instead of all being dumped at
    # the very bottom -- while Hebrew (handled above) still leads the whole list.
    _ai_by_lang = {}
    for c in engine_other:
        _ai_by_lang.setdefault(c.get('language') or '?', []).append(c)
    _emb_by_lang = {}
    for c in embedded_foreign:
        _emb_by_lang.setdefault(c.get('language') or '?', []).append(c)

    for code in sorted(set(_ai_by_lang) | set(_emb_by_lang),
                       key=lambda l: (_lang_rank(l), l)):
        # Built-in (embedded) track of this language -> top of its group.
        for c in _emb_by_lang.get(code, []):
            results.append(_clean(c))
        # Then the foreign subs of this language, best match % first.
        for c in sorted(_ai_by_lang.get(code, []),
                        key=lambda x: -x.get('_pct', 0)):
            pct = c.get('_pct', 0)
            if ai_translation_on:
                src = _decode_link(c.get('link') or '')
                if not src or src.get('type') != 'engine':
                    continue
                src = dict(src)
                src['type'] = 'engine_ai'
                src['src_lang'] = code
                rel = src.get('filename') or code
                have_hebrew = True
                results.append({
                    'filename': 'תרגום AI לעברית · {0}%  —  {1}'.format(pct, rel),
                    'language': code,
                    'link': _encode_link(src),
                    'sync': 'false',
                    'rating': c.get('rating', '3'),
                    'is_hi': False, 'is_hd': False,
                })
            else:
                # Opt-out: deliver the raw foreign sub as-is.
                results.append(_clean(c))

    skip_when_hebrew = kodi_utils.get_bool('skip_if_hebrew', True)
    if have_hebrew and skip_when_hebrew:
        return _finalize(info, results)

    # 2. For each enabled source language, surface ONE "translate
    #    this" entry from a local source:
    #       (a) alongside file (local re-watch)
    #       (b) temp-dir file (loaded by another addon, e.g. DarkSubs)
    #    Built into a separate list so cache hits can be sorted to
    #    the top of the AI section (just under Hebrew passthrough).
    ai_entries = []
    seen_langs = set()
    for src_lang in (sources if ai_translation_on else []):
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
        if not alongside and not in_temp:
            reasons.append('אין קבצי SRT ב-temp או ליד הסרט')
        msg = 'AI: אין מקור לתרגום ({0}). בחר כתובית באנגלית מ-DarkSubs ' \
              'ופתח שוב את חיפוש הכתוביות — התרגום ל-AI יופעל אוטומטית.'.format(
                ' / '.join(reasons) or 'לא ידוע')
        kodi_utils.notify(msg, time_ms=15000)
        kodi_utils.log('list_candidates returned empty: ' + repr(
            {'imdb_id': imdb_id, 'tmdb_id': tmdb_id,
             'alongside_count': len(alongside),
             'in_temp_count': len(in_temp)}),
            level='WARNING')

    return _finalize(info, results)


# ---- download / translate -------------------------------------------

def _prepare_source(raw_src):
    """Strip hearing-impaired noise from a source SRT, but only if the
    cleaner left at least 30% of the entries (otherwise keep the raw text).
    This is the SAME transform the main translate path applies before
    hashing -- factored out so the content hash is computed identically
    here and in the backfill path, guaranteeing both produce the same
    source_hash and the pool never stores two copies of one translation."""
    cleaned = srt.strip_hi_annotations(raw_src)
    if cleaned and srt.count_entries(cleaned) >= max(
            1, int(srt.count_entries(raw_src) * 0.3)):
        return cleaned
    return raw_src


def _content_hash(text):
    """sha1[:16] of the (already prepared) source text -- the pool's
    source_hash / dedup key."""
    import hashlib as _h
    return _h.sha1(text.encode('utf-8', errors='replace')).hexdigest()[:16]


def _pool_quality_ok(src_text, final):
    """Quality gate before SHARING a translation to the community pool. Skips
    obviously-broken output so it can't pollute the pool: a truncated result
    (lost too many blocks vs the source -> failed/partial chunks) or one that
    isn't really Hebrew (translation didn't happen). NOTE: it cannot catch a
    mis-synced SOURCE -- the text is correct, only the timing differs -- so
    this raises reliability but isn't a perfect guarantee. Never blocks on a
    checker error (returns True)."""
    try:
        if not final:
            return False
        if src_text:
            src_n = srt.count_entries(src_text)
            out_n = srt.count_entries(final)
            if src_n >= 5 and out_n < src_n * 0.85:
                return False  # truncated: lost too many blocks (failed chunks)
        if not srt.looks_hebrew(final):
            return False  # not really Hebrew overall
        # Partial-failure guard: a doc can read as "Hebrew overall" yet have
        # whole chunks left in English. Reject only when a LARGE share of
        # substantial cues are English-only (no Hebrew at all) -- a generous
        # 0.30 so legitimately-English lines (lyrics, on-screen signs, an
        # English phrase, half-English lines) never trip it; only a mostly-
        # broken translation does. Mixed Hebrew+English lines count as
        # translated because they contain Hebrew.
        if srt.untranslated_line_ratio(final) > 0.30:
            return False
        return True
    except Exception:
        return True


def _backfill_pool_async(info, translated_path, local_source, source_lang,
                         ar_tier=False):
    """Share an ALREADY-cached Hebrew translation to the community pool, in
    the background, the first time the user re-watches it after enabling
    pool_share. Used at the EARLY cache hit, where the source bytes (and
    therefore the content hash) aren't computed yet: we read the source on a
    daemon thread so playback is never delayed, compute the same content hash
    the fresh-translation path uses, and contribute_once (marker + server-side
    dedup => never a duplicate). One-shot per file thanks to the .shared
    marker; silent to the user on any failure."""
    if pool is None:
        return

    def _work():
        try:
            if not pool.share_enabled() or pool.was_contributed(
                    translated_path):
                return
            cached = cache.load_text(translated_path)
            if not cached:
                return
            raw = None
            if local_source and os.path.isfile(local_source):
                try:
                    with open(local_source, 'r', encoding='utf-8',
                              errors='replace') as f:
                        raw = f.read()
                except (IOError, OSError):
                    raw = None
            if not raw:
                return
            prepared = _prepare_source(raw)
            if not _pool_quality_ok(prepared, cached):
                return
            cid = _content_hash(prepared)
            _rel = None
            try:
                with open(translated_path + '.release', 'r',
                          encoding='utf-8') as _rf:
                    _rel = (_rf.read().strip() or None)
            except OSError:
                _rel = None
            pool.contribute_once(info, (cid + '_ar') if ar_tier else cid,
                                 source_lang, cached,
                                 marker_path=translated_path,
                                 release_override=_rel,
                                 kind=('ai_ar' if ar_tier else 'ai'))
        except Exception as e:
            try:
                kodi_utils.log('pool backfill failed: {0}'.format(e),
                               level='DEBUG')
            except Exception:
                pass

    try:
        import threading as _t
        _t.Thread(target=_work, daemon=True).start()
    except Exception:
        pass


def _is_google_translated(path):
    """True if this cached translation was produced by Google Translate (a
    sidecar '<path>.google' marker is written next to it). Such machine
    translations must NEVER be shared to the community pool."""
    try:
        return bool(path) and os.path.exists(path + '.google')
    except Exception:
        return False


def _google_translate_and_save(src_text, source_lang, translated, info,
                               via_quota=False):
    """Translate src_text to Hebrew with Google Translate and save it to the
    cache path `translated`. Marks it Google-translated (sidecar) so it is
    never pooled, applies the RTL punctuation fix, and returns the path (or
    None on failure)."""
    heb = None
    try:
        from . import google_translate
        heb = google_translate.translate_srt(src_text, source_lang)
    except Exception as e:
        kodi_utils.log('google translate failed: {0}'.format(e),
                       level='WARNING')
    if not heb or not heb.strip():
        kodi_utils.notify('Google Translate נכשל — נסה שוב', time_ms=4000)
        return None
    try:
        cache.save_text(translated, heb)
        try:
            open(translated + '.google', 'w').close()  # keep it out of the pool
        except Exception:
            pass
        _reapply_rtl_fix_in_place(translated)
    except Exception as e:
        kodi_utils.log('google save failed: {0}'.format(e), level='WARNING')
        return None
    kodi_utils.notify(
        'מכסת ה-AI נגמרה — תורגם עם Google Translate' if via_quota
        else 'תורגם עם Google Translate', time_ms=4000)
    return translated


# When the auto-on-play flow is driving (service._autosub_on_play), success /
# progress notifications are shown in the top overlay by the caller -- so the
# scattered success toasts here are suppressed to avoid double messaging. Error
# toasts still fire. Mirrors DarkSubs, which shows status only in its on-play
# overlay, never as toasts.
_QUIET = False


def _is_mostly_hebrew(text, min_ratio=0.30):
    """True if the SRT text is a real Hebrew translation -- not empty, and a
    meaningful share of its letters are Hebrew. Catches the two ways a weak
    model (gemini-3.1-flash-lite) silently fails: (a) it returns EMPTY (blocked
    / no content) and (b) it ECHOES the source untranslated (German/Spanish/
    English). Both used to be cached and served as 'the Hebrew translation',
    showing blank or foreign text. Numbers/names keep some Latin, so we only
    require a fraction, not all."""
    if not text or not text.strip():
        return False
    he = 0
    latin = 0
    for ch in text:
        o = ord(ch)
        if 0x0590 <= o <= 0x05FF:
            he += 1
        elif ch.isalpha() and o < 128:
            latin += 1
    letters = he + latin
    if letters < 20:
        return False  # almost no text -> treat as failed
    return (he / letters) >= min_ratio


def set_quiet(value):
    global _QUIET
    _QUIET = bool(value)


def _status(msg, **kwargs):
    """Success / informational status. Suppressed during auto-on-play (the
    overlay shows it instead); a normal toast otherwise."""
    if _QUIET:
        return
    try:
        kodi_utils.notify(msg, **kwargs)
    except Exception:
        pass


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
        _status(
            'AI: כתובית קיימת (passthrough) - {0}'.format(
                os.path.basename(path) if path else '?'),
            time_ms=4000)
        if path and os.path.isfile(path):
            return path
        return None

    if kind == 'pool':
        # A community-pool entry the user picked from the dialog. Fetch the
        # exact shared Hebrew SRT (by source hash) and hand it to Kodi.
        if pool is None:
            return None
        text = pool.fetch(info, payload.get('hash'))
        if not text:
            _status('AI: לא נמצאה כתובית במאגר', time_ms=4000)
            return None
        import hashlib as _hpool
        sid = (payload.get('hash')
               or _hpool.sha1(text.encode('utf-8', 'replace')).hexdigest()[:16])
        out = os.path.join(kodi_utils.cache_dir(), 'pool_{0}.he.srt'.format(sid))
        try:
            with open(out, 'w', encoding='utf-8') as f:
                f.write(text)
            _reapply_rtl_fix_in_place(out)
            _status('כתוביות מהמאגר הקהילתי', time_ms=4000)
            return out
        except OSError:
            return None

    if kind == 'engine':
        # Embedded Hebrew pick: just switch Kodi's subtitle stream, there
        # is no file to deliver (mirrors DarkSubs's [LOC] selection).
        if payload.get('embedded'):
            try:
                from . import subs_engine_bridge
                _elang = payload.get('lang') or 'he'
                if subs_engine_bridge.select_embedded(
                        payload.get('stream_index'), _elang):
                    _status('הופעל תרגום מובנה' + (
                        ' בעברית' if _elang == 'he' else ''), time_ms=4000)
            except Exception as e:
                kodi_utils.log('resolve embedded select failed: {0}'
                               .format(e), level='WARNING')
            return None
        # A human (or machine-translated) Hebrew subtitle the user
        # picked from the built-in sources engine. Download it directly
        # via the vendored provider -- no AI translation needed, it's
        # already Hebrew. Gated: download() returns None if the engine
        # gate is off.
        try:
            from . import subs_engine_bridge
            path = subs_engine_bridge.download(payload)
        except Exception as e:
            kodi_utils.log('resolve engine download failed: {0}'.format(e),
                           level='ERROR')
            path = None
        if path and os.path.isfile(path):
            # Ktuvit backup mirror: every HUMAN Ktuvit Hebrew sub a user
            # downloads is pushed once to the pool (kind='ktuvit'), so it
            # survives Ktuvit going offline and loads instantly afterwards.
            # Only genuine Ktuvit human subs (not machine-translated, not other
            # providers); fire-and-forget; gated by pool_share; the server +
            # the ".shared" marker guarantee no duplicate uploads.
            try:
                _src = (payload.get('source') or '').strip().lower()
                _lang = payload.get('language') or ''
                if (pool is not None and pool.share_enabled()
                        and _src == 'ktuvit' and 'Hebrew' in _lang
                        and 'MachineTranslated' not in _lang
                        and not pool.was_contributed(path)):
                    _ktext = ''
                    try:
                        with open(path, 'r', encoding='utf-8',
                                  errors='replace') as _kf:
                            _ktext = _kf.read()
                    except OSError:
                        _ktext = ''
                    if _ktext:
                        pool.contribute_ktuvit(
                            info, _ktext,
                            release=(payload.get('filename') or ''),
                            marker_path=path)
                        kodi_utils.log(
                            'ktuvit pool mirror: enqueued "{0}"'.format(
                                payload.get('filename') or ''), level='INFO')
                else:
                    kodi_utils.log(
                        'ktuvit pool mirror: not enqueued (share={0}, '
                        'src={1}, lang={2}, already_shared={3})'.format(
                            (pool.share_enabled() if pool else False),
                            _src, _lang, (pool.was_contributed(path)
                                          if pool else False)),
                        level='INFO')
            except Exception as e:
                kodi_utils.log('ktuvit pool mirror failed: {0}'.format(e),
                               level='WARNING')
            _status('כתוביות עברית מ-{0}'.format(
                payload.get('source') or 'מקור'), time_ms=4000)
            return path
        kodi_utils.notify('לא ניתן היה להוריד את הכתובית', time_ms=4000)
        return None

    if kind == 'engine_ai':
        # User picked "AI Hebrew (translate from English)" sourced from the
        # built-in engine. Download the English sub via the engine, then fall
        # through to the normal AI pipeline below to translate it to Hebrew.
        try:
            from . import subs_engine_bridge
            eng_path = subs_engine_bridge.download(payload)
        except Exception as e:
            kodi_utils.log('resolve engine_ai download failed: {0}'
                           .format(e), level='ERROR')
            eng_path = None
        if not eng_path or not os.path.isfile(eng_path):
            kodi_utils.notify('AI: לא ניתן היה להוריד את כתובית המקור',
                              time_ms=4000)
            return None
        _status('AI: מוריד אנגלית ומתרגם לעברית...', time_ms=3000)
        payload = {'type': 'ai',
                   'source_lang': payload.get('src_lang') or 'en',
                   'local_path': eng_path,
                   # Keep the SOURCE sub's real release name (e.g. "Movie.2010.
                   # 1080p.BluRay.x264-GROUP") so the delivered file and the pool
                   # upload carry it instead of a generic Title.Year.
                   'release': payload.get('filename') or '',
                   'force_ai': True}  # user explicitly asked to translate
        kind = 'ai'
        # fall through to the AI logic below

    if kind != 'ai':
        kodi_utils.log('resolve: unknown kind ' + str(kind),
                       level='WARNING')
        return None

    source_lang = payload.get('source_lang') or 'en'

    local_source = payload.get('local_path')

    # Real release name of the SOURCE subtitle being translated (carried from the
    # picked candidate). Used to (a) name the delivered Hebrew file so Kodi shows
    # the full release instead of a hash, and (b) tag the community-pool upload
    # with a real release so match-% works for everyone who downloads it -- a
    # generic "Title.Year" matches almost nothing. Falls back to the video's own
    # release name from info; token-like (debrid URL/uuid) values are dropped.
    _src_release = (payload.get('release') or '').strip()
    if not _src_release:
        for _k in ('release', 'picked_release', 'filename', 'tagline', 'label'):
            _cand = (info.get(_k) or '').strip()
            if _cand:
                _src_release = _cand
                break
    if pool is not None:
        try:
            if pool._is_token_like(_src_release):
                _src_release = ''
        except Exception:
            pass
    _release_override = _src_release or None

    # Arabic-gender-reference (opt-in, default OFF). When ON we operate in a
    # separate 'ar' quality tier: cache + pool live under their own key, so an
    # existing plain translation does NOT short-circuit (we re-translate to
    # upgrade it), while a finished ai_ar IS reused (no duplicate, no re-spend).
    # The Arabic sub is fetched + aligned later (only if we actually translate).
    # OFF = byte-identical to today.
    _ar_on = False
    try:
        _ar_on = bool(kodi_utils.get_bool('gender_ref_arabic', False))
    except Exception:
        _ar_on = False
    _tier = 'ar' if _ar_on else ''
    _pool_kind = 'ai_ar' if _ar_on else 'ai'
    _ar_map = None  # {srt_entry_number: arabic_line}, set just before chunking
    _ar_diag = {}   # arabic_gender.prepare diagnostics (reason/cands/diag)

    def _pool_key(base_hash):
        # ai_ar variants live under "<hash>_ar" so EVERY client can prefer them
        # (better quality for all) with NO worker change, and dedup-by-result
        # still prevents duplicates.
        return (base_hash + '_ar') if _ar_on else base_hash

    # Respect the user's preferred subtitle language: if they've chosen a
    # specific non-Hebrew language (e.g. English) DON'T force an AI Hebrew
    # translation -- hand back the SOURCE subtitle untranslated so they get
    # the language they asked for. Checked BEFORE the cache lookups below so
    # we never serve a previously-cached Hebrew file either. This is an
    # extra gate only; it can't re-enable translation that auto_translate /
    # force_ai_when_auto_translate_off already disabled.
    if not payload.get('force_ai') and not kodi_utils.hebrew_subtitle_wanted():
        kodi_utils.log(
            'resolve: preferred subtitle language is not Hebrew; returning '
            'the source subtitle untranslated', level='INFO')
        kodi_utils.notify(
            'AI: שפת הכתוביות המועדפת אינה עברית — מחזיר כתובית מקור ללא תרגום',
            time_ms=4000)
        if local_source and os.path.isfile(local_source):
            return local_source
        return None

    # Two-tier cache strategy:
    #  1. EARLY lookup: the local path is hashed by content (cheap
    #     because the file is small). This avoids a redundant
    #     re-translation for entries the user already translated.
    #     Same key the [CACHE] marker in list_candidates uses.
    #  2. CONTENT-HASH lookup after the source is in memory: catches
    #     the rare case where two different local paths point to
    #     byte-identical SRTs.
    early_source_id = _source_id_for_ai(payload)
    if early_source_id:
        translated = cache.translated_path(
            imdb_id, season, episode, source_lang,
            source_id=early_source_id, tier=_tier)
        # Only honour the cache if it's a REAL Hebrew translation. Older buggy
        # versions could cache an empty / source-echoed file and then serve it
        # forever as "from cache (previous translation)" -- blank or foreign
        # text. If the cached file isn't really Hebrew, delete it and re-do.
        if os.path.isfile(translated) and not _is_mostly_hebrew(
                cache.load_text(translated) or ''):
            kodi_utils.log('Discarding non-Hebrew cached translation (empty/'
                           'echoed): ' + translated, level='WARNING')
            try:
                os.remove(translated)
            except OSError:
                pass
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
            # Backfill: share this previously-translated file to the pool the
            # first time it's re-watched after pool_share is on. Runs on a
            # daemon thread (reads the source to compute the content hash), so
            # the cache hit still returns instantly. One-shot per file.
            if (pool is not None and pool.share_enabled()
                    and not _is_google_translated(translated)):
                _backfill_pool_async(info, translated, local_source,
                                     source_lang, ar_tier=_ar_on)
            return translated

    # Read the source SRT recorded at list time (alongside the video
    # or a temp-dir file loaded by another addon, e.g. DarkSubs).
    src_text = None
    if local_source and os.path.isfile(local_source):
        try:
            with open(local_source, 'r', encoding='utf-8',
                      errors='replace') as f:
                src_text = f.read()
        except (IOError, OSError):
            src_text = None
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
    src_text = _prepare_source(src_text)

    # Content-hash lookup: only catches a hit when SOURCE bytes
    # match a previously translated SRT served from a different
    # url/path. Translation is saved to the early-source-id slot
    # (so list_candidates can pre-mark it as [CACHE]) and ALSO
    # to the content-hash slot so a future click of a different
    # url with identical content also hits cache.
    content_id = _content_hash(src_text)
    if content_id != early_source_id:
        translated_by_content = cache.translated_path(
            imdb_id, season, episode, source_lang,
            source_id=content_id, tier=_tier)
        if os.path.isfile(translated_by_content) and not _is_mostly_hebrew(
                cache.load_text(translated_by_content) or ''):
            kodi_utils.log('Discarding non-Hebrew cached translation (empty/'
                           'echoed): ' + translated_by_content,
                           level='WARNING')
            try:
                os.remove(translated_by_content)
            except OSError:
                pass
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
            # Backfill: we already have the content hash here, so share the
            # cached file directly (contribute_once = marker + server dedup).
            if (pool is not None and pool.share_enabled()
                    and not _is_google_translated(translated_by_content)):
                _cached_he = cache.load_text(translated_by_content) or ''
                if _pool_quality_ok(src_text, _cached_he):
                    if _src_release:
                        try:
                            with open(translated_by_content + '.release', 'w',
                                      encoding='utf-8') as _rf:
                                _rf.write(_src_release)
                        except OSError:
                            pass
                    try:
                        pool.contribute_once(
                            info, _pool_key(content_id), source_lang,
                            _cached_he,
                            marker_path=translated_by_content,
                            release_override=_release_override,
                            kind=_pool_kind)
                    except Exception as e:
                        kodi_utils.log(
                            'pool backfill (content) failed: {0}'.format(e),
                            level='DEBUG')
            return translated_by_content

    # No hit: settle on the early-source-id slot as the canonical
    # cache path for this translation; falls back to content_id
    # when we have no stable source_id at all.
    translated = cache.translated_path(
        imdb_id, season, episode, source_lang,
        source_id=(early_source_id or content_id), tier=_tier)

    # Stash the source release name next to the cached translation, so a later
    # "share my cached translations" upload can tag it with the real release too
    # (the cache filename itself is only id+hash). Best-effort.
    if _src_release:
        try:
            with open(translated + '.release', 'w', encoding='utf-8') as _rf:
                _rf.write(_src_release)
        except OSError:
            pass

    # Community pool: before spending Gemini quota, check whether someone has
    # already translated THIS exact source (same content hash) and shared it.
    # Exact-hash match only -> perfect sync. Gated by pool_use; on any failure
    # we fall through and translate normally. Returns a path like a cache hit
    # (no progressive callbacks -- the caller's sentinel handles that).
    if pool is not None and pool.use_enabled():
        # Prefer the higher-quality Arabic-gender variant for EVERYONE (it lives
        # under "<hash>_ar"). When the feature is ON we accept ONLY ai_ar -- if
        # the pool has just a plain one, we deliberately re-translate to upgrade
        # it. When OFF we take ai_ar if present, else plain.
        pooled = pool.fetch(info, content_id + '_ar')
        if pooled:
            kodi_utils.log('pool: reusing Arabic-gender (ai_ar) variant',
                           level='INFO')
        elif not _ar_on:
            pooled = pool.fetch(info, content_id)
        if pooled:
            try:
                cache.save_text(translated, pooled)
                _reapply_rtl_fix_in_place(translated)
                kodi_utils.notify(
                    'AI: כתוביות מהמאגר הקהילתי (לא נדרש תרגום)', time_ms=4000)
                return translated
            except Exception as e:
                kodi_utils.log('pool reuse save failed: {0}'.format(e),
                               level='WARNING')

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
                'release': _src_release,
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

    # Translator selection. 'google' (the user picked it in settings) ->
    # translate with Google Translate now and skip Gemini entirely. Google
    # output is machine quality, so it is never shared to the pool. 'ai'
    # (default) falls through to the Gemini path below (which guides the user
    # to connect a key if none is set). translation_mode 'none' never reaches
    # here (list_candidates hands back raw foreign subs instead).
    if (kodi_utils.get_setting('translation_mode', 'ai') or 'ai') == 'google':
        return _google_translate_and_save(src_text, source_lang, translated,
                                          info)

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
    # Gemini 3 tuning (validated A/B): keep temperature at Google's recommended
    # default 1.0 (lowering it degrades Gemini 3 reasoning), use thinking_level
    # MEDIUM (HIGH burns the output budget -> truncation + garbling and is no
    # more accurate; MEDIUM finishes clean, ~8x cheaper, best gender accuracy),
    # and DON'T tune top_p on Gemini 3 (let the model default apply).
    temperature = kodi_utils.get_float('temperature', 1.0)
    top_p = (None if model.lower().startswith('gemini-3')
             else kodi_utils.get_float('top_p', 0.95))
    thinking_raw = (kodi_utils.get_setting('thinking_budget', 'medium')
                    or 'medium').strip().lower()
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

    # Arabic gender reference (opt-in). Only here -- after every cache/pool miss,
    # so we never pay the fetch on a hit. Fetches + time-aligns a human Arabic
    # sub (trying several, OpenSubtitles/SubSource/YIFY); returns a per-entry map
    # or None. Fully guarded; None => normal translation. Logs its decision.
    if _ar_on:
        kodi_utils.log('arabic-gender: ON -- translating "{0}" via the Arabic '
                       'gender reference path'.format(
                           (info.get('title') or imdb_id or '?')), level='INFO')
        try:
            from . import arabic_gender
            _ar_map, _ar_diag = arabic_gender.prepare(info, src_text)
        except Exception as e:
            kodi_utils.log('arabic-gender prepare crashed: {0}'.format(e),
                           level='WARNING')
            _ar_map = None
            _ar_diag = {'reason': 'crash'}

    # If the feature is on but NO usable Arabic was found, this becomes a normal
    # translation -- store it as PLAIN (never masquerade a non-boosted result as
    # ai_ar), so it can still be upgraded later when an Arabic sub appears.
    _used_ar = bool(_ar_map)
    if _ar_on and not _used_ar:
        kodi_utils.log('arabic-gender: no usable Arabic this time -> normal '
                       'translation, stored as the plain tier', level='INFO')
        _tier = ''
        _pool_kind = 'ai'
        translated = cache.translated_path(
            imdb_id, season, episode, source_lang,
            source_id=(early_source_id or content_id), tier='')
        if _src_release:
            try:
                with open(translated + '.release', 'w',
                          encoding='utf-8') as _rf:
                    _rf.write(_src_release)
            except OSError:
                pass
    _final_pool_hash = (content_id + '_ar') if (_ar_on and _used_ar) \
        else content_id

    # Anonymous usage telemetry (fire-and-forget, fully guarded). One event per
    # AI translation outcome, recording the METHOD so we can see what share uses
    # the new Arabic-gender path (ai_ar) vs fell back to plain (ai_fallback) vs
    # never had it on (ai_plain), plus success/failure. _telemetry_done guards
    # against double-emit across the multiple return paths below.
    _telemetry_done = [False]
    _t0 = time.time()  # translation-duration clock for telemetry

    def _emit(ok, note=''):
        if _telemetry_done[0]:
            return
        _telemetry_done[0] = True
        try:
            from . import telemetry
            method = ('ai_ar' if (_ar_on and _used_ar)
                      else ('ai_fallback' if _ar_on else 'ai_plain'))
            # reason: WHY it ended up on this method (esp. fallback). For
            # ai_plain the option is off; otherwise take arabic_gender's reason
            # (ok / no_arabic / no_align / crash). The alignment diag (scale/
            # vote/overlap) for a near-miss goes in 'note'.
            if method == 'ai_plain':
                reason = 'option_off'
            else:
                reason = str(_ar_diag.get('reason') or '')
            ev_note = note or ('' if reason in ('ok', '') else _ar_diag.get('diag', ''))
            telemetry.report({
                'type': 'episode' if info.get('is_episode') else 'movie',
                'title': (info.get('tvshow') or info.get('title') or '')[:120],
                'season': str(info.get('season') or ''),
                'episode': str(info.get('episode') or ''),
                'year': str(info.get('year') or ''),
                'src': source_lang or '',
                'method': method,
                'reason': reason,
                'ar_cands': int(_ar_diag.get('cands') or 0),
                'dur': max(0, int(time.time() - _t0)),
                'ok': 1 if ok else 0,
                'note': str(ev_note or '')[:80],
                'hinted': len(_ar_map or {}),
                'model': model,
                'think': str(thinking_level or thinking_budget or ''),
            })
        except Exception:
            pass

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
    # Prompt-level blocks (PROHIBITED_CONTENT) are often FLAKY -- the SAME prompt
    # frequently succeeds on a retry (observed: a chunk that blocked translated
    # fine moments later). So retry the SAME prompt up to 10 times BEFORE degrading
    # (dropping the Arabic block), to preserve the Arabic gender quality. Only if
    # all 10 attempts block do we fall back. Waits stay modest (flaky != rate
    # limit) but average >4s so we never exceed the free 15 req/min limit.
    FILTERED_BACKOFF = [2, 3, 4, 5, 6, 8, 10, 12, 15, 20]

    # Per-chunk translator. Holds the inner retry loop. Returns the
    # raw Gemini response text, or raises a Stop-style exception
    # that the orchestrator below catches and converts into a
    # cancellation across all parallel chunks.
    class _AbortTranslation(Exception):
        def __init__(self, reason, user_msg):
            self.reason = reason
            self.user_msg = user_msg

    def _translate_one(idx, ch, no_arabic=False):
        # Recursive bisection on TruncatedResponse OR low-yield
        # response (Gemini sometimes skips entries silently --
        # observed in the first end-to-end test, a 5-minute gap
        # in the middle of a translated movie). Bisecting forces
        # the model to spend more attention per entry. A FilteredResponse
        # (prompt-blocked, often PROHIBITED_CONTENT) first retries WITHOUT the
        # Arabic gender block (a common trigger), then bisects.
        if len(ch) > 1:
            try:
                response = _call_gemini(idx, ch, no_arabic=no_arabic)
            except gemini.TruncatedResponse:
                mid = len(ch) // 2
                kodi_utils.log(
                    'Chunk {0} truncated -- bisecting into {1} + {2}'
                    .format(idx, mid, len(ch) - mid), level='WARNING')
                return (_translate_one(idx, ch[:mid], no_arabic) + '\n\n'
                        + _translate_one(idx, ch[mid:], no_arabic))
            except gemini.FilteredResponse:
                if not no_arabic and _ar_map:
                    kodi_utils.log(
                        'Chunk {0} prompt-blocked -- retrying WITHOUT the '
                        'Arabic gender block'.format(idx), level='WARNING')
                    return _translate_one(idx, ch, no_arabic=True)
                mid = len(ch) // 2
                kodi_utils.log(
                    'Chunk {0} blocked -- bisecting into {1} + {2}'
                    .format(idx, mid, len(ch) - mid), level='WARNING')
                return (_translate_one(idx, ch[:mid], True) + '\n\n'
                        + _translate_one(idx, ch[mid:], True))

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
                return (_translate_one(idx, ch[:mid], no_arabic) + '\n\n'
                        + _translate_one(idx, ch[mid:], no_arabic))

            return response
        # single-entry chunk that still truncates -- shouldn't
        # happen (one SRT entry is < 100 tokens), but if it does
        # we surface the partial text so the user sees something.
        try:
            return _call_gemini(idx, ch, no_arabic=no_arabic)
        except gemini.TruncatedResponse as e:
            kodi_utils.log(
                'Chunk {0} truncated even at size 1 -- '
                'returning partial'.format(idx),
                level='ERROR')
            return e.partial_text or ''
        except gemini.FilteredResponse:
            # Retry this single entry without the Arabic block; if STILL blocked,
            # keep the SOURCE text for it so the rest of the subtitle still
            # translates instead of the whole job aborting.
            if not no_arabic and _ar_map:
                try:
                    return _call_gemini(idx, ch, no_arabic=True)
                except gemini.FilteredResponse:
                    pass
            kodi_utils.log(
                'Chunk {0} blocked even at size 1 -- keeping source text'
                .format(idx), level='WARNING')
            return '\n\n'.join(ch)

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

    def _call_gemini(idx, ch, no_arabic=False):
        body = '\n\n'.join(ch)
        prev_ctx_block = prompt.build_prev_context_block(
            prev_context_by_idx.get(idx) or [])
        # Arabic gender reference for THIS chunk's entries (opt-in). Keyed by the
        # block's own SRT number so it stays aligned regardless of chunking.
        # `no_arabic` drops it -- used when a chunk got prompt-blocked, since the
        # Arabic dialogue text is a common PROHIBITED_CONTENT trigger.
        ar_block = ''
        if _ar_map and not no_arabic:
            ent = []
            for block in ch:
                first = block.lstrip().split('\n', 1)[0].strip()
                if first.isdigit():
                    num = int(first)
                    ar = _ar_map.get(num)
                    if ar:
                        ent.append((num, ar))
            if ent:
                try:
                    ar_block = prompt.build_arabic_gender_block(ent)
                except Exception:
                    ar_block = ''
        full_prompt = (prompt_template
                       .replace('{prev_context_block}',
                                prev_ctx_block + ar_block)
                       .replace('{entry_count}', str(len(ch)))
                       .replace('{chunk}', body))
        overload_attempts = 0
        generic_attempts = 0
        filtered_attempts = 0
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
            except gemini.FilteredResponse as e:
                # Prompt/safety block -- usually FLAKY. Retry the SAME prompt a
                # few times first (preserves the Arabic gender quality); only
                # after that do we propagate so _translate_one drops the Arabic
                # block, then bisects, then keeps source. Never aborts the job.
                if filtered_attempts < len(FILTERED_BACKOFF):
                    wait = FILTERED_BACKOFF[filtered_attempts]
                    filtered_attempts += 1
                    kodi_utils.log(
                        'Chunk {0}/{1} blocked ({2}) -- flaky? retry {3}/{4} '
                        'in {5}s (same prompt)'.format(
                            idx, total, str(e)[:50], filtered_attempts,
                            len(FILTERED_BACKOFF), wait), level='WARNING')
                    time.sleep(wait)
                    continue
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
    abort_reason = None

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_idx = {
                executor.submit(_translate_one, i + 1, ch): i + 1
                for i, ch in enumerate(chunks)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    response = future.result()
                except _AbortTranslation as e:
                    abort_msg = e.user_msg
                    abort_reason = e.reason
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
                            'release': _src_release,
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
        # Daily Gemini quota exhausted -> fall back to Google Translate so the
        # user still gets Hebrew (machine quality; never pooled). Only for the
        # quota case -- other aborts (invalid key, overload, error) surface as
        # before so the user can fix them.
        if abort_reason == 'quota':
            gpath = _google_translate_and_save(src_text, source_lang,
                                               translated, info, via_quota=True)
            if gpath:
                if progressive_cb is not None:
                    try:
                        progressive_cb('done', {
                            'success': True,
                            'source_id': _progressive_source_id,
                            'release': _src_release,
                        })
                    except Exception:
                        pass
                _emit(True, 'google')
                return gpath
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
        _emit(False, 'abort:' + str(abort_reason or ''))
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
        _emit(False, 'partial')
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
    # Guard: the model sometimes returns EMPTY (blank subtitles) or ECHOES the
    # source untranslated -- both pass the entry-count check and used to be
    # cached and served as "the Hebrew translation". Verify the result is really
    # Hebrew before caching. If it isn't, do NOT cache the garbage; fall back to
    # Google Translate so the user still gets Hebrew (unless they chose 'none'),
    # otherwise fail visibly and let them retry.
    if not _is_mostly_hebrew(final):
        kodi_utils.log(
            'AI output is not Hebrew (empty or echoed source) -- not caching; '
            'len={0}'.format(len(final or '')), level='WARNING')
        mode = (kodi_utils.get_setting('translation_mode', 'ai') or 'ai')
        if mode != 'none':
            gpath = _google_translate_and_save(
                src_text, source_lang, translated, info)
            if gpath:
                _emit(True, 'google')
                return gpath
        kodi_utils.notify(
            'AI: התרגום לא הוחזר בעברית (ריק/לא תורגם). נסה שוב.', time_ms=10000)
        if progressive_cb is not None:
            try:
                progressive_cb('done', {'success': False,
                                        'source_id': _progressive_source_id})
            except Exception:
                pass
        _emit(False, 'not_hebrew')
        return None
    cache.save_text(translated, final)
    # Also save under the content-hash slot when it differs from
    # the early-source-id slot. That way the same translation
    # answers a future lookup whether the user comes back via the
    # same local path OR via a different source whose bytes
    # happen to match (e.g. a re-read of the same SRT from a
    # different local path).
    if early_source_id and content_id and content_id != early_source_id:
        try:
            cache.save_text(
                cache.translated_path(
                    imdb_id, season, episode, source_lang,
                    source_id=content_id, tier=_tier),
                final)
        except Exception as e:
            kodi_utils.log(
                'content-hash duplicate save failed: {0}'.format(e),
                level='DEBUG')

    # Share this fresh translation to the community pool (fire-and-forget on a
    # daemon thread -- never delays handing the subtitle to the player). Gated
    # by pool_share; only reached for a genuinely new translation (local cache
    # and pool both missed above).
    if pool is not None and pool.share_enabled():
        if _pool_quality_ok(src_text, final):
            try:
                pool.contribute_once(info, _final_pool_hash, source_lang,
                                     final, marker_path=translated,
                                     release_override=_release_override,
                                     kind=_pool_kind)
            except Exception as e:
                kodi_utils.log('pool contribute dispatch failed: {0}'.format(e),
                               level='DEBUG')
        else:
            kodi_utils.log(
                'pool: skipped share -- translation looks incomplete or not '
                'Hebrew (quality gate)', level='INFO')

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
                'release': _src_release,
            })
        except Exception as e:
            kodi_utils.log(
                'progressive_cb done(success) raised: ' + str(e),
                level='WARNING')
    _emit(True)
    return translated
