# Self-healing replacement of two FENtastic skin widget XML files
# so the "Personal area (must connect to Trakt)" header on the
# movies and shows pages reads as just "Personal area" -- consistent
# with the post-PR-#95 reality where TMDB Favorites cover the same
# use case without requiring a Trakt account.
#
# Surgical: only rewrites the specific widget_header line that
# matches the shipped baseline byte-for-byte. Any user or upstream
# customization to that line leaves it alone (the file is left
# untouched and the patcher moves on).

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None


SKIN_ADDON_ID = 'skin.fentastic'
WIDGET_FILES = (
    'script-fentastic-widget_movies.xml',
    'script-fentastic-widget_tvshows.xml',
)
OLD_LINE = (
    '            <param name="widget_header" '
    'value="[B][COLOR yellow]איזור אישי '
    '(חובה להתחבר לTrakt)[/COLOR][/B]"/>'
)
NEW_LINE = (
    '            <param name="widget_header" '
    'value="[B][COLOR yellow]איזור אישי[/COLOR][/B]"/>'
)


def _widget_path(filename):
    """Resolve full path to a FENtastic widget XML."""
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + SKIN_ADDON_ID + '/xml/')
    except Exception:
        return ''
    p = os.path.join(base, filename)
    return p if os.path.isfile(p) else ''


def _patch_one(filename):
    path = _widget_path(filename)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return 'read_failed'
    if NEW_LINE in content:
        return 'unchanged'
    if OLD_LINE not in content:
        return 'unmatched'
    new_content = content.replace(OLD_LINE, NEW_LINE, 1)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        return 'patched'
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 'write_failed'


def ensure_patched():
    """Apply the header rewrite to both widget XML files. Returns a
    {filename: status} dict.
    """
    return {name: _patch_one(name) for name in WIDGET_FILES}
