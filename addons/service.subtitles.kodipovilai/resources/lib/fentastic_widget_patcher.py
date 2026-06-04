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

MOVIES_POPULAR_BLOCK = '''        <include content="WidgetListBigPoster">
            <param name="content_path" value="plugin://plugin.video.pov/?name=32459&amp;iconImage=popular&amp;mode=build_movie_list&amp;action=tmdb_movies_popular"/>
            <param name="widget_header" value="[B][COLOR yellow]סרטים פופולריים[/COLOR][/B]"/>
            <param name="widget_target" value="videos"/>
            <param name="list_id" value="19015"/>
        </include>
'''

MOVIES_GENRES_BLOCK = '''        <include content="WidgetListBigEpisodes">
            <param name="content_path" value="plugin://plugin.video.pov/?mode=navigator.build_shortcut_folder_list&amp;name=FENtastic+-+%D7%A1%D7%A8%D7%98%D7%99%D7%9D+-+%D7%96%D7%90%D7%A0%D7%A8%D7%99%D7%9D&amp;iconImage=genres&amp;shortcut_folder=True&amp;external_list_item=True"/>
            <param name="widget_header" value="[B][COLOR yellow]ז'אנרים[/COLOR][/B]"/>
            <param name="widget_target" value="videos"/>
            <param name="list_id" value="19014"/>
        </include>
'''

TV_PREMIERES_BLOCK = '''        <include content="WidgetListBigPoster">
            <param name="content_path" value="plugin://plugin.video.pov/?name=32460&amp;action=tmdb_tv_premieres&amp;iconImage=fresh&amp;mode=build_tvshow_list"/>
            <param name="widget_header" value="[B][COLOR yellow]סדרות חדשות[/COLOR][/B]"/>
            <param name="widget_target" value="videos"/>
            <param name="list_id" value="22015"/>
        </include>
'''

TV_GENRES_BLOCK = '''        <include content="WidgetListBigEpisodes">
            <param name="content_path" value="plugin://plugin.video.pov/?mode=navigator.build_shortcut_folder_list&amp;name=FENtastic+-+%D7%A1%D7%93%D7%A8%D7%95%D7%AA+-+%D7%96%D7%90%D7%A0%D7%A8%D7%99%D7%9D&amp;iconImage=genres&amp;shortcut_folder=True&amp;external_list_item=True"/>
            <param name="widget_header" value="[B][COLOR yellow]ז'אנרים[/COLOR][/B]"/>
            <param name="widget_target" value="videos"/>
            <param name="list_id" value="22014"/>
        </include>
'''

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


def _include_block_containing(content, token):
    pattern = re.compile(
        r'([ \t]*<include\s+content="[^"]+">\s*'
        r'(?:(?!</include>).)*?' + re.escape(token)
        + r'(?:(?!</include>).)*?</include>\s*)',
        re.DOTALL,
    )
    return pattern.search(content)


def _insert_after_token(content, anchor_token, block):
    match = _include_block_containing(content, anchor_token)
    if match is None:
        return content, False
    return content[:match.end(1)] + block + content[match.end(1):], True


def _ensure_content_widgets(filename, content):
    """Repair the dedicated FENtastic Movies/TV Shows page widgets."""
    changed = False
    if filename == 'script-fentastic-widget_movies.xml':
        if 'tmdb_movies_popular' not in content:
            content, did = _insert_after_token(
                content, 'tmdb_movies_latest_releases',
                MOVIES_POPULAR_BLOCK)
            changed = changed or did
        if 'FENtastic+-+%D7%A1%D7%A8%D7%98%D7%99%D7%9D+-+%D7%96%D7%90%D7%A0%D7%A8%D7%99%D7%9D' not in content:
            content, did = _insert_after_token(
                content,
                '%D7%A1%D7%A8%D7%98%D7%99%D7%9D+-+%D7%9C%D7%A4%D7%99+%D7%A8%D7%A9%D7%AA%D7%95%D7%AA',
                MOVIES_GENRES_BLOCK)
            changed = changed or did
    elif filename == 'script-fentastic-widget_tvshows.xml':
        if 'tmdb_tv_premieres' not in content:
            content, did = _insert_after_token(
                content, 'trakt_tv_trending',
                TV_PREMIERES_BLOCK)
            changed = changed or did
        if 'FENtastic+-+%D7%A1%D7%93%D7%A8%D7%95%D7%AA+-+%D7%96%D7%90%D7%A0%D7%A8%D7%99%D7%9D' not in content:
            content, did = _insert_after_token(
                content,
                '%D7%A1%D7%93%D7%A8%D7%95%D7%AA+-+%D7%9C%D7%A4%D7%99+%D7%A8%D7%A9%D7%AA%D7%95%D7%AA',
                TV_GENRES_BLOCK)
            changed = changed or did
    return content, changed


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
        new_content = content
        header_status = 'unchanged'
    else:
        new_content, n = PATTERN.subn(REPLACEMENT, content, count=1)
        if n == 0:
            new_content = content
            header_status = 'unmatched'
        else:
            header_status = 'patched'

    new_content, widgets_changed = _ensure_content_widgets(
        filename, new_content)
    if new_content == content:
        _log('{0}: already migrated'.format(filename), level='DEBUG')
        return header_status
    if header_status == 'unmatched' and not widgets_changed:
        _log('{0}: no Trakt-subtitle header found -- '
             'leaving file alone'.format(filename), level='INFO')
        return 'unmatched'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        if widgets_changed:
            _log('{0}: content widgets repaired'.format(filename),
                 level='INFO')
            return 'widgets_patched' if header_status != 'patched' else 'patched'
        _log('{0}: header rewritten'.format(filename), level='INFO')
        return header_status
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
