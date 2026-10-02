# Adds a "החלף מקור" (change source) button to the Estuary skin's player OSD.
#
# Why: the build's Estuary (skin.estuary, the KODI-RD-IL custom Estuary) ships
# a fullscreen video OSD with NO change-source button, so a bad source mid-
# playback left the user stuck. (FENtastic has it; Estuary didn't.) Estuary
# even carries a COMMENTED-OUT "Twilight Switch Source Button" attempt that used
# the wrong POV param (media_type=, with an underscore); the form that actually
# works -- proven by FENtastic's OSD and NOX's next-episode button -- is:
#   plugin://plugin.video.pov/?mode=play_media&mediatype=<movie|episode>
#       &tmdb_id=...&autoplay=false
# autoplay=false forces the source dialog to re-show; since a video is already
# playing, our remember-source auto-pick hook steps aside (change-source path),
# so the user always gets the dialog and the new pick is captured.
#
# Self-healing: marker-gated, reverts prior versions, XML-parse-checked before
# an atomic write (so a bad edit can never corrupt the skin / black-screen the
# player), and preserves the file's CRLF line endings. No-op when Estuary isn't
# installed. Mirrors nox_change_source_patcher with the Estuary anchor + style.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    import xml.etree.ElementTree as ET
except Exception:
    ET = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


ESTUARY_SKIN_ID = 'skin.estuary'
OSD_REL_PATH = 'xml/VideoOSD.xml'
MARKER = 'AI_SUBS_ESTUARY_CHANGE_SOURCE_v1'
BUTTON_ID = '700458'  # verified unused across the Estuary skin

# Anchor: the always-present "next audio track" button in the right-side OSD
# grouplist (id 202). We insert the change-source button just before it.
_ANCHOR_RE = re.compile(
    r'^(?P<indent>[ \t]*)<control type="button" id="700452">',
    re.MULTILINE,
)
# Revert any prior version of our injected block (marker comment .. its closing
# </control>, including the trailing newline).
_REVERT_RE = re.compile(
    r'[ \t]*<!--\s*AI_SUBS_ESTUARY_CHANGE_SOURCE_v\d+\s*-->.*?</control>[ \t]*\r?\n',
    re.DOTALL,
)


def _mask_comments(content):
    # Keep offsets and line endings while excluding commented-out controls.
    return re.sub(r'<!--.*?-->',
                  lambda match: re.sub(r'[^\r\n]', ' ', match.group(0)),
                  content, flags=re.DOTALL)


def _dedupe_owned_buttons(content):
    # Old XML serializers may have discarded marker comments. Only remove a
    # second copy of our known ID with identical actions/visibility/label.
    # Do not remove commented examples or differently configured controls.
    seen = set()
    removed = []
    for match in re.finditer(r'<control\b[^>]*type="button"[^>]*>.*?</control>',
                             _mask_comments(content), flags=re.DOTALL):
        try:
            control = ET.fromstring(content[match.start():match.end()])
        except Exception:
            continue
        actions = tuple((action.get('condition'), action.text) for action in
                        control.findall('onclick')
                        if 'PlayerControl(Play)' not in (action.text or ''))
        if (control.get('id') != BUTTON_ID or
                not any('mode=play_media' in (text or '') and 'mediatype=' in (text or '')
                        for _, text in actions)):
            continue
        signature = (actions, control.findtext('label'),
                     tuple(e.text for e in control.findall('visible')))
        if signature in seen:
            removed.append((match.start(), match.end()))
        seen.add(signature)
    for start, end in reversed(removed):
        content = content[:start] + content[end:]
    return content


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('estuary_change_source_patcher: ' + msg, level=level)
    except Exception:
        pass


def _osd_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + ESTUARY_SKIN_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, OSD_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _button_block(indent, eol):
    inner = indent + '\t'
    mv = ('plugin://plugin.video.pov/?mode=play_media&amp;mediatype=movie'
          '&amp;tmdb_id=$INFO[VideoPlayer.UniqueID(tmdb)]&amp;autoplay=false')
    ep = ('plugin://plugin.video.pov/?mode=play_media&amp;mediatype=episode'
          '&amp;tmdb_id=$INFO[VideoPlayer.UniqueID(tmdb)]'
          '&amp;season=$INFO[VideoPlayer.Season]'
          '&amp;episode=$INFO[VideoPlayer.Episode]&amp;autoplay=false')
    lines = [
        indent + '<!-- ' + MARKER + ' -->',
        indent + '<control type="button" id="' + BUTTON_ID + '">',
        inner + '<description>POV IL change source</description>',
        inner + '<width>auto</width>',
        inner + '<height>76</height>',
        inner + '<align>center</align>',
        inner + '<texturenofocus>-</texturenofocus>',
        inner + '<texturefocus colordiffuse="button_focus">'
                'colors/white.png</texturefocus>',
        inner + '<label>[B]החלף מקור[/B]</label>',
        inner + '<visible>VideoPlayer.Content(movies) | '
                'VideoPlayer.Content(episodes)</visible>',
        inner + '<visible>!VideoPlayer.Content(LiveTV)</visible>',
        inner + '<visible>!String.Contains(Player.Folderpath, '
                'plugin.video.idanplus)</visible>',
        inner + '<visible>!String.Contains(Player.Folderpath, '
                'plugin.video.supertv)</visible>',
        inner + '<visible>!String.Contains(Player.Folderpath, '
                'plugin.video.flashstream)</visible>',
        inner + '<onclick condition="VideoPlayer.Content(movies)">'
                'RunPlugin(' + mv + ')</onclick>',
        inner + '<onclick condition="VideoPlayer.Content(episodes)">'
                'RunPlugin(' + ep + ')</onclick>',
        indent + '</control>',
    ]
    return ''.join(ln + eol for ln in lines)


def ensure_patched():
    path = _osd_path()
    if not path:
        return 'no_file'
    try:
        # newline='' disables newline translation so CRLF stays CRLF -- the
        # Estuary skin files use CRLF and we want a minimal, faithful edit.
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    already = MARKER in original

    # Strip any prior version so we re-apply cleanly (idempotent).
    content = _dedupe_owned_buttons(_REVERT_RE.sub('', original))

    # Updated skin packages already contain this action without our marker.
    # Parse real controls: commented-out Twilight examples are not buttons.
    # Remove only our marked addition, preserving the skin's native action,
    # pause behavior, visibility and exact formatting.
    try:
        tree = ET.fromstring(content)
    except Exception:
        return 'parse_failed'
    native = any(
        ('mode=player_change_source' in (action.text or '') or
         ('mode=play_media' in (action.text or '') and
          'mediatype=' in (action.text or '') and
          'autoplay=false' in (action.text or '')))
        for button in tree.findall(".//control[@type='button']")
        for action in button.findall('onclick'))
    if not native:
        # A different control owns this ID: never introduce a collision.
        if tree.find(".//control[@id='" + BUTTON_ID + "']") is not None:
            return 'id_conflict'
        m = _ANCHOR_RE.search(_mask_comments(content))
        if not m:
            _log('audio-button anchor not found -- skipping', level='WARNING')
            return 'unmatched'
        indent = m.group('indent')
        block = _button_block(indent, eol)
        content = content[:m.start()] + block + content[m.start():]

    # SAFETY: never write XML that doesn't parse -- a broken OSD would
    # black-screen the player.
    if ET is not None:
        try:
            ET.fromstring(content)
        except Exception as e:
            _log('patched XML would not parse -- skipping ({0})'.format(e),
                 level='WARNING')
            return 'parse_failed'

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

    _log('removed duplicate change-source button' if native else
         'injected change-source button into Estuary VideoOSD', level='INFO')
    return 'deduplicated' if native else ('unchanged' if already else 'patched')
