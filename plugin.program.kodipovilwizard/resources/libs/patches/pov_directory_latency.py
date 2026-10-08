"""Measure slow catalogue invocations without logging URLs or account values."""
import sys
import time

import xbmc

_DIRECTORIES = frozenset(('build_movie_list', 'build_tvshow_list',
                          'build_season_list', 'build_episode_list',
                          'build_next_episode', 'build_in_progress_episode'))


def _action(value):
    if (isinstance(value, str) and len(value) <= 64 and
            value.startswith(('tmdb_', 'trakt_', 'mdblist_', 'pov_', 'next_episode', 'in_progress')) and
            all(c.isascii() and (c.isalnum() or c == '_') for c in value)):
        return value
    return 'other' if value else 'none'


def install(native):
    original = native['routing']
    if getattr(original, '_povil_latency', False):
        return
    # A reused interpreter can call Router long after entry import. Count that
    # import only on its first invocation, rather than the entire idle session.
    entry_started = native.get('_povil_entry_started')
    native['_povil_entry_import_seconds'] = (max(0, time.perf_counter()-entry_started)
        if isinstance(entry_started, (int, float)) else 0)

    def routing(sys_obj):
        entry_import = native.pop('_povil_entry_import_seconds', 0)
        started = time.perf_counter()
        try:
            return original(sys_obj)
        finally:
            finished = time.perf_counter()
            # Fast routes incur no extra parse, GUI query or log allocation.
            if finished - started >= 0.25:
                try:
                    params = native['kodi_utils'].parsed_query(sys_obj.argv[2])
                    mode = params.get('mode')
                    if mode in _DIRECTORIES:
                        limit = int(params.get('widget_limit') or 0)
                        kind = 'widget' if limit > 0 else 'directory'
                        xbmc.log('[POV IL timing] kind=%s mode=%s action=%s '
                                 'route_ms=%d entry_ms=%d skin=%s arch=%d' % (
                                     kind, mode, _action(params.get('action')),
                                     round((finished-started)*1000), round((finished-started+entry_import)*1000),
                                     xbmc.getSkinDir(), 64 if sys.maxsize > 2**32 else 32), xbmc.LOGINFO)
                except Exception:
                    pass  # Diagnostics never replace a native result/exception.
    routing._povil_latency = True
    native['routing'] = routing
