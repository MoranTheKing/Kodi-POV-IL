# Make the player's "החלף מקור" (change source) button PAUSE the video before it
# opens the source-selection screen (it used to pause; now it kept playing in
# the background). We inject one extra onclick -- PlayerControl(Play) gated on
# Player.Playing, so it only ever pauses (never un-pauses) -- right before the
# button's existing "open source screen" onclick. onclicks fire top-to-bottom,
# so: pause, then open the dialog.
#
# IMPORTANT (no double-toggle): PlayerControl(Play) TOGGLES play/pause, so we
# must never inject two pauses into the SAME firing scope (they'd cancel out).
#   * NOX / Estuary  : one button with two condition-gated onclicks (movie vs
#                      episode) -> inject ONCE, before the first (mode 'first').
#   * FENtastic      : the change-source onclicks live in SEPARATE list <item>s
#                      (each item has exactly one onclick, only the selected
#                      item fires) -> inject before EACH (mode 'each'). Plus the
#                      shared __ChooseSourceOsd__ include (one button) -> 'first'.
#
# FENtastic's OSD files use raw unescaped "&" in RunPlugin URLs, so the XML
# parse-CHECK escapes bare ampersands first (the written file keeps raw "&").
# Marker-gated (idempotent + self-healing), atomic. No-op for skins/files not
# installed or where the onclick isn't found.

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

# NOX / Estuary: the button we inject uses RunPlugin(plugin://plugin.video.pov/
# ?mode=play_media...). FENtastic: RunPlug[Ii]n($VAR[OsdReplaceSourceStartPoint]
# ...).
_POV_RX = re.compile(
    r'^(?P<i>[ \t]*)(?P<o><onclick[^>]*>RunPlugin\('
    r'plugin://plugin\.video\.pov/\?mode=play_media[^<]*</onclick>)',
    re.MULTILINE)
_FEN_RX = re.compile(
    r'^(?P<i>[ \t]*)(?P<o><onclick[^>]*>RunPlug[Ii]n\('
    r'\$VAR\[OsdReplaceSourceStartPoint\][^<]*</onclick>)',
    re.MULTILINE)

# (skin id, OSD file, regex, mode 'first'|'each')
TARGETS = (
    ('skin.povil.nox', 'xml/VideoOSD.xml', _POV_RX, 'first'),
    ('skin.estuary', 'xml/VideoOSD.xml', _POV_RX, 'first'),
    # FENtastic: the change-source onclicks appear inline as separate list
    # items in each player style, plus once in a shared include.
    ('skin.fentastic', 'xml/Includes_Onclicks.xml', _FEN_RX, 'first'),
    ('skin.fentastic', 'xml/Includes_VideoOsd.xml', _FEN_RX, 'each'),
    ('skin.fentastic', 'xml/Includes_VideoOsd1.xml', _FEN_RX, 'each'),
)

# Escape bare "&" only for the well-formedness check (file keeps raw "&").
_RAW_AMP = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('change_source_pause_patcher: ' + msg, level=level)
    except Exception:
        pass


def _xml_ok(content):
    if ET is None:
        return True
    try:
        ET.fromstring(_RAW_AMP.sub('&amp;', content))
        return True
    except Exception:
        return False


def _path(skin_id, rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + skin_id + '/')
    except Exception:
        return ''
    p = os.path.join(base, rel.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _patch_one(skin_id, rel, rx, mode):
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
    matches = list(rx.finditer(original))
    if not matches:
        return 'unmatched'          # button/onclick not present
    if mode == 'first':
        matches = matches[:1]
    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    content = original
    # Insert from the LAST match backwards so earlier offsets stay valid.
    for m in reversed(matches):
        inject = m.group('i') + PAUSE + eol
        content = content[:m.start()] + inject + content[m.start():]

    if not _xml_ok(content):
        _log('{0}: patched XML would not parse -- skipping'.format(skin_id),
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
    out = {}
    for skin_id, rel, rx, mode in TARGETS:
        key = skin_id + ':' + os.path.basename(rel)
        try:
            out[key] = _patch_one(skin_id, rel, rx, mode)
        except Exception as e:
            _log('{0}: crashed: {1}'.format(key, e), level='WARNING')
            out[key] = 'error'
    return out
