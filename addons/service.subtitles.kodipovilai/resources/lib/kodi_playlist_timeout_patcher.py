# "הניגון נכשל" after backing out of a source list, without having tried to
# play anything.
#
# This is not the add-on's dialog and not a failed stream. It is Kodi's, and
# the trigger is a CLOCK, not an error. From Kodi 21.3's PlayListPlayer.cpp,
# every time a plugin is asked to play and does not hand back a playable path:
#
#     m_iFailedSongs++;
#     if ((m_iFailedSongs >= m_playlistRetries && m_playlistRetries >= 0) ||
#         ((duration.count() >= m_playlistTimeout * 1000) && m_playlistTimeout))
#     {
#         ... HELPERS::ShowOKDialogText(CVariant{16026}, CVariant{16027});
#         m_iFailedSongs = 0;                    <- and the streak restarts
#     }
#     else if (playlist.GetPlayable() > 0) ...   <- silent
#     else  "no more playable items"             <- also silent
#
# `duration` is measured from the start of the FIRST failed play in the
# current run, and the run is only cleared by this dialog or by a playback
# that actually succeeds. `playlisttimeout` defaults to 20 seconds.
#
# Backing out of a source list is one of these "failures": the add-on has to
# resolve something, and there is nothing to resolve. So the dialog appears
# whenever a user has been browsing sources for more than 20 seconds without
# playing anything -- and then does NOT appear on the next few back-outs,
# because the dialog itself reset the clock. That is the whole of the "only
# the first time" pattern. Verified against a field log; all five failures in
# it are predicted exactly:
#
#     3.74s silent | 14.56s silent | 45.33s DIALOG | 2.61s silent | 20.31s DIALOG
#
# It cannot be fixed from inside the add-on. Umbrella already takes its own
# quietest exit -- resolve(True) with an empty offscreen item -- and Kodi
# still counts it, because an item with no path is not playable no matter
# what the resolve said. The counter lives in Kodi and nothing exposes it.
#
# So the fix is the setting that drives the clock. `playlisttimeout` 0
# disables the timed branch (`&& m_playlistTimeout` is false at 0), leaving
# `playlistretries` -- untouched at its default 100 -- to still stop a
# genuinely runaway playlist, with the dialog.
#
# What this gives up is worth stating plainly: a real playback failure that
# takes more than 20 seconds to fail will now abort quietly instead of
# raising Kodi's dialog. That is a smaller loss than it sounds, because the
# dialog was never a report that THIS playback failed -- the same failure is
# already silent today if it happens quickly. It says "you have been failing
# for 20 seconds", which is why a deliberate back-out triggers it at all.
# Both POV and Umbrella raise their own messages when a source genuinely
# fails, and those are unaffected.
#
# The write merges: anything already in advancedsettings.xml is preserved
# byte for byte, and an explicit <playlisttimeout> that is already there is
# left alone, because that is someone stating a preference. Kodi reads this
# file once at startup, so the change takes effect from the next start.

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


MARKER = 'AI_SUBS_PLAYLIST_TIMEOUT_v1'
SETTING = 'playlisttimeout'

_ROOT_OPEN_RE = re.compile(r'<advancedsettings[^>]*>')
_REVERT_RE = re.compile(
    r'[ \t]*<!--[ \t]*' + MARKER + r'[ \t]*-->[ \t]*\r?\n'
    r'[ \t]*<' + SETTING + r'>[^<]*</' + SETTING + r'>[ \t]*\r?\n')

_DEFAULT_FILE = (
    '<advancedsettings>\n'
    '  <!-- ' + MARKER + ' -->\n'
    '  <' + SETTING + '>0</' + SETTING + '>\n'
    '</advancedsettings>\n')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('kodi_playlist_timeout_patcher: ' + msg, level=level)
    except Exception:
        pass


def _path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://profile/')
    except Exception:
        return ''
    if not base:
        return ''
    return os.path.join(base, 'advancedsettings.xml')


def _root(text):
    """The parsed <advancedsettings> root, or None if this is not one."""
    try:
        from xml.etree import ElementTree
        r = ElementTree.fromstring(text)
    except Exception:
        return None
    return r if r.tag == 'advancedsettings' else None


def _valid_xml(text):
    return _root(text) is not None


def _already_declared(root):
    """Whether the file already states a <playlisttimeout>.

    Asked of the PARSED tree, never of the raw text. advancedsettings.xml is
    conventionally full of commented-out examples, and a substring scan reads
    `<!-- <playlisttimeout>20</playlisttimeout> -->` as a setting -- which
    would make this patcher answer 'already_set' on every boot forever and
    never apply the fix. That is the same "reports success, changes nothing"
    failure this whole change exists to close. Parsing also gets the cases a
    `<tag\\s*>` regex misses for the opposite reason: `<playlisttimeout />`
    and `<playlisttimeout unit="s">10</playlisttimeout>` are real settings,
    and injecting a second one ahead of them would silently override a value
    this module promises to leave alone."""
    return root.find(SETTING) is not None


def revert(content):
    """`content` with our two lines removed."""
    return _REVERT_RE.sub('', content)


def ensure_patched():
    """Returns 'no_profile' | 'created' | 'already_set' | 'patched'
    | 'unchanged' | 'unmatched' | 'bad_xml' | 'read_failed' | 'write_failed'.
    Never raises."""
    path = _path()
    if not path:
        return 'no_profile'

    if not os.path.isfile(path):
        return _write(path, _DEFAULT_FILE, 'created')

    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    content = revert(original)

    root = _root(content)
    if root is None:
        _log('not a parseable <advancedsettings> file -- leaving it alone',
             level='WARNING')
        return 'unmatched'

    # Someone -- the base build, the user, another tool -- has already stated
    # a value. Theirs wins; we are not here to overrule a deliberate choice.
    if _already_declared(root):
        return 'already_set'

    m = _ROOT_OPEN_RE.search(content)
    if not m:
        _log('no <advancedsettings> root found -- leaving the file alone',
             level='WARNING')
        return 'unmatched'

    # Take the newline style from the break right after the root tag, not
    # from a sample of the head: that is the exact spot being spliced.
    em = re.search(r'\r?\n', content[m.end():])
    eol = em.group(0) if em else '\n'
    # Match the indentation the file already uses for its own children.
    indent = '  '
    im = re.search(r'\r?\n([ \t]+)<', content[m.end():])
    if im:
        indent = im.group(1)
    block = (eol + indent + '<!-- ' + MARKER + ' -->'
             + eol + indent + '<' + SETTING + '>0</' + SETTING + '>')
    content = content[:m.end()] + block + content[m.end():]

    if not _valid_xml(content):
        _log('patched advancedsettings.xml would not parse -- skipping',
             level='WARNING')
        return 'bad_xml'
    if content == original:
        return 'unchanged'
    return _write(path, content, 'patched')


def _write(path, content, ok_status):
    tmp = path + '.aitmp'
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
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
    _log('playlisttimeout set to 0; Kodi will stop raising "playback failed" '
         'after a cancelled source pick from the next start', level='INFO')
    return ok_status
