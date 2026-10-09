"""Read the native last-episode rows through the existing watched-history index."""

WINDOW_QUERY = '''
    SELECT media_id, title, last_played, season, episode
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY media_id ORDER BY season DESC, episode DESC
        ) AS r
        FROM watched_status
        WHERE db_type = ?
    ) AS t
    WHERE r = 1
'''

SEEK_QUERY = '''
    SELECT media_id, title, last_played, season, episode
    FROM watched_status
    WHERE rowid IN (
        SELECT (
            SELECT rowid FROM watched_status AS history
            WHERE history.db_type = ? AND history.media_id IS shows.media_id
            ORDER BY history.season DESC, history.episode DESC, history.rowid ASC
            LIMIT 1
        )
        FROM (SELECT DISTINCT media_id FROM watched_status WHERE db_type = ?) AS shows
    )
    ORDER BY media_id
'''


def _has_seek_index(cursor):
    if any(str(row[1]).lower() in ('rowid', '_rowid_', 'oid')
           for row in cursor.execute('PRAGMA table_info(watched_status)').fetchall()):
        return False
    expected = ('db_type', 'media_id', 'season', 'episode')
    for row in cursor.execute('PRAGMA index_list(watched_status)').fetchall():
        if not row[2] or (len(row) > 4 and row[4]):
            continue
        name = str(row[1]).replace('"', '""')
        columns = tuple(item[2] for item in cursor.execute('PRAGMA index_info("' + name + '")').fetchall())
        if columns == expected:
            # Preserve native tie order for legacy NULL episode rows. A custom
            # descending or collated index is not the official schema.
            keys = [item for item in cursor.execute('PRAGMA index_xinfo("' + name + '")').fetchall()
                    if len(item) > 5 and item[5]]
            if (len(keys) == 4 and all(not item[3] and item[4] == 'BINARY' for item in keys)):
                return True
    return False


def next_episodes(native, watched_indicators):
    """Keep fresh provider state and full rows; add no watched-state cache or index."""
    dropped = native['get_dropped_info_tv'](watched_indicators)
    connection = native['_database_connect'](watched_indicators)
    try:
        cursor = native['set_PRAGMAS'](connection)
        try:
            if _has_seek_index(cursor):
                rows = cursor.execute(SEEK_QUERY, ('episode', 'episode')).fetchall()
            else:
                rows = cursor.execute(WINDOW_QUERY, ('episode',)).fetchall()
        except Exception:
            # Older/custom schemas (including WITHOUT ROWID) retain the native query.
            rows = cursor.execute(WINDOW_QUERY, ('episode',)).fetchall()
        return [{'media_ids': {'tmdb': row[0]}, 'last_played': row[2],
                 'season': row[3], 'episode': row[4]}
                for row in rows if int(row[0]) not in dropped]
    finally:
        connection.close()
