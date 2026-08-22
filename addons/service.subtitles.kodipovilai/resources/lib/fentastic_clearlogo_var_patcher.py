# Two missing brackets that made a whole feature invisible.
#
# FOUND IN A USER'S LOG, one line after the video window opened:
#
#     error <general>: unmatched parentheses in
#                      string.isempty(listitem.art(clearlogo)
#
# The source is the skin's own Variables.xml:
#
#     <variable name="ClearArtLogo">
#         <value condition="!String.IsEmpty(ListItem.Art(clearlogo)">...
#         <value condition="String.IsEmpty(ListItem.Art(clearlogo)">...
#     </variable>
#
# `String.IsEmpty(` is opened and never closed -- `ListItem.Art(clearlogo)`
# closes only its own bracket. Kodi cannot parse either condition, says so
# once, and treats both as false. The variable has no unconditional fallback
# value, so it resolves to NOTHING, always, on every device.
#
# WHAT THAT COSTS: `$VAR[ClearArtLogo]` has exactly one user, and it is one of
# this build's own additions -- the `Poster_View_Art_Logo` include in
# View_51_Poster.xml, whose whole body is an <image> with that variable as its
# texture. So the logo it was written to draw has never once appeared, on any
# device, since the day it was written. Not a regression: a feature that was
# dead on arrival and looked like a design decision.
#
# THIS FIXES THAT ONE VARIABLE AND NOTHING ELSE. A scan of the shipped skins
# finds around three dozen other conditions with unbalanced brackets, most of
# them in FENtastic's own upstream code (Player.Art, VideoPlayer.offset, the
# ExtendedInfo window). They are recorded here so nobody has to rediscover
# them, and deliberately left alone: this one has a log line proving Kodi
# rejects it and a dead feature proving what that costs, and the others have
# neither. Fixing a condition that might currently be doing something useful
# by accident, on a skin nobody here can test on a television, is how a
# cosmetic repair becomes a support thread.
#
# IT LANDS AT THE NEXT KODI START. Kodi parses skin XML once; only ReloadSkin
# re-reads it, and an unconditional skin reload on every boot is exactly what
# this codebase already refuses to do elsewhere (see pov_reload's repair, which
# reloads once and only after proving it is safe). A logo that appears next
# launch instead of this one is worth less than a home screen that flashes for
# everybody, every time.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


SKIN_ADDON_ID = 'skin.fentastic'
REL = 'xml/Variables.xml'

# Verbatim from the shipped skin, CRLF and all. The whole variable, not just
# the two broken attributes: a skin that has been edited into some other shape
# is one this must not touch, and matching the block is what says so.
BROKEN = (
    '\t<variable name="ClearArtLogo">\r\n'
    '\t\t<value condition="!String.IsEmpty(ListItem.Art(clearlogo)">'
    '$INFO[ListItem.Art(clearlogo)]</value>\r\n'
    '\t\t<value condition="String.IsEmpty(ListItem.Art(clearlogo)">'
    '$INFO[ListItem.Art(clearart)]</value>\r\n'
    '\t</variable>'
)

FIXED = (
    '\t<variable name="ClearArtLogo">\r\n'
    '\t\t<value condition="!String.IsEmpty(ListItem.Art(clearlogo))">'
    '$INFO[ListItem.Art(clearlogo)]</value>\r\n'
    '\t\t<value condition="String.IsEmpty(ListItem.Art(clearlogo))">'
    '$INFO[ListItem.Art(clearart)]</value>\r\n'
    '\t</variable>'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('fentastic_clearlogo_var_patcher: ' + msg, level=level)
    except Exception:
        pass


def _path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + SKIN_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *REL.split('/'))
    return p if os.path.isfile(p) else ''


def _variants(text):
    """(broken, fixed) rendered in whatever line endings the file uses.

    The shipped file is CRLF, but it has been through extractors and skin
    updates on devices nobody here has seen. Matching only CRLF would report
    'unmatched' on an LF copy and leave it broken forever, which is the
    failure mode this whole family of patchers exists to avoid.
    """
    if '\r\n' in text[:8192]:
        return BROKEN, FIXED
    return BROKEN.replace('\r\n', '\n'), FIXED.replace('\r\n', '\n')


def ensure_patched():
    """Idempotent. Never raises. Returns 'no_skin' | 'unchanged' | 'patched'
    | 'unmatched' | 'read_failed' | 'write_failed'."""
    path = _path()
    if not path:
        return 'no_skin'
    try:
        with open(path, encoding='utf-8', newline='') as f:
            text = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    broken, fixed = _variants(text)
    if fixed in text:
        return 'unchanged'
    # count, not `in`: two copies of this variable means a skin somebody has
    # edited, and the right answer there is to leave it alone.
    if text.count(broken) != 1:
        _log('the ClearArtLogo variable is not in the shape this repairs; '
             'leaving Variables.xml alone', level='WARNING')
        return 'unmatched'

    new_text = text.replace(broken, fixed, 1)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new_text)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log("the poster view's clear-logo can resolve now; it shows from the "
         'next Kodi start')
    return 'patched'
