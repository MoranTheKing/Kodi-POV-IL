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

THE ALTERNATIVES (0.5.11). The owner, a day into the home's trailers: "the trailers are really
short -- surely a film has several; play the regular or the long ones, not a ten-second clip. How
am I to know in ten seconds whether I want to watch?" TMDb does not say how long a video is, and
the Hebrew "trailer" of a film is often a distributor's ten-second spot. So the address POV names
carries, after the chosen trailer, up to ALTERNATIVES more in the same order of preference
(...video_id=FIRST&povil_alt=SECOND.THIRD -- the YouTube add-on ignores the extra field, seen in
the QA Kodi), and the home's trailer desk, which learns each one's length when it reads its
stream, plays the first that is long enough (trailers.py).

A SEASON'S OWN VIDEOS (0.5.36). TMDb keeps many a season's trailers on the season, not on the
series: Dexter: Resurrection, Nov 2026 -- "Season 2 Official Trailer" and its two teasers are
listed under season 2 only, and a viewer saw the series' trailer on season 2's poster ("it did
not change to another trailer"). POV reads the series' videos only. So the seasons' list asks
TMDb once more, for the videos of all its seasons in one request (append_to_response, up to
APPEND_MAX seasons each; POV's own cache keeps the answer SEASON_VIDEOS_HOURS), and a season's
own trailers come first. Which season and series each one is of is kept for the Wizard
(OWNERS_FILE): the trailer's subtitles and their post name the title by it (trailers.py).
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
PURGE_FLAG = 'povil_trailer_pick_v2'      # (v2: every cached title is asked again -- its trailer gets its alternatives)
ALTERNATIVES = 3
ALT_FIELD = '&povil_alt='
APPEND_MAX = 20                 # TMDb's limit of append_to_response
SEASON_VIDEOS_HOURS = 48
OWNERS_FILE = 'season_trailers.json'
OWNERS_KEEP = 3000
_SEASON_VIDEOS = {}             # the series' TMDb id -> {season: [its own videos]}, for for_season in this run


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


def _all(found, lang, wanted):
    """The keys of the trailers wanted(video) accepts: the Hebrew ones, then the others."""
    keys = []
    for hebrew in (True, False):
        for video in found:
            if ((video.get('iso_639_1') or '') == lang) == hebrew and wanted(video) and video['key'] not in keys:
                keys.append(video['key'])
    return keys


def ranked(videos, data=None, lang='he', mediatype='movie'):
    """Every trailer of a film or a series, the one to name first."""
    found = trailers(videos)
    lang = (lang or 'he')[:2]
    keys = []
    if mediatype != 'movie':
        seasons = (data or {}).get('seasons') or (data or {}).get('season_data')
        keys = _all(found, lang, lambda v: season_of(v, seasons) in (1, None))
    return keys + [key for key in _all(found, lang, lambda v: True) if key not in keys]


def with_alternatives(keys):
    """What follows "video_id=" in the address: the first key, then the next few as alternatives."""
    if not keys:
        return None
    rest = keys[1:1 + ALTERNATIVES]
    return keys[0] + (ALT_FIELD + '.'.join(rest) if rest else '')


def pick(videos, data=None, lang='he', mediatype='movie'):
    """The trailer to name for a film or a series -- its key, with its alternatives -- or None when it has none."""
    return with_alternatives(ranked(videos, data, lang, mediatype))


def for_season(meta, season, lang='he', address='plugin://plugin.video.youtube/play/?video_id=%s'):
    """The address of the trailer of one season of a series, or None (the series' own then stands): the season's own
    videos (read_season_videos) first, then the series' videos of that season; Hebrew ones first."""
    try:
        season = int(season)
    except Exception:
        return None
    meta = meta or {}
    seasons = meta.get('season_data')
    own = [v for v in _SEASON_VIDEOS.get(str(meta.get('tmdb_id') or ''), {}).get(season) or []
           if isinstance(v, dict) and named_season(v.get('name')) in (None, season)]
    dated = [v for v in meta.get('all_trailers') or [] if isinstance(v, dict) and season_of(v, seasons) == season]
    named = with_alternatives(_all(trailers(own + dated), (lang or 'he')[:2], lambda v: True))
    return address % named if named else None


def season_videos_url(tmdb_id, numbers, lang='he'):
    return '/3/tv/%s?append_to_response=%s&include_video_language=%s,en,null' % (
        tmdb_id, ','.join('season/%d/videos' % n for n in numbers), (lang or 'he')[:2])


def read_season_videos(meta, numbers, lang='he', get=None, cache=None, owners=None):
    """Ask TMDb (through POV's own request and cache: get, cache) for the videos the seasons `numbers` of the series
    `meta` keep themselves; for for_season. Returns {season: [videos]}. owners: the file the Wizard reads them from."""
    tmdb = str((meta or {}).get('tmdb_id') or '')
    wanted = sorted({int(n) for n in numbers or [] if str(n).isdigit() and 0 < int(n) < 100})
    if not tmdb or not wanted:
        return {}
    if get is None:
        from indexers.tmdb_api import get_tmdb as get
    if cache is None:
        from caches.main_cache import cache_object as cache

    def fetch(url):
        answer = get(url)
        if not isinstance(answer, dict):
            return None            # (not kept: asked again next time)
        return {k: v for k, v in answer.items() if k.startswith('season/')}
    found = {}
    for start in range(0, len(wanted), APPEND_MAX):
        chunk = wanted[start:start + APPEND_MAX]
        answer = cache(fetch, 'povil_season_videos_%s_%s_%s' % (tmdb, (lang or 'he')[:2], '.'.join(map(str, chunk))),
                       season_videos_url(tmdb, chunk, lang), expiration=SEASON_VIDEOS_HOURS)
        for n in chunk:
            got = (answer or {}).get('season/%d/videos' % n) if isinstance(answer, dict) else None
            found[n] = [v for v in (got or {}).get('results') or [] if isinstance(v, dict)]
    _SEASON_VIDEOS[tmdb] = found
    try:
        if owners is None:
            import os
            import xbmcvfs
            folder = xbmcvfs.translatePath('special://profile/addon_data/plugin.program.kodipovilwizard/')
            owners = os.path.join(folder, OWNERS_FILE) if os.path.isdir(folder) else None
        if owners:
            remember(owners, tmdb, found)
    except Exception:
        pass
    return found


def remember(path, tmdb, found, now=None):
    """Keep, for the Wizard, which series and season each season's own trailer is of: {video: [tmdb, season, language,
    time]}. Written only when something is new; the oldest go past OWNERS_KEEP."""
    import json
    import os
    import time
    now = time.time() if now is None else now
    try:
        with open(path, encoding='utf-8') as handle:
            kept = json.load(handle)
        if not isinstance(kept, dict):
            kept = {}
    except (OSError, ValueError):
        kept = {}
    changed = False
    for season, videos in found.items():
        for video in trailers(videos):
            entry = [tmdb, int(season), video.get('iso_639_1') or '']
            if (kept.get(video['key']) or [])[:3] != entry:
                kept[video['key']] = entry + [int(now)]
                changed = True
    if not changed:
        return False
    if len(kept) > OWNERS_KEEP:
        for old in sorted(kept, key=lambda k: (kept[k] + [0, 0, 0, 0])[3])[:len(kept) - OWNERS_KEEP]:
            kept.pop(old, None)
    with open(path + '.tmp', 'w', encoding='utf-8') as handle:
        json.dump(kept, handle)
    os.replace(path + '.tmp', path)
    return True


def season_owner(path, video):
    """(tmdb id, season, language) of a season's own trailer that remember() kept, or None."""
    import json
    try:
        with open(path, encoding='utf-8') as handle:
            entry = json.load(handle).get(video)
        return (str(entry[0]), int(entry[1]), str(entry[2] or '')) if entry else None
    except Exception:
        return None


def _to_renew(meta):
    """Is a cached film (POV keeps it as JSON) to be asked again -- it names no trailer, or names one without
    having been given its alternatives? An entry that cannot be read is left alone."""
    import json
    try:
        return ALT_FIELD not in (json.loads(meta).get('trailer') or '')
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
                 if _to_renew(meta)]
        con.executemany("DELETE FROM metadata WHERE db_type = 'movie' AND tmdb_id = ?", films)
        con.commit()
    finally:
        con.close()
    with open(flag, 'w') as handle:
        handle.write('1')
    log('trailer pick: %d series and %d films will be asked again' % (gone, len(films)))
    return gone + len(films)
