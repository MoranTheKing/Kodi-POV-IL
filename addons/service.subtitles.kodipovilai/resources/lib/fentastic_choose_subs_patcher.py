# Repoint FENtastic's player "בחר כתוביות" button to MoranSubs's own subtitle
# chooser window.
#
# Why: the button (skin.fentastic/xml/Includes_VideoOsd3.xml, id 700451,
# "DarkSubs Subtitles Window Button") was wired to DarkSubs:
#     RunScript(service.subtitles.All_Subs,sub_window_unpause)
# Once the built-in engine is on, DarkSubs (service.subtitles.All_Subs) is
# disabled, so that button did nothing useful (it fell through to the search,
# duplicating "Download subtitle"). We point it at MoranSubs's pyxbmct chooser
# instead:
#     RunScript(service.subtitles.kodipovilai,action=choose_subs)
#
# Self-healing: re-applied every Kodi startup (so a Tal skin refresh that
# re-introduces the DarkSubs call is corrected again), idempotent, XML-parse-
# checked before writing, atomic. No-op when FENtastic isn't installed.

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


SKIN_ID = 'skin.fentastic'
REL_PATH = 'xml/Includes_VideoOsd3.xml'
OLD_CALL = 'RunScript(service.subtitles.All_Subs,sub_window_unpause)'
NEW_CALL = 'RunScript(service.subtitles.kodipovilai,action=choose_subs)'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('fentastic_choose_subs_patcher: ' + msg, level=level)
    except Exception:
        pass


def _path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + SKIN_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    path = _path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if OLD_CALL not in original:
        # Already ours (or the button changed) -- nothing to do.
        return 'ok' if NEW_CALL in original else 'unmatched'

    content = original.replace(OLD_CALL, NEW_CALL)

    # Never write a file that wouldn't parse.
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
