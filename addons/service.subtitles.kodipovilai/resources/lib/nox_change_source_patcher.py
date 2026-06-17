# Adds a "החלף מקור" (change source) button to the NOX skin's player OSD.
#
# Why: the NOX skin (skin.povil.nox, an Estuary MOD) ships a fullscreen
# video OSD with NO change-source button, so if a source turns out bad
# mid-playback the user has no way to pick another without stopping and
# re-opening from scratch. (FENtastic has this button; NOX didn't.)
#
# NOX even carries a COMMENTED-OUT attempt at this button, but it used the
# wrong POV mode (mode=playback.media&media_type=...), which is why it was
# disabled. The mode that actually works -- proven by both FENtastic's OSD
# and NOX's own "next episode" button -- is:
#   plugin://plugin.video.pov/?mode=play_media&mediatype=<movie|episode>
#       &tmdb_id=...&autoplay=false
# autoplay=false forces the source-selection dialog to show (re-scrape),
# and because a video is already playing our remember-source auto-pick hook
# steps aside (change-source path), so the user always gets the dialog.
#
# Self-healing: marker-gated, reverts prior versions, XML-parse-checked
# before writing (so a bad edit can never corrupt the skin and black-screen
# the player), atomic write. No-op when NOX isn't installed.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    import xml.etree.ElementTree as ET
except Exception:
    ET = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


NOX_SKIN_ID = 'skin.povil.nox'
OSD_REL_PATH = 'xml/VideoOSD.xml'
MARKER = 'AI_SUBS_NOX_CHANGE_SOURCE_v1'
BUTTON_ID = '39517'  # verified unused across the NOX skin

# Anchor: the always-present "audio" button in the right-side OSD grouplist.
# We insert the change-source button just before it.
_ANCHOR_RE = re.compile(
    r'^(?P<indent>[ \t]*)<control type="button" id="70038">',
    re.MULTILINE,
)
# Revert any prior version of our injected block (marker comment .. its
# closing </control>, including the trailing newline).
_REVERT_RE = re.compile(
    r'[ \t]*<!--\s*AI_SUBS_NOX_CHANGE_SOURCE_v\d+\s*-->.*?</control>[ \t]*\r?\n',
    re.DOTALL,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('nox_change_source_patcher: ' + msg, level=level)
    except Exception:
        pass


def _osd_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + NOX_SKIN_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, OSD_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _button_block(indent, eol):
    inner = indent + '\t'
    mv = ('plugin://plugin.video.pov/?mode=play_media&amp;mediatype=movie'
          '&amp;tmdb_id=$INFO[VideoPlayer.UniqueID(tmdb)]&amp;autoplay=false')
    ep = ('plugin://plugin.video.pov/?mode=play_media&amp;mediatype=episode'
          '&amp;tmdb_id=$INFO[VideoPlayer.UniqueID(tmdb)]'
          '&amp;season=$INFO[VideoPlayer.Season]'
          '&amp;episode=$INFO[VideoPlayer.Episode]&amp;autoplay=false')
    lines = [
        indent + '<!-- ' + MARKER + ' -->',
        indent + '<control type="button" id="' + BUTTON_ID + '">',
        inner + '<description>POV IL change source</description>',
        inner + '<visible>VideoPlayer.Content(movies) | '
                'VideoPlayer.Content(episodes)</visible>',
        inner + '<visible>!VideoPlayer.Content(LiveTV)</visible>',
        inner + '<visible>!String.Contains(Player.Folderpath, '
                'plugin.video.idanplus)</visible>',
        inner + '<visible>!String.Contains(Player.Folderpath, '
                'plugin.video.supertv)</visible>',
        inner + '<visible>!String.Contains(Player.Folderpath, '
                'plugin.video.flashstream)</visible>',
        inner + '<height>80</height>',
        inner + '<width>220</width>',
        inner + '<include>SettingsItemCommonOSD</include>',
        inner + '<font>font25_title</font>',
        inner + '<label>החלף מקור</label>',
        inner + '<onclick condition="VideoPlayer.Content(movies)">'
                'RunPlugin(' + mv + ')</onclick>',
        inner + '<onclick condition="VideoPlayer.Content(episodes)">'
                'RunPlugin(' + ep + ')</onclick>',
        indent + '</control>',
    ]
    return ''.join(ln + eol for ln in lines)


def ensure_patched():
    path = _osd_path()
    if not path:
        return 'no_file'
    try:
        # newline='' disables newline translation so CRLF stays CRLF -- the
        # NOX skin files use CRLF and we want a minimal, faithful edit.
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    already = MARKER in original

    # Strip any prior version so we re-apply cleanly (idempotent).
    content = _REVERT_RE.sub('', original)

    m = _ANCHOR_RE.search(content)
    if not m:
        _log('audio-button anchor not found -- skipping', level='WARNING')
        return 'unmatched'
    indent = m.group('indent')
    block = _button_block(indent, eol)
    # Insert the block (with its own trailing EOL) right before the anchor
    # line's indentation.
    content = content[:m.start()] + block + content[m.start():]

    # SAFETY: never write XML that doesn't parse -- a broken OSD would
    # black-screen the player.
    if ET is not None:
        try:
            ET.fromstring(content)
        except Exception as e:
            _log('patched XML would not parse -- skipping ({0})'.format(e),
                 level='WARNING')
            return 'parse_failed'

    if content == original:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log('injected change-source button into NOX VideoOSD', level='INFO')
    return 'unchanged' if already else 'patched'
