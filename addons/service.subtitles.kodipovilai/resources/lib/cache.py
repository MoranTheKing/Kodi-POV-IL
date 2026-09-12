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
# '.google' says the file is machine translation and must never reach the
# community pool; '.emb2' marks an embedded-source pool entry; '.release'
# carries the source release name.
_SIDECARS = ('.google', '.emb2', '.release')


def _sidecar_parent(path):
    """The translation a marker belongs to, or '' when this is not a marker."""
    for suf in _SIDECARS:
        if path.endswith(suf):
            return path[:-len(suf)]
    return ''


def _walk_cache_files():
    """Yield (full_path, atime_or_mtime, size_bytes) for every file
    under the cache root.

    A SIDECAR INHERITS ITS PARENT'S RECENCY. load_text() touches only the
    translation, so a marker sitting beside a file that is read every week
    still ages out on its own mtime. For '.google' that is a correctness bug,
    not a tidiness one: once the marker is gone _is_google_translated() answers
    False, and the next cache hit backfills machine translation into the
    community pool -- the one thing translate.py:1595 and srt.py:1701 both say
    must never happen. Ageing a marker with the file it describes removes the
    whole class; it also stops a marker outliving its parent, which would leave
    a stray zero-byte file behind forever.
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
            # No parent left -> recency 0, so the orphan is evicted next pass.
            recency = prec[0] if prec else 0.0
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
