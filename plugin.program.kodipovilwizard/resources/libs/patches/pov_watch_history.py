"""Build native TV history groups once, without copying each episode prefix."""


def tv_history(native, watched_indicators):
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
