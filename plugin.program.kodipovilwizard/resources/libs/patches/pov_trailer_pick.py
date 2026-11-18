"""Which of a title's trailers POV names (Wizard 0.5.7).

POV asked TMDb for a title's videos in the build's language only and named the first trailer of the
answer. A viewer, Nov 2026, once the home began to play trailers: "for a series, when the only
Hebrew trailer is a later season's, prefer the original trailer -- there usually is one for the
first season; asked for Hebrew trailers it skips the first season's". And the owner: "first of all
a trailer translated to Hebrew when there is one -- for the season itself on a season's poster, for
a film in general -- and for series as he wrote".

So TMDb is asked for the videos in the build's language AND the original ones (one request, as
before: include_video_language), and the choice is:
  * a film: a Hebrew trailer, else an original one;
  * a series: a Hebrew trailer of its first season, else an original trailer of its first season,
    else any Hebrew trailer, else any original one;
  * a season: a Hebrew trailer of that season, else an original trailer of that season, else what
    the series has.
"Hebrew" is TMDb's language of the video. Which season a trailer is of: what its name says
("Season 2", "עונה 3", "העונה השנייה", "Final Season"); when the name says nothing, the season it
was published for -- the first one that began no more than six weeks before the trailer came out.
A trailer published more than a year after the last season began says nothing that way (an old
series whose trailers were uploaded later): it counts as the series' own.
"""
import re

KINDS = ('Trailer', 'Teaser')
EARLY_DAYS = 45         # a season's trailer may come out this long after the season began
STALE_DAYS = 365        # ... and one published this long after the LAST season began tells nothing by its date
LAST = 99               # "final season", "last season": a later season, whichever its number
_NUMBER = re.compile(r'(?:\bseasons?|\bseries|\bstaffel|\bsaison|עונה|עונת)\s*#?\s*(\d{1,2})\b', re.I)
_SHORT = re.compile(r'\bS(\d{1,2})\b')
_WORDS = (
    (1, ('first season', 'season one', 'העונה הראשונה', 'עונה ראשונה')),
    (2, ('second season', 'season two', 'העונה השנייה', 'העונה השניה', 'עונה שנייה', 'עונה שניה')),
    (3, ('third season', 'season three', 'העונה השלישית', 'עונה שלישית')),
    (4, ('fourth season', 'season four', 'העונה הרביעית', 'עונה רביעית')),
    (5, ('fifth season', 'season five', 'העונה החמישית', 'עונה חמישית')),
    (6, ('sixth season', 'season six', 'העונה השישית', 'עונה שישית')),
    (7, ('seventh season', 'season seven', 'העונה השביעית', 'עונה שביעית')),
    (8, ('eighth season', 'season eight', 'העונה השמינית', 'עונה שמינית')),
    (LAST, ('final season', 'last season', 'העונה האחרונה', 'עונה אחרונה', 'עונת הסיום')),
)
PURGE_FLAG = 'povil_trailer_pick_v1'


def named_season(name):
    """The season a trailer's name speaks of, or None."""
    text = name or ''
    found = _NUMBER.search(text) or _SHORT.search(text)
    if found:
        return int(found.group(1))
    low = text.lower()
    for number, words in _WORDS:
        if any(word in low for word in words):
            return number
    return None


def _day(text):
    """Days since year 0 of a date TMDb writes ('2024-05-17' or '2024-05-17T16:00:00.000Z'), or None."""
    try:
        year, month, day = (int(part) for part in str(text)[:10].split('-'))
        return year * 372 + month * 31 + day            # ordering and rough distances are all that is asked
    except Exception:
        return None


def dated_season(published, seasons):
    """The season a trailer was published for, by the dates the seasons began; None when that tells nothing."""
    out = _day(published)
    began = sorted((s.get('season_number'), _day(s.get('air_date'))) for s in seasons or []
                   if isinstance(s, dict) and s.get('season_number') and _day(s.get('air_date')))
    if out is None or not began:
        return None
    if out > began[-1][1] + STALE_DAYS:
        return None
    for number, day in began:
        if out <= day + EARLY_DAYS:
            return number
    return began[-1][0]


def season_of(video, seasons):
    named = named_season(video.get('name'))
    if named is not None:
        return named
    if len([s for s in seasons or [] if isinstance(s, dict) and s.get('season_number')]) <= 1:
        return 1
    return dated_season(video.get('published_at'), seasons)


def trailers(videos):
    """The YouTube trailers of TMDb's answer, trailers before teasers, otherwise in TMDb's order."""
    found = [v for v in videos or [] if isinstance(v, dict) and v.get('site') == 'YouTube' and v.get('type') in KINDS and v.get('key')]
    return sorted(found, key=lambda v: KINDS.index(v['type']))


def _first(found, lang, wanted):
    """The key of the first Hebrew trailer wanted(video) accepts, else of the first other one."""
    for hebrew in (True, False):
        for video in found:
            if ((video.get('iso_639_1') or '') == lang) == hebrew and wanted(video):
                return video['key']
    return None


def pick(videos, data=None, lang='he', mediatype='movie'):
    """The key of the trailer to name for a film or a series, or None when it has none."""
    found = trailers(videos)
    if not found:
        return None
    lang = (lang or 'he')[:2]
    if mediatype != 'movie':
        seasons = (data or {}).get('seasons') or (data or {}).get('season_data')
        early = _first(found, lang, lambda v: season_of(v, seasons) in (1, None))
        if early:
            return early
    return _first(found, lang, lambda v: True)


def for_season(meta, season, lang='he', address='plugin://plugin.video.youtube/play/?video_id=%s'):
    """The address of the trailer of one season of a series, or None (the series' own then stands)."""
    try:
        season = int(season)
    except Exception:
        return None
    seasons = (meta or {}).get('season_data')
    key = _first(trailers((meta or {}).get('all_trailers')), (lang or 'he')[:2], lambda v: season_of(v, seasons) == season)
    return address % key if key else None


def _no_trailer(meta):
    """Does a cached title (POV keeps it as JSON) name no trailer? An entry that cannot be read is left alone."""
    import json
    try:
        return not json.loads(meta).get('trailer')
    except Exception:
        return False


def purge_once(folder, connect=None, log=lambda text: None):
    """Once per device: what POV has in its cache was asked for Hebrew videos only, and an older
    title stays there for half a year. The series are let go -- any of them may now name another
    trailer -- and so are the films that name no trailer (in the QA Kodi 676 of 1,090: they have an
    original one to gain); a film that names a trailer names its Hebrew one and is left. Each is
    asked again, with the original videos, the next time it is shown. Returns the number of titles
    let go, or None when there was nothing to do."""
    import os
    flag = os.path.join(folder, PURGE_FLAG)
    cache = os.path.join(folder, 'metacache.db')
    if os.path.exists(flag) or not os.path.isfile(cache):
        return None
    if connect is None:
        import sqlite3
        connect = sqlite3.connect
    con = connect(cache, timeout=10.0)
    try:
        gone = con.execute("DELETE FROM metadata WHERE db_type = 'tvshow'").rowcount
        films = [(tmdb,) for tmdb, meta in con.execute("SELECT tmdb_id, meta FROM metadata WHERE db_type = 'movie'").fetchall()
                 if _no_trailer(meta)]
        con.executemany("DELETE FROM metadata WHERE db_type = 'movie' AND tmdb_id = ?", films)
        con.commit()
    finally:
        con.close()
    with open(flag, 'w') as handle:
        handle.write('1')
    log('trailer pick: %d series and %d films with no trailer will be asked again' % (gone, len(films)))
    return gone + len(films)
