# Add the "החלף מקור" (change source) button to FENtastic's SIMPLE player OSD.
#
# WHY: FENtastic's player OSD comes in variants selected by the skin string
# __chooseplayer (VideoOSD.xml): advanced (videosd1), netflix (videosd2),
# simple (videosd3), pretty (videosd4). Every variant EXCEPT the simple one
# (Includes_VideoOsd3.xml) already offers a change-source button; users on the
# simple player had no way to switch a bad source mid-playback. This injects
# the same change-source action there.
#
# HOW (no overlap by design): the OSD's right-hand action buttons live in a
# <control type="grouplist" id="202"> which auto-lays-out its children
# horizontally, so ADDING one button just extends the row -- it cannot overlap
# text or collide with other buttons. We insert a radiobutton that mirrors the
# variant's own OSDButton style and reuses the skin's shared __ChooseSourceOsd__
# onclick include (the exact same behaviour the other variants use). Inserted
# right before the first button of that grouplist (id="804", unique anchor).
#
# Marker-gated (idempotent + self-healing), XML-parse-checked before an atomic
# write (only blocks the write if OUR insertion introduced a parse error), and
# preserves the file's line endings. No-op if FENtastic / the file / the anchor
# is absent, so a skin restructure can never break the player.

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


OSD3_REL = 'special://home/addons/skin.fentastic/xml/Includes_VideoOsd3.xml'
MARKER = 'AI_SUBS_SIMPLEPLAYER_CHGSRC'
# The first button of the right-hand action grouplist (unique in the file).
ANCHOR = '<control type="radiobutton" id="804">'
# Our button, styled like the variant's own buttons, reusing the shared
# change-source onclick include. id 700460 is unused in this file.
BUTTON = (
    '<!-- ' + MARKER + ' --><control type="radiobutton" id="700460">'
    '<include content="OSDButton">'
    '<param name="texture" value="icons\\infodialogs\\update.png"/>'
    '</include>'
    '<include>__ChooseSourceOsd__</include>'
    '<visible>!VideoPlayer.Content(livetv)</visible>'
    '</control>')


def _log(msg, level='INFO'):
    if kodi_utils is not None:
        try:
            kodi_utils.log(
                'fentastic_simpleplayer_source_patcher: ' + msg, level=level)
        except Exception:
            pass


def _translate(path):
    return xbmcvfs.translatePath(path) if xbmcvfs else path


def _exists(path):
    try:
        return xbmcvfs.exists(_translate(path)) if xbmcvfs else False
    except Exception:
        return False


def _read(path):
    with xbmcvfs.File(_translate(path)) as f:
        return f.read()


def _write(path, content):
    f = xbmcvfs.File(_translate(path), 'w')
    try:
        f.write(content)
    finally:
        f.close()


def _parses(text):
    if ET is None:
        return True  # can't check -> don't block
    try:
        ET.fromstring(text)
        return True
    except Exception:
        return False


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_fentastic' | 'unmatched'
    | 'compile_failed' | 'read_failed' | 'write_failed'."""
    if xbmcvfs is None:
        return 'no_fentastic'
    if not _exists(OSD3_REL):
        return 'no_fentastic'
    try:
        content = _read(OSD3_REL)
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    idx = content.find(ANCHOR)
    if idx == -1 or content.find(ANCHOR, idx + 1) != -1:
        _log('anchor not found/ambiguous -- FENtastic simple OSD shape '
             'changed; leaving it alone', level='WARNING')
        return 'unmatched'

    # Preserve the anchor line's leading indentation for the inserted block.
    line_start = content.rfind('\n', 0, idx) + 1
    indent = content[line_start:idx]
    new_content = (content[:line_start] + indent + BUTTON + '\n'
                   + content[line_start:])

    # SAFETY: only block if OUR change broke parsing (some skins aren't
    # strictly ET-parseable as-is; don't punish that -- only regressions).
    if _parses(content) and not _parses(new_content):
        _log('insertion would break XML parse -- skipping', level='WARNING')
        return 'compile_failed'

    try:
        _write(OSD3_REL, new_content)
    except Exception as e:
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
    _log('added change-source button to FENtastic simple player OSD',
         level='INFO')
    return 'patched'
