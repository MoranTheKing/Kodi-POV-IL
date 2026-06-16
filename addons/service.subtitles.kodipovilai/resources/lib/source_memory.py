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
