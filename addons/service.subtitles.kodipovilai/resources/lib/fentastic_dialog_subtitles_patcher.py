# Self-healing patch of FENtastic skin's DialogSubtitles.xml so the
# subtitle-picker dialog HEADER prefers the window property
# `subs.player_filename` (set by POV's source picker via
# pov_source_name_patcher) over the built-in `Player.Filename`
# info-label.
#
# Why this exists:
#   Kodi's DialogSubtitles renders the heading from
#   `<label>$INFO[Player.Filename]</label>` in the skin's XML.
#   Player.Filename is computed by Kodi as the basename of
#   xbmc.Player().getPlayingFile() -- which for TorBox CDN URLs
#   (`store-N.torbox.app/<uuid>?token=...`) is just the UUID. RD/AD
#   URLs include the release filename so this looked fine, but on
#   TorBox the user sees gibberish at the top of the dialog and can't
#   visually compare against subtitle release names.
#
#   Window(10000).Property(subs.player_filename) is the property
#   DarkSubs natively reads into Tagline_From_Fen (intended for
#   FEN-family scrapers to expose the picked release name). When
#   POV's source picker sets it, we want the dialog header to use
#   that value instead of Player.Filename.
#
# Approach:
#   Replace the single label control with TWO copies of it, each
#   gated on whether subs.player_filename is set:
#     - if set: show $INFO[Window(10000).Property(subs.player_filename)]
#     - else:   fall back to $INFO[Player.Filename] (original behaviour)
#
# Self-healing: re-applies on every Kodi startup. If FENtastic
# upstream restructures the dialog XML in a way our pattern doesn't
# match, we skip with a log warning and the dialog header goes back
# to its pre-patch behaviour (UUID for TorBox).

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


SKIN_ADDON_ID = 'skin.fentastic'
DIALOG_REL_PATH = 'xml/DialogSubtitles.xml'

MARKER = '<!-- AI_SUBS_DIALOG_HEADER_v1 -->'

# Exact bytes of the upstream "Video label" control. Tabs are 4-deep
# (matches FENtastic's indentation). Line endings are LF (verified
# with cat -A on the file in the build zip).
OLD_BLOCK = (
    '\t\t\t\t<control type="label">\n'
    '\t\t\t\t\t<description>Video label</description>\n'
    '\t\t\t\t\t<top>-45</top>\n'
    '\t\t\t\t\t<width>920</width>\n'
    '\t\t\t\t\t<height>30</height>\n'
    '\t\t\t\t\t<font>font30_title</font>\n'
    '\t\t\t\t\t<label>$INFO[Player.Filename]</label>\n'
    '\t\t\t\t\t<align>center</align>\n'
    '\t\t\t\t\t<aligny>center</aligny>\n'
    '\t\t\t\t\t<textcolor>grey</textcolor>\n'
    '\t\t\t\t\t<shadowcolor>black</shadowcolor>\n'
    '\t\t\t\t\t<scroll>true</scroll>\n'
    '\t\t\t\t</control>\n'
)

# Two stacked label controls with mutually-exclusive <visible>
# conditions. The first (preferred) uses subs.player_filename; the
# second is the upstream behaviour as a fallback.
NEW_BLOCK = (
    '\t\t\t\t' + MARKER + '\n'
    '\t\t\t\t<control type="label">\n'
    '\t\t\t\t\t<description>Video label (AI Subs: picked release '
    'name)</description>\n'
    '\t\t\t\t\t<top>-45</top>\n'
    '\t\t\t\t\t<width>920</width>\n'
    '\t\t\t\t\t<height>30</height>\n'
    '\t\t\t\t\t<font>font30_title</font>\n'
    '\t\t\t\t\t<label>$INFO[Window(10000).Property(subs.player_filename)'
    ']</label>\n'
    '\t\t\t\t\t<align>center</align>\n'
    '\t\t\t\t\t<aligny>center</aligny>\n'
    '\t\t\t\t\t<textcolor>grey</textcolor>\n'
    '\t\t\t\t\t<shadowcolor>black</shadowcolor>\n'
    '\t\t\t\t\t<scroll>true</scroll>\n'
    '\t\t\t\t\t<visible>!String.IsEmpty(Window(10000).Property('
    'subs.player_filename))</visible>\n'
    '\t\t\t\t</control>\n'
    '\t\t\t\t<control type="label">\n'
    '\t\t\t\t\t<description>Video label (fallback: Player.Filename)'
    '</description>\n'
    '\t\t\t\t\t<top>-45</top>\n'
    '\t\t\t\t\t<width>920</width>\n'
    '\t\t\t\t\t<height>30</height>\n'
    '\t\t\t\t\t<font>font30_title</font>\n'
    '\t\t\t\t\t<label>$INFO[Player.Filename]</label>\n'
    '\t\t\t\t\t<align>center</align>\n'
    '\t\t\t\t\t<aligny>center</aligny>\n'
    '\t\t\t\t\t<textcolor>grey</textcolor>\n'
    '\t\t\t\t\t<shadowcolor>black</shadowcolor>\n'
    '\t\t\t\t\t<scroll>true</scroll>\n'
    '\t\t\t\t\t<visible>String.IsEmpty(Window(10000).Property('
    'subs.player_filename))</visible>\n'
    '\t\t\t\t</control>\n'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('fentastic_dialog_subtitles_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _dialog_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + SKIN_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, DIALOG_REL_PATH)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Inject the conditional-header label-pair into FENtastic's
    DialogSubtitles.xml. Idempotent (skip if marker present),
    defensive (skip if upstream changed the shape).
    """
    path = _dialog_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER.encode('utf-8') in content:
        return 'unchanged'
    old_bytes = OLD_BLOCK.encode('utf-8')
    if old_bytes not in content:
        _log('DialogSubtitles.xml Video-label shape changed -- '
             'skipping', level='WARNING')
        return 'unmatched'
    new_content = content.replace(old_bytes, NEW_BLOCK.encode('utf-8'), 1)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'wb') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('rewrote dialog header label to prefer '
             'subs.player_filename over Player.Filename',
             level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
