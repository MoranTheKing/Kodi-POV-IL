# -*- coding: utf-8 -*-
"""Hebrew subtitles for the trailers the build's home plays (MoranSubs 0.3.99; the Wizard 0.5.29 plays the trailers
and shows the subtitles).

The owner, Nov 2026, after a blind study (Gemini 3.1 Flash Lite against Google Translate on 13 trailers: Gemini won
13 of 13): "translate the trailers with Gemini 3.1 Flash Lite, one request a trailer ... let the viewers' 500 free
daily requests of that model be used -- we use it nowhere else -- but remember there are paying users: only their
FREE quota may be used, nothing beyond it".

So a trailer is translated here, once, with the viewer's OWN key, and shared through the pool (pool.share_trailer;
the Worker publishes it to GitHub Pages, where every device reads it -- the Wizard asks there first):
  * ONLY A FREE KEY. A key is checked once a week at no cost to anyone (free_tier): an INVALID request (role
    "nobody", never billed) to a model that has no free quota -- a free key is refused on its quota first (429,
    a "...-FreeTier" quota), a billed key passes the quota and is refused as invalid (400). Seen on the QA key
    (free): 429 FreeTier on gemini-3.1-pro-preview and gemini-pro-latest. Anything but that 429 -- a billed key, an
    unknown answer, no network -- and nothing is translated (fails closed).
  * At most DAY_CAP requests a quota day (Google's Pacific day, gemini_quota) -- the free tier's 500 less a margin;
    the day's 429 stops it until the next. Not at all when the viewer's own translation model is this one (his
    films come first), nor when he chose Google Translate (no AI).
  * One request a trailer: the words of YouTube's captions (the Wizard reads them with the YouTube add-on's code)
    with the second each is spoken at -- or, with no captions, Gemini listens to the trailer itself (a fallback:
    clearly more meaning errors in the study).

The Wizard asks by a job file and NotifyAll(povil.tsub,job); this module answers with <video>.he.srt in the same
folder, Window(home).Property(povil.tsub.ready) = the video, and NotifyAll(povil.tsub,ready). While this device may
translate, Window(home).Property(povil.tsub.able) is "1" -- the Wizard reads no captions from YouTube otherwise.
"""
import hashlib
import json
import os
import re
import threading
import time

from resources.lib import kodi_utils

MODEL = 'gemini-3.1-flash-lite'
DAY_CAP = 480
PROBE_MODELS = ('gemini-3.1-pro-preview', 'gemini-pro-latest')
TIER_S = 7 * 86400
SENDER = 'povil.tsub'
ABLE, READY = 'povil.tsub.able', 'povil.tsub.ready'
FOLDER = 'special://temp/povil_tsub/'
STATE_FILE = 'trailer_subs.json'
FAILED_S = 86400                    # a trailer that could not be translated is not tried again for this long
BUSY_S = 1800                       # ... one Gemini was busy for (or the network failed), twice in a row: this long
BUSY_RETRY_S = 2.0                  # the one retry at once, while the trailer still plays
REQUEST_TIMEOUT = 90
_VIDEO = re.compile(r'^[A-Za-z0-9_-]{11}$')
_HEB = re.compile(u'[א-ת]')
_LATIN = re.compile(r'[A-Za-z]')
_LOCK = threading.Lock()

# The words of YouTube's automatic captions, EACH NUMBERED; the model answers which words each subtitle holds and the
# times are the words' own (by_words): a subtitle comes with its first word and goes a moment after its last. (FORMAT 2,
# MoranSubs 0.3.103. The owner, Nov 2026, on The Simpsons' trailer: "the subtitles are not quite in sync -- lines come
# early or late". Before, a time stood before every sixth word and the model named the nearest: a line could start a
# few words early or late, and end at the next time after a pause -- "green screen", spoken in half a second, stayed
# seven.)
ASR_PROMPT = u'''You are writing the Hebrew subtitles of a trailer: {what}.

Below is everything spoken in the trailer, as automatic speech recognition heard it ({lang}), word by word, each word after its number in square brackets.
The recognition has no punctuation and mishears words, names above all. First work out what was actually said -- you know this title: its characters, places and terms -- and where each sentence begins and ends; several people speak in turn. Never translate a misheard word literally.
If the speech is already Hebrew, answer only: NONE

Write the Hebrew a professional Israeli subtitler would: natural spoken Hebrew, not word-for-word; correct grammatical gender; names of people and places in their accepted Hebrew spelling.
One subtitle per sentence or short exchange: at most about 60 characters and about 6 seconds of speech. A longer sentence is split into two subtitles at a natural pause.
Every word belongs to exactly one subtitle, in order, and everything said is translated, to the last word: nothing left out, nothing added.

Answer with one subtitle per line, in this exact form and nothing else:
FIRST-LAST|Hebrew text
FIRST is the number of the subtitle's first word, LAST the number of its last word; the next subtitle begins at the word after LAST.

Speech:
{speech}
'''
FORMAT = 2                          # a translation's version (f): 2 = timed by its words (by_words); 1 = before
WORD_S = 0.6                        # how long a word lasts at most (the captions give when each one begins)
LEAD_S = 0.1                        # a subtitle comes this much before its first word
GAP_S = 2.5                         # a pause this long inside a subtitle, then a word or two: those are not waited for
TAIL_WORDS = 2
# A reply that counted the words wrong (The Big Bang Theory's trailer, the owner, Nov 2026: "something was not right with the
# subtitles" -- some 40 s with none): Flash-Lite now and then numbers a subtitle's words wrong, and every subtitle after it
# holds the words -- and the times -- of the one before. Its Hebrew is fine. The lengths tell: a subtitle's Hebrew is about as
# long as the English it holds. Split the words the reply holds into as many spans as there are subtitles by length
# alone: a sound reply's own split costs a little more (40 QA replies of 6 trailers: 38 at 0.01-0.085 a subtitle), a
# miscounted one far more (the other two, 0.19 and 0.22). Words a reply leaves out (a song) count for nothing.
# Then the trailer is asked once more -- the same request, about one in twenty -- and should that one drift too, the
# lengths place the subtitles of the better of the two (pulled to its own subtitle ends and to the pauses).
DRIFT = 0.15                        # more than this a subtitle: miscounted
DRIFT_LINES = 4                     # (fewer subtitles say nothing)
SPLIT_WORDS = 45                    # a subtitle holds at most this many words (the split by length)
SPLIT_BAND = 60                     # ... and ends at most this many words from where the reply ended it
PAUSE_PULL = 0.15
END_PULL = 0.2

MANUAL_PROMPT = u'''You are writing the Hebrew subtitles of a trailer: {what}.

Below are the trailer's subtitles ({lang}), written by a person, one numbered line each.
Translate each line into the Hebrew a professional Israeli subtitler would write: natural spoken Hebrew, not word-for-word; correct grammatical gender; names of people and places in their accepted Hebrew spelling; short. A sentence that runs over several lines is translated so that each line still holds its own part, in Hebrew word order.
A line that is only a sound or music mark ([Music], an applause) is answered empty.

Answer with exactly one line per numbered line, in this exact form and nothing else:
NUMBER|Hebrew text

Lines:
{lines}
'''

LISTEN_PROMPT = u'''This video is a trailer: {what}.
If the video already shows Hebrew subtitles on the screen, or its speech is Hebrew, answer only: NONE
Otherwise listen to everything that is spoken in it and write its Hebrew subtitles, the way a professional Israeli subtitler would: natural spoken Hebrew, correct grammatical gender, names of people and places in their accepted Hebrew spelling, short lines (about 42 characters at most), each subtitle a whole thought.
Text shown on screen in English (title cards) is translated too. Music and sounds get no subtitle.

Answer with one subtitle per line, in this exact form and nothing else:
START-END|Hebrew text
START and END are the times in the video in seconds with one decimal (for example 12.4-15.0), END after START, in order, not overlapping.
'''


def log(msg):
    try:
        kodi_utils.log('[trailer_subs] ' + msg)
    except Exception:
        pass


# ---------------------------------------------------------------- state
def _state_path():
    return os.path.join(kodi_utils.addon_profile_path(), STATE_FILE)


def _load():
    try:
        with open(_state_path(), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    try:
        path = _state_path()
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        pass


def _quota_day():
    from resources.lib import gemini_quota
    return gemini_quota._today_utc()


def _key():
    return (kodi_utils.get_setting('api_key', '') or '').strip()


def _key_id(key):
    return hashlib.sha256(key.encode('utf-8', 'replace')).hexdigest()[:12]


# ---------------------------------------------------------------- the free tier, at no cost
def classify_probe(status, body):
    """'free' | 'billed' | 'unknown' from the answer to the invalid probe request (free_tier)."""
    if status == 429:
        try:
            err = (json.loads(body) or {}).get('error') or {}
            for d in err.get('details') or []:
                for v in (d.get('violations') or []) if isinstance(d, dict) else []:
                    if 'freetier' in str(v.get('quotaId', '')).lower():
                        return 'free'
        except Exception:
            pass
        return 'unknown'
    if status == 400:
        return 'billed'
    return 'unknown'


def free_tier(key, post=None):
    """Is the key on Google's free tier? One invalid request (never billed), to the first probe model that exists."""
    import requests
    from resources.lib import gemini
    post = post or requests.post
    body = {'contents': [{'role': 'nobody', 'parts': [{'text': 'OK'}]}]}
    for model in PROBE_MODELS:
        try:
            r = post('%s/models/%s:generateContent' % (gemini.API_BASE, model), json=body,
                     headers={'x-goog-api-key': key}, timeout=30)
        except Exception:
            return 'unknown'
        if r.status_code == 404:
            continue                # the model is gone: the next
        return classify_probe(r.status_code, r.text or '')
    return 'unknown'


def tier(key, now=None, probe=free_tier):
    """The key's tier, checked at most once in TIER_S (a key that changed is checked again)."""
    now = now or time.time()
    with _LOCK:
        data = _load()
        known = (data.get('tier') or {}).get(_key_id(key))
        if known and now - known[1] < TIER_S and known[0] in ('free', 'billed'):
            return known[0]
    found = probe(key)
    with _LOCK:
        data = _load()
        data['tier'] = {_key_id(key): [found, now]}       # only the key in use is remembered
        _save(data)
    log('the key is checked: %s' % found)
    return found


# ---------------------------------------------------------------- may this device translate a trailer now?
def eligible(now=None, probe=free_tier):
    """(True, '') or (False, why)."""
    try:
        from resources.lib import gemini
        if not gemini.ai_mode_on():
            return False, 'not AI translation'
    except Exception:
        return False, 'no AI'
    key = _key()
    if not key:
        return False, 'no key'
    if (kodi_utils.get_setting('model', '') or '').strip().lower() == MODEL:
        return False, 'the films use this model'
    data = _load()
    day = _quota_day()
    if data.get('quota_out') == day:
        return False, 'the day\'s free quota is used'
    if data.get('day') == day and int(data.get('used') or 0) >= DAY_CAP:
        return False, 'the day\'s requests are used'
    found = tier(key, now=now, probe=probe)
    if found != 'free':
        return False, 'not a free key (%s)' % found
    return True, ''


def publish_able(able):
    """'1' or '0' -- never left empty once said: the Wizard waits for the word while it is empty (0.3.100)."""
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty(ABLE, '1' if able else '0')
    except Exception:
        pass


def tier_cached(now=None):
    """Whether this device's answer needs no request: the key's tier is known from this week's check (or there is no
    key at all)."""
    try:
        key = _key()
    except Exception:
        return False
    if not key:
        return True
    known = (_load().get('tier') or {}).get(_key_id(key))
    return bool(known and (now or time.time()) - known[1] < TIER_S and known[0] in ('free', 'billed'))


def _count_request():
    with _LOCK:
        data = _load()
        day = _quota_day()
        if data.get('day') != day:
            data['day'], data['used'] = day, 0
        data['used'] = int(data.get('used') or 0) + 1
        _save(data)
        return data['used']


def _quota_out():
    with _LOCK:
        data = _load()
        data['quota_out'] = _quota_day()
        _save(data)


def _failed(video, now=None, seconds=FAILED_S):
    """Not tried again until now + seconds (failed: {video: until}; an older entry -- the time of the failure -- is in
    the past by now and asks again)."""
    now = now or time.time()
    with _LOCK:
        data = _load()
        failed = {v: t for v, t in (data.get('failed') or {}).items() if t > now}
        failed[video] = now + seconds
        data['failed'] = failed
        _save(data)


def _recently_failed(video, now=None):
    now = now or time.time()
    return now < ((_load().get('failed') or {}).get(video) or 0)


class Busy(Exception):
    """Gemini busy (5xx) or the network failing: a passing trouble, tried again soon (BUSY_RETRY_S, BUSY_S)."""


# ---------------------------------------------------------------- the request
def marked(words, every=6, gap=0.7):
    """[(second, word)] as one line with a [second] before every few words and after every pause."""
    out, since, last = [], every, None
    for at, word in words:
        if since >= every or last is None or at - last > gap:
            out.append('[%.1f]' % at)
            since = 0
        out.append(word)
        since += 1
        last = at
    return ' '.join(out)


def indexed(words):
    """[(second, word)] as one line: every word after its number in square brackets."""
    return ' '.join('[%d]%s' % (n, word) for n, (_at, word) in enumerate(words, 1))


def _hebrew_length(text):
    return len(re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', text or '', flags=re.UNICODE)).strip())


def _span_cost(words, lengths):
    """cost(i, a, b): subtitle i holding words a+1..b -- how far its Hebrew length is from those words' English length
    (the whole reply's ratio)."""
    import math
    total = [0]
    for _at, word in words:
        total.append(total[-1] + len(re.sub(r'[^a-z0-9]', '', str(word).lower())) + 1)
    ratio = sum(lengths) / float(total[-1] or 1)

    def cost(i, a, b):
        return math.log((lengths[i] + 4.0) / ((total[b] - total[a]) * ratio + 4.0)) ** 2
    return cost


def _pause(words, b):
    """(a split after word b -- 1-based -- at a pause is cheaper)"""
    if b <= 0 or b >= len(words):
        return 0.0
    return -PAUSE_PULL * min(float(words[b][0]) - float(words[b - 1][0]), 2.0)


def split_by_length(words, lengths, near, ends=(), pull=0.0):
    """([(first, last)], cost): all the words, in order, in len(lengths) spans whose English lengths follow the
    subtitles' Hebrew lengths. near: where the reply ended each subtitle -- a span ends within SPLIT_BAND words of it;
    a split at a pause costs less, and (pull) at one of `ends`."""
    W, N = len(words), len(lengths)
    cost = _span_cost(words, lengths)
    inf = float('inf')
    best = [{0: 0.0}] + [None] * N
    back = [None] * (N + 1)
    for i in range(1, N + 1):
        if i == N:
            stops = [W]
        else:
            stops = range(max(i, near[i - 1] - SPLIT_BAND), min(W - (N - i), near[i - 1] + SPLIT_BAND) + 1)
        row, came = {}, {}
        for b in stops:
            extra = _pause(words, b) - (pull if b in ends else 0.0)
            here = inf
            for a, before in best[i - 1].items():
                if 0 < b - a <= SPLIT_WORDS:
                    c = before + cost(i - 1, a, b)
                    if c < here:
                        here, came[b] = c, a
            if here < inf:
                row[b] = here + extra
        if not row:
            return None, inf
        best[i], back[i] = row, came
    spans, b = [], W
    for i in range(N, 0, -1):
        a = back[i][b]
        spans.append((a + 1, b))
        b = a
    spans.reverse()
    return spans, best[N][W]


def _held(rows, words):
    """(the words the subtitles hold, in order; each subtitle's span among them; each one's place among all the words).
    A reply may leave words out -- a song, a sound, a line it judged not worth a subtitle: those say nothing of how it
    counted (the reviewer: counted over all the words, such a reply looked miscounted and its subtitles were moved)."""
    places, spans = [], []
    for first, last, _t in rows:
        start = len(places)
        places.extend(range(first - 1, last))
        spans.append((start + 1, len(places)))
    return [words[i] for i in places], spans, places


def drift(rows, words):
    """How much more a subtitle the reply's own split of the words it holds costs than their best split by length
    (0 for a short reply)."""
    if len(rows) < DRIFT_LINES:
        return 0.0
    held, spans, _places = _held(rows, words)
    if len(held) < len(rows):
        return 0.0
    lengths = [_hebrew_length(t) for _f, _l, t in rows]
    _spans, best = split_by_length(held, lengths, [l for _f, l in spans])
    if best == float('inf'):
        return 0.0
    cost, own, W = _span_cost(held, lengths), 0.0, len(held)
    for i, (first, last) in enumerate(spans):
        own += cost(i, first - 1, last) + (_pause(held, last) if last < W else 0.0)
    return (own - best) / len(rows)


def respan(rows, words):
    """The rows with the words they hold placed among them by length, pulled to the reply's own subtitle ends."""
    held, spans, places = _held(rows, words)
    lengths = [_hebrew_length(t) for _f, _l, t in rows]
    new, _cost = split_by_length(held, lengths, [l for _f, l in spans], ends={l for _f, l in spans}, pull=END_PULL)
    if not new:
        return rows
    return [(places[f - 1] + 1, places[l - 1] + 1, t) for (f, l), (_f, _l, t) in zip(new, rows)]


def by_words(text, words, info=None, fix=False):
    """FIRST-LAST|text lines (word numbers) as [(start, end, text)] in seconds, timed by the words themselves: from just
    before the first word, to a moment after the last -- long enough to be read, never into the next subtitle. Lines out
    of order, overlapping or naming words that are not there are left out. info['covered']: how many words they hold."""
    rows = []
    for line in (text or '').splitlines():
        m = re.match(r'\s*\[?(\d+)\]?\s*-\s*\[?(\d+)\]?\s*\|(.*)$', line)
        if not m or not m.group(3).strip():
            continue
        first, last = int(m.group(1)), int(m.group(2))
        if not (1 <= first <= last <= len(words)) or (rows and first <= rows[-1][1]):
            continue
        rows.append((first, last, m.group(3).strip()))
    if info is not None or fix:
        try:
            score = drift(rows, words)
        except Exception:
            score = 0.0
        if info is not None:
            info['drift'] = round(score, 3)
        if fix and score > DRIFT:
            rows = respan(rows, words)
    if info is not None:
        info['covered'] = sum(last - first + 1 for first, last, _t in rows)
        info['words'] = len(words)
    out = []
    for n, (first, last, text_) in enumerate(rows):
        start = float(words[first - 1][0])
        said = float(words[last - 1][0])
        after = float(words[last][0]) if last < len(words) else said + 1.2
        # the captions sometimes hear the last word or two of a sentence long after the rest ("...a car accident last
        # [8 s] night", QA): the subtitle goes after the words before that pause -- it holds their meaning already
        times = [float(words[i][0]) for i in range(first - 1, last)]
        for i in range(len(times) - 1, max(len(times) - 1 - TAIL_WORDS, 0), -1):
            if times[i] - times[i - 1] > GAP_S:
                said, after = times[i - 1], times[i]
                break
        # ... and the first word or two long before the rest (an exclamation, then the sentence -- the blind judges, Nov
        # 2026: such lines came 5-7 s early): the subtitle comes with the words after that pause
        for i in range(1, min(TAIL_WORDS, len(times) - 1) + 1):
            if times[i] - times[i - 1] > GAP_S and times[i] <= said:
                start = times[i]
                break
        spoken_end = min(after, said + WORD_S)
        reading = min(6.0, 0.8 + len(text_) / 17.0)
        end = min(max(spoken_end + 0.4, start + reading), start + 7.0)
        if n + 1 < len(rows):
            end = min(end, float(words[rows[n + 1][0] - 1][0]) - LEAD_S - 0.05)
        start = max(start - LEAD_S, out[-1][1] if out else 0.0)
        out.append((round(start, 2), round(max(end, start + 0.3), 2), text_))
    return out


def timed(text, end_of_speech):
    """START-END|text lines as [(start, end, text)] in seconds: each kept in order, at least 1.2 s and at most 7 s
    long, ending before the next begins."""
    cues = []
    for line in (text or '').splitlines():
        m = re.match(r'\s*\[?(\d+(?:\.\d+)?)\]?\s*-\s*\[?(\d+(?:\.\d+)?)\]?\s*\|(.*)$', line)
        if m and m.group(3).strip():
            cues.append([float(m.group(1)), float(m.group(2)), m.group(3).strip()])
    out = []
    for n, (a, b, t) in enumerate(cues):
        nxt = cues[n + 1][0] if n + 1 < len(cues) else end_of_speech + 1.5
        b = min(max(b, a + 1.2), nxt, a + 7.0) if nxt > a else a + 1.2
        if out and a < out[-1][0]:
            continue
        out.append((round(a, 2), round(b, 2), t))
    return out


def numbered(text, english):
    got = {}
    for line in (text or '').splitlines():
        m = re.match(r'\s*(\d+)\s*\|(.*)$', line)
        if m and 1 <= int(m.group(1)) <= len(english):
            got[int(m.group(1))] = m.group(2).strip()
    return [(a, b, got[n]) for n, (a, b, _t) in enumerate(english, 1) if got.get(n)]


def what_of(job):
    name = job.get('original') or job.get('title') or 'an unknown title'
    kind = 'series' if job.get('kind') == 'tv' else 'film'
    he = job.get('title') if job.get('title') and job.get('title') != name else ''
    return '%s "%s"%s%s' % ('the ' + kind, name, (' (%s)' % job['year']) if job.get('year') else '',
                            (', known in Hebrew as "%s"' % he) if he else '')


def request_parts(job):
    """(parts, read) for the job: read(text) -> [(start, end, text)]."""
    what = what_of(job)
    lang = job.get('lang') or 'en'
    if job.get('src') == 'asr' and job.get('words'):
        words = [(float(a), str(w)) for a, w in job['words']]
        prompt = ASR_PROMPT.format(what=what, lang=lang, speech=indexed(words))
        info = {}

        def read(text, fix=False):
            return by_words(text, words, info, fix)
        read.info = info
        return [{'text': prompt}], read
    if job.get('src') == 'manual' and job.get('cues'):
        english = [(float(a), float(b), str(t)) for a, b, t in job['cues']]
        prompt = MANUAL_PROMPT.format(what=what, lang=lang, lines='\n'.join('%d|%s' % (n, t) for n, (_a, _b, t) in enumerate(english, 1)))
        return [{'text': prompt}], lambda text: numbered(text, english)
    parts = [{'fileData': {'fileUri': 'https://www.youtube.com/watch?v=' + job['v'], 'mimeType': 'video/*'}},
             {'text': LISTEN_PROMPT.format(what=what)}]
    return parts, lambda text: timed(text, float(job.get('duration') or 600))


def ask(key, parts, post=None):
    """One request to MODEL. The reply's text; raises gemini's errors (QuotaExceeded on the day's 429)."""
    import requests
    from resources.lib import gemini
    post = post or requests.post
    payload = {'contents': [{'parts': parts}],
               'generationConfig': {'maxOutputTokens': 8192, 'thinkingConfig': {'thinkingLevel': 'low'}},
               'safetySettings': gemini._safety_settings(MODEL)}
    r = post('%s/models/%s:generateContent' % (gemini.API_BASE, MODEL), json=payload,
             headers={'x-goog-api-key': key, 'Content-Type': 'application/json'}, timeout=REQUEST_TIMEOUT)
    if r.status_code == 429:
        raise gemini._classify_429(r)
    if r.status_code in (500, 502, 503, 504):
        raise Busy('HTTP %d' % r.status_code)
    if r.status_code != 200:
        raise gemini.GeminiError('HTTP %d' % r.status_code)
    return gemini._generated_text(r.json())


def _passing(exc):
    """Is it a passing trouble -- Gemini busy, the network failing -- rather than the request's own fault?"""
    if isinstance(exc, Busy):
        return True
    name = type(exc).__name__
    return name in ('ConnectionError', 'Timeout', 'ReadTimeout', 'ConnectTimeout', 'ChunkedEncodingError')


def hebrew_enough(cues):
    text = ' '.join(t for _a, _b, t in cues)
    heb, latin = len(_HEB.findall(text)), len(_LATIN.findall(text))
    return heb >= 20 and heb / float(heb + latin) >= 0.6


def to_srt(cues):
    from resources.lib import srt as srt_mod

    def stamp(s):
        ms = int(round(s * 1000))
        return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
    text = '\n'.join('%d\n%s --> %s\n%s\n' % (n, stamp(a), stamp(b), t) for n, (a, b, t) in enumerate(cues, 1))
    try:
        # the punctuation on the right side, as the viewer's own subtitles (his rtl_punct_mode)
        return srt_mod.fix_rtl_punctuation(text)
    except Exception:
        return text


# ---------------------------------------------------------------- a job
def handle(job, key=None, post=None, write=None, now=None):
    """Translates the job's trailer. Returns the cues, or None (and why, in the log)."""
    video = str(job.get('v') or '')
    if not _VIDEO.match(video):
        return None
    if _recently_failed(video, now):
        return None
    key = key or _key()
    parts, read = request_parts(job)
    used = _count_request()
    began = time.time()
    try:
        try:
            text = ask(key, parts, post=post)
        except Exception as exc:
            if not _passing(exc):
                raise
            # (the owner's log, Nov 2026: a trailer QA translated at once failed on his device in a second -- and was
            # not asked again for a day. A passing trouble is asked once more at once, then in BUSY_S)
            time.sleep(BUSY_RETRY_S)
            used = _count_request()
            text = ask(key, parts, post=post)
    except Exception as exc:
        try:
            from resources.lib import gemini
            if isinstance(exc, gemini.QuotaExceeded):
                _quota_out()
                log('the day\'s free quota of %s is used' % MODEL)
                return None
        except Exception:
            pass
        passing = _passing(exc)
        log('%s: not translated (%s %s; again in %s)' % (video, type(exc).__name__, str(exc)[:80],
                                                         '30 minutes' if passing else 'a day'))
        _failed(video, now, BUSY_S if passing else FAILED_S)
        return None
    if (text or '').strip().upper().startswith('NONE'):
        log('%s: already Hebrew' % video)
        _failed(video, now)
        return None
    cues = read(text)
    info = getattr(read, 'info', None) or {}
    if cues and info.get('drift', 0) > DRIFT:
        # the reply counted the words wrong (DRIFT): asked once more; should that drift too, the better of the two is
        # placed by the lengths
        first = (info['drift'], text)
        log('%s: the reply counted the words wrong (%.2f a subtitle): asked once more' % (video, info['drift']))
        try:
            used = _count_request()
            again = ask(key, parts, post=post)
            cues_again = read(again)
            usable = bool(cues_again) and hebrew_enough(cues_again)
            if usable and info.get('drift', 0) <= DRIFT:
                text, cues = again, cues_again
            else:
                # (the one that miscounted less -- a second reply that is not Hebrew enough is not a choice: the reviewer)
                text = again if usable and info.get('drift', 0) < first[0] else first[1]
                cues = read(text, fix=True)
                log('%s: placed by the lengths' % video)
        except Exception as exc:
            try:
                from resources.lib import gemini
                if isinstance(exc, gemini.QuotaExceeded):
                    _quota_out()
            except Exception:
                pass
            log('%s: asked once more: %s -- placed by the lengths' % (video, type(exc).__name__))
            cues = read(first[1], fix=True)
        info = getattr(read, 'info', None) or {}
    if not cues or not hebrew_enough(cues):
        log('%s: no usable subtitles in the reply' % video)
        _failed(video, now)
        return None
    held = (', %d of %d words' % (info['covered'], info['words'])) if info.get('words') else ''
    log('%s: %d subtitles (%s%s, %.1f s, request %d today)' % (video, len(cues), job.get('src') or 'listen', held,
                                                                  time.time() - began, used))
    (write or _write)(video, cues)
    return cues


def _folder():
    import xbmcvfs
    path = xbmcvfs.translatePath(FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def _write(video, cues):
    import xbmc
    import xbmcgui
    path = os.path.join(_folder(), video + '.he.srt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(to_srt(cues))
    with open(os.path.join(_folder(), video + '.he.json'), 'w', encoding='utf-8') as f:
        # (the version with the lines: the Wizard keeps it, and a newer one replaces an older one -- 0.3.103)
        json.dump({'c': [[int(a * 1000), int(b * 1000), t] for a, b, t in cues], 'f': FORMAT}, f, ensure_ascii=False)
    xbmcgui.Window(10000).setProperty(READY, video)
    xbmc.executebuiltin('NotifyAll(%s,ready)' % SENDER)


def share(job, cues):
    """The translation to the pool (the Worker's /tsub), when the viewer shares (pool_share)."""
    try:
        from resources.lib import pool
        if not pool.share_enabled() or time.time() < float(_load().get('closed_until') or 0):
            return
        body = {'v': job['v'], 's': job.get('src') if job.get('src') in ('asr', 'manual') else 'listen', 'm': MODEL,
                'n': job.get('title') or job.get('original') or '', 'y': job.get('year') or '',
                # a film or a series, and a series' trailer's season (the Wizard 0.5.34): the channel's post says it
                'k': job.get('kind') or '', 'e': job.get('season') or '',
                # the translation's version: a newer one replaces an older one of the same trailer everywhere
                'f': FORMAT,
                'c': [[int(a * 1000), int(b * 1000), t] for a, b, t in cues]}
        status, answer = pool.share_trailer(body)
        if status == 429 and (answer or {}).get('closed'):
            with _LOCK:
                data = _load()
                data['closed_until'] = time.time() + float((answer or {}).get('retry_s') or 3600)
                _save(data)
        log('%s shared: %s' % (job['v'], status))
    except Exception as exc:
        log('not shared: %s' % type(exc).__name__)


# ---------------------------------------------------------------- the device, once a day
def say_seen(now=None):
    """Once a UTC day: this device to the pool's dashboard -- whether it keeps its lists in sync through its own Google
    Drive (the Wizard's cloud sync) and runs Onyx. The owner, 20 Nov 2026: "how many have connected to the syncs" --
    their Drives are theirs alone, nothing else could tell. The install's anonymous id only (as every pool request)."""
    try:
        day = time.strftime('%Y%m%d', time.gmtime(now or time.time()))
        with _LOCK:
            if _load().get('seen_day') == day:
                return False
        import xbmc
        import xbmcvfs
        from resources.lib import pool
        if not (pool.use_enabled() or pool.share_enabled()):
            return False            # the viewer told this device not to talk to the pool: nothing (the reviewer)
        tokens = xbmcvfs.translatePath('special://profile/addon_data/plugin.program.kodipovilwizard/cloud_sync/tokens.json')
        # ONE try a day, whatever the answer: a Worker without /seen yet answers its landing page, and a retry at every
        # ten-minute round on every device would cost the free plan thousands of requests (a day not counted is all)
        with _LOCK:
            data = _load()
            data['seen_day'] = day
            _save(data)
        status, answer = pool.say_seen({'sync': os.path.isfile(tokens), 'onyx': xbmc.getSkinDir() == 'skin.povil.onyx'})
        return status == 200 and bool((answer or {}).get('ok'))
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- the service
def start(monitor):
    """Listens for the Wizard's jobs; says whether this device may translate. Never raises."""
    try:
        import xbmc
    except Exception:
        return
    pending = {'job': None}
    wake = threading.Event()

    def refresh():
        try:
            able, why = eligible()
        except Exception as exc:
            able, why = False, type(exc).__name__
        publish_able(able)
        return able, why

    class Listener(xbmc.Monitor):
        def onNotification(self, sender, method, data):
            if sender != SENDER or not method.endswith('job'):
                return
            try:
                with open(os.path.join(_folder(), 'job.json'), encoding='utf-8') as f:
                    pending['job'] = json.load(f)
                wake.set()
            except Exception:
                pass

    def run():
        # The listener lives in this thread and this thread waits on it: Kodi hands a Monitor its notifications on
        # the thread that made it, while that thread waits (QA Kodi: made on the service's own thread, the Wizard's
        # job never arrived -- that thread waits elsewhere)
        listener = Listener()
        # The word at once when the key's tier is known from this week's check: the Wizard waits for it before the
        # first trailer (the owner, 20 Nov 2026: the first trailer after a start was left untranslated -- the word came
        # 11 s later). A key still to be checked is checked a moment after Kodi's start (once a week at most).
        if not tier_cached() and listener.waitForAbort(20):
            return
        able, why = refresh()
        log('trailer subtitles: %s' % ('this device translates' if able else 'no (%s)' % why))
        threading.Thread(target=say_seen, name='MoranSubsSeen').start()
        idle = 0.0
        while not listener.abortRequested():
            if listener.waitForAbort(0.5):
                break
            job, pending['job'] = pending['job'], None
            if not job:
                idle += 0.5
                if idle >= 600:
                    idle = 0.0
                    refresh()
                    threading.Thread(target=say_seen, name='MoranSubsSeen').start()      # (a new UTC day)
                continue
            idle = 0.0
            able, why = refresh()
            if not able:
                log('%s: not translated (%s)' % (job.get('v'), why))
                continue
            log('%s: translating (%s)' % (job.get('v'), job.get('src') or 'listen'))
            cues = handle(job)
            if cues:
                threading.Thread(target=share, args=(job, cues), name='MoranSubsTrailerShare').start()
            refresh()
        del listener

    threading.Thread(target=run, name='MoranSubsTrailers').start()
