# Idan Plus sends YouTube the word "watch" instead of a video id.
#
# THE REPORT: nothing from Kan 11 plays; a YouTube toast says "This video is
# unavailable". The log says why, and it is not YouTube refusing anything:
#
#     Params: {'video_id': 'watch'}
#     video_id: 'watch'   Client: 'tv_unplugged'    Reason: 'This video is unavailable'
#     video_id: 'watch'   Client: 'tv'              Reason: 'This video is unavailable'
#     video_id: 'watch'   Client: 'ios_testsuite_params'   ...
#     video_id: 'watch'   Client: 'android_testsuite_params'
#     video_id: 'watch'   Client: 'android_vr'
#
# Five player clients, five identical refusals, because there is no video whose
# id is "watch". YouTube answered correctly; the question was wrong.
#
# WHERE IT COMES FROM. resources/lib/common.py:
#
#     def GetYouTube(url):
#         if url.endswith('/'): url = url[:-1]
#         video_id = url[url.rfind('/')+1:]      # last PATH segment
#         if '?' in video_id:
#             video_id = video_id[:video_id.find('?')]
#         return '{0}/play/?video_id={1}'.format(youtubePlugin, video_id)
#
# It reads the id out of the PATH. That works for the two short forms and
# breaks on the ordinary one, where the id is a QUERY PARAMETER:
#
#     youtu.be/<ID>                 -> <ID>      ok
#     youtube.com/embed/<ID>        -> <ID>      ok
#     youtube.com/live/<ID>         -> <ID>      ok
#     youtube.com/watch?v=<ID>      -> 'watch'   <- the whole bug
#
# The truncation at '?' removes exactly the part that holds the answer. Kan
# evidently started handing out watch?v= links where it used to hand out embed
# ones, and nothing on the add-on side could read them.
#
# THE FIX is one line before the return: if the url carries a v= parameter,
# that is the id. Otherwise leave what was already computed alone.
#
# IT IS DELIBERATELY WRITTEN TO AGREE RATHER THAN TO OVERRIDE, and that is the
# property that makes it safe to leave in place:
#
#   * it only speaks when there is a `v=` to read, so every url the stock
#     function already got right comes out byte-identical -- measured across
#     youtu.be, /embed/, /live/, a trailing slash, and youtu.be with a ?t=
#     timestamp;
#   * and when it does speak, it returns the same id any correct
#     implementation would. So if Idan Plus ships its own fix and both end up
#     running, they cannot disagree.
#
# AND IT RETIRES ITSELF. Before anything else, _already_handles_v() looks at
# the function as it stands: if it has learned to read the query parameter, we
# report 'already_fixed' and touch nothing -- quietly, because that status is
# not one service.py warns about. Without that check, an upstream fix would
# leave this reporting 'unmatched' and logging a WARNING on every boot forever,
# which is how a patcher outlives its bug and becomes noise.
#
# VERSION NOTE. The function is byte-identical in the 3.9.1 the build ships and
# in the 4.0.2 the add-on self-updates to, so one anchor covers both. Checked
# rather than assumed: 4.0.2 was fetched from the Fishenzon repo and diffed.

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


IDANPLUS_ADDON_ID = 'plugin.video.idanplus'
COMMON_REL = 'resources/lib/common.py'

MARKER = '# AI_SUBS_IDAN_YT_ID_v1'
# Prefix, never an enumerated list of predecessors.
_MARKER_ANY = '# AI_SUBS_IDAN_YT_ID_v'

# The two lines we insert between. Anchored on the truncation AND the return,
# so a rewrite of either end is a shape we do not recognise rather than a
# guess.
_TRUNC = "\t\tvideo_id = video_id[:video_id.find('?')]\n"
_RETURN = ("\treturn '{0}/play/?video_id={1}'.format(youtubePlugin, "
           "video_id)\n")

# `re` is imported at the top of common.py (line 3) and used throughout, so the
# injected line needs nothing new in scope. The id charset is YouTube's own
# (alphanumeric, dash, underscore); the {6,} floor keeps a stray `v=1` style
# parameter from being mistaken for one.
_FIX = ("\tvideo_id = (re.findall(r'[?&]v=([0-9A-Za-z_-]{6,})', url) "
        "or [video_id])[0]  " + MARKER + "\n")


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('idanplus_youtube_id_patcher: ' + msg, level=level)
    except Exception:
        pass


def _fitter(content):
    eol = '\r\n' if '\r\n' in content else '\n'
    return (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t), eol


def _revert(content, eol='\n'):
    """Delete a previous version's injected block.

    A marked line plus everything indented strictly deeper below it. Ours is a
    single marked line and the line under it is the `return` at the same depth,
    so the walk stops at once.
    """
    lines = content.split(eol)
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if _MARKER_ANY not in line:
            out.append(line)
            i += 1
            continue
        base = len(line) - len(line.lstrip())
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip():
                if (len(nxt) - len(nxt.lstrip())) <= base:
                    break
                i += 1
                continue
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if (j >= len(lines)
                    or (len(lines[j]) - len(lines[j].lstrip())) <= base):
                break
            i = j
    return eol.join(out)


def _idan_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + IDANPLUS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _function_body(content):
    """GetYouTube as it currently stands, or '' if it is not there."""
    try:
        start = content.index('def GetYouTube(url):')
    except ValueError:
        return ''
    rest = content[start + 1:]
    nxt = rest.find('\ndef ')
    return content[start:start + 1 + nxt] if nxt != -1 else content[start:]


def _already_handles_v(body):
    """True when the function reads the id out of the query string itself.

    Ours is not the only possible fix, so this asks about the BEHAVIOUR the
    fix provides rather than looking for our marker: any implementation that
    mentions the `v` parameter or parses the query is doing the job, and we
    should stand down rather than add a second opinion.
    """
    if MARKER in body or _MARKER_ANY in body:
        return False        # that is us, not them
    return bool(re.search(r"v=|parse_qs|query", body))


def ensure_patched():
    """Idempotent. Never raises. Returns 'no_idanplus' | 'no_file' |
    'no_function' | 'already_fixed' | 'unchanged' | 'patched' | 'repatched' |
    'unmatched' | 'read_failed' | 'write_failed' | 'compile_failed' |
    'revert_failed'."""
    if xbmcvfs is None:
        return 'no_idanplus'
    path = _idan_path(COMMON_REL)
    if not path:
        return 'no_file'

    try:
        with open(path, encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    fit, eol = _fitter(content)

    if MARKER in content:
        return 'unchanged'

    body = _function_body(content)
    if not body:
        _log('GetYouTube is not in this version of common.py; leaving it alone',
             level='WARNING')
        return 'no_function'

    # BEFORE the anchor check, so an upstream fix retires us quietly instead of
    # reporting a shape we do not recognise every boot.
    if _already_handles_v(body):
        _log('Idan Plus reads the v= parameter itself now; standing down')
        return 'already_fixed'

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content, eol)
        repatch = True
        if _MARKER_ANY in content:
            _log('could not remove an older injection', level='WARNING')
            return 'revert_failed'

    anchor = fit(_TRUNC + _RETURN)
    if content.count(anchor) != 1:
        _log('GetYouTube does not have the expected shape -- Idan Plus may '
             'have refactored it; leaving the file alone', level='WARNING')
        return 'unmatched'

    new_content = content.replace(
        anchor, fit(_TRUNC + _FIX + _RETURN), 1)

    try:
        # lstrip the BOM for the check only -- see the note in
        # pov_debrid_unbound_guard_patcher; a leading U+FEFF is fine for
        # import and fatal for compile().
        compile(new_content.lstrip('﻿'), path, 'exec')
    except SyntaxError as e:
        _log('compile check failed, not writing: {0}'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    pycache = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache):
        for fn in os.listdir(pycache):
            if fn.startswith('common.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass

    _log('Kan 11 YouTube links resolve again: the id is read from the v= '
         'parameter instead of the path')
    return 'repatched' if repatch else 'patched'
