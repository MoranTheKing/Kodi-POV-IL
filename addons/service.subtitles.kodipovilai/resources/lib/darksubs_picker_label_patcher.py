# Self-healing patch of DarkSubs's custom subtitle-picker dialog XML
# so long release names don't get cut off mid-line. Many DarkSubs
# builds put the release name in a `<control type="label">` with
# `wrapmultiline=true` AND a fixed row height that's only tall enough
# for ~1 line -- the second line gets clipped, hiding the release
# group (the part the user actually needs to identify the file).
#
# Strategy:
#   1. Walk service.subtitles.All_Subs/resources/skins/Default/
#      for any .xml file.
#   2. For each XML, parse defensively (regex-based; XML namespaces
#      vary across skins and full ElementTree handling adds risk).
#   3. Find `<control type="label">` blocks whose body references
#      $INFO[ListItem.Label] or $INFO[ListItem.Label2] -- these are
#      the per-row provider + release-name labels.
#   4. If the block doesn't already have `<scroll>true</scroll>`, add
#      it just before `</control>`. Kodi's marquee scroll lets the
#      user see the full text (release group, encoder, etc.) instead
#      of a truncated wrap.
#   5. Mark the patched file with a header comment so a re-run is a
#      no-op. Self-healing: re-applies on every Kodi startup so a
#      DarkSubs update can't permanently revert it.
#
# Conservative choices:
#   - Only labels that reference ListItem.Label{,2} are touched. Other
#     labels (header, buttons, status text) are left alone.
#   - We add `<scroll>true</scroll>` only when missing. If the skin
#     author already configured scroll, we don't double-add.
#   - We never CHANGE existing attributes (e.g. wrapmultiline). Just
#     add the scroll directive. Kodi takes scroll over wrap.
#   - Files with 0 matching labels are skipped without write.
#   - Atomic write (tmp + os.replace) so a crash can't leave a half-
#     written XML.
#
# Why not patch the active skin's DialogSubtitles.xml instead?
#   DarkSubs ships its OWN custom dialog (the screenshot shows the
#   "DarkSubs" header + services panel on the left) rather than
#   piggybacking on Kodi's standard subtitle dialog. The XML lives
#   inside DarkSubs's own addon tree, NOT in the active skin.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
SKINS_REL_PATH = 'resources/skins/Default'

# Header comment we drop into each patched file. Idempotency gate.
MARKER = '<!-- AI_SUBS_DARKSUBS_PICKER_LABEL_SCROLL_v1 -->'

# Match an entire <control type="label">...</control> element. DOTALL
# so the body can span multiple lines; non-greedy so we capture
# exactly the smallest enclosing control (not the whole file).
_LABEL_CONTROL_RE = re.compile(
    rb'(?P<indent>[ \t]*)<control\s+type="label"[^>]*>'
    rb'(?P<body>(?:(?!</control>).)*?)</control>',
    re.DOTALL,
)

# Inside a captured label body, look for the row-label info refs we
# care about. ListItem.Label is the provider/percent line, Label2 is
# the release name -- both get cut off in the picker if the row is
# too short.
_ROW_LABEL_INFO_RE = re.compile(
    rb'\$INFO\[ListItem\.Label2?\]')

# Whether the captured body already has a <scroll>true</scroll>
# directive (any whitespace, any case on "true").
_HAS_SCROLL_RE = re.compile(
    rb'<scroll>\s*true\s*</scroll>', re.IGNORECASE)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log(
            'darksubs_picker_label_patcher: ' + msg, level=level)
    except Exception:
        pass


def _darksubs_skins_dir():
    """Return the absolute path to DarkSubs's resources/skins/Default
    directory, or '' if DarkSubs isn't installed."""
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SKINS_REL_PATH)
    return p if os.path.isdir(p) else ''


def _iter_xml_files(root):
    """Yield absolute paths of every .xml file under root. DarkSubs
    keeps its skin XMLs in subfolders by resolution (720p, 1080i)
    so we walk recursively."""
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith('.xml'):
                yield os.path.join(dirpath, fn)


def _patch_xml_bytes(content):
    """Return (new_content, count_changed). Idempotent: if the marker
    is already present at the top of the file, returns (content, 0)
    without doing anything."""
    if MARKER.encode('utf-8') in content:
        return content, 0

    # Count how many label controls we'll modify. Only ones that
    # reference ListItem.Label{,2} AND don't already have scroll.
    edits = []
    for m in _LABEL_CONTROL_RE.finditer(content):
        body = m.group('body')
        if not _ROW_LABEL_INFO_RE.search(body):
            continue
        if _HAS_SCROLL_RE.search(body):
            continue
        edits.append(m)

    if not edits:
        return content, 0

    # Apply edits from END to START so earlier match offsets stay
    # valid as we splice in additional bytes.
    new_content = content
    for m in reversed(edits):
        original = m.group(0)
        # Splice <scroll>true</scroll> right before </control>. Match
        # whatever indentation the body uses for the closing tag --
        # if we find a leading-indent line ending with </control>,
        # mirror its indent; otherwise put it inline.
        body = m.group('body')
        close_indent_match = re.search(
            rb'(?P<ws>[ \t]*)$', body, re.MULTILINE)
        ws = (close_indent_match.group('ws')
              if close_indent_match else b'')
        scroll_tag = ws + b'<scroll>true</scroll>\n' + ws
        modified = original.replace(
            b'</control>', scroll_tag + b'</control>', 1)
        new_content = (new_content[:m.start()] + modified
                       + new_content[m.end():])

    # Drop the marker as the first non-XML-declaration line so a
    # second run sees it and bails. Place it after `<?xml ... ?>`
    # if present; otherwise prepend.
    eol = b'\r\n' if b'\r\n' in new_content[:8192] else b'\n'
    marker_line = MARKER.encode('utf-8') + eol
    decl_match = re.match(
        rb'<\?xml[^?]*\?>\s*', new_content, re.DOTALL)
    if decl_match:
        new_content = (new_content[:decl_match.end()] + marker_line
                       + new_content[decl_match.end():])
    else:
        new_content = marker_line + new_content
    return new_content, len(edits)


def _patch_file(path):
    """Read, patch, atomic-write. Returns the edit count (0 = no-op,
    >0 = patched). On any error, leaves the file untouched and
    logs."""
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 0

    new_content, count = _patch_xml_bytes(content)
    if count == 0:
        return 0

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
        _log('write failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 0
    return count


def ensure_patched():
    """Walk DarkSubs's skin XML files and add `<scroll>true</scroll>`
    to per-row labels that reference ListItem.Label{,2}. Idempotent.
    Returns one of: 'no_darksubs' | 'no_skins_dir' | 'patched' |
    'already_patched' | 'nothing_to_patch'."""
    root = _darksubs_skins_dir()
    if not root:
        return 'no_darksubs'

    files_patched = 0
    total_edits = 0
    any_marker_seen = False
    for path in _iter_xml_files(root):
        # Quick marker check before the full parse path -- saves work
        # on subsequent runs where every file is already patched.
        try:
            with open(path, 'rb') as f:
                first_kb = f.read(2048)
            if MARKER.encode('utf-8') in first_kb:
                any_marker_seen = True
                continue
        except OSError:
            continue
        n = _patch_file(path)
        if n > 0:
            files_patched += 1
            total_edits += n

    if files_patched == 0:
        if any_marker_seen:
            return 'already_patched'
        return 'nothing_to_patch'
    _log('patched {0} files / {1} label controls in DarkSubs '
         'picker XML'.format(files_patched, total_edits),
         level='INFO')
    return 'patched'
