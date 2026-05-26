# Self-healing patch of plugin.video.pov's sources.py so that when
# POV picks a source from the source-select dialog, it stashes the
# picked release name + URL in a Kodi Window(10000) property right
# before yielding the link to the player.
#
# Why: DarkSubs runs as a separate addon (separate Python process
# when its subtitle.module is dispatched) and reads
# xbmc.Player().getPlayingFile() to get the filename for matching
# subtitle release names by token overlap. For TorBox sources the
# CDN URL is opaque (`store-N.torbox.app/<uuid>?token=...`) so the
# basename is just a UUID and the matcher gets 0% every time. For
# RD/AD the URL has the release filename but it might be a slightly
# different transliteration than the source POV originally picked.
#
# Either way, the cleanest filename to feed the matcher is the one
# POV itself picked from the user's source list (item['name'] inside
# the `_process` generator in `play_file`). That release name is
# guaranteed to contain the full token set the subtitle release names
# were authored against (encoder, source, group, etc).
#
# Window properties on Window(10000) are persistent across the
# addon-dispatch boundary, so DarkSubs can read them via
# `xbmc.Window(10000).getProperty('pov_picked_source_name')`. We
# also write the picked URL alongside the name so DarkSubs can
# verify that the property is for the *current* playback and not a
# stale value from an earlier POV play.
#
# Self-healing: re-applies on every Kodi startup. If POV upstream
# restructures _process() or play_file() in a way our pattern
# doesn't match, we skip with a log warning and the TorBox fallback
# in darksubs_filename_fallback_patcher carries on by synthesising
# a filename from VideoPlayer info-labels (lower-fidelity but better
# than 0%).

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
SOURCES_REL_PATH = 'resources/lib/modules/sources.py'

MARKER = '# AI_SUBS_POV_SOURCE_NAME'

# Match the single-line yield inside _process() in play_file().
# POV uses tabs for indentation (4 tabs deep inside the generator
# function). Verified by inspecting the upstream file.
OLD_BLOCK = (
    '\t\t\t\tif link is not None: yield link\r\n'
)

NEW_BLOCK = (
    '\t\t\t\tif link is not None:\r\n'
    '\t\t\t\t\t' + MARKER + ': stash the picked release name + URL\r\n'
    '\t\t\t\t\t# in a Window property so DarkSubs (separate addon) can\r\n'
    '\t\t\t\t\t# read it and use the real filename for subtitle matching\r\n'
    '\t\t\t\t\t# instead of the opaque CDN basename (TorBox UUID, etc.).\r\n'
    '\t\t\t\t\ttry:\r\n'
    '\t\t\t\t\t\timport xbmcgui as _aix_gui_pov\r\n'
    '\t\t\t\t\t\t_aix_w_pov = _aix_gui_pov.Window(10000)\r\n'
    "\t\t\t\t\t\t_aix_w_pov.setProperty('pov_picked_source_name', "
    "item.get('name', '') or '')\r\n"
    "\t\t\t\t\t\t_aix_w_pov.setProperty('pov_picked_source_url', "
    "link or '')\r\n"
    '\t\t\t\t\texcept Exception: pass\r\n'
    '\t\t\t\t\tyield link\r\n'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_source_name_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SOURCES_REL_PATH)
    return p if os.path.isfile(p) else ''


def _detect_lineendings(content):
    """Return the line-ending byte sequence used in `content`. POV's
    files have historically been LF but we should handle both."""
    return b'\r\n' if b'\r\n' in content[:2048] else b'\n'


def ensure_patched():
    """Inject the source-name-stashing block into POV's _process()
    generator. Idempotent (skip if marker present), defensive (skip
    if upstream changed the shape).
    """
    path = _sources_path()
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
    eol = _detect_lineendings(content)
    old_bytes = OLD_BLOCK.encode('utf-8')
    new_bytes = NEW_BLOCK.encode('utf-8')
    if eol == b'\n':
        old_bytes = old_bytes.replace(b'\r\n', b'\n')
        new_bytes = new_bytes.replace(b'\r\n', b'\n')
    if old_bytes not in content:
        _log('_process() yield shape changed upstream -- skipping',
             level='WARNING')
        return 'unmatched'
    new_content = content.replace(old_bytes, new_bytes, 1)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'wb') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('injected source-name window-property stash into '
             'sources.py::_process()', level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
