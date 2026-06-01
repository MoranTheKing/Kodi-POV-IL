# Self-healing patch of DarkSubs's sub_window.py so the subtitle
# picker's per-row height is tall enough for long release names
# to display without getting clipped mid-wrap.
#
# Why this patcher exists:
#   DarkSubs's MySubs dialog is a pyxbmct.AddonDialogWindow with a
#   pyxbmct.List() control populated by `addItems(strings)` -- it is
#   NOT skin XML. PR #157 wrote an XML patcher targeting
#   resources/skins/Default/ but DarkSubs ships no skins folder at
#   all, so #157 ended up a no-op. The actual fix lives one bytecode
#   removed: pyxbmct.List() defaults to _itemHeight=27 which fits
#   one line of text. Long release names like
#   "The.Super.Mario.Galaxy.Movie.2026.1080p.WEB-RIP.x265.10Bit.HEVC.
#    Eng.DD.5.1+Sub.ViTO" wrap onto a second line that the 27-pixel
#   row clips, hiding the release group at the end.
#
#   Bumping _itemHeight to 60 doubles the row so two wrapped lines
#   fit cleanly. Side effect: ~2x fewer rows visible at once in the
#   picker. Acceptable -- the user can scroll, and seeing the FULL
#   release name is the whole point.
#
# Strategy:
#   1. Resolve sub_window.py at runtime via special://home/addons/.
#   2. Regex-find the `self.list = pyxbmct.List()` line. Allow
#      tolerant whitespace inside the parens / around the equals
#      sign so a DarkSubs update with cosmetic-only changes still
#      matches.
#   3. Rewrite to `self.list = pyxbmct.List(_itemHeight=60)` with a
#      trailing marker comment so the next run sees it and bails.
#   4. Invalidate the .pyc cache so reuselanguageinvoker picks up
#      the new bytecode on next import (same pattern as the other
#      darksubs_*_patcher modules).
#   5. Atomic write (tmp + os.replace) so a crash leaves the file
#      untouched.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
SUB_WINDOW_REL_PATH = 'resources/modules/sub_window.py'

MARKER = '# AI_SUBS_DARKSUBS_PICKER_ITEM_HEIGHT_v1'

# Target per-row height in pixels. pyxbmct.List default is 27 (fits
# one line). 60 fits the wrapped two-line layout DarkSubs uses for
# long release names. Reduces visible rows in the picker by roughly
# half -- acceptable trade-off for the full filename being readable.
ITEM_HEIGHT_PX = 60

# Match `self.list = pyxbmct.List()` with tolerant whitespace inside
# the parens and around the assignment. Anchored per-line. The match
# captures the indent so the rewrite preserves it. Refuse to touch
# a call that already has arguments (the user / a future DarkSubs
# update may have set something we'd overwrite).
_LIST_CALL_RE = re.compile(
    rb'^(?P<indent>[ \t]*)self\.list[ \t]*=[ \t]*'
    rb'pyxbmct\.List\([ \t]*\)[ \t]*(?P<eol>\r?\n|$)',
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log(
            'darksubs_picker_height_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sub_window_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SUB_WINDOW_REL_PATH)
    return p if os.path.isfile(p) else ''


def _invalidate_pyc_cache(py_path):
    """Wipe stale sub_window.cpython-*.pyc so DarkSubs re-compiles
    on next import. Same logic as the other darksubs_* patchers --
    duplicated intentionally to keep this module self-contained."""
    try:
        pkg_dir = os.path.dirname(py_path)
        base = os.path.splitext(os.path.basename(py_path))[0]
        cache_dir = os.path.join(pkg_dir, '__pycache__')
        if not os.path.isdir(cache_dir):
            return
        prefix = base + '.cpython-'
        for fname in os.listdir(cache_dir):
            if fname.startswith(prefix) and fname.endswith('.pyc'):
                try:
                    os.remove(os.path.join(cache_dir, fname))
                except OSError:
                    pass
    except Exception:
        pass


def ensure_patched():
    """Find sub_window.py and bump the pyxbmct.List item height so
    wrapped release names don't get clipped. Idempotent (returns
    'already_patched' on re-run). Returns one of: 'no_darksubs' |
    'patched' | 'already_patched' | 'unmatched' | 'read_failed' |
    'write_failed'."""
    path = _sub_window_path()
    if not path:
        return 'no_darksubs'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    matches = list(_LIST_CALL_RE.finditer(content))
    if len(matches) == 0:
        _log('self.list = pyxbmct.List() not found -- DarkSubs may '
             'have refactored sub_window.py', level='WARNING')
        return 'unmatched'
    if len(matches) > 1:
        _log('matched {0} candidate sites -- refusing to rewrite '
             'ambiguously'.format(len(matches)), level='WARNING')
        return 'unmatched'

    m = matches[0]
    rewrite = (
        m.group('indent')
        + b'self.list = pyxbmct.List(_itemHeight='
        + str(ITEM_HEIGHT_PX).encode('ascii')
        + b')  ' + MARKER.encode('utf-8')
        + m.group('eol')
    )
    new_content = content[:m.start()] + rewrite + content[m.end():]

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _invalidate_pyc_cache(path)
    _log('bumped pyxbmct.List _itemHeight to {0} so wrapped release '
         'names display fully'.format(ITEM_HEIGHT_PX), level='INFO')
    return 'patched'
