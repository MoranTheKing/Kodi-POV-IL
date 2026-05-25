# Self-healing replacement of two FENtastic skin widget XML files
# so the "Personal area (must connect to Trakt)" header on the
# movies and shows pages reads as just "Personal area" -- consistent
# with the post-PR-#95 reality where TMDB Favorites cover the same
# use case without requiring a Trakt account.
#
# Regex-based match so we tolerate small whitespace variations
# (different leading-space count, different attribute order) that
# may exist between the shipped XML and what the user actually has
# on disk after a skin update or other patcher run.

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


SKIN_ADDON_ID = 'skin.fentastic'
WIDGET_FILES = (
    'script-fentastic-widget_movies.xml',
    'script-fentastic-widget_tvshows.xml',
)

# Match the widget_header param for the personal-area widget.
# The pattern tolerates three pre-existing baselines and migrates
# all of them to the current recommended header (which advises
# users to add items to TMDB / Trakt before POV-local):
#   A. shipped v0 baseline:        [B][COLOR yellow]איזור אישי
#                                  (חובה להתחבר לTrakt)[/COLOR][/B]
#   B. v0.2.18 patcher result:     [B][COLOR yellow]איזור אישי[/COLOR][/B]
#   C. v0.2.20 patcher result:     [B][COLOR yellow]איזור אישי[/COLOR][/B]
#                                  [COLOR gray][I]· מומלץ לחבר TMDB + Trakt[/I][/COLOR]
# Anything else (user customized) is left alone.
PATTERN = re.compile(
    r'<param\s+name="widget_header"\s+'
    r'value="\[B\]\[COLOR\s+yellow\]איזור אישי'
    r'(?:\s*\(\s*חובה\s+להתחבר\s+ל?\s*Trakt\s*\))?'
    r'\[/COLOR\]\[/B\]'
    r'(?:\s+\[COLOR\s+gray\]\[I\]·\s*מומלץ\s+לחבר\s+TMDB\s*\+\s*Trakt'
    r'\[/I\]\[/COLOR\])?'
    r'"\s*/>',
    re.DOTALL,
)
REPLACEMENT = (
    '<param name="widget_header" '
    'value="[B][COLOR yellow]איזור אישי[/COLOR][/B]   '
    '[COLOR gray][I]· מומלץ להוסיף ב-TMDB + Trakt לפני POV-מקומי'
    '[/I][/COLOR]"/>'
)
# Token unique to the new (post-recommendation) header. Present in
# v0.2.24+ only; absent from all earlier baselines.
NEW_TOKEN = 'לפני POV-מקומי'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('fentastic_widget_patcher: ' + msg, level=level)
    except Exception:
        pass


def _widget_path(filename):
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
        _log('{0}: file not found'.format(filename), level='INFO')
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(filename, e),
             level='WARNING')
        return 'read_failed'
    if NEW_TOKEN in content:
        _log('{0}: already migrated'.format(filename), level='DEBUG')
        return 'unchanged'
    new_content, n = PATTERN.subn(REPLACEMENT, content, count=1)
    if n == 0:
        _log('{0}: no Trakt-subtitle header found -- '
             'leaving file alone'.format(filename), level='INFO')
        return 'unmatched'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('{0}: header rewritten'.format(filename), level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(filename, e),
             level='WARNING')
        return 'write_failed'


def ensure_patched():
    """Apply the header rewrite to both widget XML files. Returns a
    {filename: status} dict.
    """
    return {name: _patch_one(name) for name in WIDGET_FILES}
