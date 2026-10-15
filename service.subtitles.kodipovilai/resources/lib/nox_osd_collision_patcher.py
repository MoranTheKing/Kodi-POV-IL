# Fix the NOX player OSD collision the LAST change-source fix exposed: adding the
# "החלף מקור" button to NOX's right-aligned OSD group (id 202) widened that group,
# which pushed its leftmost item -- "הפרק הבא" (next episode) -- left into the
# central play controls. The controls get WIDER while playing (rewind/forward
# appear), so the overlap only shows during playback (paused looks fine).
#
# Fix without removing any button: shrink the right-group buttons so the group
# returns to the width it had BEFORE we added "החלף מקור". The added button is
# ~220px; we reclaim that same ~220px across the row, so the visible buttons sum
# to the ORIGINAL total (next 220 + audio 150 + info 140 = 510):
#       next 160 + change-source 160 + audio 90 + info 100 = 510
# => "הפרק הבא" sits back at its original (collision-free) position. Because it
# matches the original total width, the fix is resolution-independent (Kodi
# scales the whole skin), so there is no pixel guessing.
#
# Marker-gated (idempotent + self-healing), XML-parse-checked, atomic, no-op when
# NOX isn't installed or the buttons aren't at their known original widths.

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
MARKER = 'AI_SUBS_NOX_OSD_FIX_v1'

# (button id, original width, new width). Returns the right group to its
# pre-change-source total width (see header).
_WIDTHS = (
    ('70036', '220', '160'),   # "הפרק הבא" (next episode, novix)
    ('70037', '220', '160'),   # "עבור לפרק הבא" (next episode, drax)
    ('39517', '220', '160'),   # "החלף מקור" (our change-source button)
    ('70038', '150', '90'),    # "שמע" (audio)
    ('70043', '140', '100'),   # "מידע" (info)
)

# The native-player include has no <controls> element, so 0.3.30 never wrote
# its marker there; and a width pattern that could run past its own control
# then shrank the NEXT matching button on the following boot.  These are the
# buttons that took the hit (id, original width, width the stray pass left).
_COLLATERAL = (
    ('70039', '150', '90'),
    ('700450', '140', '100'),
)


def _own_width(bid):
    """Pattern for a button's OWN <width>, never crossing its </control>."""
    return re.compile(
        r'(<control type="button" id="' + re.escape(bid) +
        r'">(?:(?!</control>).)*?<width>)(\d+)(</width>)', re.DOTALL)


def _set_width(content, bid, expected, new):
    rx = _own_width(bid)
    match = rx.search(content)
    if not match or match.group(2) != expected:
        return content, 0
    return (content[:match.start(2)] + new + content[match.end(2):]), 1


def _with_marker(content):
    marker = '<!-- ' + MARKER + ' -->'
    if '<controls>' in content:
        return content.replace('<controls>', '<controls>\n\t\t' + marker, 1)
    root = re.search(r'<(includes|window)\b[^>]*>', content)
    if not root:
        return None
    return content[:root.end()] + '\n\t' + marker + content[root.end():]


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('nox_osd_collision_patcher: ' + msg, level=level)
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
    native = os.path.join(base, 'xml', 'Includes_POVIL_NativePlayer.xml')
    if os.path.isfile(native):
        return native
    p = os.path.join(base, OSD_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    path = _osd_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in original:
        return 'ok'                 # already fixed

    content = original
    changed = 0
    for bid, old, new in _WIDTHS:
        # Only this button's OWN <width>; never another control's.
        content, n = _set_width(content, bid, old, new)
        changed += n

    repaired = 0
    if changed == 0:
        # An earlier, markerless pass already applied our widths.  If it also
        # shrank the neighbours (the exact 0.3.30 second-boot signature),
        # restore them; either way record the marker so nothing re-runs.
        ours = []
        for bid, _old, new in _WIDTHS:
            match = _own_width(bid).search(content)
            if match:
                ours.append(match.group(2) == new)
        if not ours or not all(ours):
            return 'unmatched'      # widths already differ / buttons absent
        for bid, original_width, shrunk in _COLLATERAL:
            content, n = _set_width(content, bid, shrunk, original_width)
            repaired += n

    # Drop the marker in so the fix is idempotent.
    marked = _with_marker(content)
    if marked is None:
        return 'unmatched'
    content = marked

    if ET is not None:
        try:
            ET.fromstring(content)
        except Exception as e:
            _log('patched XML would not parse -- skipping ({0})'.format(e),
                 level='WARNING')
            return 'parse_failed'

    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
    if changed == 0:
        _log('marker recorded; restored {0} neighbouring button width(s)'
             .format(repaired))
        return 'repaired' if repaired else 'ok'
    return 'patched'
