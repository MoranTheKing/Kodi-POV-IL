# Make the player's "החלף מקור" (change source) button PAUSE the video before it
# opens the source-selection screen (it used to pause; now it kept playing in
# the background). We inject one extra onclick -- PlayerControl(Play) gated on
# Player.Playing, so it only ever pauses (never un-pauses) -- right before the
# button's existing "open source screen" onclick. onclicks fire top-to-bottom,
# so: pause, then open the dialog.
#
# Covers every skin that has the button, each with its own onclick signature:
#   * NOX / Estuary : <onclick ...>RunPlugin(plugin://plugin.video.pov/?mode=
#                     play_media...)</onclick>   (Estuary's is inserted by
#                     estuary_change_source_patcher, so this must run AFTER it)
#   * FENtastic     : the __ChooseSourceOsd__ include in Includes_Onclicks.xml,
#                     <onclick ...>RunPlugIn($VAR[OsdReplaceSourceStartPoint]...
#
# Marker-gated (idempotent + self-healing), XML-parse-checked, atomic. No-op for
# skins/files not installed or where the onclick isn't found.

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


MARKER = 'AI_SUBS_CHGSRC_PAUSE'
PAUSE = ('<!-- ' + MARKER + ' --><onclick condition="Player.Playing">'
         'PlayerControl(Play)</onclick>')

# (skin id, OSD file, regex matching the FIRST change-source onclick line)
TARGETS = (
    ('skin.povil.nox', 'xml/VideoOSD.xml',
     re.compile(r'^(?P<i>[ \t]*)(?P<o><onclick[^>]*>RunPlugin\('
                r'plugin://plugin\.video\.pov/\?mode=play_media[^<]*'
                r'</onclick>)', re.MULTILINE)),
    ('skin.estuary', 'xml/VideoOSD.xml',
     re.compile(r'^(?P<i>[ \t]*)(?P<o><onclick[^>]*>RunPlugin\('
                r'plugin://plugin\.video\.pov/\?mode=play_media[^<]*'
                r'</onclick>)', re.MULTILINE)),
    ('skin.fentastic', 'xml/Includes_Onclicks.xml',
     re.compile(r'^(?P<i>[ \t]*)(?P<o><onclick[^>]*>RunPlug[Ii]n\('
                r'\$VAR\[OsdReplaceSourceStartPoint\][^<]*</onclick>)',
                re.MULTILINE)),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('change_source_pause_patcher: ' + msg, level=level)
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


def _patch_one(skin_id, rel, rx):
    path = _path(skin_id, rel)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(skin_id, e), level='WARNING')
        return 'read_failed'

    if MARKER in original:
        return 'ok'                 # already injected
    m = rx.search(original)
    if not m:
        return 'unmatched'          # button/onclick not present
    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    indent = m.group('i')
    inject = indent + PAUSE + eol
    content = original[:m.start()] + inject + original[m.start():]

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
    out = {}
    for skin_id, rel, rx in TARGETS:
        try:
            out[skin_id] = _patch_one(skin_id, rel, rx)
        except Exception as e:
            _log('{0}: crashed: {1}'.format(skin_id, e), level='WARNING')
            out[skin_id] = 'error'
    return out
