# Generic patcher for ANY skin's DialogSubtitles.xml so the dialog
# header reads our `Window(10000).Property(subs.player_filename)`
# instead of (or as a fallback to) `Player.Filename`.
#
# Problem we're solving:
#   The subtitle picker shows the playing-file name at the top of the
#   dialog via `$INFO[Player.Filename]` in the SKIN's
#   DialogSubtitles.xml. Player.Filename is computed by Kodi from the
#   URL of the playing item -- and for TorBox playbacks the URL is
#   just a UUID hash, so the user sees gibberish instead of the
#   release name. Our subs_filename_publisher already writes the real
#   release name to `subs.player_filename`, and DarkSubs reads that
#   property natively for matching -- but the HEADER label is
#   skin-side, so we have to patch the skin XML.
#
# Why generic (vs the FENtastic-only patcher):
#   Users install on whatever skin they like -- Arctic Zephyr,
#   Estuary, Aeon Nox, etc. Each skin has its own DialogSubtitles.xml
#   structure but they all share the `$INFO[Player.Filename]` idiom.
#   Detecting the active skin and patching its XML in place covers
#   every user without needing per-skin patcher modules.
#
# Strategy:
#   1. Resolve the active skin via xbmc.getSkinDir().
#   2. Find DialogSubtitles.xml in the skin's xml/ directory (or
#      720p/ -- some older skins use that).
#   3. Regex-find `<control type="label">...$INFO[Player.Filename]...</control>`
#      (whole element including surrounding tabs / spaces).
#   4. Replace it with the SAME element TWICE, each with a
#      mutually-exclusive `<visible>` gate -- first reads
#      `subs.player_filename`, second falls back to Player.Filename.
#   5. Self-healing: re-applies on every Kodi startup so a skin
#      update can't permanently revert it.

import os
import re

try:
    import xbmc
    import xbmcvfs
except Exception:
    xbmc = None
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


MARKER = '<!-- AI_SUBS_DIALOG_HEADER_v2 -->'

# v1 marker (the FENtastic-only patcher's marker) -- we strip the
# v1 inject before applying v2 so users upgrading from the
# FENtastic-specific patch get the new dual-visibility pair.
OLD_MARKERS = ('<!-- AI_SUBS_DIALOG_HEADER_v1 -->',)

# Regex: find an entire <control type="label">...</control> element
# whose body mentions $INFO[Player.Filename] (or .FileName -- skins
# differ on the capitalisation of the N). DOTALL + non-greedy so we
# capture exactly the smallest enclosing <control>. Case-insensitive
# on the info-label because skins vary on capitalisation.
_LABEL_CONTROL_RE = re.compile(
    r'(?P<indent>[ \t]*)<control\s+type="label"[^>]*>'
    r'(?:(?!</control>).)*?'
    r'\$INFO\[Player\.File[Nn]ame\]'
    r'(?:(?!</control>).)*?</control>',
    re.DOTALL,
)

# Matches just the Player.Filename info-label so we can swap it out
# inside the captured control element without rewriting the whole
# string. Case-insensitive for the same reason as above.
_PLAYER_FILENAME_RE = re.compile(
    r'\$INFO\[Player\.File[Nn]ame\]')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('skin_dialog_subtitles_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _current_skin_id():
    """Returns the addon-ID of the currently-active skin, e.g.
    'skin.fentastic', 'skin.arctic.zephyr.2'. Empty if unavailable."""
    if xbmc is None:
        return ''
    try:
        return xbmc.getSkinDir() or ''
    except Exception:
        return ''


def _dialog_path(skin_id):
    """Try the two common locations for DialogSubtitles.xml in a
    skin tree: xml/ (Kodi 18+ skins) and 720p/ (older skins).
    Returns the first existing path or ''."""
    if not skin_id or xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + skin_id + '/')
    except Exception:
        return ''
    for sub in ('xml', '720p', '1080i'):
        p = os.path.join(base, sub, 'DialogSubtitles.xml')
        if os.path.isfile(p):
            return p
    return ''


def _strip_old_markers(content):
    """Best-effort removal of v1 (FENtastic-only) inject. If the
    user upgraded from the FENtastic-specific patcher, their XML
    has two duplicated <control> blocks tagged with the v1 marker.
    We pull both blocks AND the marker line so the v2 substitution
    has a clean original-shape file to match against."""
    for old in OLD_MARKERS:
        # The v1 inject placed the marker on its own line ABOVE the
        # duplicated pair of control blocks. Remove the marker line
        # AND the next two control blocks following it.
        pat = re.compile(
            r'[ \t]*' + re.escape(old) + r'[ \t]*\r?\n'
            r'(?:[ \t]*<control\s+type="label"[^>]*>'
            r'(?:(?!</control>).)*?</control>[ \t]*\r?\n){2}',
            re.DOTALL,
        )
        content, n = pat.subn('', content, count=1)
        if n:
            _log('stripped v1 (FENtastic-only) inject before '
                 'applying v2 generic patch', level='INFO')
    return content


def _build_replacement(match):
    """Given the regex match of a `<control type="label">...
    $INFO[Player.Filename]...</control>` element, produce the
    replacement block: that same element twice, each gated by
    `<visible>` to read subs.player_filename first, fall back to
    Player.Filename when ours is empty. Preserves the original
    indentation so the XML stays readable."""
    original = match.group(0)
    indent = match.group('indent')
    # Build the "ours" variant: same XML but with the Player.Filename
    # info-label (any capitalisation) swapped to our window property,
    # plus a visible-when-set gate added before </control>.
    ours = _PLAYER_FILENAME_RE.sub(
        '$INFO[Window(10000).Property(subs.player_filename)]',
        original, count=1)
    # Inject the visible condition right before </control> -- if
    # the original already had a <visible>, prepend our gate with
    # an AND so we don't override the skin's own visibility logic.
    ours_visible = ('<visible>!String.IsEmpty('
                    'Window(10000).Property(subs.player_filename))'
                    '</visible>')
    fallback_visible = ('<visible>String.IsEmpty('
                        'Window(10000).Property(subs.player_filename))'
                        '</visible>')
    ours = _splice_visible(ours, ours_visible)
    fallback = _splice_visible(original, fallback_visible)
    # Drop the v2 marker on its own line right above the pair so
    # the next run can detect (and skip) idempotently.
    return ('{0}{1}\n{2}\n{0}{3}'
            ).format(indent, MARKER, ours, fallback)


def _splice_visible(control_xml, visible_xml):
    """Insert `visible_xml` just before the closing </control>.
    If the control already has a <visible>, wrap it in
    String.IsEmpty + and so both conditions must hold."""
    # Try to detect an existing <visible> -- conservatively combine
    # via AND so the skin's original visibility logic still applies.
    existing = re.search(r'<visible>(?P<expr>.*?)</visible>',
                         control_xml, re.DOTALL)
    if existing:
        new_expr = ('[' + existing.group('expr').strip() + '] + '
                    '[' + re.search(r'<visible>(.*?)</visible>',
                                    visible_xml,
                                    re.DOTALL).group(1) + ']')
        return control_xml.replace(
            existing.group(0),
            '<visible>' + new_expr + '</visible>', 1)
    # No existing visible -- insert before </control>.
    return control_xml.replace(
        '</control>', visible_xml + '</control>', 1)


def ensure_patched():
    """Find the active skin's DialogSubtitles.xml and patch it.
    Idempotent (skip if v2 marker present). Self-migrates a v1
    inject (the FENtastic-only patcher's output) before applying
    v2. Returns one of: 'patched' | 'already_patched' | 'no_skin'
    | 'no_file' | 'unmatched' | 'read_failed' | 'write_failed'.
    """
    skin_id = _current_skin_id()
    if not skin_id:
        return 'no_skin'
    path = _dialog_path(skin_id)
    if not path:
        _log('skin {0} has no DialogSubtitles.xml -- skipping'
             .format(skin_id), level='INFO')
        return 'no_file'
    try:
        with open(path, 'rb') as f:
            content = f.read().decode('utf-8', errors='replace')
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'read_failed'

    # v2 already in place? bail.
    if MARKER in content:
        return 'already_patched'

    # If v1 (FENtastic-only) was applied, strip it so we get a clean
    # template to re-substitute.
    content = _strip_old_markers(content)

    if not _PLAYER_FILENAME_RE.search(content):
        _log('no $INFO[Player.Filename] in {0} -- this skin does '
             'not use the header label we patch, nothing to do'
             .format(path), level='INFO')
        return 'no_target'

    m = _LABEL_CONTROL_RE.search(content)
    if not m:
        _log('found Player.Filename but the surrounding <control> '
             'element did not match our pattern in {0} -- skin XML '
             'shape is unusual'.format(path), level='WARNING')
        return 'unmatched'

    new_content = content[:m.start()] + _build_replacement(m) \
        + content[m.end():]

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'wb') as f:
            f.write(new_content.encode('utf-8'))
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'write_failed'

    _log('patched DialogSubtitles.xml of skin {0} so the header '
         'prefers subs.player_filename'.format(skin_id),
         level='INFO')
    return 'patched'
