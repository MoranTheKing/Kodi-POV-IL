"""Build native TV history groups once, without copying each episode prefix."""
from contextvars import ContextVar
import sys


_next_history = ContextVar('povil_next_episode_history', default=None)


def next_constructor(instance, constructor, params, reader):
    """Run the native constructor with a single, exception-safe unused-read ticket."""
    context = None
    if (params.get('mode') == 'build_next_episode' and
            hasattr(constructor, '__code__') and hasattr(reader, '__code__')):
        context = (instance, constructor.__code__, reader.__code__)
    token = _next_history.set(context)
    try:
        return constructor(params)
    finally:
        _next_history.reset(token)


def _unused_next_history():
    context = _next_history.get()
    if context is None:
        return False
    _next_history.set(None)  # A ticket can skip exactly one explicitly scoped read.
    try:
        reader = sys._getframe(2)
        caller = reader.f_back
        return (reader.f_code is context[2] and caller is not None and
                caller.f_code is context[1] and caller.f_locals.get('self') is context[0])
    except ValueError:
        return False


def tv_history(native, watched_indicators):
    if _unused_next_history():
        return native['MappingProxyType']({})
    groups = {}
    connection = None
    try:
        command = native['GET_MOVIE_SHOW'] % (
            'media_id, title, last_played, season, episode')
        connection = native['_database_connect'](watched_indicators)
        cursor = native['set_PRAGMAS'](connection)
        for row in cursor.execute(command, ('episode',)).fetchall():
            # Keep the native database's ordering, ID types and complete rows.
            # Tuple concatenation on every episode copies an ever larger
            # prefix; append first, then make the same immutable result once.
            groups.setdefault(row[0], []).append(row)
    except Exception:
        pass  # Same empty/partial-history behavior as the native read.
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return native['MappingProxyType']({key: tuple(rows) for key, rows in groups.items()})
