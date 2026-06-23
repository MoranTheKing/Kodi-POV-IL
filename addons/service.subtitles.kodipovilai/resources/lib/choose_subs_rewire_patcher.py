# Repoint the player's "בחר כתוביות" button to MoranSubs's own subtitle chooser,
# in EVERY skin that ships the old DarkSubs "Subtitles Window" button.
#
# Both FENtastic and Estuary carry the same button wired to DarkSubs:
#     RunScript(service.subtitles.All_Subs,sub_window_unpause)
# Once the built-in engine is on, DarkSubs (service.subtitles.All_Subs) is
# disabled, so the button did nothing useful. We swap that call for ours:
#     RunScript(service.subtitles.kodipovilai,action=choose_subs)
#
# Self-healing: re-applied every Kodi startup (so a skin refresh that re-adds
# the DarkSubs call is corrected again), idempotent, XML-parse-checked before
# writing, atomic. No-op for skins/files that aren't installed or don't contain
# the call. (NOX has no such button -- it's handled by nox_choose_subs_patcher;
# AF3 has none either.)

import os

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


OLD_CALL = 'RunScript(service.subtitles.All_Subs,sub_window_unpause)'
NEW_CALL = 'RunScript(service.subtitles.kodipovilai,action=choose_subs)'

# (skin id, OSD file holding the button)
TARGETS = (
    ('skin.fentastic', 'xml/Includes_VideoOsd3.xml'),
    ('skin.estuary', 'xml/VideoOSD.xml'),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('choose_subs_rewire_patcher: ' + msg, level=level)
    except Exception:
        pass


def _path(skin_id, rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + skin_id + '/')
    except Exception:
        return ''
    p = os.path.join(base, rel.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _patch_one(skin_id, rel):
    path = _path(skin_id, rel)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(skin_id, e), level='WARNING')
        return 'read_failed'

    if OLD_CALL not in original:
        return 'ok' if NEW_CALL in original else 'unmatched'

    content = original.replace(OLD_CALL, NEW_CALL)

    if ET is not None:
        try:
            ET.fromstring(content)
        except Exception as e:
            _log('{0}: patched XML would not parse -- skipping ({1})'.format(
                skin_id, e), level='WARNING')
            return 'parse_failed'

    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        _log('{0}: write failed: {1}'.format(skin_id, e), level='WARNING')
        return 'write_failed'
    return 'patched'


def ensure_patched():
    """Returns a dict {skin_id: status}. Best-effort across all targets."""
    out = {}
    for skin_id, rel in TARGETS:
        try:
            out[skin_id] = _patch_one(skin_id, rel)
        except Exception as e:
            _log('{0}: crashed: {1}'.format(skin_id, e), level='WARNING')
            out[skin_id] = 'error'
    return out
