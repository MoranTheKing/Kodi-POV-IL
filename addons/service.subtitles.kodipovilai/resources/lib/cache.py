# Persistent translation cache. Stored under
# userdata/addon_data/<id>/cache/. Files are named by deterministic
# hash of (imdb_id, season, episode, source_lang) so the same item
# always lands on the same path; existence + age check on lookup.
#
# Eviction policy:
#  - TTL: any file not accessed for cache_ttl_days days is removed
#  - Size cap: if cache exceeds cache_size_mb, oldest-access first
#    until back to 80% of cap
# The daemon in service.py runs this once per Kodi start + every
# 24h.

import os
import hashlib
import time
import json

from . import kodi_utils

CACHE_SUBDIR_TRANSLATED = 'translated'
CACHE_SUBDIR_SOURCE     = 'source'
CACHE_SUBDIR_METADATA   = 'metadata'


def _ensure_subdir(name):
    p = os.path.join(kodi_utils.cache_dir(), name)
    if not os.path.isdir(p):
        try:
            os.makedirs(p)
        except OSError:
            pass
    return p


def _key(imdb_id, season, episode, source_lang, source_id=None):
    """Stable filename for one cached translation.

    source_id (Wyzie URL or sha1 of source SRT content) is ALWAYS
    mixed into the digest when provided. Before v0.2.48 it was only
    mixed in when imdb_id was missing, which meant two different
    source SRTs for the same movie/episode collided on one cache
    slot -- clicking subtitle B after caching A would serve A's
    translation as if it were B's.
    """
    parts = [str(imdb_id or 'unknown'),
             str(season or '0'),
             str(episode or '0'),
             str(source_lang or 'en'),
             str(source_id or '')]
    digest = hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:16]
    return '{0}_S{1}E{2}_{3}_{4}'.format(parts[0], parts[1], parts[2], parts[3], digest)


def translated_path(imdb_id, season, episode, source_lang,
                    source_id=None, tier=''):
    # `tier` namespaces a higher-quality variant in its OWN cache file without
    # colliding with the plain one (currently 'ar' = Arabic-gender-boosted).
    suffix = ('.' + tier) if tier else ''
    return os.path.join(
        _ensure_subdir(CACHE_SUBDIR_TRANSLATED),
        _key(imdb_id, season, episode, source_lang, source_id) +
        suffix + '.he.srt')


# The tiers a translation can have been written under, best first. '' is the
# plain slot used when no gender reference was found.
TRANSLATED_TIERS = ('ar', '')


def find_translated(imdb_id, season, episode, source_lang, source_id=None):
    """The cached translation for this source, whichever tier it landed in.

    WHY THIS EXISTS. resolve() writes with tier='ar' whenever a gender
    reference was found and with '' when none was, and a LOOKUP cannot know
    which happened last time -- the setting's value today says nothing about
    whether a reference aligned for that particular title. Every caller that
    guessed a single tier was therefore wrong for some share of jobs: the
    [CACHE] marker and the cache-hit fast path both guessed '', so on a title
    that DID get a reference they missed a translation that was sitting right
    there, and the user had to re-pick the subtitle by hand on the next entry
    instead of it loading straight from cache.

    Returns the path, or '' when nothing is cached.
    """
    for tier in TRANSLATED_TIERS:
        p = translated_path(imdb_id, season, episode, source_lang,
                            source_id=source_id, tier=tier)
        try:
            if os.path.isfile(p):
                return p
        except OSError:
            pass
    return ''


def source_path(imdb_id, season, episode, source_lang,
                source_id=None):
    return os.path.join(
        _ensure_subdir(CACHE_SUBDIR_SOURCE),
        _key(imdb_id, season, episode, source_lang, source_id) +
        '.{0}.srt'.format(source_lang))


def metadata_path(imdb_id):
    safe = hashlib.sha1(str(imdb_id).encode('utf-8')).hexdigest()[:16]
    return os.path.join(_ensure_subdir(CACHE_SUBDIR_METADATA),
                        '{0}_{1}.json'.format(str(imdb_id) or 'unknown', safe))


def load_text(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = f.read()
        # Refresh atime/mtime so LRU eviction tracks usage.
        try:
            now = time.time()
            os.utime(path, (now, now))
        except OSError:
            pass
        return data
    except (IOError, OSError, UnicodeDecodeError):
        return None


def save_text(path, content):
    if not path:
        return False
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except (IOError, OSError):
        return False


def load_json(path):
    raw = load_text(path)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def save_json(path, data):
    try:
        return save_text(path, json.dumps(data, ensure_ascii=False, indent=0))
    except (TypeError, ValueError):
        return False


# Zero-byte markers written NEXT TO a translation, not standing on their own.
# Longest first: '.emb2.shared' has to be stripped whole, because '<path>.emb2'
# is only a marker KEY (translate._pool_marker) and no such file is ever
# written -- taking it as the parent would make every embedded marker look
# orphaned.
#   .shared        pool.
#   .emb2.shared   pool._marker_path(translate._pool_marker(p, 'ai_emb')).
#   .google        srt.is_google_translated -- this file is machine
#                  translation and must never reach the community pool.
#   .release       the source release name, used to tag a pool upload.
_SIDECARS = ('.emb2.shared', '.shared', '.google', '.release')


def _sidecar_parent(path):
    """The translation a marker belongs to, or '' when this is not a marker."""
    for suf in _SIDECARS:
        if path.endswith(suf):
            return path[:-len(suf)]
    return ''


def _walk_cache_files():
    """Yield (full_path, atime_or_mtime, size_bytes) for every file
    under the cache root.

    A SIDECAR IS AS RECENT AS THE FILE IT DESCRIBES. load_text() touches only
    the translation, so a marker beside a file that is read every week still
    ages out on its own mtime. For '.google' that is a correctness bug rather
    than untidiness: once the marker is gone is_google_translated() answers
    False and the next cache hit backfills machine translation into the
    community pool, which translate.py and srt.py both say must never happen.
    '.shared' has the same shape -- lose it and the file is re-uploaded.

    A marker with NO parent keeps its own recency. That is what matters for
    '.release', which is written when the reference is chosen -- one to three
    minutes before cache.save_text() creates the translation -- so a prune() in
    that window must not treat it as an orphan and delete it mid-job. Once it
    IS old and still parentless, it is collected normally.

    max() rather than plain inheritance is defensive only: it would keep a
    freshly-rewritten marker beside a parent that is already past its TTL. No
    test covers that because no caller currently produces it -- the distinction
    is not load-bearing today, and it is written here so the next reader does
    not mistake it for a behaviour that is being relied on.

    Note this materialises the file table before yielding, where it used to
    stream: a sidecar cannot be scored without its parent's stat, and the
    parent may come later in the walk. At the 200 MB default that is a few MB;
    at the 2000 MB maximum roughly 35 MB, briefly, on a background thread.
    """
    root = kodi_utils.cache_dir()
    stats = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            stats[p] = (max(st.st_atime, st.st_mtime), st.st_size)
    for p, (recency, size) in stats.items():
        parent = _sidecar_parent(p)
        if parent:
            prec = stats.get(parent)
            if prec:
                recency = max(recency, prec[0])
        yield p, recency, size


def prune():
    """Apply TTL + size-cap eviction. Safe to run any time; returns
    (files_removed, bytes_freed) for caller telemetry."""
    ttl_days = kodi_utils.get_int('cache_ttl_days', 180)
    cap_mb   = kodi_utils.get_int('cache_size_mb', 200)
    cap_bytes = max(10, cap_mb) * 1024 * 1024
    cutoff    = time.time() - ttl_days * 86400

    removed = 0
    freed   = 0

    # Pass 1: TTL eviction.
    survivors = []
    for path, recency, size in _walk_cache_files():
        if recency < cutoff:
            try:
                os.remove(path)
                removed += 1
                freed += size
            except OSError:
                pass
        else:
            survivors.append((path, recency, size))

    # Pass 2: size cap. Sort by oldest-access first and drop until
    # we're under 80% of the cap.
    total = sum(s for _, _, s in survivors)
    target = int(cap_bytes * 0.8)
    if total <= cap_bytes:
        return removed, freed

    survivors.sort(key=lambda t: t[1])  # oldest first
    for path, _recency, size in survivors:
        if total <= target:
            break
        try:
            os.remove(path)
            removed += 1
            freed += size
            total -= size
        except OSError:
            pass

    return removed, freed


def clear_all():
    """Wipe every file under cache/. Returns count removed."""
    count = 0
    for path, _r, _s in _walk_cache_files():
        try:
            os.remove(path)
            count += 1
        except OSError:
            pass
    return count


def total_size_mb():
    total = 0
    for _p, _r, s in _walk_cache_files():
        total += s
    return total / (1024.0 * 1024.0)
