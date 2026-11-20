"""A title's trailer behind the home's hero (Onyx), the way a streaming service's own screen plays one.

The owner (Nov 2026), with a video of another app: "the trailer playing on the title itself". What
that takes in Kodi, measured in the QA Kodi:
  * POV gives every title its trailer as the YouTube add-on's address. Handing that address to
    Kodi's player (PlayMedia) puts Kodi's busy dialog over the home for as long as the add-on
    takes to answer -- 1.5 s on a fast PC, and it takes the remote's keys meanwhile -- and the
    first time ever the add-on asks its "Setup Wizard" question. Neither can happen by itself
    on a screen someone is only browsing.
  * The YouTube add-on's own code, asked from a thread of the Wizard's service, answers with the
    stream itself and shows nothing; the stream is then played as a plain address in Kodi's
    preview mode (windowed), which the skin draws behind the hero.

HOW THE SKIN ASKS (as for the ratings, ratings.py): once the screen has rested a few seconds on a
title the skin writes its trailer address to Window(home).Property(povil.tr.ask) and announces it
(NotifyAll(povil.trailer,ask)); when the title changes, a dialog opens or the home is left, it
empties the property and announces "stop". This module writes Window(home).Property(povil.tr.on):
the ask whose trailer it started -- the skin shows the picture only while the two agree.

WHAT IT NEVER DOES: start a trailer while anything else is playing, or stop anything it did not
start. The subtitles add-on leaves alone a playback whose address is the one in povil.tr.file.

ON FOR EVERYONE unless the viewer switches it off (the skin's setting POVILNoTrailers, a tile among
the home's shortcuts) -- the owner, Nov 2026: "on by default for everyone ... every device must be
able to run it ... it has to work in every situation". What that took, each seen in the QA Kodi:

  * THE YOUTUBE ADD-ON'S OWN SERVER. Every stream it names is read through a small server inside
    Kodi that belongs to it, and it SHUTS THAT SERVER DOWN once Kodi has been left alone for half
    a minute -- which is what a viewer resting on the home does. Its own player wakes the server
    before it plays (yt_play.py: ipc_exec(SERVER_WAKEUP)); its door for other add-ons
    (youtube_resolver) does not. A trailer handed to Kodi while that server is down does not
    play, and worse: Kodi's player waits twenty seconds for every one of the stream's parts, and
    Kodi's whole screen waits with it the moment the player is told to stop (twice in one hour,
    several minutes each). So: the server is woken first (light_streams), and before Kodi's
    player hears of the trailer this module reads the stream's first bytes itself, with a short
    wait (reachable). A stream that does not answer is never handed to Kodi. That server also
    refuses callers that are not on a home-network address -- its own address on a phone's mobile
    connection is not one (the owner's phone, Nov 2026: no trailer played at all): the manifest
    is then read, and played, through 127.0.0.1 (reachable). Three trailers in a row that do not
    play and the trailers rest ten minutes, so a device they do not work on is not asked of
    YouTube at every title.
  * THE STOP IS NEVER PYTHON'S OWN Player.stop(). That call waits, holding Python, until Kodi has
    stopped; Kodi, stopping, asks the YouTube add-on's server about the stream (the player's
    open parts, the file's date for Kodi's own records) -- and that server is Python too, so
    it cannot answer until the call returns. Measured: every stop of a trailer froze Kodi's
    screen for 40 s (two waits of 20), and a stop during the opening for minutes. Sent as
    Kodi's built-in (PlayerControl(Stop), which returns at once) the same stop took 0.02 s and
    nothing froze. Desk is handed that built-in as `halt`.
  * A PLAYER THAT IS STILL OPENING IS NOT TOLD TO STOP EITHER: Kodi's screen waits for the player,
    and the player for every part of the stream it has begun to open. The stop is remembered
    and carried out at the trailer's first picture (Desk.stop, Desk.playback_started); the
    picture is not shown meanwhile, and the next title's trailer waits for it.
  * A STOP THAT COMES WHILE THE TRAILER OPENS MAY NOT BE MEANT. On the owner's phone (his second
    log, Nov 2026) the same trailer opened five times in a row and was stopped each time within a
    tenth of a second of its first picture; the fifth stop froze the screen twenty seconds. The
    skin had said "stop" while the trailer was opening -- with Kodi's busy dialog over the home
    what the skin reads of the home is not what it reads a moment later -- the stop was carried
    out at the first picture, the skin asked again, and so on. Now such a stop is looked at
    again half a second after the first picture (Desk._late_stop, wanted_now): if the home is
    on the screen with no dialog and the title is still the one the trailer is of, the trailer
    plays on and the skin's question is put back. A trailer that IS stopped as it begins, twice
    for the same title, leaves that title alone for a while. The log says what the screen looked
    like when the stop came.
  * NOTHING CAN OPEN A TRAILER OVER AND OVER. After the fixes above the owner still saw one case
    (removing a series from "next episode": five opens, a stuck screen, and the removal did not
    happen) that the QA Kodi could not be made to show. So, whatever the cause: one title's
    trailer is opened at most OPENS times in OPENS_S seconds and the title then rests; and no
    trailer starts within ACTION_REST_S seconds of POV being asked to DO something (a menu's
    action, a pressed title -- pov_list_snapshot.serve_early notes it before POV even loads), so
    an action's question or a starting film never finds a trailer opening under it.
  * EVERY DEVICE: left to itself the YouTube add-on names the best stream its own settings allow
    -- of ten trailers three came as 1080p AV1 and one as 4K VP9, which a small box decodes in
    software. The trailer asks for H.264 up to 720p instead (light_streams): every box decodes
    that in its chip. Nothing of the YouTube add-on's own settings is touched; the choice lives
    in this interpreter only.
  * A TRAILER THAT STOPS COMING: Desk.guard watches the clock of the trailer it started; one that
    stands still is stopped, the still comes back, and that title is not asked again for a
    while. Nothing is ever said on the screen -- also not by Kodi: for a play that does not open
    Kodi puts its own "playback failed" box on the screen (seen with an address that answers
    nothing), and when the play was this module's trailer the box is closed (close_failure_box).
  * A FILM STARTED OVER A TRAILER: POV's and Umbrella's players watch their own playback from the
    moment they start it, and the trailer's "stopped" arriving in between made them lose the film
    (no resume point, no watched mark). patches/home_trailer_gone.py stops the trailer and waits
    for it to be gone right before they start (the play guard they already call).
  * Kodi asked every row of the home again whenever a playback started or stopped: the skin's rows
    now carry an order Kodi does not re-ask for (gen_home.py, follows_no_playback).
"""
import os
import re
import threading

SENDER = 'povil.trailer'
ASK, ON = 'povil.tr.ask', 'povil.tr.on'
FILE = 'povil.tr.file'          # the address of the trailer the player was handed: another add-on tells a trailer from a film by it
PEEK = 'povil.tr.peek'          # the title the screen is on, named by the skin at once: its trailer is read while the screen rests
PEEK_S = 0.7                    # ... once the screen has stayed on it this long (not every poster passed on the way:
                                # each reading is several requests to YouTube from the viewer's address -- review)
FOUND_S = 120                   # a trailer read ahead is played within this long of its reading, or read again
FOUND_MAX = 8                   # (the ones read ahead and not asked for: the last few are kept)
OPENING = 'povil.tr.opening'    # set from the moment the player is told to play until the first picture (or the viewer moving on)
OFF_SWITCH = 'POVILNoTrailers'  # the skin's setting: set = the viewer switched the trailers off
HERO_LABEL = 9809               # the home's hidden label that holds the trailer address of the title in the hero (gen_home.py)
YOUTUBE = 'plugin.video.youtube'
# None in the first seconds of this thread. It was a minute -- and this thread is started only after the
# Wizard has seen the home's rows settle and has checked for updates, so a viewer waited well over a minute
# from Kodi's start for the first trailer and took the trailers for broken (the owner, Nov 2026: "it has to
# work right when one enters Kodi"). The start is over by the time this thread exists; a few seconds are
# left for what the Wizard still does right after it.
# It was 8 s, and the trailer was read from YouTube only after them -- 12 s from the home to the first
# trailer on a fast PC (QA Kodi: thread born 2.4 s after the home, 8 s of rest, 1.7 s of reading). The owner,
# Nov 2026: "on the first entry to Kodi the first trailer takes several seconds, without my touching
# anything -- can the first loading be much shorter?" Now 3 s, the trailer is read DURING them (Desk._start)
# and the YouTube add-on's code is loaded as this thread begins (watch: warm).
QUIET_START_S = 3
# Kodi's start: the YouTube add-on's own service may not be up yet when the first trailer is asked for, so its
# server cannot be woken. For this long after this thread began that is waited out and tried again, and is
# not counted among the trailers that did not play (three of those and the trailers rest ten minutes).
START_GRACE_S = 60
START_RETRY_S = 3
MAX_HEIGHT = 720                # what the trailer asks of YouTube: H.264 up to this, which every box decodes in its chip
HEAVY = ('vp9', 'av01', 'hdr', 'hfr', '3d', 'vr')
WAKE_S = 5                      # how long the YouTube add-on's server may take to wake (its own player waits as long)
ANSWER_S = 4.0                  # how long each of the stream's first bytes may take to arrive, read here before Kodi's player hears of it
OPEN_S = 20                     # no picture this long after the player was told to play: given up
OPEN_LIMIT_S = 120              # ... and after this long the opening is taken to be over whatever Kodi said
STALL_S = 8                     # the clock of a playing trailer standing still this long: given up
GIVEN_UP_S = 30 * 60            # a title whose trailer was given up is not asked again for this long
FAILURE_BOX_S = 4.0             # how long Kodi's "playback failed" box is looked for after a trailer failed to open
LOOPBACK = '127.0.0.1'
FAILS, REST_S = 3, 10 * 60      # this many trailers in a row that did not play: none is tried for this long
# the YouTube add-on's server asleep and not woken: its port is looked at (youtube_port.py), at most this often
PORT_CHECK_S = 60
SETTLE_S = 0.5                  # a stop that came while the trailer opened is looked at again this long after the first picture
ACTION = 'povil.pov.action'     # when POV was last asked to do something (pov_list_snapshot.serve_early writes it)
ACTION_REST_S = 12              # no trailer starts this long after it: the action may ask a question, or start a film
OPENS, OPENS_S = 2, 60          # one title's trailer is opened this many times within this long, never more --
#                                 counting only opens that were stopped as they began (a trailer that was watched
#                                 for a while is not counted: browsing back and forth is not a loop)
QUICK_S = 1.0                   # a trailer stopped sooner than this after its first picture was stopped "as it began"
#                                 (the loop on the phone stopped it within 0.13 s; a viewer browsing takes longer to move on)
# Kodi's own box for a play that did not open: its heading is Kodi's string 16026 ("Playback failed");
# any other OK box that happens to be up is not this module's to close
FAILURE_BOX = 'Window.IsActive(okdialog) + String.IsEqual(Control.GetLabel(1),$LOCALIZE[16026])'
MIN_TRAILER_S = 45              # a trailer shorter than this is a spot: an alternative is tried
# The YouTube add-on asks YouTube for a video as several kinds of client and plays the addresses of the last
# that answered. YouTube cuts the streams of this one short: every read past about a minute of the stream is
# refused (403), the player stops asking for anything and the trailer stands still some fifteen seconds in
# (the owner's phone and the QA Kodi, Nov 2026; anxdpanic/plugin.video.youtube issues 1481 and 1483, open
# since Aug 2026 with add-on 7.4.4). Without it the add-on plays the complete streams of its other clients.
CUT_SHORT = ('android_vr',)
# An LG TV (webOS). The owner's LG (webOS 26 firmware, Kodi 21.0, Nov 2026): films play there, but the TV's own
# decoder refused every trailer ("CDVDVideoCodecStarfish: Load failed"), no picture came and the player hung
# opening -- H.264 (0.5.13) and VP9 (0.5.14) alike, both 720p, both through inputstream.adaptive. What Kodi asks the
# TV's decoder with is the codec, the size and the frame rate only (Kodi 21.0 source) -- the manifest names all
# three -- so of what differs from a film, two things are left: the size (a film is 1080p and up), and that a
# film is read by Kodi's own player (FFmpeg), a trailer by inputstream.adaptive. Both are taken away (0.5.16): the
# trailer is 1080p H.264, like a film, and goes to Kodi's own player as an HLS playlist (webos_hls) cut from the
# same YouTube files -- FFmpeg reads that playlist and its pieces as it reads a film over the network.
WEBOS_VIDEO = 'avc1'
WEBOS_HEIGHT = 1080
# A trailer in Hebrew (the owner, Nov 2026: "in the series the trailers are in English with no Hebrew
# translation ... find the trailer with a Hebrew translation, exactly like the original" -- and NOT a machine
# translation: "Google's or YouTube's translation is simply not good"). TMDb lists a Hebrew trailer for few
# series (in the QA Kodi 3 of 20 -- and those three are the ones picked). Two more places, both human:
#   * YouTube itself: an Israeli distributor's or channel's upload whose title says it is translated
#     ("<name> | טריילר מתורגם"). Searched once per title by its Hebrew name (translated_query / translated_pick:
#     the title must say "translated" and name the series or film; YouTube's own machine-translated titles say
#     neither), kept in translated_trailers.json, and tried before TMDb's trailers.
# No subtitles are asked of YouTube for a trailer: its own are speech recognition or a machine translation, and
# asked for every trailer they were refused anyway ("429 Too Many Requests" in the QA Kodi).
# (a Hebrew-dubbed trailer counts too: Disney Israel's for a children's film, say)
TRANSLATED = ('מתורגם', 'מתורגמת', 'תרגום', 'כתוביות בעברית', 'עם כתוביות', 'מדובב', 'מדובבת')
NOT_A_TRAILER = ('ביקורת', 'סיכום', 'תגובה', 'מאחורי הקלעים', 'ראיון', 'review', 'reaction', 'recap', 'explained',
                 'behind the scenes', 'interview', 'full episode', 'פרק מלא')
# A "trailer" that sells a way to watch the film is not one (the owner, Nov 2026, Coco's: a still picture saying
# "watch Coco free, built-in translation, the link in the description"). Checked on every video's own YouTube
# title before it is played -- TMDb's too -- and on the search's results.
NOT_A_TRAILER_EITHER = ('בחינם', 'חינם', 'סרט מלא', 'הסרט המלא', 'לינק', 'קישור', 'בתיאור', 'להורדה', 'full movie',
                        'watch free', 'free online', 'watch online', 'online free', 'download', 'link in', 'in description',
                        'stream free')
# ... and these only next to one of those, or on a channel that is not a distributor's or a service's: yes and
# HOT title real trailers "עכשיו לצפייה ישירה ב-yes VOD"
SELLING_IF_NOT_TRUSTED = ('לצפייה ישירה', 'צפייה ישירה', 'צפייה מלאה')


def selling(title, channel=None):
    """Does a video's title sell a way to watch (a scam, not a trailer)? channel: the uploader when known."""
    plain = ' %s ' % _plain(title)
    if any(' %s ' % _plain(word) in plain for word in NOT_A_TRAILER_EITHER):
        return True
    soft = any(' %s ' % _plain(word) in plain for word in SELLING_IF_NOT_TRUSTED)
    return bool(soft and channel is not None and not trusted(channel))


def video_title(stream):
    """The YouTube video's own title, as the YouTube add-on gives it with the stream."""
    meta = (stream or {}).get('meta') or {}
    return meta.get('title') or ((meta.get('video') or {}).get('title')) or ''
TRANSLATED_FOUND_S, TRANSLATED_NONE_S = 14 * 86400, 3 * 86400     # a search is kept this long (found / none)
# (v2, 0.5.17: searched again under the scam filter; v3, 0.5.30: under the film / series rule, translated_pick)
TRANSLATED_FILE = 'translated_trailers_v3.json'
# A translated trailer of the OTHER kind: a viewer, via the owner, Nov 2026 -- the Pokémon series (1997) played the
# dubbed trailer of the film "Detective Pikachu" (its title names "פוקימון" too). For a series a result that says it is
# a film is left out, for a film one that says it is a series; and one that names a year far from the title's.
FILM_WORDS = ('הסרט', 'סרט', 'the movie', 'movie', 'film')
SERIES_WORDS = ('הסדרה', 'סדרה', 'סדרת', 'עונה', 'עונת', 'season', 'series', 'episode', 'פרק')
# the uploads of Israeli distributors and of the services themselves come first (no channel's logo over the
# picture -- seen in the QA Kodi: YouTube's first answer for one series was a small channel's, its logo on it)
TRUSTED_CHANNELS = ('hit', 'tulip', 'forum film', 'פורום פילם', 'united king', 'יונייטד קינג', 'yes', 'hot', 'netflix',
                    'נטפליקס', 'disney', 'דיסני', 'prime video', 'פריים וידאו', 'apple tv', 'hbo', 'paramount', 'פרמאונט',
                    'סרטי שני', 'globus', 'גלובוס', 'כאן', 'kan', 'keshet', 'קשת', 'reshet', 'רשת', 'cinema city', 'סינמה סיטי',
                    'lev cinema', 'לב')
_HEBREW = re.compile('[\u0590-\u05ff]')


def _plain(text):
    """A name as compared: lower case, letters and digits only, single spaces."""
    return ' '.join(re.sub(r'[^\w]+', ' ', (text or '').lower()).split())


def translated_query(meta):
    """(query, names) for a title's translated trailer on YouTube, from POV's metadata of it; (None, ()) when
    it has no name to look for."""
    title, original = (meta or {}).get('title') or '', (meta or {}).get('original_title') or ''
    names = tuple(n for n in (_plain(title), _plain(original)) if n)
    if not names:
        return None, ()
    name = title if _HEBREW.search(title) else (original or title)
    return '%s טריילר מתורגם' % name, names


def seconds_of(text):
    """'1:49' or '1:02:03' as seconds; None for anything else."""
    parts = (text or '').strip().split(':')
    if not 1 < len(parts) < 4 or not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def search_results(answer):
    """[(title, seconds, video id, channel)] of a YouTube search answer (its own API, the video renderers in it)."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            video = node.get('videoRenderer')
            if isinstance(video, dict) and video.get('videoId'):
                title = ''.join(run.get('text', '') for run in (video.get('title') or {}).get('runs') or [])
                channel = ''.join(run.get('text', '') for run in (video.get('ownerText') or video.get('longBylineText') or {}).get('runs') or [])
                found.append((title, seconds_of((video.get('lengthText') or {}).get('simpleText')), video['videoId'], channel))
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(answer)
    return found


def title_of(rows, key):
    """(meta, hebrew) of the title of POV's cache whose trailer is `key`'s first video -- the title that names it
    as its trailer, else one that lists it -- or (None, False). rows: (db_type, tmdb_id, meta JSON)."""
    import json
    video = video_id(key)
    if not video:
        return None, False
    listed = None
    for db_type, tmdb_id, text in rows:
        try:
            meta = json.loads(text)
        except Exception:
            continue
        videos = [v for v in meta.get('all_trailers') or [] if isinstance(v, dict) and v.get('key') == video]
        hebrew = any(v.get('iso_639_1') == 'he' for v in videos)
        meta = dict(meta, povil_id='%s:%s' % (db_type, tmdb_id))
        if 'video_id=' + video in (meta.get('trailer') or ''):
            return meta, hebrew
        if videos and listed is None:
            listed = (meta, hebrew)
    return listed or (None, False)


def trusted(channel):
    """Is the channel an Israeli distributor's or a service's own (TRUSTED_CHANNELS, a whole word of its name)?"""
    plain = ' %s ' % _plain(channel)
    return any(' %s ' % _plain(name) in plain for name in TRUSTED_CHANNELS)


def other_kind(title, kind, year=None, names=()):
    """Does a result's title say it is the other kind (kind: 'tv' or 'movie'), or name a year far from the title's?
    (A word of the title's own name says nothing: "זה: פרק שני" is a film -- the reviewer.)"""
    plain = ' %s ' % _plain(title)
    words = FILM_WORDS if kind == 'tv' else SERIES_WORDS if kind == 'movie' else ()
    words = [w for w in words if all(' %s ' % _plain(w) not in ' %s ' % n for n in names if n)]
    if any(' %s ' % _plain(word) in plain for word in words):
        return True
    try:
        year = int(str(year)[:4])
    except (TypeError, ValueError):
        return False
    years = [int(y) for y in re.findall(r'(?<!\d)(19\d\d|20\d\d)(?!\d)', title)]
    # (a series runs for years: only a year before it began is another title's)
    return bool(years) and all((y < year - 1) if kind == 'tv' else abs(y - year) > 1 for y in years)


# words that may follow a title's name in an upload's title and still be its own trailer
PLAIN_WORDS = ('טריילר', 'מתורגם', 'מתורגמת', 'מדובב', 'מדובבת', 'רשמי', 'חדש', 'עונה', 'trailer', 'official', 'teaser',
               'season', 'final', 'hd', '4k', 'tv')
# ... and a series' own season, in words ("X: העונה השנייה" -- the reviewer; the ordinals of pov_trailer_pick._WORDS)
SEASON_WORDS = ('עונה', 'העונה', 'עונת', 'season', 'הראשונה', 'ראשונה', 'השנייה', 'השניה', 'שנייה', 'שניה', 'השלישית',
                'שלישית', 'הרביעית', 'רביעית', 'החמישית', 'חמישית', 'השישית', 'שישית', 'השביעית', 'שביעית', 'השמינית',
                'שמינית', 'התשיעית', 'תשיעית', 'העשירית', 'עשירית', 'האחרונה', 'אחרונה', 'החדשה', 'first', 'second', 'third',
                'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'final', 'new', 'one', 'two', 'three',
                'four', 'five', 'six')


def another_title(title, names, kind=None):
    """Does the upload name ANOTHER title that begins with this one's name -- "פוקימון: הבלש פיקאצ'ו" for the series
    "פוקימון", "דיונה: חלק שני" for "דיונה"? The part of its title that holds the name has a colon and words after the
    name that are not a trailer's own (PLAIN_WORDS, a number)."""
    for part in re.split(r'\s[|•\-–—]\s|\|', title or ''):
        if ':' not in part:
            continue
        words = _plain(part).split()
        for name in names:
            name_words = (name or '').split()
            if name_words and words[:len(name_words)] == name_words:
                rest = [w for w in words[len(name_words):] if w not in PLAIN_WORDS and not w.isdigit()]
                if rest and kind == 'tv' and any(w in ('עונה', 'העונה', 'עונת', 'season') for w in words[len(name_words):]):
                    rest = [w for w in rest if w not in SEASON_WORDS]
                if rest:
                    return True
    return False


def translated_pick(results, names, most=2, kind=None, year=None):
    """The video ids of the results that are a translated trailer of the title: the title says translated and
    names the series or film, 45 s to 5 minutes, not a review or the like, and not of the other kind (other_kind).
    Distributors' and services' own first, then the others, each in YouTube's order; `most` at most."""
    results = sorted(results, key=lambda item: not trusted(item[3] if len(item) > 3 else ''))
    picked = []
    for item in results:
        title, seconds, video = item[:3]
        plain = _plain(title)
        if not any(word in title for word in TRANSLATED):
            continue
        if other_kind(title, kind, year, names) or another_title(title, names, kind):
            continue
        if not any(name and (' %s ' % name) in (' %s ' % plain) for name in names):
            continue        # (whole words: "Up" or "היא" is not a part of another word)
        if seconds is None or not MIN_TRAILER_S <= seconds <= 300:
            continue
        if any(word in plain for word in NOT_A_TRAILER) or selling(title, item[3] if len(item) > 3 else ''):
            continue
        if re.match(r'^[\w-]{11}$', video or '') and video not in picked:
            picked.append(video)
        if len(picked) >= most:
            break
    return picked


# ... and if even that shows no picture there, the trailers are switched off on that TV (the settings tile says
# so and turns them back on): the player hung opening there, and would at every start. Kept with the Kodi
# version it happened on -- a TV whose Kodi is upgraded gets its trailers back once.
WEBOS_OFF_FILE = 'trailers_webos_off.json'
WEBOS_WAY = 'hls'               # how an LG TV plays them (0.5.16): a TV that switched them off another way tries once
TRIES = 3                       # ... this many of a title's trailers at most, each costs a second or two
_VIDEO_ID = re.compile(r'[?&]video_id=([\w-]{11})(?:&|$)')
_ALTERNATIVES = re.compile(r'[?&]povil_alt=([\w.-]+)')
_LENGTH = re.compile(r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"')
_SET = re.compile(r'<AdaptationSet\b(.*?)</AdaptationSet>', re.S)
_KIND = re.compile(r'(?:mimeType|contentType)="(video|audio)')
_BASE = re.compile(r'<BaseURL>(.*?)</BaseURL>', re.S)


class Asleep(Exception):
    """The YouTube add-on's server did not wake: no trailer this time (nothing is wrong with the code)."""


def video_id(address):
    """The YouTube id in the trailer address POV gives a title, or None for anything else."""
    address = address or ''
    if not address.startswith('plugin://%s/' % YOUTUBE):
        return None
    found = _VIDEO_ID.search(address)
    return found.group(1) if found else None


def video_ids(address):
    """The trailers a title's address names: the chosen one, then its alternatives (pov_trailer_pick.py)."""
    first = video_id(address)
    if not first:
        return []
    found = _ALTERNATIVES.search(address or '')
    rest = [part for part in (found.group(1).split('.') if found else []) if re.match(r'^[\w-]{11}$', part)]
    return [first] + [part for part in rest if part != first]


def manifest_seconds(manifest):
    """How long the video of a DASH manifest is, in seconds, or None when it does not say."""
    found = _LENGTH.search(manifest or '')
    if not found or not any(found.groups()):
        return None
    hours, minutes, seconds = (float(part) if part else 0.0 for part in found.groups())
    return hours * 3600 + minutes * 60 + seconds


def pick(streams):
    """The stream to play of what the resolver answered: the first that has an address and is not live."""
    for stream in streams or []:
        if isinstance(stream, dict) and stream.get('url') and not stream.get('live'):
            return stream
    return None


def whole_streams(groups, cut_short=CUT_SHORT):
    """The YouTube add-on's groups of clients without those whose streams YouTube cuts short."""
    return tuple((name, tuple(client for client in clients if client not in cut_short)) for name, clients in groups)


def on_webos(app_id, kodi_path, os_info):
    """An LG TV: webOS gives every app its APPID, installs it under /usr/palm/applications, and names itself.
    (Kodi 21 has no System.Platform condition for webOS; the caller passes the APPID only on a Linux that is
    not Android.)"""
    return bool(app_id) or '/usr/palm/applications/' in (kodi_path or '') or 'webos' in (os_info or '').lower()


def webos_guard(path, kodi_version, off, set_off, log, way=WEBOS_WAY):
    """On an LG TV: (back_on_now, switch_off). back_on_now -- the trailers were switched off here on an older
    Kodi, or when they were played another way, and are on again (the file is gone). switch_off() -- the
    trailer showed no picture: off, with the Kodi version and the way."""
    import json
    back = False
    try:
        with open(path, encoding='utf-8') as handle:
            kept = json.load(handle)
        was, was_way = kept.get('kodi'), kept.get('way')
        if not off():
            # the viewer switched them back on by hand: whatever they choose later is theirs, never undone here
            os.remove(path)
        elif was != kodi_version or was_way != way:
            os.remove(path)
            set_off(False)
            back = True
            log('an LG TV (webOS): trailers on again -- %s' % (
                'Kodi is %s now (they were switched off on %s)' % (kodi_version, was) if was != kodi_version
                else 'a new way to play them (%s)' % way))
    except (OSError, ValueError, AttributeError):
        pass

    def switch_off():
        set_off(True)
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump({'kodi': kodi_version, 'way': way}, handle)
        except OSError:
            pass
        log('an LG TV (webOS): the trailer showed no picture -- trailers switched off on this TV '
            '(the settings tile turns them back on)')
    return back, switch_off


def light_streams(video, provider_class, context_class, wake, video_codec='avc1', max_height=MAX_HEIGHT):
    """What the YouTube add-on answers for a trailer when asked for H.264 up to MAX_HEIGHT.

    First its server is woken, as its own player does before it plays (raises Asleep if it is
    not). Then its settings object is asked two things on the way to a stream: which heights and
    which kinds of stream. Both are answered here, on the object of THIS interpreter -- nothing
    is written. So is which of its clients' streams are taken (whole_streams), on the client
    object of this interpreter: the add-on's own playback is as it was.
    """
    provider, context = provider_class(), context_class()
    if not context.ipc_exec(wake, timeout=WAKE_S):
        raise Asleep()
    settings = context.get_settings()
    heights = [quality for quality in settings.mpd_video_qualities() if quality['nom_height'] <= max_height]
    if not heights:
        raise ValueError('no adaptive streams in the YouTube add-on')
    kinds = frozenset(kind for kind in settings.stream_features() if kind not in HEAVY and kind != 'avc1') | frozenset((video_codec, 'mp4a'))
    settings.mpd_video_qualities = lambda value=None: heights
    settings.stream_features = lambda value=None, raw_values=False: sorted(kinds) if raw_values else kinds
    client = provider.get_client(context=context)
    groups = getattr(client, '_client_groups', None)
    if groups:
        client._client_groups = whole_streams(groups)
    streams, _ = client.load_stream_info(video_id=video)
    return sorted(streams or [], key=lambda stream: stream.get('sort', (0, 0)))


def first_addresses(manifest):
    """The address of the first picture stream and of the first sound stream in a DASH manifest."""
    from html import unescape
    found = {}
    for block in _SET.findall(manifest or ''):
        kind, base = _KIND.search(block), _BASE.search(block)
        if kind and base and kind.group(1) not in found:
            found[kind.group(1)] = unescape(base.group(1).strip())
    return [found[kind] for kind in ('video', 'audio') if kind in found]


def _host(url):
    from urllib.parse import urlsplit
    try:
        return urlsplit(url).hostname or ''
    except Exception:
        return ''


def address_kind(url):
    """What kind of address a stream is read at -- for the log, which never carries the address itself."""
    host = _host(url)
    parts = host.split('.')
    if host in ('localhost', '::1') or parts[0] == '127':
        return 'this device'
    try:
        first, second = int(parts[0]), int(parts[1])
    except Exception:
        return 'other'
    if first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168):
        return 'home network'
    return 'other'


def through_this_device(url):
    """The same address reached through the device's own loopback, or None when it already is (or cannot be)."""
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(url)
        if parts.scheme != 'http' or not parts.hostname or address_kind(url) == 'this device':
            return None
        netloc = LOOPBACK + (':%d' % parts.port if parts.port else '')
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return None


def _origin(url):
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return '%s://%s' % (parts.scheme, parts.netloc)


def _why(exc):
    code = getattr(exc, 'code', None)
    return 'HTTP %s' % code if isinstance(code, int) else type(exc).__name__


def reachable(stream, fetch, save=None, log=lambda text: None):
    """The stream to hand to Kodi's player -- read HERE first, with a short wait -- or None.

    fetch(address, headers, seconds, byte range or None) returns what was read. For a DASH
    manifest: the manifest itself, then the first bytes of its first picture stream and of its
    first sound stream. Anything that fails or stays silent is a no, and the log says which step
    and how (never the address).

    THE YOUTUBE ADD-ON'S SERVER MAY REFUSE ITS OWN ADDRESS. It names its streams at the address of
    the device's network interface and answers only callers from a home-network address. On the
    owner's phone (Nov 2026) every trailer ended here with an HTTP error on the manifest: on a
    mobile or a VPN connection that address is not a home-network one. The server listens on
    every interface, so the same manifest is then read through 127.0.0.1, its stream addresses
    are turned the same way, and save(text, address) keeps it where that server serves manifests
    from and returns the address it now has there (Kodi's player does not open a manifest that
    is a file: seen in the QA Kodi, three ways). The stream comes back with that address.
    """
    url, headers = stream.get('url') or '', stream.get('headers') or {}
    if isinstance(headers, str):
        headers = {}
    try:
        if str(stream.get('container') or '').lower() != 'mpd':
            return stream if fetch(url, headers, ANSWER_S, 'bytes=0-1023') else None
    except Exception as exc:
        log('no answer: stream %s' % _why(exc))
        return None
    turned = None
    try:
        manifest = fetch(url, headers, ANSWER_S, None)
    except Exception as first:
        turned = through_this_device(url) if save is not None else None
        if turned is None:
            log('no answer: manifest %s at a "%s" address' % (_why(first), address_kind(url)))
            return None
        try:
            manifest = fetch(turned, headers, ANSWER_S, None)
        except Exception as second:
            log('no answer: manifest %s at a "%s" address, %s through this device' % (_why(first), address_kind(url), _why(second)))
            return None
        log('manifest %s at a "%s" address: read through this device instead' % (_why(first), address_kind(url)))
    if not manifest:
        log('no answer: empty manifest')
        return None
    text = manifest.decode('utf-8', 'replace')
    stream = dict(stream, seconds=manifest_seconds(text))
    if turned:
        text = text.replace(_origin(url), _origin(turned))
    try:
        for address in first_addresses(text):
            if not fetch(address, headers, ANSWER_S, 'bytes=0-1023'):
                log('no answer: empty stream')
                return None
    except Exception as exc:
        log('no answer: stream %s' % _why(exc))
        return None
    if not turned:
        return stream
    try:
        kept = save(text, turned)
    except Exception as exc:
        log('no answer: manifest not kept (%s)' % type(exc).__name__)
        return None
    return dict(stream, url=kept) if kept else None


def parse_sidx(data, start):
    """[(offset, size, seconds)] of the pieces an MP4 file's 'sidx' box lists. data: the bytes of the file's
    index range, which begins at byte `start` of the file (the pieces follow the box)."""
    import struct
    at = data.find(b'sidx')
    if at < 4:
        raise ValueError('no sidx box')
    box = at - 4
    size = struct.unpack('>I', data[box:at])[0]
    version, p = data[at + 4], at + 8
    _reference, timescale = struct.unpack('>II', data[p:p + 8])
    p += 8
    if version == 0:
        _earliest, first = struct.unpack('>II', data[p:p + 8])
        p += 8
    else:
        _earliest, first = struct.unpack('>QQ', data[p:p + 16])
        p += 16
    count = struct.unpack('>H', data[p + 2:p + 4])[0]
    p += 4
    if not timescale or not count or len(data) < p + 12 * count:
        raise ValueError('sidx cut short')
    offset, pieces = start + box + size + first, []
    for _ in range(count):
        reference, duration, _sap = struct.unpack('>III', data[p:p + 12])
        p += 12
        if reference >> 31:
            raise ValueError('sidx of sidx')
        pieces.append((offset, reference & 0x7FFFFFFF, duration / float(timescale)))
        offset += reference & 0x7FFFFFFF
    return pieces


def mpd_choice(manifest, codec='avc1', max_height=WEBOS_HEIGHT):
    """(video, audio) of a DASH manifest the YouTube add-on wrote: each a dict of url, init and index (byte
    ranges as (first, last)), codecs, bandwidth, and for the picture width and height. The picture: the tallest
    of `codec` up to max_height (else the tallest of any); the sound: the default AAC track (else any)."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(manifest)
    ns = {'d': 'urn:mpeg:dash:schema:mpd:2011'}

    def span(text):
        first, _, last = (text or '').partition('-')
        return int(first), int(last)
    videos, audios = [], []
    for aset in root.iterfind('.//d:AdaptationSet', ns):
        kind = aset.get('contentType') or (aset.get('mimeType') or '').partition('/')[0]
        for rep in aset.iterfind('d:Representation', ns):
            base, segment = rep.find('d:BaseURL', ns), rep.find('d:SegmentBase', ns)
            init = segment.find('d:Initialization', ns) if segment is not None else None
            if base is None or init is None or not (base.text or '').strip() or not segment.get('indexRange'):
                continue
            mime = rep.get('mimeType') or aset.get('mimeType') or ''
            if not mime.endswith('/mp4'):
                continue        # (FFmpeg reads MP4 pieces; WebM ones are left to the others)
            item = dict(url=base.text.strip(), init=span(init.get('range')), index=span(segment.get('indexRange')),
                        codecs=rep.get('codecs') or '', bandwidth=int(rep.get('bandwidth') or 0),
                        width=int(rep.get('width') or 0), height=int(rep.get('height') or 0),
                        default=aset.get('default') == 'true')
            (videos if kind == 'video' else audios if kind == 'audio' else []).append(item)
    fits = [v for v in videos if v['height'] <= max_height]
    of_codec = [v for v in fits if v['codecs'].startswith(codec)] or fits
    video = max(of_codec, key=lambda v: (v['height'], v['bandwidth'])) if of_codec else None
    aac = [a for a in audios if a['codecs'].startswith('mp4a')] or audios
    audio = max(aac, key=lambda a: (a['default'], a['bandwidth'])) if aac else None
    return video, audio


def piece_address(address, number):
    """The address of an HLS piece as Kodi 22's FFmpeg takes it: the file's own address, with a field of its own
    that ends in .mp4 (number 0 is the file's header). QA Kodi 22.0 RC2, Nov 2026, the trailer otherwise:
    - "[hls] parse_playlist error Invalid data found when processing input": its FFmpeg reads a piece only from
      an address that ends like a media file, and the YouTube add-on's "/youtube/stream?..." does not -- the
      trailer "did not open";
    - with one address for all the pieces it read the first piece and its next ones as one stream, and the
      picture stopped at the first piece's end (~10 s: the sound's pieces are 10 s long).
    The add-on's server passes over a field it does not know; Kodi 21's FFmpeg checks neither."""
    return '%s%spovil=%d.mp4' % (address, '&' if '?' in address else '?', number)


def media_playlist(stream, pieces):
    """An HLS media playlist of one MP4 file: its header, then its pieces, each a byte range of the same file."""
    import math
    first, last = stream['init']
    lines = ['#EXTM3U', '#EXT-X-VERSION:7', '#EXT-X-TARGETDURATION:%d' % max(1, math.ceil(max(p[2] for p in pieces))),
             '#EXT-X-MEDIA-SEQUENCE:0', '#EXT-X-PLAYLIST-TYPE:VOD',
             '#EXT-X-MAP:URI="%s",BYTERANGE="%d@%d"' % (piece_address(stream['url'], 0), last - first + 1, first)]
    for number, (offset, size, seconds) in enumerate(pieces, 1):
        lines += ['#EXTINF:%.3f,' % seconds, '#EXT-X-BYTERANGE:%d@%d' % (size, offset), piece_address(stream['url'], number)]
    return '\n'.join(lines + ['#EXT-X-ENDLIST', ''])


def master_playlist(video, audio, video_address, audio_address):
    """The HLS playlist Kodi's player is handed: the picture, with the sound as its audio track."""
    return '\n'.join(['#EXTM3U', '#EXT-X-VERSION:7', '#EXT-X-INDEPENDENT-SEGMENTS',
                      '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="audio",DEFAULT=YES,AUTOSELECT=YES,URI="%s"' % audio_address,
                      '#EXT-X-STREAM-INF:BANDWIDTH=%d,RESOLUTION=%dx%d,CODECS="%s,%s",AUDIO="audio"'
                      % (video['bandwidth'] + audio['bandwidth'], video['width'], video['height'], video['codecs'], audio['codecs']),
                      video_address, ''])


def served_address(address, name):
    """The address at which the YouTube add-on's server serves the file `name` of its folder (the server of
    `address`, a manifest it serves)."""
    from urllib.parse import urlsplit, urlunsplit, urlencode
    parts = urlsplit(address)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({'file': name}), ''))


def webos_hls(stream, fetch, save, log=lambda text: None, codec=WEBOS_VIDEO, max_height=WEBOS_HEIGHT):
    """The trailer (a DASH manifest the YouTube add-on serves) as an HLS playlist for Kodi's own player, kept
    beside it; the stream with that address, or None. save(name, text) keeps a file and returns its address."""
    url, headers = stream.get('url') or '', stream.get('headers') or {}
    if isinstance(headers, str):
        headers = {}
    try:
        video, audio = mpd_choice(fetch(url, headers, ANSWER_S, None).decode('utf-8', 'replace'), codec, max_height)
        if not video or not audio:
            log('no HLS: the manifest has no MP4 %s' % ('picture' if not video else 'sound'))
            return None
        from urllib.parse import urlsplit, parse_qs
        manifest_name = (parse_qs(urlsplit(url).query).get('file') or ['trailer.mpd'])[0]
        name = 'povil_hls_' + os.path.basename(manifest_name).rsplit('.', 1)[0]
        made = {}
        for kind, item in (('v', video), ('a', audio)):
            first, last = item['index']
            pieces = parse_sidx(fetch(item['url'], headers, ANSWER_S, 'bytes=%d-%d' % (first, last)), first)
            made[kind] = save('%s_%s.m3u8' % (name, kind), media_playlist(item, pieces))
        master = save(name + '.m3u8', master_playlist(video, audio, made['v'], made['a']))
    except Exception as exc:
        log('no HLS: %s' % _why(exc))
        return None
    return dict(stream, url=master, container='hls', ffmpeg=True, height=video['height'], manifest=url)


def kept_address(address, prefix='povil_'):
    """(file name, address) for a turned manifest kept beside the one the YouTube add-on wrote: the
    add-on's server serves the file named in the address's `file` field from its own folder."""
    from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
    parts = urlsplit(address)
    query = parse_qs(parts.query)
    name = (query.get('file') or [''])[0]
    if not name or name != os.path.basename(name) or not name.endswith('.mpd'):
        return None, None
    query['file'] = [prefix + name]
    return prefix + name, urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ''))


def close_failure_box(visible, run, wait, seconds=FAILURE_BOX_S, step=0.1):
    """A trailer failed to open: Kodi's "playback failed" box, if it comes up, is closed.

    visible(condition) and run(built-in) are Kodi's; wait(seconds) returns True when Kodi is
    closing. Returns True when a box was closed.
    """
    waited = 0.0
    while waited < seconds:
        if visible(FAILURE_BOX):
            run('Dialog.Close(okdialog,true)')
            return True
        if wait(step):
            return False
        waited += step
    return False


def headers_text(headers):
    """The request headers of a stream as Kodi's player properties want them (name=value&name=value)."""
    if not headers:
        return ''
    if isinstance(headers, str):
        return headers
    from urllib.parse import quote
    return '&'.join('%s=%s' % (name, quote(str(value))) for name, value in sorted(headers.items()))


class Desk(object):
    """Starts and stops the home's trailer. Kodi's pieces are handed in, so it runs without Kodi."""

    def __init__(self, home, player, resolve, make_item, enabled, log=lambda text: None, clock=None,
                 ready=lambda stream: stream, halt=None, wanted_now=lambda key: False, look=lambda key: '', settle=0.0,
                 acting=lambda: False, no_picture=None, translated=lambda key: [], repair=lambda: None, subs=None):
        import time
        self.home, self.player, self.resolve, self.make_item = home, player, resolve, make_item
        self.enabled, self.log, self.ready = enabled, log, ready
        # how the player is told to stop: in Kodi a built-in that returns at once, never the player's own stop
        # (see the module's text); without Kodi, the test's own player
        self.halt = halt or player.stop
        # wanted_now(key): is the home on the screen, with no dialog, on the title this trailer is of?
        # look(key): the same in words, for the log. settle: how long after the first picture a stop
        # that came during the opening is looked at again (0: at once, on the caller's thread).
        self.wanted_now, self.look, self.settle = wanted_now, look, settle
        self.acting = acting        # is POV carrying out an action right now (or was a moment ago)?
        self.no_picture = no_picture    # called when a trailer showed no picture at all (an LG TV: switched off)
        self.translated = translated    # the ids of a title's translated trailers on YouTube, tried first ([]: none)
        # repair(): the YouTube add-on did not wake its server -- its port is looked at, and moved when this device
        # does not let it open it (youtube_port.py); truthy when it was moved
        self.repair = repair
        # subs: Hebrew subtitles on the trailer (trailer_subs.Subs) -- told of its first picture and of its end
        self.subs = subs
        self.hebrew_videos = set()      # the translated or dubbed uploads found: Hebrew already, no subtitle over them
        self.port_checked = None
        self.stream = None              # the stream of the trailer this desk handed to the player
        self.opened = {}            # the ask -> when its trailer was handed to the player, the last few times
        self.choice = {}            # the ask -> the one of its trailers that was found long enough (or the longest)
        self.shown = None           # when the trailer on the player showed its first picture
        self.quick = {}             # the ask of a trailer stopped as it began -> how many times in a row
        self.said = 0               # how many times the log was told of a stop during an opening
        self.clock = clock or time.time
        self.born = self.clock()
        self.waiting = threading.Event()        # set when Kodi closes: a waiting trailer gives up at once
        self.ours = None            # the address of the trailer this desk handed to the player, until it is over
        self.key = None             # ... and the ask it was started for
        self.opening = None         # when the player was told to play, until its first picture (or its failing)
        self.stop_wanted = False    # the viewer moved on while it was opening: stopped at its first picture
        self.given_up = {}          # the ask of a trailer that did not play -> when it was given up
        self.failed = 0             # trailers in a row that did not play
        self.resting = 0.0          # ... and until when none is tried because of it
        self.let_go = None          # the address of a trailer this desk forgot before it was seen to end
        self.ticket = 0
        self.lock = threading.Lock()
        self.peek_ticket = 0
        self.found = {}             # the ask -> (stream, why, when): its trailer read ahead, until it is asked for
        self.fetching = {}          # the ask -> an Event, set when the reading of its trailer is over
        self.ahead = threading.Lock()   # one reading ahead at a time: the next waits until the last one stops

    def is_ours(self):
        try:
            return bool(self.ours) and self.player.isPlaying() and self.player.getPlayingFile() == self.ours
        except Exception:
            return False

    def _opening(self):
        """Is the player still opening this desk's trailer? (An opening Kodi never said a word about ends by itself.)"""
        if self.opening is not None and self.clock() - self.opening >= OPEN_LIMIT_S:
            self.opening = None
            if not self.is_ours():
                self._forget()
        return self.opening is not None

    def _forget(self):
        self.shown = None
        # (remembered: should it show a picture after all -- a word of Kodi's about another playback was
        # taken for its failing, or it opened later than anyone waits -- it is stopped then, not left to
        # play unseen with its sound on)
        self.let_go = self.ours or self.let_go
        self.ours = self.key = self.opening = None
        self.stop_wanted = False
        if self.subs is not None:
            self.subs.gone()
        self.home.clearProperty(ON)
        self.home.clearProperty(FILE)
        self.home.clearProperty(OPENING)

    def _busy_with_another(self):
        try:
            return self.player.isPlaying() and not self.is_ours()
        except Exception:
            return True

    def asked(self):
        """The skin asked for the trailer in povil.tr.ask. Returns the job to run off this thread, or None."""
        key = self.home.getProperty(ASK)
        video = video_id(key)
        if not video or not self.enabled() or self._busy_with_another():
            return None
        if self.clock() - self.given_up.get(key, -GIVEN_UP_S) < GIVEN_UP_S or self.clock() < self.resting:
            return None             # it did not play a moment ago (or none does on this device now): the still stays
        if self.acting():
            return None             # POV is doing something the viewer asked for: nothing starts under it
        with self.lock:
            if self.ours and self.key == key and (self.is_ours() or self._opening()):
                # it plays, or is opening: the viewer came back to it before it was stopped
                self.stop_wanted = False
                self.home.setProperty(ON, key)
                return None
        with self.lock:
            self.ticket += 1
            ticket = self.ticket
        # Kodi has just started: the trailer waits until the start is over, and plays then only if
        # this is still the title on screen
        wait = max(0.0, QUIET_START_S - (self.clock() - self.born))
        return lambda: self._start(key, video, ticket, wait)

    def _wanted(self, key, ticket):
        return ticket == self.ticket and self.home.getProperty(ASK) == key

    def _start(self, key, video, ticket, wait=0.0):
        began = self.clock()
        # the trailer before this one is still opening: a player that is opening is left alone
        while self._opening():
            if self.waiting.wait(0.2) or not self._wanted(key, ticket):
                return False
        while True:
            try:
                # (Kodi has just started -- wait: the trailer is read meanwhile, and played when the start is over)
                stream, why, gone = self._obtain(key, lambda: self._wanted(key, ticket))
                break
            except Asleep:
                if self.clock() - self.born < START_GRACE_S:
                    # Kodi's start: the YouTube add-on's service may not be up yet. Tried again in a moment, and
                    # not counted among the trailers that did not play.
                    if self.waiting.wait(START_RETRY_S) or not self._wanted(key, ticket):
                        return False
                    continue
                if self._port_moved():
                    # (not counted: the add-on starts its server again on the new port, and the next title has it)
                    self.log('the YouTube add-on did not wake its server: its port was moved')
                else:
                    self._did_not_play('the YouTube add-on did not wake its server')
                return False
        if gone:
            return False
        rest = wait - (self.clock() - began)
        if rest > 0:
            self.waiting.wait(rest)
            if not self._wanted(key, ticket):
                return False
        with self.lock:
            self.found.pop(key, None)       # (read once, played once: a later visit reads it again)
        if stream is None:
            if why:
                # none answers: never handed to Kodi's player, and this title rests for a while
                self.given_up[key] = self.clock()
                self._did_not_play(why)
            return False
        self.choice[key] = stream['video']
        with self.lock:
            # the answer took a moment: only if this is still the title on screen, and nothing else began
            if not self._wanted(key, ticket) or self._busy_with_another() or self._opening() or self.acting():
                return False
            times = [at for at in self.opened.get(key, []) if self.clock() - at < OPENS_S]
            if len(times) >= OPENS:
                # whatever keeps stopping and asking for it would do so again
                self.given_up[key] = self.clock()
                self.opened.pop(key, None)
                self._did_not_play('opened %d times in %d s: %s' % (OPENS, OPENS_S, video))
                return False
            self.opened[key] = times + [self.clock()]
            url = stream['url']
            self.ours, self.key, self.opening, self.stop_wanted = url, key, self.clock(), False
            self.stream = stream
            # (set before the player starts: the subtitles add-on reads it when the playback begins)
            self.home.setProperty(ON, key)
            self.home.setProperty(FILE, url)
            # (Kodi shows its busy dialog while a playback opens: the skin keeps its spinner off meanwhile)
            self.home.setProperty(OPENING, '1')
            self.player.play(url, self.make_item(url, stream), True)
        return True

    def _find(self, key, still):
        """Read the title's trailer from YouTube: (stream, why, gone). stream None: none found (why: what went
        wrong, if anything did); gone: the title is no longer wanted (still() said no) -- nothing is known.
        Raises Asleep when the YouTube add-on did not wake its server.

        A REAL TRAILER: the title's address names its chosen trailer and a few alternatives; the first
        that is MIN_TRAILER_S long is played, else the longest of those read (the owner: "a ten-second
        clip tells me nothing"). The one found is remembered, so the next visit asks for it alone."""
        stream, why = None, None
        if key in self.choice:
            candidates = [self.choice[key]]
        else:
            try:
                found = list(self.translated(key) or [])
            except Exception as exc:
                self.log('no translated trailer: %s' % _why(exc))
                found = []
            self.hebrew_videos.update(found)
            candidates = (found + [v for v in video_ids(key) if v not in found])[:TRIES + len(found)]
        for number, candidate in enumerate(candidates):
            if number and not still():
                return None, None, True
            try:
                found = pick(self.resolve(candidate))
                if found is not None and selling(video_title(found)):
                    self.log('not a trailer (it sells a way to watch): %s' % candidate)
                    continue
            except Asleep:
                raise
            except Exception as exc:
                why = '%s: %s' % (type(exc).__name__, str(exc)[:160])
                continue
            if found is None:
                continue
            if not still():
                return None, None, True
            found = self.ready(found)
            if not found:
                why = 'given up (no answer): %s' % candidate
                self.choice.pop(key, None)      # (the one remembered no longer answers: its alternatives next time)
                continue
            found = dict(found, video=candidate, hebrew=candidate in self.hebrew_videos)
            seconds = found.get('seconds')
            if stream is None or (seconds or 0) > (stream.get('seconds') or 0):
                stream = found
            if seconds is None or seconds >= MIN_TRAILER_S:
                break
        return stream, why, False

    def _obtain(self, key, still):
        """_find's answer for the title: the one read ahead a moment ago, the one being read now (waited for
        while still() holds), or one read here."""
        while True:
            with self.lock:
                kept = self.found.get(key)
                if kept is not None and self.clock() - kept[2] < FOUND_S:
                    return kept[0], kept[1], False
                event = self.fetching.get(key)
                if event is None:
                    event = self.fetching[key] = threading.Event()
                    break
            while not event.is_set():
                if self.waiting.wait(0.1) or not still():
                    return None, None, True
            # (over: its answer is kept now -- or that reading was given up as the viewer moved on: read here)
        try:
            stream, why, gone = self._find(key, still)
            if not gone:
                with self.lock:
                    self.found[key] = (stream, why, self.clock())
                    for old in sorted(self.found, key=lambda name: self.found[name][2])[:-FOUND_MAX]:
                        self.found.pop(old, None)
            return stream, why, gone
        finally:
            with self.lock:
                self.fetching.pop(key, None)
            event.set()

    def peeked(self):
        """The skin named the title the screen is on (povil.tr.peek). Its trailer is read now, so it is ready
        when the screen has rested on the title and the skin asks for it (the owner, Nov 2026: "as fast as
        possible, almost at once"). Returns the job to run off this thread, or None."""
        key = self.home.getProperty(PEEK)
        if not video_id(key) or not self.enabled() or self._busy_with_another() or self.acting():
            return None
        if self.clock() - self.given_up.get(key, -GIVEN_UP_S) < GIVEN_UP_S or self.clock() < self.resting:
            return None
        if self.clock() - self.born < QUIET_START_S:
            return None             # Kodi is starting: the ask reads it, after the start
        with self.lock:
            if self.ours and self.key == key:
                return None         # it plays, or is opening
            self.peek_ticket += 1
            ticket = self.peek_ticket
        return lambda: self._read_ahead(key, ticket)

    def _read_ahead(self, key, ticket):
        def still():
            return ticket == self.peek_ticket and key in (self.home.getProperty(PEEK), self.home.getProperty(ASK))
        if self.waiting.wait(PEEK_S) or not still():
            return False
        # (the one before, of a title the screen has left, stops at its next step: its still() says no)
        while not self.ahead.acquire(timeout=0.1):
            if self.waiting.is_set() or not still():
                return False
        try:
            self._obtain(key, still)
        except Asleep:
            pass                    # (the ask says so, when it comes)
        except Exception as exc:
            self.log('read ahead: %s' % _why(exc))
        finally:
            self.ahead.release()
        return False

    def _port_moved(self):
        now = self.clock()
        if self.port_checked is not None and now - self.port_checked < PORT_CHECK_S:
            return False
        self.port_checked = now
        try:
            return bool(self.repair())
        except Exception as exc:
            self.log('the YouTube add-on\'s port was not checked: %s' % _why(exc))
            return False

    def _did_not_play(self, why):
        """One more trailer that did not play; FAILS of them in a row and the trailers rest."""
        self.failed += 1
        self.log(why)
        if self.failed >= FAILS:
            self.failed = 0
            self.resting = self.clock() + REST_S
            self.log('%d trailers in a row did not play: none is tried for %d minutes' % (FAILS, REST_S // 60))

    def guard(self, tick=1.0):
        """Watches the trailer this desk has just started, on the thread that started it. One that
        shows no picture within OPEN_S is given up without a word to the player (see stop); one
        whose clock stands still for STALL_S while it plays is stopped. Either way its title is
        not asked again for a while. Returns True when it gave the trailer up."""
        with self.lock:
            url, key, ticket = self.ours, self.key, self.ticket
        if not url:
            return False
        last, moved, seen = None, self.clock(), False
        while not self.waiting.wait(tick):
            with self.lock:
                # ended, or something else has the player; or the viewer moved on after its first picture. A
                # viewer moving on while it still OPENS changes nothing here: the stop waits for that picture,
                # and one that never comes is still a trailer that showed no picture (the owner's LG, 0.5.14:
                # the player hung opening, he moved on after nine seconds, and nothing counted it)
                if self.ours != url or (ticket != self.ticket and self.opening is None):
                    return False
            try:
                now = self.player.getTime() if self.is_ours() else None
            except Exception:
                now = None
            if now is not None and now > 0 and now != last:
                last, moved, seen = now, self.clock(), True
            elif self.clock() - moved >= (STALL_S if seen else OPEN_S):
                with self.lock:
                    if self.ours != url or (ticket != self.ticket and self.opening is None):
                        return False
                    self.given_up[key] = self.clock()
                    self.home.clearProperty(ON)
                    self.home.clearProperty(OPENING)
                    if self.opening is not None:
                        self.stop_wanted = True     # still opening: stopped if it ever shows a picture
                    else:
                        ours = self.is_ours()
                        self._forget()
                        if ours:
                            self.halt()
                self._did_not_play('given up (%s): %s' % ('stood still' if seen else 'no picture', video_id(key)))
                if not seen and self.no_picture:
                    self.no_picture()
                return True
        return False

    def stop(self):
        """The skin moved on: stop the trailer -- only if it is this desk's that plays.

        A player that is still OPENING is never told to stop: Kodi's screen waits for the player,
        and the player for every part of the stream it has begun to open (seen: minutes). The
        picture is taken off the screen now; the player is stopped at its first picture.
        """
        with self.lock:
            self.ticket += 1        # an answer still on its way is no longer wanted
            self.home.clearProperty(ON)
            self.home.clearProperty(OPENING)
            if self.ours and self._opening():
                self.stop_wanted = True
                if self.said < 5:
                    self.said += 1
                    self.log('stop while opening (%s)' % self.look(self.key))
                return False
            ours = self.is_ours()
            if ours:
                self._stopped_early(self.key)
            self._forget()
            if ours:
                self.halt()
        return ours

    def _stopped_early(self, key):
        """A trailer is being stopped: was it as it began? Twice in a row for one title and the title is
        left alone for a while -- whatever stops it would stop it again (seen: five times in ten seconds)."""
        if self.shown is not None and self.clock() - self.shown >= QUICK_S:
            # it was watched for a while: neither "as it began" nor one of the opens that are counted --
            # a viewer going back and forth between two titles sees their trailers every time
            self.quick.pop(key, None)
            self.opened.pop(key, None)
            return
        self.quick[key] = self.quick.get(key, 0) + 1
        if self.quick[key] >= 2:
            self.quick.pop(key, None)
            self.given_up[key] = self.clock()
            self._did_not_play('stopped as it began, twice: %s' % video_id(key))

    def _late_stop(self, url, key):
        """The trailer has shown its first picture and a stop came while it opened: look again."""
        if self.settle:
            self.waiting.wait(self.settle)
        try:
            wanted = bool(self.wanted_now(key))
        except Exception:
            wanted = False
        with self.lock:
            if self.ours != url or not self.stop_wanted:
                return
            self.stop_wanted = False
            if wanted and self.is_ours():
                # not meant: the title is still on the screen. The skin's question is put back, so it
                # neither asks again nor hides the picture
                self.home.setProperty(ASK, key)
                self.home.setProperty(ON, key)
                self.log('a stop that came while the trailer opened was not meant: it plays on')
                return
            ours = self.is_ours()
            if ours:
                self.shown = None       # stopped because of what happened while it opened: "as it began"
                self._stopped_early(key)
            self._forget()
            if ours:
                self.halt()

    def playback_over(self):
        """Kodi says a playback ended, stopped or failed. Returns True when it was this desk's
        trailer and it never showed a picture (Kodi then has a box to say so, which nobody wants)."""
        with self.lock:
            if self.ours and not self.is_ours():
                failed = self.opening is not None
                if failed:
                    self.given_up[self.key] = self.clock()
                elif self.shown is not None and self.clock() - self.shown >= QUICK_S:
                    self.opened.pop(self.key, None)     # it played and ended: not an open to count
                self._forget()
                return failed
            if not self.ours:
                self.home.clearProperty(OPENING)
        return False

    def playback_started(self):
        """Something began to play: the trailer (then it is no longer opening, and is stopped now if
        the viewer moved on meanwhile), or something else (then the player is someone else's)."""
        with self.lock:
            self.home.clearProperty(OPENING)
            if self.ours and self.is_ours():
                self.failed = 0     # a trailer shows its picture: they work on this device
                self.shown = self.clock()
                if self.subs is not None and self.opening is not None:
                    try:
                        self.subs.started(self.stream, self.key)
                    except Exception as exc:
                        self.log('subtitles: %s' % _why(exc))
            if not self.ours or not self.is_ours():
                try:
                    orphan = bool(self.let_go) and self.player.isPlaying() and self.player.getPlayingFile() == self.let_go
                except Exception:
                    orphan = False
                if self.ours:
                    self._forget()
                self.let_go = None
                if orphan:
                    self.halt()
                return
            self.opening = None
            late = (self.ours, self.key) if self.stop_wanted else None
        if late:
            if self.settle:
                threading.Thread(target=self._late_stop, args=late, name='POVILTrailerLook').start()
            else:
                self._late_stop(*late)


def watch():
    """The Wizard's start-up service runs this as one of its threads, for as long as Kodi runs."""
    import sys
    import time
    import xbmc
    import xbmcgui
    import xbmcvfs

    def log(text):
        xbmc.log('[POV IL trailers] %s' % text, xbmc.LOGINFO)

    def enabled():
        # (none on a children's profile: its guard stops every playback it did not approve -- with the
        # blocking stop this module must never meet -- and a trailer is not rated for the child)
        return (not xbmc.getCondVisibility('Skin.HasSetting(%s)' % OFF_SWITCH) and
                home.getProperty('POVIL.ChildProfile') != 'true' and
                xbmc.getCondVisibility('System.AddonIsEnabled(%s)' % YOUTUBE))

    def resolve(video):
        folder = xbmcvfs.translatePath('special://home/addons/%s/resources/lib/' % YOUTUBE)
        if folder not in sys.path:
            sys.path.append(folder)
        from youtube_plugin.youtube.provider import Provider
        from youtube_plugin.kodion.context import XbmcContext
        from youtube_plugin.kodion.constants import SERVER_WAKEUP
        return light_streams(video, Provider, XbmcContext, SERVER_WAKEUP, video_codec=video_codec, max_height=max_height)

    def fetch(address, headers, seconds, span):
        # (a plain read of this module's own: no proxy for an address inside this device)
        import urllib.request
        request = urllib.request.Request(address, headers=dict(headers or {}))
        if span:
            request.add_header('Range', span)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=seconds) as answer:
            return answer.read(64 * 1024 if span else 2 * 1024 * 1024)

    def save(text, address):
        # beside the manifest the YouTube add-on wrote, in the folder its server serves them from
        from youtube_plugin.kodion.constants import TEMP_PATH
        name, kept = kept_address(address)
        if not name:
            return None
        with open(os.path.join(xbmcvfs.translatePath(TEMP_PATH), name), 'w', encoding='utf-8') as handle:
            handle.write(text)
        return kept

    def save_named(name, text, manifest):
        # beside the manifests of the YouTube add-on, served by its server (webos_hls)
        from youtube_plugin.kodion.constants import TEMP_PATH
        with open(os.path.join(xbmcvfs.translatePath(TEMP_PATH), name), 'w', encoding='utf-8') as handle:
            handle.write(text)
        return served_address(manifest, name)

    def ready(stream):
        stream = reachable(stream, fetch, save, log)
        if stream is not None and webos_player:
            # (each reading its own manifest's address: a trailer read ahead and one asked for may be read at once)
            manifest = stream.get('url') or ''
            stream = webos_hls(stream, fetch, lambda name, text: save_named(name, text, manifest), log)
        return stream

    kept_path = os.path.join(xbmcvfs.translatePath('special://profile/addon_data/plugin.program.kodipovilwizard/'), TRANSLATED_FILE)
    pov_cache = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/metacache.db')

    def youtube_search(query):
        # YouTube's own search (no key): the YouTube add-on's "v1" client, as it browses with it
        folder = xbmcvfs.translatePath('special://home/addons/%s/resources/lib/' % YOUTUBE)
        if folder not in sys.path:
            sys.path.append(folder)
        from youtube_plugin.youtube.provider import Provider
        from youtube_plugin.kodion.context import XbmcContext
        client = Provider().get_client(context=XbmcContext())
        return client.api_request(client='v1', method='POST', path='search', do_auth=False, notify=False,
                                  post_data={'query': query, 'params': 'EgIQAQ%3D%3D'})

    seen, kept_lock = {}, threading.Lock()

    def translated(key):
        video = video_id(key)
        if not video:
            return []
        if video not in seen:
            found = look_up(video, key)
            if found is None:
                return []       # (POV does not hold the title yet: asked again on the next visit)
            seen[video] = found
        return list(seen[video])

    def keep(update):
        # read, change and write the kept answers under a lock; written whole beside and moved into place
        import json
        with kept_lock:
            try:
                with open(kept_path, encoding='utf-8') as handle:
                    kept = json.load(handle)
            except (OSError, ValueError):
                kept = {}
            update(kept)
            if len(kept) > 2000:
                for old in sorted(kept, key=lambda k: kept[k].get('t') or 0)[:500]:
                    kept.pop(old, None)
            try:
                with open(kept_path + '.tmp', 'w', encoding='utf-8') as handle:
                    json.dump(kept, handle)
                os.replace(kept_path + '.tmp', kept_path)
            except OSError:
                pass

    def look_up(video, key):
        # (once per title per session; the kept answer by the trailer's video spares POV's cache a full read)
        import json
        import sqlite3
        try:
            with open(kept_path, encoding='utf-8') as handle:
                kept = json.load(handle)
        except (OSError, ValueError):
            kept = {}
        entry = kept.get('v:' + video) or {}
        if time.time() - float(entry.get('t') or 0) < (TRANSLATED_FOUND_S if entry.get('ids') else TRANSLATED_NONE_S):
            return list(entry.get('ids') or [])
        if not os.path.isfile(pov_cache):
            return None
        con = sqlite3.connect('file:%s?mode=ro' % pov_cache, uri=True, timeout=2.0)
        try:
            rows = con.execute('SELECT db_type, tmdb_id, meta FROM metadata WHERE meta LIKE ?', ('%' + video + '%',)).fetchall()
        finally:
            con.close()
        meta, hebrew = title_of(rows, key)
        if meta is None:
            return None         # (a title POV does not hold yet)
        if hebrew:
            return []           # (its own trailer is Hebrew already)
        entry = kept.get(meta['povil_id']) or {}
        age = time.time() - float(entry.get('t') or 0)
        if age < (TRANSLATED_FOUND_S if entry.get('ids') else TRANSLATED_NONE_S):
            keep(lambda kept: kept.__setitem__('v:' + video, entry))
            return list(entry.get('ids') or [])
        query, names = translated_query(meta)
        if not query:
            return []
        kind = 'tv' if meta['povil_id'].startswith('tv') else 'movie'
        ids = translated_pick(search_results(youtube_search(query)), names, kind=kind, year=meta.get('year'))
        log('translated trailer for %s: %s' % (meta['povil_id'], ', '.join(ids) or 'none on YouTube'))
        answer = {'ids': ids, 't': time.time()}
        keep(lambda kept: kept.update({meta['povil_id']: answer, 'v:' + video: answer}))
        return ids

    def make_item(url, stream):
        item = xbmcgui.ListItem(path=url, offscreen=True)
        container = str(stream.get('container') or '').lower()
        if stream.get('ffmpeg'):
            # (an LG TV: Kodi's own player, FFmpeg, reads the HLS playlist -- no inputstream.adaptive)
            item.setMimeType('application/vnd.apple.mpegurl')
            item.setContentLookup(False)
        elif stream.get('adaptive') or container in ('mpd', 'hls'):
            item.setProperty('inputstream', 'inputstream.adaptive')
            item.setMimeType('application/dash+xml' if container != 'hls' else 'application/x-mpegURL')
            item.setContentLookup(False)
            headers = headers_text(stream.get('headers'))
            if headers:
                item.setProperty('inputstream.adaptive.manifest_headers', headers)
                item.setProperty('inputstream.adaptive.stream_headers', headers)
        return item

    home = xbmcgui.Window(10000)
    video_codec, no_picture, max_height, webos_player = 'avc1', None, MAX_HEIGHT, False
    app_id = os.environ.get('APPID') if xbmc.getCondVisibility('System.Platform.Linux + !System.Platform.Android') else None
    if on_webos(app_id, xbmcvfs.translatePath('special://xbmc/'), xbmc.getInfoLabel('System.OSVersionInfo')):
        video_codec, max_height, webos_player = WEBOS_VIDEO, WEBOS_HEIGHT, True
        log('an LG TV (webOS): trailers %dp through Kodi\'s own player (HLS)' % WEBOS_HEIGHT)
        _back, no_picture = webos_guard(
            os.path.join(xbmcvfs.translatePath('special://profile/addon_data/plugin.program.kodipovilwizard/'), WEBOS_OFF_FILE),
            xbmc.getInfoLabel('System.BuildVersion'),
            off=lambda: xbmc.getCondVisibility('Skin.HasSetting(%s)' % OFF_SWITCH),
            set_off=lambda on: xbmc.executebuiltin('Skin.%s(%s)' % ('SetBool' if on else 'Reset', OFF_SWITCH)),
            log=log)
    home.clearProperty(ON)
    home.clearProperty(FILE)
    home.clearProperty(OPENING)

    def over():
        if desk.playback_over():
            desk._did_not_play('did not open')
            threading.Thread(target=close_failure_box, name='POVILTrailerBox',
                             args=(xbmc.getCondVisibility, xbmc.executebuiltin, listener.waitForAbort)).start()

    class Events(xbmc.Player):
        def onAVStarted(self):
            desk.playback_started()

        def onPlayBackStopped(self):
            over()

        def onPlayBackEnded(self):
            over()

        def onPlayBackError(self):
            over()

    BUSY = 'Window.IsActive(busydialog) | Window.IsActive(busydialognocancel)'
    DIALOG = 'System.HasActiveModalDialog + !Window.IsActive(busydialog) + !Window.IsActive(busydialognocancel)'
    # where a trailer plays behind a title: the home, and the Videos window's views (a season's list, a search's
    # results, the inner lists -- Onyx 1.0.26; the skin's TRAILER_SCREEN). Each holds the label HERO_LABEL.
    SCREEN = 'Window.IsActive(home) | Window.IsActive(videos)'

    def wanted_now(key):
        # (Kodi's busy dialog may still be closing: what is read of the home under it is not the home's)
        for _ in range(10):
            if not xbmc.getCondVisibility(BUSY) or listener.waitForAbort(0.1):
                break
        return (enabled() and xbmc.getCondVisibility(SCREEN) and not xbmc.getCondVisibility(DIALOG) and
                xbmc.getInfoLabel('Control.GetLabel(%d)' % HERO_LABEL) == key)

    def look(key):
        label = xbmc.getInfoLabel('Control.GetLabel(%d)' % HERO_LABEL)
        return 'home=%d dialog=%d busy=%d title=%s focus=%s' % (
            xbmc.getCondVisibility(SCREEN), xbmc.getCondVisibility(DIALOG), xbmc.getCondVisibility(BUSY),
            'same' if label == key else ('none' if not label else 'another'), xbmc.getInfoLabel('System.CurrentControlId') or 'none')

    def acting():
        try:
            return time.time() - float(home.getProperty(ACTION) or 0) < ACTION_REST_S
        except Exception:
            return False

    player = Events()
    def repair():
        from resources.libs import youtube_port
        return youtube_port.run(log)

    def describe(video, key):
        # the title the trailer is of, for its translation (POV's cache, by the title's own trailer)
        import sqlite3
        own = video_id(key) or video
        if not os.path.isfile(pov_cache):
            return {}
        con = sqlite3.connect('file:%s?mode=ro' % pov_cache, uri=True, timeout=2.0)
        try:
            rows = con.execute('SELECT db_type, tmdb_id, meta FROM metadata WHERE meta LIKE ?', ('%' + own + '%',)).fetchall()
        finally:
            con.close()
        meta, _hebrew = title_of(rows, key)
        if not meta:
            return {}
        return {'title': meta.get('title') or '', 'original': meta.get('original_title') or '',
                'year': str(meta.get('year') or '')[:4], 'kind': 'tv' if meta['povil_id'].startswith('tv') else 'movie'}

    def load_captions(video):
        # the stream's information read again, subtitles asked for -- the YouTube add-on's own code, for a trailer
        # MoranSubs is about to translate only (trailer_subs.capture keeps its caption tracks)
        folder = xbmcvfs.translatePath('special://home/addons/%s/resources/lib/' % YOUTUBE)
        if folder not in sys.path:
            sys.path.append(folder)
        from youtube_plugin.youtube.provider import Provider
        from youtube_plugin.kodion.context import XbmcContext
        from youtube_plugin.youtube.client import subtitles as yt_subtitles
        trailer_subs.capture(yt_subtitles.Subtitles)
        provider, context = Provider(), XbmcContext()
        settings = context.get_settings()
        settings.get_subtitle_selection = lambda: 2
        settings.subtitle_download = lambda: True
        provider.get_client(context=context).load_stream_info(video_id=video)

    from resources.libs import trailer_subs
    def moransubs_answers():
        # (MoranSubs 0.3.100+ always gives its word: none yet = it has not started; an older one leaves "no" empty)
        try:
            return (xbmc.getCondVisibility('System.AddonIsEnabled(service.subtitles.kodipovilai)') and
                    trailer_subs.version_at_least(xbmc.getInfoLabel('System.AddonVersion(service.subtitles.kodipovilai)'),
                                                  trailer_subs.WORD_FROM))
        except Exception:
            return False

    subs = trailer_subs.Subs(home, player, log, xbmcvfs.translatePath, xbmc.executebuiltin, describe=describe,
                             setting=lambda name: xbmc.getCondVisibility('Skin.HasSetting(%s)' % name),
                             captions=load_captions, answers=moransubs_answers)
    desk = Desk(home, player, resolve, make_item, enabled, log, ready=ready, acting=acting,
                halt=lambda: xbmc.executebuiltin('PlayerControl(Stop)'),
                wanted_now=wanted_now, look=look, settle=SETTLE_S, no_picture=no_picture, translated=translated,
                repair=repair, subs=subs)
    subs.waiting = desk.waiting

    def run(job):
        threading.Thread(target=lambda: job() and desk.guard(), name='POVILTrailer').start()

    class Listener(xbmc.Monitor):
        def onNotification(self, sender, method, data):
            # NotifyAll(povil.trailer,ask) arrives as sender 'povil.trailer', method 'Other.ask'
            what = method.rpartition('.')[2] if sender == SENDER else None
            try:
                if what == 'ask':
                    job = desk.asked()
                    if job is not None:
                        run(job)
                elif what == 'peek':
                    job = desk.peeked()
                    if job is not None:
                        run(job)
                elif what == 'stop':
                    desk.stop()
                elif what in ('alone', 'shared'):
                    # the trailer has the screen to itself (the skin's TRAILER_ALONE), or the home is back over it:
                    # its subtitles show only on the former
                    subs.alone(what == 'alone')
            except Exception as exc:
                log('%s: %r' % (what, exc))

    listener = Listener()

    def warm():
        # the YouTube add-on's code, loaded now: on a small box its first loading is a good part of the first
        # trailer's wait (the modules resolve() names; nothing is asked of YouTube)
        try:
            if enabled():
                folder = xbmcvfs.translatePath('special://home/addons/%s/resources/lib/' % YOUTUBE)
                if folder not in sys.path:
                    sys.path.append(folder)
                from youtube_plugin.youtube.provider import Provider     # noqa: F401
                from youtube_plugin.kodion.context import XbmcContext    # noqa: F401
        except Exception as exc:
            log('warm: %s' % _why(exc))

    threading.Thread(target=warm, name='POVILTrailerWarm').start()
    try:
        # the skin may have asked before this thread was listening (Kodi's start): the skin does not
        # ask twice for the same title
        job = desk.asked()
        if job is not None:
            run(job)
    except Exception as exc:
        log('first ask: %r' % exc)
    try:
        # callbacks are delivered while this thread waits here
        while not listener.waitForAbort(600):
            pass
    finally:
        desk.waiting.set()
        try:
            desk.stop()
        except Exception:
            pass
