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
    import xbmc
    import xbmcvfs
except Exception:
    xbmc = None
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
            <param name="content_path" value="plugin://plugin.video.pov/?iconImage=genres.png&amp;menu_type=movie&amp;mode=navigator.genres&amp;name=32470"/>
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
            <param name="content_path" value="plugin://plugin.video.pov/?iconImage=genres.png&amp;menu_type=tvshow&amp;mode=navigator.genres&amp;name=32470"/>
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


# One-shot marker for the ADD-if-absent widget seeds below. These widget XMLs
# are the same files FENtastic's own widget editor writes user customisations
# into (and the wizard's quick-update extractor deliberately preserves them for
# that reason). Re-adding a missing block on EVERY start meant a user who
# deleted one of our widget rows got it back on the next boot, forever. Now the
# blocks are seeded once per device; afterwards the user owns the widget list.
# The old->new URL migrations and header rewrite still run every start -- they
# only match our own previous baselines, never a user-authored row.
_WIDGET_SEED_FLAG = '_fen_widgets_seeded'
_WIDGET_SEED_VERSION = 'v1'


def _widgets_already_seeded():
    if kodi_utils is None:
        return False
    try:
        return (kodi_utils.get_setting(_WIDGET_SEED_FLAG, '')
                == _WIDGET_SEED_VERSION)
    except Exception:
        return False


def _mark_widgets_seeded():
    if kodi_utils is None:
        return
    try:
        kodi_utils.set_setting(_WIDGET_SEED_FLAG, _WIDGET_SEED_VERSION)
    except Exception:
        pass


def _ensure_content_widgets(filename, content, allow_insert=True):
    """Repair the dedicated FENtastic Movies/TV Shows page widgets."""
    changed = False
    if filename == 'script-fentastic-widget_movies.xml':
        old_movie_genres = (
            'plugin://plugin.video.pov/?mode=navigator.build_shortcut_folder_list'
            '&amp;name=FENtastic+-+%D7%A1%D7%A8%D7%98%D7%99%D7%9D+-+'
            '%D7%96%D7%90%D7%A0%D7%A8%D7%99%D7%9D&amp;iconImage=genres'
            '&amp;shortcut_folder=True&amp;external_list_item=True'
        )
        new_movie_genres = (
            'plugin://plugin.video.pov/?iconImage=genres.png&amp;'
            'menu_type=movie&amp;mode=navigator.genres&amp;name=32470'
        )
        if old_movie_genres in content:
            content = content.replace(old_movie_genres, new_movie_genres)
            changed = True
        if allow_insert and 'tmdb_movies_popular' not in content:
            content, did = _insert_after_token(
                content, 'tmdb_movies_latest_releases',
                MOVIES_POPULAR_BLOCK)
            changed = changed or did
        if allow_insert and 'menu_type=movie&amp;mode=navigator.genres' not in content:
            content, did = _insert_after_token(
                content,
                '%D7%A1%D7%A8%D7%98%D7%99%D7%9D+-+%D7%9C%D7%A4%D7%99+%D7%A8%D7%A9%D7%AA%D7%95%D7%AA',
                MOVIES_GENRES_BLOCK)
            changed = changed or did
    elif filename == 'script-fentastic-widget_tvshows.xml':
        old_tv_genres = (
            'plugin://plugin.video.pov/?mode=navigator.build_shortcut_folder_list'
            '&amp;name=FENtastic+-+%D7%A1%D7%93%D7%A8%D7%95%D7%AA+-+'
            '%D7%96%D7%90%D7%A0%D7%A8%D7%99%D7%9D&amp;iconImage=genres'
            '&amp;shortcut_folder=True&amp;external_list_item=True'
        )
        new_tv_genres = (
            'plugin://plugin.video.pov/?iconImage=genres.png&amp;'
            'menu_type=tvshow&amp;mode=navigator.genres&amp;name=32470'
        )
        if old_tv_genres in content:
            content = content.replace(old_tv_genres, new_tv_genres)
            changed = True
        if allow_insert and 'tmdb_tv_premieres' not in content:
            content, did = _insert_after_token(
                content, 'trakt_tv_trending',
                TV_PREMIERES_BLOCK)
            changed = changed or did
        if allow_insert and 'menu_type=tvshow&amp;mode=navigator.genres' not in content:
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


def _patch_one(filename, allow_insert=True):
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
        filename, new_content, allow_insert=allow_insert)
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


# The five files FENtastic loads as includes from Includes.xml. They define
# MovieWidgets, TVShowWidgets and Custom1Widgets -- the widget rows behind the
# Movies, TV Shows and IdanPlus menu entries.
RESTORE_FILES = (
    'script-fentastic-widget_movies.xml',
    'script-fentastic-widget_tvshows.xml',
    'script-fentastic-widget_custom1.xml',
    'script-fentastic-widget_custom2.xml',
    'script-fentastic-widget_custom3.xml',
    # Not a widget file, but the same repair with the same evidence. The
    # shipped DialogSeekBar.xml is missing one </control> for the group opened
    # at line 11, so Kodi logs
    #     Unable to load window XML: .../DialogSeekBar.xml. Line 287
    #     Error reading end tag.
    # on every single start and the playback seek bar never loads. The bundled
    # copy is that same file with the one closing tag put back.
    'DialogSeekBar.xml',
)

_XML_REPAIR_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'skin_repair', 'fentastic_xml')


_SKIN_RELOADED = [False]


def _reload_skin_if_fentastic():
    """A restored include only takes effect once the skin re-reads it.

    Kodi resolves includes when the skin loads, so a file put back afterwards
    is invisible until the next load -- which is exactly why "switch to another
    skin and back" was the only thing that ever appeared to help. Do the reload
    here instead of leaving the user to discover it.

    Guarded four ways: only when FENtastic is the active skin, never during
    playback, at most once per service run, and NEVER while POV is being
    cycled.

    That last guard is not theoretical. A user's build broke on exactly this
    pairing: pov_reload had POV disabled to make it re-import its patched
    sources, and this reload landed 0.6 s into that window. ReloadSkin()
    rebuilds every window, the home screen came back with its POV widgets, and
    each one raised "Unknown addon id 'plugin.video.pov'" -- ending with POV's
    own service killed for not stopping in time, and the quick update never
    recording itself as done, so it retried and nagged on every launch. The
    same update applied cleanly when they switched to NOX and back, because
    this patcher does not run on NOX at all. That is what named the pairing.
    """
    if _SKIN_RELOADED[0] or xbmc is None:
        return
    try:
        if xbmc.getCondVisibility('Player.HasMedia'):
            return
        if xbmc.getSkinDir() != SKIN_ADDON_ID:
            return
        # Wait, do not skip: the restored includes are the whole point of this
        # reload, so dropping it would leave the widgets missing until the next
        # skin change. A few seconds later is free; a few seconds early is the
        # bug above.
        # Decided inside the try, acted on outside it: a `return` inside
        # would be swallowed by the except, and the reload would go ahead
        # exactly when it must not.
        settled = True
        try:
            from resources.lib import pov_reload
            settled = pov_reload.wait_until_settled(30)
        except Exception:
            settled = True
        if not settled:
            _log('POV still cycling after 30s; leaving the reload for the '
                 'next service run rather than rebuilding the home screen '
                 'against an add-on that cannot resolve', level='WARNING')
            return
        _SKIN_RELOADED[0] = True
        _log('reloading the skin so the restored widget includes take effect '
             'now, instead of at the next skin change', level='WARNING')
        xbmc.executebuiltin('ReloadSkin()')
    except Exception as e:
        _log('skin reload failed: {0}'.format(e), level='WARNING')


def _is_unparseable(path):
    """True only when the file is definitely not XML Kodi can load.

    Errs towards leaving the file alone: any trouble reading it, or any doubt,
    reads as fine. Only a hard parse failure counts as broken.
    """
    try:
        import xml.etree.ElementTree as _ET
        with open(path, 'rb') as f:
            _ET.fromstring(f.read())
        return False
    except Exception as e:
        if e.__class__.__name__ == 'ParseError':
            return True
        return False


def _restore_missing_widget_files():
    """Put back the widget include files when the skin is missing them.

    They ship inside the build and are absent on real devices anyway, on fresh
    installs and after quick updates alike. Two independent sources say so on
    the same boot -- Kodi logs

        Error loading include file .../script-fentastic-widget_movies.xml:
        Failed to open file (row: 0, col: 0)

    and this patcher logs 'file not found' for the same path. The consequence
    is not subtle: Includes.xml pulls these in at its top, so without them
    MovieWidgets, TVShowWidgets and Custom1Widgets are never defined, Kodi
    reports "Skin has invalid include" for all three, and the Movies, TV Shows
    and IdanPlus screens come up completely empty. That is the "FENtastic has
    no content" report, and it explains why nothing helped: switching skins,
    quick-updating and restarting all assume the file is there to be read.

    Writes a file only when it is MISSING, or when it is present and does not
    parse as XML at all. The second case is not a judgement call: Kodi refuses
    such a file itself and says so in the log, so there is nothing working to
    preserve. Anything that parses is left exactly as it is, whatever it
    contains, so a widget layout the user or the skin's own editor wrote is
    never replaced by ours.
    """
    if xbmcvfs is None:
        return []
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + SKIN_ADDON_ID + '/xml/')
    except Exception:
        return []
    if not os.path.isdir(base):
        return []          # skin not installed -- nothing to repair, retry later
    restored = []
    for name in RESTORE_FILES:
        live = os.path.join(base, name)
        if os.path.exists(live) and not _is_unparseable(live):
            continue
        src = os.path.join(_XML_REPAIR_DIR, name)
        if not os.path.isfile(src):
            continue
        try:
            with open(src, 'rb') as f:
                body = f.read()
            tmp = live + '.kpovtmp'
            with open(tmp, 'wb') as f:
                f.write(body)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, live)
            restored.append(name)
        except OSError as e:
            _log('could not restore {0}: {1}'.format(name, e), level='WARNING')
    return restored


def ensure_patched():
    """Apply the header rewrite to both widget XML files. Returns a
    {filename: status} dict. Add-if-absent widget blocks are seeded once per
    device (see _WIDGET_SEED_FLAG); the marker is only written once BOTH files
    were actually seen, so a not-yet-installed skin retries next start.

    Missing include files are put back FIRST, so the rewrite below has
    something to rewrite instead of reporting 'no_file' forever.
    """
    restored = _restore_missing_widget_files()
    if restored:
        _log('restored {0} missing widget include file(s): {1} -- these define '
             'MovieWidgets/TVShowWidgets/Custom1Widgets, so Movies, TV Shows '
             'and IdanPlus were empty without them'
             .format(len(restored), ', '.join(restored)), level='WARNING')
        _reload_skin_if_fentastic()

    allow_insert = not _widgets_already_seeded()
    results = {name: _patch_one(name, allow_insert=allow_insert)
               for name in WIDGET_FILES}
    if allow_insert and all(
            status not in ('no_file', 'read_failed', 'write_failed')
            for status in results.values()):
        _mark_widgets_seeded()
    return results
