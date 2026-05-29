# Self-healing patch of the ACTIVE skin's DialogSubtitles.xml row
# layout so long release names in the subtitle picker don't get
# clipped mid-wrap.
#
# Why we go after the SKIN's XML (not DarkSubs):
#   The picker the user sees in the screenshot (with the services
#   panel on the left, the file path at the top, and the subtitle
#   list on the right) is Kodi's NATIVE DialogSubtitles dialog --
#   DarkSubs is just one of the listed services. The list layout
#   (row height, label height, wrap behaviour) lives in the active
#   skin's DialogSubtitles.xml, not in DarkSubs.
#
# What gets clipped:
#   In FENtastic (the build's default skin), the row is:
#       <itemlayout width="920" height="100">  <!-- 100 px -->
#         ...
#         <control type="textbox">
#           <height>100</height>
#           <label>$INFO[ListItem.Label2]</label>
#           ...
#         </control>
#       </itemlayout>
#   font12 over two wrapped lines plus line-spacing renders to
#   ~105-110 px, so the bottom 5-10 px of the second line gets
#   clipped. Bumping the row + textbox height to ~140 px gives the
#   wrap room to breathe without crowding adjacent rows.
#
# Strategy:
#   1. Resolve the active skin's DialogSubtitles.xml via the same
#      lookup helper as skin_dialog_subtitles_patcher (xml/ then
#      720p/ then 1080i/).
#   2. Find `<itemlayout ... height="N">...</itemlayout>` and
#      `<focusedlayout ... height="N">...</focusedlayout>` blocks
#      that contain `$INFO[ListItem.Label2]` (so we don't touch
#      layouts in other dialogs that the skin author might have
#      laid out at the same dimension by coincidence). For each
#      matching layout, bump the `height="N"` attribute and any
#      inner `<height>N</height>` element that belongs to a
#      `<control type="textbox">` referencing ListItem.Label2.
#   3. Marker-gated. Self-healing on Kodi startup so a skin update
#      can't permanently revert it.
#   4. Atomic write (tmp + os.replace).
#
# Conservative defaults:
#   - Only itemlayout/focusedlayout blocks containing Label2 are
#     touched.
#   - Only TEXTBOX heights inside those layouts are bumped (avoids
#     resizing the flag image, the rating image, etc.).
#   - The bump is a fixed +40 px (not a multiplier) so small
#     existing layouts grow proportionally less than tall ones --
#     skins with already-tall rows (>=200) get a no-op-ish
#     adjustment.
#   - Existing height >= 140 -> skip (skin author already handled
#     it).

import os
import re

try:
    import xbmc
    import xbmcvfs
except ImportError:
    xbmc = None
    xbmcvfs = None

from . import kodi_utils


MARKER = '<!-- AI_SUBS_DIALOG_ROW_HEIGHT_v1 -->'

# Bump every too-short layout / textbox by this many pixels.
HEIGHT_BUMP_PX = 40

# A layout we'll consider "already tall enough" -- skip it.
TALL_ENOUGH_PX = 140

# Match an entire <itemlayout> or <focusedlayout> element including
# the height="N" attribute. Capture both the attribute number and
# the whole body so we can decide if it contains ListItem.Label2
# and rewrite only when it does.
_LAYOUT_RE = re.compile(
    rb'(?P<tag><(?P<which>itemlayout|focusedlayout)\b[^>]*?'
    rb'\sheight="(?P<h>\d+)"[^>]*>)'
    rb'(?P<body>(?:(?!</(?P=which)>).)*?)'
    rb'</(?P=which)>',
    re.DOTALL,
)

# Inside a layout body, find a TEXTBOX control whose body
# references ListItem.Label2 -- this is the release-name control
# whose own height also needs bumping when the layout grows. Body
# may include arbitrary other elements (height, font, label, etc.)
# in any order.
_TEXTBOX_LABEL2_RE = re.compile(
    rb'<control\s+type="textbox"[^>]*>'
    rb'(?P<inner>(?:(?!</control>).)*?'
    rb'\$INFO\[ListItem\.Label2\]'
    rb'(?:(?!</control>).)*?)'
    rb'</control>',
    re.DOTALL,
)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log(
            'skin_dialog_subtitles_row_patcher: ' + msg, level=level)
    except Exception:
        pass


def _current_skin_id():
    if xbmc is None:
        return ''
    try:
        return xbmc.getSkinDir() or ''
    except Exception:
        return ''


def _dialog_path(skin_id):
    """Locate DialogSubtitles.xml under the skin's typical
    subdirectories (xml/, 720p/, 1080i/). Returns '' on miss."""
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


def _bump_inner_textbox_heights(layout_body, bump):
    """Inside a layout body, find textbox controls that reference
    $INFO[ListItem.Label2] and bump their <height>N</height> by
    `bump`. Returns the modified body (or the original if no
    textbox-label2 control was present)."""
    out_chunks = []
    last_end = 0
    for tm in _TEXTBOX_LABEL2_RE.finditer(layout_body):
        # Bump every <height>N</height> inside this control body.
        inner = tm.group('inner')
        def _bump_h(hm):
            n = int(hm.group(1))
            if n >= TALL_ENOUGH_PX:
                return hm.group(0)
            return b'<height>' + str(n + bump).encode('ascii') \
                   + b'</height>'
        new_inner = re.sub(
            rb'<height>(\d+)</height>', _bump_h, inner)
        out_chunks.append(layout_body[last_end:tm.start()])
        out_chunks.append(b'<control type="textbox"')
        # Preserve the original opening tag's other attributes by
        # re-reading them from the match. The textbox regex anchors
        # on `<control type="textbox"` so we just need to extract
        # whatever followed up to the first `>`.
        # Simpler: rebuild the full control with the new inner.
        opening_end = tm.group(0).find(b'>') + 1
        opening = tm.group(0)[:opening_end]
        out_chunks[-1] = opening  # replace placeholder above
        out_chunks.append(new_inner)
        out_chunks.append(b'</control>')
        last_end = tm.end()
    out_chunks.append(layout_body[last_end:])
    return b''.join(out_chunks)


def _patch_layout(m):
    """Given a <itemlayout|focusedlayout> match, decide whether to
    bump heights. Returns the replacement bytes (or None to leave
    the original alone)."""
    h = int(m.group('h'))
    body = m.group('body')
    if b'$INFO[ListItem.Label2]' not in body:
        return None
    if h >= TALL_ENOUGH_PX:
        return None
    new_h = h + HEIGHT_BUMP_PX
    # Rewrite the height="N" in the opening tag.
    tag = m.group('tag')
    new_tag = re.sub(
        rb'\sheight="\d+"',
        b' height="' + str(new_h).encode('ascii') + b'"',
        tag, count=1)
    new_body = _bump_inner_textbox_heights(body, HEIGHT_BUMP_PX)
    return new_tag + new_body + b'</' + m.group('which') + b'>'


def ensure_patched():
    """Bump itemlayout/focusedlayout heights in the active skin's
    DialogSubtitles.xml so long release names in the picker don't
    get clipped mid-wrap. Idempotent. Returns one of: 'no_skin' |
    'no_file' | 'already_patched' | 'no_target' | 'patched' |
    'read_failed' | 'write_failed'."""
    skin_id = _current_skin_id()
    if not skin_id:
        return 'no_skin'
    path = _dialog_path(skin_id)
    if not path:
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

    # Walk every layout match, collect rewrites.
    rewrites = []
    for m in _LAYOUT_RE.finditer(content):
        new = _patch_layout(m)
        if new is None:
            continue
        rewrites.append((m.start(), m.end(), new))
    if not rewrites:
        return 'no_target'

    # Apply from end to start so earlier offsets stay valid.
    new_content = content
    for start, end, new in reversed(rewrites):
        new_content = new_content[:start] + new + new_content[end:]

    # Drop the marker after the XML declaration (if present).
    eol = b'\r\n' if b'\r\n' in new_content[:8192] else b'\n'
    marker_line = MARKER.encode('utf-8') + eol
    decl_match = re.match(
        rb'<\?xml[^?]*\?>\s*', new_content, re.DOTALL)
    if decl_match:
        new_content = (new_content[:decl_match.end()] + marker_line
                       + new_content[decl_match.end():])
    else:
        new_content = marker_line + new_content

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
        return 'write_failed'
    _log('bumped {0} layout(s) in {1} so wrapped release names '
         'display fully'.format(len(rewrites), path), level='INFO')
    return 'patched'
