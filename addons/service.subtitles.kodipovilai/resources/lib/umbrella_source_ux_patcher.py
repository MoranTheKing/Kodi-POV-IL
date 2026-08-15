# Two small repairs to Umbrella's source-selection flow.
#
# 1. PREWARM -- the Hebrew match badge on the FIRST entry, not the second.
#
#    he_sub_match's background warm is what fills the badge for titles whose
#    Hebrew subs are not already in the community pool. Left to itself it only
#    starts when the source WINDOW is built, i.e. after the scrape has already
#    finished -- so it is still running when the window opens and the % only
#    appears on the second or third entry to a title. POV has had the fix for
#    a while (pov_prewarm_patcher): fire the warm at the START of the scrape
#    so it runs CONCURRENTLY with it, and the cache is ready by the time the
#    window opens. This is the same fix for Umbrella. Same one warm per title,
#    no extra reads, no added stall -- it is fire-and-forget.
#
# 2. QUIET CANCEL -- backing out of the source list is not a playback failure.
#
#    Open a title, look at the sources, decide against it, press Back: Kodi
#    puts up "Playback failed". The cause is in Umbrella's own cancel branch,
#    and so is the cure -- it already has the right code, gated behind
#    `enable_playnext`:
#
#        if self.enable_playnext:
#            # Resolving with False triggers "Playback Failed". Resolve with
#            # True + empty offscreen item instead so no error dialog appears.
#            ... control.resolve(int(argv[1]), True, control.item(offscreen=True))
#        else:
#            control.cancelPlayback()          <-- this is the error dialog
#
#    Its own comment states the fix. We simply take the quiet path whichever
#    way that setting is set, because a user who backed out on purpose has not
#    experienced a failure. The `except:` handler's cancelPlayback is left
#    alone on purpose: that one IS a real error and should still say so.
#
# Both edits are marker-gated, compile()-checked before writing, atomic, and
# revertible. No-op when Umbrella is not installed.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
SOURCES_REL_PATH = 'resources/lib/modules/sources.py'

PREWARM_MARKER = 'AI_SUBS_UMB_PREWARM_v1'
CANCEL_MARKER = 'AI_SUBS_UMB_QUIETCANCEL_v1'

# The interactive scrape's entry point. Unique: one def in the file.
_DIALOG_RE = re.compile(
    r'^(?P<indent>[ \t]*)def getSources_dialog\(self, title, year, imdb, '
    r'tvdb, season, episode, tvshowtitle, premiered, timeout=90\):'
    r'[ \t]*(?P<cr>\r?)$\n(?P<try_indent>[ \t]*)try:[ \t]*(?=\r?$)',
    re.MULTILINE,
)
_PREWARM_REVERT_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_UMB_PREWARM_v\d+[ \t]*\r?\n"
    r"(?:(?!#[ \t]*(?:END[ \t]+)?AI_SUBS_UMB_PREWARM_v)[\s\S])*?"
    r"[ \t]*#[ \t]*END[ \t]+AI_SUBS_UMB_PREWARM_v\d+[ \t]*\r?\n"
)

# The user-cancelled branch. Pinned to the `else:` that follows the
# enable_playnext block, via the line that is unique to it.
_CANCEL_RE = re.compile(
    r'^(?P<indent>[ \t]*)else:[ \t]*\r?\n'
    r'(?P<bind>[ \t]*)control\.cancelPlayback\(\)[ \t]*(?=(?P<cr>\r?)$)',
    re.MULTILINE,
)
_CANCEL_REVERT_RE = re.compile(
    r'^(?P<indent>[ \t]*)else:[ \t]*(?P<eol>\r?\n)'
    r'[ \t]*#[ \t]*AI_SUBS_UMB_QUIETCANCEL_v\d+[ \t]*\r?\n'
    r'(?:(?!#[ \t]*AI_SUBS_UMB_QUIETCANCEL_v)[\s\S])*?'
    r'[ \t]*#[ \t]*END[ \t]+AI_SUBS_UMB_QUIETCANCEL_v\d+[ \t]*\r?\n',
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_source_ux_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SOURCES_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _prewarm_lines(indent, eol):
    """Fire-and-forget: every failure mode ends in `pass`, because a warm that
    cannot start must never stop a scrape the user is waiting for."""
    raw = [
        '# ' + PREWARM_MARKER,
        'try:',
        '\timport sys as _pw_s, xbmcvfs as _pw_v',
        "\t_pw_p = _pw_v.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')",
        '\tif _pw_p not in _pw_s.path: _pw_s.path.append(_pw_p)',
        '\timport he_sub_match as _pw_m; _pw_m.prewarm(self.meta)',
        'except Exception:',
        '\tpass',
        '# END ' + PREWARM_MARKER,
    ]
    return ''.join(indent + ln + eol for ln in raw)


def _cancel_lines(indent, eol):
    """Umbrella's own quiet-resolve, lifted out from behind enable_playnext."""
    raw = [
        '# ' + CANCEL_MARKER,
        '# Backing out of the source list is a choice, not a failure. This is',
        "# Umbrella's own no-error path, taken whatever enable_playnext says.",
        'control.playlist.clear()',
        'try: control.player.stop()',
        'except: pass',
        'try:',
        '\tfrom sys import argv as _qc_argv',
        '\tcontrol.resolve(int(_qc_argv[1]), True, control.item(offscreen=True))',
        '\tcontrol.closeOk()',
        'except Exception:',
        '\tcontrol.cancelPlayback()',
        '# END ' + CANCEL_MARKER,
    ]
    return ''.join(indent + ln + eol for ln in raw)


def revert(content):
    """`content` with both edits removed, restoring upstream byte for byte."""
    out = _PREWARM_REVERT_RE.sub('', content)
    return _CANCEL_REVERT_RE.sub(
        lambda m: m.group('indent') + 'else:' + m.group('eol')
        + m.group('indent') + '\tcontrol.cancelPlayback()' + m.group('eol'),
        out)


def ensure_patched():
    """Returns 'no_file' | 'read_failed' | 'unmatched' | 'compile_failed'
    | 'unchanged' | 'patched' | 'write_failed'."""
    path = _sources_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    content = revert(original)

    # 1) prewarm, straight after `try:` at the top of getSources_dialog.
    m = _DIALOG_RE.search(content)
    if not m:
        _log('getSources_dialog anchor not found -- skipping', level='WARNING')
        return 'unmatched'
    eol = '\r\n' if m.group('cr') else '\n'
    body_indent = m.group('try_indent') + '\t'
    content = (content[:m.end()] + eol
               + _prewarm_lines(body_indent, eol).rstrip(eol)
               + content[m.end():])

    # 2) the quiet cancel. Searched AFTER the prewarm insert so the offsets
    #    below are against the current text, not a stale copy.
    c = _CANCEL_RE.search(content)
    if not c:
        _log('cancel branch not found -- prewarm only', level='WARNING')
    else:
        ceol = '\r\n' if c.group('cr') else '\n'
        replacement = (c.group('indent') + 'else:' + ceol
                       + _cancel_lines(c.group('bind'), ceol).rstrip(ceol))
        content = content[:c.start()] + replacement + content[c.end():]

    try:
        compile(content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'
    if content == original:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
    _log('prewarm + quiet cancel injected into Umbrella sources', level='INFO')
    return 'patched'
