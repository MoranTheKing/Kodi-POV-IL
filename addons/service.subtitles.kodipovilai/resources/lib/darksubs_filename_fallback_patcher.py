# Self-healing patch of DarkSubs's get_playing_filename() to fall
# back to a synthetic release-name-style filename when the played
# URL has an opaque hash as its basename.
#
# Context: TorBox's CDN returns URLs like
#   https://store-N.torbox.app/<uuid>?token=...
# When DarkSubs reads xbmc.Player().getPlayingFile() it gets that
# URL, strips the query, takes the basename, and ends up with
# just `<uuid>`. The percentage matcher then tokenises the UUID
# (which has zero release-name tokens) and gets 0% overlap with
# every subtitle in the list -- regardless of how well the
# subtitle actually syncs.
#
# Real-Debrid / AllDebrid don't have this problem because their
# unrestrict URLs include the release filename in the path:
#   https://x.real-debrid.com/d/<id>/Daredevil.Born.Again.S02E05.1080p.WEB-DL.mkv
# so the basename has all the tokens DarkSubs's matcher needs.
#
# Fix: detect hash-like basenames and synthesise a usable filename
# from VideoPlayer / ListItem info-labels:
#   Title.SxxExx.QUALITYp.mkv
# This gives the matcher real tokens to compare against subtitle
# release names. Expected post-patch behaviour for TorBox: 30-50%
# match (still lower than RD/AD because we lose encoder + group
# tokens, but high enough to rank subtitles meaningfully instead
# of all showing 0%).
#
# Self-healing: re-applies on every Kodi startup. If DarkSubs
# upstream restructures get_playing_filename in a way our OLD
# pattern doesn't match, we skip with a log -- the percentage
# matcher goes back to being broken for TorBox but nothing else
# breaks.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
GENERAL_REL_PATH = 'resources/modules/general.py'

MARKER = '# AI_SUBS_FILENAME_FALLBACK'

# Match: original "    file_original_path = os.path.basename(...)" +
# the indented blank line + "    return file_original_path"
# all with CRLF line endings (DarkSubs's file uses Windows line
# endings on disk).
OLD_BLOCK = (
    '    file_original_path = os.path.basename(file_original_path)\r\n'
    '            \r\n'
    '    return file_original_path\r\n'
)

NEW_BLOCK = (
    '    file_original_path = os.path.basename(file_original_path)\r\n'
    '            \r\n'
    '    ' + MARKER + ': prefer the release name POV picked from the\r\n'
    '    # source-select dialog (stashed in a Window(10000) property by\r\n'
    '    # POV before play()). This gives the matcher the real release\r\n'
    '    # name -- complete with encoder/source/group tokens -- regardless\r\n'
    '    # of what the debrid CDN URL looks like. Stale-property guard:\r\n'
    '    # only trust the property if the URL POV stored alongside the\r\n'
    '    # name matches the currently-playing URL. Falls back to the\r\n'
    '    # synthetic-from-info-labels path for non-POV playbacks where\r\n'
    '    # the basename still looks like an opaque hash.\r\n'
    '    try:\r\n'
    '        import xbmcgui as _aix_gui\r\n'
    '        _aix_w = _aix_gui.Window(10000)\r\n'
    "        _aix_pn = _aix_w.getProperty('pov_picked_source_name')\r\n"
    "        _aix_pu = _aix_w.getProperty('pov_picked_source_url')\r\n"
    '        _aix_cu = xbmc.Player().getPlayingFile() or ""\r\n'
    '        if _aix_pn and _aix_pu and _aix_pu == _aix_cu:\r\n'
    '            file_original_path = _aix_pn\r\n'
    '        elif _ai_subs_filename_looks_like_hash(file_original_path):\r\n'
    '            _synthetic = _ai_subs_synthesize_filename_from_metadata()\r\n'
    '            if _synthetic:\r\n'
    '                file_original_path = _synthetic\r\n'
    '    except Exception:\r\n'
    '        pass\r\n'
    '    \r\n'
    '    return file_original_path\r\n'
)

# Helper functions appended at the end of general.py.
HELPER_BLOCK = (
    '\r\n'
    '\r\n'
    + MARKER + ' helpers, injected by service.subtitles.kodipovilai.\r\n'
    '# Used by the patched get_playing_filename() to recover when the\r\n'
    '# played URL basename is just an opaque hash (TorBox CDN behaviour).\r\n'
    'def _ai_subs_filename_looks_like_hash(name):\r\n'
    '    """True if `name` has no recognisable release-name tokens --\r\n'
    '    likely a UUID/hash returned by a CDN that omits the original\r\n'
    '    filename from the URL path."""\r\n'
    '    if not name:\r\n'
    '        return True\r\n'
    '    lower = name.lower()\r\n'
    '    # Has a video extension? Real filename, leave alone.\r\n'
    '    for ext in (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".webm",\r\n'
    '                ".ts", ".m2ts"):\r\n'
    '        if lower.endswith(ext):\r\n'
    '            return False\r\n'
    '    # Common release tokens present? Real filename.\r\n'
    '    for token in ("1080p", "720p", "2160p", "480p", "bluray",\r\n'
    '                  "webrip", "web-dl", "hdtv", "x264", "x265",\r\n'
    '                  "hevc", "remux", "amzn", "nflx", "dsnp",\r\n'
    '                  "atvp", "hmax"):\r\n'
    '        if token in lower:\r\n'
    '            return False\r\n'
    '    # Has a season/episode marker? Real filename.\r\n'
    '    import re as _re\r\n'
    '    if _re.search(r"s\\d{1,2}e\\d{1,3}", lower):\r\n'
    '        return False\r\n'
    '    # UUID-ish: mostly hex + dashes.\r\n'
    '    hex_chars = sum(1 for c in name if c in "0123456789abcdefABCDEF-")\r\n'
    '    return hex_chars / max(len(name), 1) > 0.80\r\n'
    '\r\n'
    '\r\n'
    'def _ai_subs_synthesize_filename_from_metadata():\r\n'
    '    """Build a synthetic release-style filename from VideoPlayer /\r\n'
    '    ListItem info-labels so DarkSubs\'s percentage matcher has real\r\n'
    '    tokens to compare against subtitle release names."""\r\n'
    '    title = (xbmc.getInfoLabel("VideoPlayer.Title") or\r\n'
    '             xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or\r\n'
    '             xbmc.getInfoLabel("ListItem.OriginalTitle") or\r\n'
    '             xbmc.getInfoLabel("ListItem.Title"))\r\n'
    '    if not title:\r\n'
    '        return ""\r\n'
    '    year = (xbmc.getInfoLabel("VideoPlayer.Year") or\r\n'
    '            xbmc.getInfoLabel("ListItem.Year"))\r\n'
    '    season = (xbmc.getInfoLabel("VideoPlayer.Season") or\r\n'
    '              xbmc.getInfoLabel("ListItem.Season"))\r\n'
    '    episode = (xbmc.getInfoLabel("VideoPlayer.Episode") or\r\n'
    '               xbmc.getInfoLabel("ListItem.Episode"))\r\n'
    '    quality = xbmc.getInfoLabel("VideoPlayer.VideoResolution")\r\n'
    '    parts = [title.replace(" ", ".")]\r\n'
    '    try:\r\n'
    '        s = int(season)\r\n'
    '        e = int(episode)\r\n'
    '        parts.append("S{0:02d}E{1:02d}".format(s, e))\r\n'
    '    except (ValueError, TypeError):\r\n'
    '        if year:\r\n'
    '            parts.append(str(year))\r\n'
    '    if quality and quality.isdigit():\r\n'
    '        parts.append(quality + "p")\r\n'
    '    return ".".join(parts) + ".mkv"\r\n'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('darksubs_filename_fallback_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _general_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, GENERAL_REL_PATH)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Inject the hash-detection + synthetic-filename fallback into
    DarkSubs's get_playing_filename(). Idempotent (skip if marker
    present), defensive (skip if upstream changed the shape).
    """
    path = _general_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER.encode('utf-8') in content:
        return 'unchanged'
    old_bytes = OLD_BLOCK.encode('utf-8')
    if old_bytes not in content:
        _log('get_playing_filename body shape changed upstream -- '
             'skipping', level='WARNING')
        return 'unmatched'
    new_content = (
        content.replace(old_bytes, NEW_BLOCK.encode('utf-8'), 1)
        + HELPER_BLOCK.encode('utf-8')
    )
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'wb') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('injected hash-filename fallback into '
             'get_playing_filename()', level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
