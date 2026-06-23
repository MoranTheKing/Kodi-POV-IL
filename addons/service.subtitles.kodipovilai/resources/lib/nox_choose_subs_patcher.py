# Adds a "בחר כתוביות" (choose subtitles) button to the NOX skin's player OSD
# (skin.povil.nox/xml/VideoOSD.xml), wired to MoranSubs's own subtitle-chooser
# window:
#     RunScript(service.subtitles.kodipovilai,action=choose_subs)
#
# NOX shipped without this button; FENtastic had one (pointing at the now-
# disabled DarkSubs), so this brings NOX to parity. The chooser is a pyxbmct
# window (skin-agnostic) and falls back to Kodi's native selector on failure.
#
# Self-healing: marker-gated, reverts prior versions, XML-parse-checked before
# writing (a broken OSD would black-screen the player), atomic write. No-op
# when NOX isn't installed.

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
MARKER = 'AI_SUBS_NOX_CHOOSE_SUBS_v1'
BUTTON_ID = '39518'  # unused in NOX (39517 is the change-source button)

# Anchor: the always-present "audio" button in the right-side OSD grouplist.
_ANCHOR_RE = re.compile(
    r'^(?P<indent>[ \t]*)<control type="button" id="70038">',
    re.MULTILINE,
)
_REVERT_RE = re.compile(
    r'[ \t]*<!--\s*AI_SUBS_NOX_CHOOSE_SUBS_v\d+\s*-->.*?</control>[ \t]*\r?\n',
    re.DOTALL,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('nox_choose_subs_patcher: ' + msg, level=level)
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
    lines = [
        indent + '<!-- ' + MARKER + ' -->',
        indent + '<control type="button" id="' + BUTTON_ID + '">',
        inner + '<description>MoranSubs choose subtitles</description>',
        inner + '<visible>!VideoPlayer.Content(LiveTV) | '
                'VideoPlayer.HasSubtitles</visible>',
        inner + '<visible>!String.Contains(Player.Folderpath, '
                'plugin.video.idanplus)</visible>',
        inner + '<height>80</height>',
        inner + '<width>220</width>',
        inner + '<include>SettingsItemCommonOSD</include>',
        inner + '<font>font25_title</font>',
        inner + '<label>בחר כתוביות</label>',
        inner + '<onclick>RunScript(service.subtitles.kodipovilai,'
                'action=choose_subs)</onclick>',
        indent + '</control>',
    ]
    return ''.join(ln + eol for ln in lines)


def ensure_patched():
    path = _osd_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'

    # Strip any prior version so we re-apply cleanly (idempotent).
    content = _REVERT_RE.sub('', original)

    m = _ANCHOR_RE.search(content)
    if not m:
        _log('audio-button anchor not found -- skipping', level='WARNING')
        return 'unmatched'
    indent = m.group('indent')
    block = _button_block(indent, eol)
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

    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
    return 'patched'
