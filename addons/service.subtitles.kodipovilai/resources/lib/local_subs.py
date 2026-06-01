# Discover SRT files we can feed to the AI translator without
# touching OpenSubtitles ourselves. Two sources:
#
#   1. find_alongside(video_path) -- SRTs next to the video file on
#      disk. Only meaningful for local-file playback.
#
#   2. find_in_temp() -- recently-touched SRTs in Kodi's special://
#      temp dir. This is where Kodi drops subtitles downloaded by
#      OTHER subtitle addons (DarkSubs, OpenSubtitles, etc.) as the
#      user picks them from the search dialog. Picking up these
#      files lets the user pull source subtitles through any of
#      their already-configured subtitle addons and just use our
#      addon as the AI translator on top, instead of us re-doing
#      the search via OpenSubtitles ourselves.

import os
import time

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import language_detect


SRT_SUFFIXES = ('.srt',)


def _detect(path):
    """Best-effort language for a given SRT path. Filename hint
    first, then content sniff. Empty string if undecided."""
    lang = language_detect.from_filename(path)
    if lang:
        return lang
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            sample = fh.read(4000)
        return language_detect.detect(sample) or ''
    except (IOError, OSError):
        return ''


def find_alongside(video_path):
    """Return [(path, lang), ...] for SRTs sitting next to a local
    video. Streams (URLs, plugin:// paths) return []."""
    if not video_path:
        return []
    if video_path.startswith(('http://', 'https://', 'plugin://',
                              'rtsp://', 'udp://', 'rtmp://')):
        return []
    try:
        if not os.path.isfile(video_path):
            return []
        video_dir = os.path.dirname(video_path)
        base = os.path.splitext(os.path.basename(video_path))[0]
        if not video_dir or not base:
            return []
        out = []
        for name in os.listdir(video_dir):
            lname = name.lower()
            if not lname.endswith(SRT_SUFFIXES):
                continue
            if not name.lower().startswith(base.lower()):
                continue
            full = os.path.join(video_dir, name)
            lang = _detect(full)
            out.append((full, lang))
        return out
    except (OSError, IOError):
        return []


def find_in_temp(max_age_seconds=300):
    """Return [{path, lang, mtime, name}, ...] for .srt files in
    special://temp/ that were touched in the last max_age_seconds.

    Default window dropped from 15 minutes to 5 minutes -- the
    previous window was wide enough to carry the just-applied
    Hebrew sub from movie A into movie B's subtitle dialog, where
    we'd offer it as a passthrough match.

    Caller decides per-language what to do with the result. The
    orchestrator in translate.py refuses to surface Hebrew matches
    from this list (those are too likely to be cross-movie leakage
    from a previous addon's TempSubtitle.he.srt).
    """
    if xbmcvfs is None:
        return []
    try:
        temp_dir = xbmcvfs.translatePath('special://temp/')
    except Exception:
        return []
    if not temp_dir or not os.path.isdir(temp_dir):
        return []
    now = time.time()
    out = []
    try:
        names = os.listdir(temp_dir)
    except OSError:
        return []
    for name in names:
        if not name.lower().endswith(SRT_SUFFIXES):
            continue
        full = os.path.join(temp_dir, name)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if now - mtime > max_age_seconds:
            continue
        lang = _detect(full)
        out.append({
            'path': full, 'lang': lang, 'mtime': mtime, 'name': name,
        })
    out.sort(key=lambda r: -r['mtime'])
    return out


def purge_temp_subs():
    """Delete every .srt file in special://temp/. Used by the
    'clear temp subtitles' settings action and by the one-shot
    service-startup cleanup that ships with the temp-leak fix.
    Returns the number of files removed."""
    if xbmcvfs is None:
        return 0
    try:
        temp_dir = xbmcvfs.translatePath('special://temp/')
    except Exception:
        return 0
    if not temp_dir or not os.path.isdir(temp_dir):
        return 0
    removed = 0
    try:
        for name in os.listdir(temp_dir):
            if not name.lower().endswith(SRT_SUFFIXES):
                continue
            full = os.path.join(temp_dir, name)
            try:
                os.remove(full)
                removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed
