# Self-healing patch of FENtastic's DialogNotification.xml so toast
# notifications wrap to multiple lines instead of horizontally
# scrolling. Kodi's fadelabel control scrolls long text horizontally
# in a direction that ignores BiDi -- for Hebrew users this means
# notifications visually scroll left-to-right (= backwards), which
# happens to all addons' notifications, not just ours. Earlier
# attempts to bias the scroll via U+200F RLM did not work; the
# widget appears to be BiDi-deaf for marquee direction.
#
# Fix: switch the message control's `fadelabel` to `wraplabel`.
# Wraplabel breaks long text onto multiple lines instead of
# scrolling, so there's no scroll direction to get wrong. Both
# control types share the same property set we use here (align,
# aligny, font, width, height, top, left), so all short
# notifications render identically to before.
#
# The patch is gated on the marker comment in the file and is
# idempotent + reversible. If FENtastic ever updates its
# DialogNotification.xml from the canonical Estuary shape, we
# detect the unknown shape and skip the patch -- the user's
# notifications keep working with the upstream marquee, just
# scrolling backwards as before.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils

FENTASTIC_ADDON_ID = 'skin.fentastic'
NOTIFICATION_REL_PATH = 'xml/DialogNotification.xml'

INJECT_VERSION = 1
MARKER = '<!-- AI_SUBS_NOTIFICATION_WRAP_v{0} -->'.format(INJECT_VERSION)
OLD_MARKERS = []

# The exact substring we replace. Anchored on the control id (402,
# which is the message label) so we don't touch the title label
# (id 401) -- only the body wraps. Kept tab-indent-loose by
# matching whitespace flexibly in the regex below; the marker line
# we insert preserves the original indentation we matched.
_FADELABEL_RE = re.compile(
    r'(?P<indent>[ \t]*)'
    r'<control[ \t]+type="fadelabel"[ \t]+id="402">',
)


def _xml_path():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                FENTASTIC_ADDON_ID, NOTIFICATION_REL_PATH))
    except Exception:
        return None


def _atomic_write(path, content):
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp, path)
        return True
    except OSError:
        try: os.remove(tmp)
        except OSError: pass
        return False


def ensure_patched():
    """Switch FENtastic's notification message control from
    fadelabel to wraplabel. Idempotent + safe to call on every
    Kodi startup.

    Returns one of:
      'patched'         -- we just made the change
      'already_patched' -- marker present, no-op
      'no_fentastic'    -- skin not installed
      'unmatched'       -- DialogNotification.xml has been
                           refactored beyond the expected shape;
                           we bail without touching it
      'write_failed'    -- couldn't write the file
      'read_failed'     -- couldn't read the file
    """
    p = _xml_path()
    if not p or not os.path.isfile(p):
        return 'no_fentastic'
    try:
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        kodi_utils.log(
            'fentastic_patcher: read failed: {0}'.format(e),
            level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    # Find the message label and swap the control type.
    m = _FADELABEL_RE.search(content)
    if not m:
        kodi_utils.log(
            'fentastic_patcher: fadelabel id=402 not found, '
            'leaving DialogNotification.xml untouched',
            level='WARNING')
        return 'unmatched'

    indent = m.group('indent')
    replacement = (
        '{0}{1}\n'
        '{0}<control type="wraplabel" id="402">'
    ).format(indent, MARKER)

    new_content = (
        content[:m.start()] + replacement + content[m.end():]
    )

    # Sanity: did we end up with valid-looking XML? Cheap check:
    # opening/closing tag balance for <window>, <control>, etc.
    # If counts diverge, something went badly wrong; bail.
    def _tag_count(s, name):
        opens  = len(re.findall(r'<{0}[\s>]'.format(name), s))
        closes = len(re.findall(r'</{0}>'.format(name), s))
        return opens, closes
    for tag in ('window', 'controls', 'control'):
        o, c = _tag_count(new_content, tag)
        if o != c:
            kodi_utils.log(
                'fentastic_patcher: sanity check failed for <{0}> '
                '({1} open / {2} close), aborting write'.format(
                    tag, o, c),
                level='WARNING')
            return 'unmatched'

    if not _atomic_write(p, new_content):
        kodi_utils.log(
            'fentastic_patcher: write failed for {0}'.format(p),
            level='WARNING')
        return 'write_failed'

    kodi_utils.log(
        'fentastic_patcher: switched message control to wraplabel '
        'in {0} (v{1})'.format(p, INJECT_VERSION),
        level='INFO')
    return 'patched'


def ensure_unpatched():
    """Reverse the patch -- switch wraplabel back to fadelabel.
    For users who want the upstream behaviour back, or for safe
    cleanup when bumping INJECT_VERSION. Idempotent: if the marker
    isn't there, no write happens."""
    p = _xml_path()
    if not p or not os.path.isfile(p):
        return 'no_fentastic'
    try:
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return 'read_failed'
    if MARKER not in content:
        return 'no_change'
    # Strip the marker line AND swap wraplabel back to fadelabel.
    new_content = re.sub(
        r'[ \t]*' + re.escape(MARKER) + r'\s*\n', '', content)
    new_content = re.sub(
        r'<control[ \t]+type="wraplabel"[ \t]+id="402">',
        '<control type="fadelabel" id="402">',
        new_content,
    )
    if not _atomic_write(p, new_content):
        return 'write_failed'
    kodi_utils.log(
        'fentastic_patcher: reverted message control to fadelabel',
        level='INFO')
    return 'unpatched'
