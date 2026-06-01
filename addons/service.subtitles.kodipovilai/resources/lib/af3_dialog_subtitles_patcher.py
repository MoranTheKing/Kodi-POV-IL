# Self-healing patch of Arctic Fuse 3's Dialog_DialogSubtitles.xml so
# the subtitle picker dialog HEADER prefers our `Window(10000).Property(
# subs.player_filename)` window property (set by POV's source picker
# AND/OR our own SubsFilenamePublisher player monitor) over the
# built-in `Player.FileName`.
#
# Why this is a separate patcher from skin_dialog_subtitles_patcher:
#   The generic skin patcher matches `<control type="label">…$INFO[
#   Player.Filename]…</control>` in a skin's DialogSubtitles.xml.
#   AF3's wrapper DialogSubtitles.xml is just 8 lines that include a
#   named `DialogSubtitles` template -- the actual layout (and the
#   `$INFO[Player.FileName]` reference) lives in a SEPARATE file,
#   `Dialog_DialogSubtitles.xml`, inside a `<param name="label">…</param>`
#   of an include block. Completely different shape; the generic
#   regex bails with 'no_target'.
#
# What we patch in AF3:
#   1. Inject a `<variable name="ai_subs_header_label">` at the top of
#      the `<includes>` root with conditional fallback semantics:
#        - if our window property is set, use it
#        - otherwise fall back to Player.FileName
#      Kodi's `<variable>` element supports condition-gated values
#      natively, so we get clean fallback behaviour without needing
#      two separate controls.
#   2. Swap `<param name="label">$INFO[Player.FileName]</param>` to
#      `<param name="label">$VAR[ai_subs_header_label]</param>`.
#
# Both edits in the same file (Dialog_DialogSubtitles.xml). Atomic
# write, marker-gated, self-heals on every Kodi startup.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


AF3_ADDON_ID = 'skin.arctic.fuse.3'
DIALOG_SUBS_REL_PATH = '1080i/Dialog_DialogSubtitles.xml'

MARKER = '<!-- AI_SUBS_AF3_HEADER_v1 -->'

# Variable definition we inject. Conditional fallback: our window
# property takes priority when set; otherwise Player.FileName -- so
# users who play through POV (or any flow that sets the property
# via SubsFilenamePublisher) get the release name in the header,
# and direct file playback still shows something sensible.
_VARIABLE_DEF = (
    '\n    ' + MARKER + '\n'
    '    <variable name="ai_subs_header_label">\n'
    '        <value condition="!String.IsEmpty(Window(10000)'
    '.Property(subs.player_filename))">'
    '$INFO[Window(10000).Property(subs.player_filename)]</value>\n'
    '        <value>$INFO[Player.FileName]</value>\n'
    '    </variable>\n'
)

# Match the existing param line (with tolerant whitespace) so we
# can swap it. Anchored per-line; captures indentation so the
# replacement preserves it.
_PARAM_LABEL_RE = re.compile(
    rb'^(?P<indent>[ \t]*)<param[ \t]+name="label">[ \t]*'
    rb'\$INFO\[Player\.FileName\][ \t]*</param>[ \t]*'
    rb'(?P<eol>\r?\n|$)',
    re.MULTILINE,
)

# Match the opening <includes> tag so we can inject the variable
# definition immediately after it.
_INCLUDES_OPEN_RE = re.compile(rb'<includes>\s*\n')


def _log(msg, level='INFO'):
    try:
        kodi_utils.log(
            'af3_dialog_subtitles_patcher: ' + msg, level=level)
    except Exception:
        pass


def _dialog_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + AF3_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, DIALOG_SUBS_REL_PATH)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Inject the conditional header variable + swap the Player.FileName
    reference. Idempotent. Returns one of: 'no_af3' | 'no_file' |
    'already_patched' | 'patched' | 'unmatched' | 'read_failed' |
    'write_failed'."""
    path = _dialog_path()
    if not path:
        # AF3 either isn't installed yet (user hasn't switched to it)
        # or its directory structure changed. Either way -- nothing
        # to do this run; we'll try again next startup.
        return 'no_file'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    # Find the single param-label line we're rewriting. Require
    # exactly one match -- 0 means AF3 refactored the file, >1 means
    # ambiguity.
    matches = list(_PARAM_LABEL_RE.finditer(content))
    if len(matches) != 1:
        _log('expected exactly 1 match of $INFO[Player.FileName] in '
             'param-label form, got {0} -- AF3 may have refactored '
             'Dialog_DialogSubtitles.xml; leaving file alone'.format(
                 len(matches)), level='WARNING')
        return 'unmatched'

    # Step 1: inject the variable definition right after <includes>.
    include_open = _INCLUDES_OPEN_RE.search(content)
    if not include_open:
        _log('no <includes> opening tag in Dialog_DialogSubtitles.xml '
             '-- file structure unrecognised', level='WARNING')
        return 'unmatched'
    inject_pos = include_open.end()
    content = (content[:inject_pos]
               + _VARIABLE_DEF.encode('utf-8')
               + content[inject_pos:])

    # Step 2: swap the param-label. Re-find since the variable
    # injection shifted offsets.
    matches = list(_PARAM_LABEL_RE.finditer(content))
    if len(matches) != 1:
        # Should not happen unless something extraordinarily weird
        # happened between the two passes.
        _log('post-inject re-scan no longer matches exactly once '
             '({0}) -- aborting'.format(len(matches)),
             level='WARNING')
        return 'unmatched'
    m = matches[0]
    rewrite = (m.group('indent')
               + b'<param name="label">$VAR[ai_subs_header_label]'
               b'</param>'
               + m.group('eol'))
    content = content[:m.start()] + rewrite + content[m.end():]

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'write_failed'
    _log('patched AF3 Dialog_DialogSubtitles.xml header label to use '
         'subs.player_filename window property with fallback to '
         'Player.FileName', level='INFO')
    return 'patched'
