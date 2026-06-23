# Make NOX's player open MoranSubs's subtitle chooser -- WITHOUT adding a new
# OSD button.
#
# History: an earlier version ADDED a "בחר כתוביות" button to NOX's right-side
# OSD grouplist. That group is right-aligned and already near the centre play
# controls, so the extra button pushed "החלף מקור" left until it overlapped the
# fast-forward/next button. NOX already ships a subtitle button (id 70046,
# label "כתוביות") that merely opens ActivateWindow(2118); we repurpose THAT to
# open our chooser instead -- so the OSD layout is unchanged (no collision).
#
# This patcher therefore: (a) REMOVES the button the old version added (so
# existing installs self-heal), and (b) rewires button 70046's onclick. Marker-
# gated, XML-parse-checked, atomic, no-op when NOX isn't installed.

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
OLD_ONCLICK = '<onclick>ActivateWindow(2118)</onclick>'
NEW_ONCLICK = ('<onclick>RunScript(service.subtitles.kodipovilai,'
               'action=choose_subs)</onclick>')

# Remove the button the previous version inserted (any marked v\d+ block).
_OLD_BTN_RE = re.compile(
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

    # (a) drop any button the old version added.
    content = _OLD_BTN_RE.sub('', original)
    # (b) rewire the existing subtitles button (70046).
    if OLD_ONCLICK in content:
        content = content.replace(OLD_ONCLICK, NEW_ONCLICK)

    if content == original:
        # nothing to do (already rewired + no stale button, or button gone).
        return 'ok'

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
