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
    p = os.path.join(base, OSD_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


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

    if MARKER in original:
        return 'ok'                 # already fixed

    content = original
    changed = 0
    for bid, old, new in _WIDTHS:
        # Match this button's OWN <width> (the first one after its id), so we
        # never touch another control that happens to share the width value.
        rx = re.compile(
            r'(<control type="button" id="' + re.escape(bid) +
            r'">.*?<width>)' + old + r'(</width>)', re.DOTALL)
        content, n = rx.subn(r'\g<1>' + new + r'\g<2>', content, count=1)
        changed += n

    if changed == 0:
        return 'unmatched'          # widths already differ / button absent

    # Drop the marker in right after <controls> so the fix is idempotent.
    content = content.replace('<controls>',
                              '<controls>\n\t\t<!-- ' + MARKER + ' -->', 1)

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
    return 'patched'
