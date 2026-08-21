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
# The truncation at '?' removes exactly the part that holds the answer.
#
# AND THE ADD-ON BUILDS THAT URL ITSELF, which is the part worth understanding
# before touching this. Kan does not hand out links at all. Its mobile API
# returns a BARE ID:
#
#     GET https://mobapi.kan.org.il/api/mobile/program?id=1073649
#     entry[3]: id=1073666  content.type='youtube-id'  content.src='oRFeZUO5GVw'
#
# and kan.py's _mobStreamFromEntry wraps it:
#
#     if ctype == 'youtube-id' and src:
#         return 'youtube', 'https://www.youtube.com/watch?v={0}'.format(src)
#
# then hands that to GetYouTube, which unwraps it back to 'watch'. The add-on
# starts with a perfectly good id, constructs a URL around it, and then fails
# to parse its own construction. A round trip that destroys the data.
#
# SO THIS IS NOT A REGRESSION AND NOT SOMETHING KAN CHANGED. Every Kan item of
# type 'youtube-id' has always failed and always will until this is fixed --
# verified against the live API: all five episodes of that program resolve to
# 'watch' on stock and to their real ids once patched. (The trailer in the same
# program is type 'video/hls' and goes down a different path entirely, which is
# why one item in a list can play while the rest cannot.)
#
# An earlier version of this comment blamed Kan for moving from embed links to
# watch links. That was wrong, and the owner caught it by pointing at a working
# youtu.be link and asking why it did not match the diagnosis. The fix was
# right; the story was not.
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
# AND WHEN IDAN PLUS FIXES IT, THIS STOPS AND SAYS SO. The anchor is the stock
# buggy body byte-for-byte: if it matches, the bug is verbatim present and we
# patch; if it does not, the function has changed and nothing is touched. See
# the long note above ensure_patched for the two mechanisms that tried to
# decide WHY it changed, and why neither survived review.
#
# VERSION NOTE. The function is byte-identical in the 3.9.1 the build ships and
# in the 4.0.2 the add-on self-updates to, so one anchor covers both. Checked
# rather than assumed: 4.0.2 was fetched from the Fishenzon repo and diffed.

import os

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
# injected line needs nothing new in scope -- and THIS module does not import
# it at all, because the regex below is text we write into somebody else's
# file, never a pattern we compile here. The id charset is YouTube's own
# (alphanumeric, dash, underscore); the {6,} floor keeps a stray `v=1` style
# parameter from being mistaken for one.
#
# GATED ON "what stock extracted cannot be a YouTube id". A review broke the
# ungated version in one line: `youtu.be/<ID>?v=<OTHER>` has a real id in the
# PATH and a stray v= in the query, and scanning the whole url took the wrong
# one -- changing an answer stock had got right, the one thing this must never
# do.
#
# The first gate was `== 'watch'`, the literal signature of the report, and a
# second round found that too narrow: `watch/?v=<ID>` leaves stock with an
# EMPTY string and `Watch?v=<ID>` leaves it 'Watch' -- both still broken,
# neither equal to 'watch'.
#
# An eleven-character id from YouTube's own charset is the test, because that
# is what success looks like and anything else is failure by definition. The
# line fires exactly when stock produced something that cannot be an id, and
# so can never touch a url stock resolved correctly.
_FIX = ("\tif not re.match(r'^[0-9A-Za-z_-]{11}$', video_id or ''): "
        "video_id = (re.findall(r'[?&]v=([0-9A-Za-z_-]{11})', url) "
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


# THERE WAS A "RETIRE YOURSELF" CHECK HERE. TWO OF THEM. BOTH WERE WRONG.
#
# Round 1: it read the function text for `v=|parse_qs|query`. A comment saying
# "query the path", or a variable called search_query, made that true -- so a
# still-broken version would be left broken and reported 'already_fixed', a
# status service.py deliberately does not warn about. Silently.
#
# Round 2: the replacement EXECUTED the candidate function instead. That
# answered the question honestly and bought a blast radius to do it. The slice
# handed to exec ran from `def GetYouTube` to the next top-level `def`, and on
# the real 4.0.2 tree that gap ALREADY holds a module-level statement
# (`_cfSession = {...}`) -- so anything sitting there would run at OUR startup,
# unconditionally, before the function was even called. And `except Exception`
# does not catch SystemExit: a `sys.exit()` in that body escaped this function,
# escaped ensure_patched, escaped service.py's step wrapper, and aborted the
# whole startup-repair pass. Idan Plus declares reuselanguageinvoker, so its
# own crashes stay in its own interpreter; running its code inside ours handed
# it ours.
#
# THE ANCHOR ALREADY ANSWERS THE USEFUL HALF. It is the stock buggy body,
# byte-for-byte. Matching means the bug is verbatim present. Not matching means
# the function changed, and no honest cheap test tells us whether it was fixed,
# refactored, or broken differently -- so we touch nothing and say so once, in
# the log, exactly like every other patcher in this tree.
#
# That costs a WARNING line per boot on a device whose Idan Plus has moved on.
# That is not a problem for the user; it is the signal to retire this file. It
# is worth more than a clever mechanism that has now been wrong twice, once in
# the direction of failing silently and once in the direction of running
# somebody else's code in our process.


def ensure_patched():
    """Idempotent. Never raises. Returns 'no_idanplus' | 'no_file' |
    'unchanged' | 'patched' | 'repatched' | 'unmatched' | 'read_failed' |
    'write_failed' | 'compile_failed' | 'revert_failed'."""
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

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content, eol)
        repatch = True
        if _MARKER_ANY in content:
            _log('could not remove an older injection', level='WARNING')
            return 'revert_failed'

    anchor = fit(_TRUNC + _RETURN)
    if content.count(anchor) != 1:
        _log('GetYouTube no longer has the shape this fix was written for; '
             'nothing was changed. If Idan Plus has fixed the v= parsing '
             'itself then this patcher has done its job and should be '
             'retired; if not, it needs a new anchor.', level='WARNING')
        return 'unmatched'

    new_content = content.replace(
        anchor, fit(_TRUNC + _FIX + _RETURN), 1)

    try:
        # lstrip the BOM for the check only -- see the note in
        # pov_debrid_unbound_guard_patcher; a leading U+FEFF is fine for
        # import and fatal for compile().
        compile(new_content.lstrip('\ufeff'), path, 'exec')
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
