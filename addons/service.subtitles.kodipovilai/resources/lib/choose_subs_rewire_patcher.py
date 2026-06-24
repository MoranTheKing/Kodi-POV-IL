# Repoint the player's "בחר כתוביות" / "חפש כתובית" button to MoranSubs's own
# subtitle chooser, in EVERY skin + EVERY player style that ships it.
#
# The button historically had up to two onclick branches, gated by a skin
# setting ("בחירת כתוביות פותח את החלון של קודי"):
#   * DarkSubs branch : RunScript(service.subtitles.All_Subs,sub_window_unpause)
#   * "Kodi window"    : ActivateWindow(subtitlesearch) / ActivateWindow(
#                        SubtitleSearch)
# DarkSubs is disabled once the built-in engine is on, and several player styles
# only ever had the "Kodi window" branch -- so depending on the skin setting and
# player style the button opened Kodi's native download window (or nothing). We
# point EVERY branch at our own chooser instead; the native download window is
# still one tap away from inside the chooser ("הורדת כתוביות (Kodi)" button), so
# nothing is lost:
#     RunScript(service.subtitles.kodipovilai,action=choose_subs)
#
# Self-healing: re-applied every Kodi startup (so a skin refresh that re-adds an
# old call is corrected again), idempotent, XML-parse-checked before writing,
# atomic. No-op for skins/files that aren't installed or don't contain any of the
# old calls. (NOX has no such button -- it's handled by nox_choose_subs_patcher;
# AF3 has none either.)

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


NEW_CALL = 'RunScript(service.subtitles.kodipovilai,action=choose_subs)'

# Every old "open subtitle UI" action the choose-subs button used, in any skin /
# player style -> our chooser. These strings only ever appear in that button
# within the targeted files (verified), so a scoped replace is safe.
#   NOTE: ActivateWindow(osdsubtitlesettings) is the *settings* (delay/sync)
#   button, NOT this one, so it is deliberately NOT listed.
OLD_CALLS = (
    'RunScript(service.subtitles.All_Subs,sub_window_unpause)',
    'ActivateWindow(subtitlesearch)',
    'ActivateWindow(SubtitleSearch)',
)

# (skin id, OSD file holding the button). FENtastic carries the button in EVERY
# player style (simple/advanced/netflix/pretty -> Includes_VideoOsd[ ,1,2,3,4]),
# each with its own onclick form; Estuary has it in VideoOSD.xml.
TARGETS = (
    ('skin.fentastic', 'xml/Includes_VideoOsd.xml'),
    ('skin.fentastic', 'xml/Includes_VideoOsd1.xml'),
    ('skin.fentastic', 'xml/Includes_VideoOsd2.xml'),
    ('skin.fentastic', 'xml/Includes_VideoOsd3.xml'),
    ('skin.fentastic', 'xml/Includes_VideoOsd4.xml'),
    ('skin.estuary', 'xml/VideoOSD.xml'),
    # NOX: catches the old All_Subs button form (e.g. skin v1.0.7) so the button
    # reaches our chooser even before the skin updates. (nox_choose_subs_patcher
    # also handles NOX's newer ActivateWindow(2118) form -- both are idempotent.)
    ('skin.povil.nox', 'xml/VideoOSD.xml'),
)

# FENtastic's OSD files use raw, unescaped "&" in RunPlugin URLs (Kodi's skin
# parser tolerates it, strict XML does not), so a plain ET.fromstring would
# reject them. Escape bare ampersands only for the well-formedness CHECK -- the
# file we write keeps the original raw "&".
_RAW_AMP = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)')


def _parses(content):
    if ET is None:
        return True
    try:
        ET.fromstring(_RAW_AMP.sub('&amp;', content))
        return True
    except Exception:
        return False


def _edit_safe(original, content):
    """Our edit is a pure swap of one complete builtin (RunScript/ActivateWindow)
    for another inside existing <onclick> text -- it can't change XML structure.
    Some FENtastic files don't even parse as strict XML to begin with (Kodi-only
    quirks like a "--->" comment), so we don't demand absolute validity: we only
    reject the edit if it turned a CLEANLY-parsing file into a broken one."""
    if ET is None:
        return True
    return _parses(content) or not _parses(original)


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

    if not any(call in original for call in OLD_CALLS):
        return 'ok' if NEW_CALL in original else 'unmatched'

    content = original
    for call in OLD_CALLS:
        content = content.replace(call, NEW_CALL)

    if not _edit_safe(original, content):
        _log('{0}: edit would break XML -- skipping'.format(skin_id),
             level='WARNING')
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
    """Returns a dict {"skin_id:file": status}. Best-effort across all targets
    (a skin can have several player-style files)."""
    out = {}
    for skin_id, rel in TARGETS:
        key = skin_id + ':' + os.path.basename(rel)
        try:
            out[key] = _patch_one(skin_id, rel)
        except Exception as e:
            _log('{0}: crashed: {1}'.format(key, e), level='WARNING')
            out[key] = 'error'
    return out
