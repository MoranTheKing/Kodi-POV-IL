# Remembers which source the user picked for a given movie/episode, so a
# future play can auto-pick the same (or a similar) source instead of showing
# the source/servers dialog again.
#
# PHASE 1 (current): CAPTURE ONLY. A small block injected into POV's
# sources.py::play_file() writes a per-media JSON record here whenever the user
# plays a chosen source (gated by the `remember_source` setting, OFF by
# default). This module is the read side + the shared key/format contract; it
# changes no playback behavior. PHASE 2 will read these records to auto-pick.
#
# Storage: one file per media under
#   addon_data/service.subtitles.kodipovilai/source_memory/<key>.json
# (one file per key => no read-modify-write race between concurrent plays).
# Record shape (written by the POV patch):
#   {name, hash, quality, provider, debrid, release_title}

import os
import json

from . import kodi_utils

SUBDIR = 'source_memory'


def _dir():
    base = kodi_utils.cache_dir()
    # cache_dir() is .../addon_data/<id>/cache; source memory is a sibling of
    # cache so a "clear cache" doesn't wipe remembered sources.
    root = os.path.dirname(base) if base else ''
    p = os.path.join(root, SUBDIR) if root else ''
    return p


def key(media_type, media_id, season=None, episode=None):
    """Stable key matching the format the POV capture patch writes."""
    return '{0}_{1}_s{2}_e{3}'.format(
        media_type or 'movie', media_id or '',
        season if season not in (None, '') else 0,
        episode if episode not in (None, '') else 0)


def get(media_type, media_id, season=None, episode=None):
    """Return the remembered source record for this media, or None."""
    d = _dir()
    if not d:
        return None
    path = os.path.join(d, key(media_type, media_id, season, episode) + '.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except (IOError, OSError, ValueError):
        return None


def count():
    """How many sources have been remembered (for diagnostics)."""
    d = _dir()
    if not d or not os.path.isdir(d):
        return 0
    try:
        return len([f for f in os.listdir(d) if f.endswith('.json')])
    except OSError:
        return 0


def prune(max_keep=2000):
    """Cap the source_memory directory so it can never grow without bound.
    Keeps the `max_keep` most-recently-modified records and deletes the rest
    (oldest first). Each record is tiny (~340 bytes), so even the cap is well
    under a couple of MB -- this just guarantees it never creeps up over years
    of watching. A pruned title simply shows the source dialog again next time,
    exactly like a first watch. Returns the number of files removed."""
    d = _dir()
    if not d or not os.path.isdir(d):
        return 0
    try:
        entries = [f for f in os.listdir(d) if f.endswith('.json')]
    except OSError:
        return 0
    if len(entries) <= max_keep:
        return 0
    paths = []
    for fn in entries:
        fp = os.path.join(d, fn)
        try:
            paths.append((os.path.getmtime(fp), fp))
        except OSError:
            pass
    paths.sort(key=lambda t: t[0])  # oldest first
    removed = 0
    for _mtime, fp in paths[:len(paths) - max_keep]:
        try:
            os.remove(fp)
            removed += 1
        except OSError:
            pass
    return removed


def dir_path():
    """The source_memory directory path (for diagnostics)."""
    return _dir() or ''


def list_all():
    """Return [(key, record), ...] for every remembered source (diagnostics)."""
    d = _dir()
    out = []
    if not d or not os.path.isdir(d):
        return out
    try:
        names = sorted(f for f in os.listdir(d) if f.endswith('.json'))
    except OSError:
        return out
    for fn in names:
        try:
            with open(os.path.join(d, fn), 'r', encoding='utf-8') as f:
                out.append((fn[:-5], json.loads(f.read())))
        except (IOError, OSError, ValueError):
            pass
    return out
