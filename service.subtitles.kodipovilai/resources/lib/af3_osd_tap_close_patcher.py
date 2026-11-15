# MoranSubs by MoranTheKing - https://github.com/MoranTheKing/Kodi-POV-IL
# SPDX-License-Identifier: GPL-3.0-or-later (additional terms: LICENSE.txt)
# Arctic Fuse 3's player controls close on a tap (or a click) on the picture.
#
# The owner, on a phone (15 Nov 2026): "if I press the middle while the
# player is open, the player should close -- in the other skins' players
# too". Kodi itself only ever OPENS the controls from a tap on the picture;
# closing them takes a control that sits under the tap. Estuary has one (its
# "background close area"), the build's own skins got one in the same
# release, and Arctic Fuse 3 has none -- and updates itself, so the control
# is put into its VideoOSD.xml here, again after every update.
#
# The control is the FIRST one inside <controls>: Kodi offers a tap to the
# controls drawn last first, so every button of the skin keeps its own taps
# and this one takes only what none of them does. It has no picture. No key
# leads to it, and any arrow from it goes to the window's default control.
# The bottom 280 px (the buttons) are left out, as in Estuary.
#
# Marker-gated and atomic like the other AF3 patchers; a file without
# exactly one <controls> element, or without the default control this was
# written against, is left alone.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


AF3_ADDON_ID = 'skin.arctic.fuse.3'
VIDEO_OSD_REL_PATH = '1080i/VideoOSD.xml'

MARKER = '<!-- AI_SUBS_AF3_OSD_TAP_CLOSE_v1 -->'
AREA_ID = 6990

_CONTROLS_OPEN_RE = re.compile(rb'(?P<indent>[ \t]*)<controls>[ \t]*(?P<eol>\r?\n)')
_DEFAULT_RE = re.compile(rb'<defaultcontrol[^>]*>\s*(\d+)\s*</defaultcontrol>')
_COMMENT_RE = re.compile(rb'<!--.*?-->', re.S)


def _area(indent, eol, default_id):
    pad = indent + '    '
    lines = [
        pad + MARKER,
        pad + '<control type="button" id="{0}">'.format(AREA_ID),
        pad + '    <description>a tap or a click on the picture closes the controls</description>',
        pad + '    <left>0</left>',
        pad + '    <top>0</top>',
        pad + '    <width>100%</width>',
        pad + '    <bottom>280</bottom>',
        pad + '    <texturefocus />',
        pad + '    <texturenofocus />',
        pad + '    <onclick>Action(close)</onclick>',
    ]
    for tag in ('onup', 'ondown', 'onleft', 'onright'):
        lines.append(pad + '    <{0}>{1}</{0}>'.format(tag, default_id))
    lines.append(pad + '</control>')
    return eol.join(lines) + eol


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('af3_osd_tap_close_patcher: ' + msg, level=level)
    except Exception:
        pass


def _osd_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + AF3_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, VIDEO_OSD_REL_PATH)
    return p if os.path.isfile(p) else ''


def patch_text(content):
    """`content` (bytes of VideoOSD.xml) with the area, or None when the
    file is not the shape this was written against."""
    opens = list(_CONTROLS_OPEN_RE.finditer(content))
    # the default control the window really has: not one left in a comment
    default = _DEFAULT_RE.search(_COMMENT_RE.sub(b'', content))
    if len(opens) != 1 or content.count(b'<controls') != 1 or default is None:
        return None
    if re.search(rb'id="%d"' % AREA_ID, content):
        return None                 # the skin uses the id now: not ours to share
    m = opens[0]
    area = _area(m.group('indent').decode('ascii'), m.group('eol').decode('ascii'),
                 default.group(1).decode('ascii'))
    return content[:m.end()] + area.encode('utf-8') + content[m.end():]


def ensure_patched():
    """Idempotent. Returns 'no_file' | 'already_patched' | 'patched' |
    'unmatched' | 'read_failed' | 'write_failed'."""
    path = _osd_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'read_failed'
    if MARKER.encode('utf-8') in content:
        return 'already_patched'
    patched = patch_text(content)
    if patched is None:
        _log('VideoOSD.xml is not the shape this was written against (one '
             '<controls>, a default control, id {0} free) -- left alone'.format(AREA_ID),
             level='WARNING')
        return 'unmatched'
    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(patched)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'write_failed'
    _log('a tap on the picture now closes Arctic Fuse 3\'s player controls')
    return 'patched'
