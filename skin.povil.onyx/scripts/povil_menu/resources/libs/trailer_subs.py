"""Hebrew subtitles on the trailers the home plays (Wizard 0.5.29; MoranSubs 0.3.99 translates).

The owner, Nov 2026: "most series have no Hebrew subtitles on their trailers, and some films neither" -- and, after a
blind study (Gemini 3.1 Flash Lite against Google Translate on 13 trailers: Gemini won 13 of 13), "go".

Where a trailer's subtitles come from, in order:
  1. this device's own copy (CACHE: every trailer it showed subtitles for, kept);
  2. GitHub Pages (PAGES/tsubs/<sha1 of the video id>.json) -- every trailer anyone translated, published there by
     the repository's workflow (tools/trailer_subs_export.py). The pool's Worker serves no trailer subtitle: a
     million trailer views cost it nothing (the owner: "never near the free plan's limit, even under extreme
     load"). A trailer not there is not asked again for MISS_S;
  3. a translation by MoranSubs on this device, with the viewer's own FREE Gemini quota only -- when MoranSubs says
     it may (Window(home).Property(povil.tsub.able)); MoranSubs then shares it, so it is translated once for all.
     What it translates: the captions YouTube has for the trailer, read with the YouTube add-on's own code for a job
     only (capture(): the add-on asks YouTube again when no subtitle comes back, so no trailer that is not being
     translated goes near it), else Gemini listens to the trailer itself.

NEVER over a trailer that is Hebrew already (the owner: "remember the trailers with Hebrew built in -- you will not
see a Hebrew subtitle track, but they have Hebrew"): one picked as a translated or dubbed upload (trailers.py's
search), one whose YouTube title has Hebrew letters, one whose speech is Hebrew. A Hebrew track a person wrote is
used as it is.

SHOWN ONLY WHILE THE TRAILER HAS THE SCREEN (the skin's TRAILER_ALONE: the home faded away; the skin says so with
NotifyAll(povil.trailer,alone|shared)): Kodi draws subtitles over the home's video window too, under the rows (seen
in the QA Kodi). Each Hebrew line is wrapped in a right-to-left embedding, as MoranSubs' own files: the question mark
stood on the wrong side without it (QA Kodi).
"""
import hashlib
import html
import json
import os
import re
import threading
import time

PAGES = 'https://morantheking.github.io/Kodi-POV-IL/'
CACHE = 'special://profile/addon_data/plugin.program.kodipovilwizard/trailer_subs/'
JOBS = 'special://temp/povil_tsub/'
OFF_SWITCH = 'POVILTrailerSubsOff'      # the skin's setting: set = the viewer switched the trailers' subtitles off
ABLE, READY, SENDER = 'povil.tsub.able', 'povil.tsub.ready', 'povil.tsub'
MISS_S = 3600                           # a trailer with no subtitles on Pages is not asked again for this long
CONFIG_S = 6 * 3600                     # tsubs/config.json (the owner's switch) and tsubs/drop.json, read again after
CONFIG_RETRY_S = 600                    # ... and after this long when Pages did not answer
FETCH_S = 5
JOB_WAIT_S = 120                        # MoranSubs' answer, while the trailer still plays
ABLE_WAIT_S = 30                        # MoranSubs' word (may this device translate?) right after Kodi's start
WORD_FROM = (0, 3, 100)                 # the first MoranSubs that always gives the word ('1' or '0')
# The lines DRAWN BY THE SKIN (Onyx 1.0.30): the line of the moment in Window(home).Property(LINE), and LINES_ON while
# the trailer playing has subtitles. Kodi draws no subtitles over a video window whose picture is on a layer of its
# own -- Android's MediaCodec surface (the owner's devices, Nov 2026: the subtitle loaded at once, none shown); on a
# PC the picture and its subtitles are drawn together, which is why the QA Kodi showed them.
LINE, LINES_ON = 'povil.tsub.line', 'povil.tsub.on'
DRAWN_FROM = (1, 0, 30)                 # the first Onyx that draws them
LINE_TICK_S = 0.2
# A translation's version (f): 2 = timed by the words of the captions (MoranSubs 0.3.103). One from YouTube's automatic
# captions of an older version is OUTDATED: a device that translates makes it again, and the new one replaces it
# everywhere (Pages, the devices, the channel) -- the owner, Nov 2026: "replace what was there until now". The old one is
# shown meanwhile.
FORMAT = 2


def outdated(data):
    try:
        return (data or {}).get('s') == 'asr' and int((data or {}).get('f') or 1) < FORMAT
    except (TypeError, ValueError):
        return False
KEEP = 3000                             # trailers kept in CACHE
_VIDEO = re.compile(r'^[A-Za-z0-9_-]{11}$')
_HEBREW = re.compile('[\u05d0-\u05ea]')
RLE, PDF = '\u202b', '\u202c'


def version_at_least(text, least):
    parts = tuple(int(p) for p in re.findall(r'\d+', text or '')[:3])
    return bool(parts) and parts >= tuple(least)


def line_at(cues, ms):
    """The text of the cue [start_ms, end_ms, text] the moment ms is in, or ''."""
    for start, end, text in cues:
        if start <= ms < end:
            return text
    return ''


def label_text(text):
    """A cue's text for a skin label: lines joined by Kodi's [CR], brackets that Kodi would read as tags made round."""
    lines = [line.strip() for line in str(text).replace('[', '(').replace(']', ')').split('\n') if line.strip()]
    return '[CR]'.join(lines)


def path_of(video):
    """(folder, file) of a trailer under tsubs/ -- the hash, not the id: YouTube ids differ by letter case."""
    h = hashlib.sha1(video.encode('ascii')).hexdigest()
    return h[:2], h[:16] + '.json'


# ---------------------------------------------------------------- YouTube's captions (vtt)
_TIME = re.compile(r'(\d+):(\d\d):(\d\d)[.,](\d{3})\s+-->\s+(\d+):(\d\d):(\d\d)[.,](\d{3})')
_TAG = re.compile(r'<[^>]+>')
_WORD = re.compile(r'<(\d+):(\d\d):(\d\d)[.,](\d{3})>')
_SPLIT = re.compile(r'(<\d+:\d\d:\d\d[.,]\d{3}>)')


def _secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def vtt_cues(text):
    """A .vtt as [(start, end, text)]. Automatic captions come as rolling two-line cues with word tags: the new
    words of each are its last tagged line."""
    blocks, cur = [], None
    for line in text.replace('\r', '').split('\n'):
        m = _TIME.search(line)
        if m:
            g = m.groups()
            cur = [_secs(*g[:4]), _secs(*g[4:]), []]
            blocks.append(cur)
        elif cur is not None:
            if line.strip():
                cur[2].append(line)
            elif cur[2]:
                cur = None
    rolling = any('<c>' in l for b in blocks for l in b[2])
    out = []
    for start, end, lines in blocks:
        if rolling:
            tagged = [l for l in lines if '<c>' in l or _WORD.search(l)]
            if not tagged:
                continue
            words = html.unescape(_TAG.sub('', tagged[-1])).strip()
        else:
            words = html.unescape(_TAG.sub('', ' '.join(l.strip() for l in lines))).strip()
        words = re.sub(r'\s+', ' ', words)
        if not words or (out and out[-1][2] == words):
            continue
        out.append((round(start, 2), round(end, 2), words))
    return out


def vtt_words(text):
    """An automatic track's words with the second each is spoken at: [(second, word)]; [] for a track a person wrote."""
    out, cur = [], None
    for line in text.replace('\r', '').split('\n'):
        m = _TIME.search(line)
        if m:
            cur = _secs(*m.groups()[:4])
            continue
        if cur is None or not _WORD.search(line):
            continue
        at = cur
        for piece in _SPLIT.split(line):
            stamp = _WORD.fullmatch(piece)
            if stamp:
                at = _secs(*stamp.groups())
                continue
            for word in html.unescape(_TAG.sub('', piece)).split():
                out.append((round(at, 2), word))
        cur = None
    return out


# the YouTube add-on's Subtitles object of a trailer being translated, by video (capture)
_CAPTURED, _WANTED, _CAPTURED_LOCK = {}, set(), threading.Lock()


def capture(subtitles_class):
    """For a video in _WANTED only: the YouTube add-on's Subtitles object is kept here and False is answered -- "no
    subtitles, and ask nothing more" (None would send it to YouTube for more: player_client's caption fallback).
    Any other video gets the add-on's own answer, as before."""
    if getattr(subtitles_class, '_povil_capture', False):
        return
    original = subtitles_class.get_subtitles

    def get_subtitles(self, *args, **kwargs):
        video = getattr(self, 'video_id', None)
        with _CAPTURED_LOCK:
            wanted = video in _WANTED
            if wanted:
                _CAPTURED[video] = self
        if wanted:
            return False
        return original(self, *args, **kwargs)
    subtitles_class.get_subtitles = get_subtitles
    subtitles_class._povil_capture = True


def load_tracks(video, loader):
    """The trailer's caption tracks: loader(video) reads the stream's information with subtitles asked for (the
    YouTube add-on's own code, in trailers.py); capture() keeps them. Returns what went wrong, or ''."""
    with _CAPTURED_LOCK:
        _WANTED.add(video)
        _CAPTURED.pop(video, None)
    try:
        loader(video)
        return ''
    except Exception as exc:
        return '%s: %s' % (type(exc).__name__, str(exc)[:100])
    finally:
        with _CAPTURED_LOCK:
            _WANTED.discard(video)


def captured_tracks(video):
    with _CAPTURED_LOCK:
        subs = _CAPTURED.get(video)
    if subs is None:
        return None, []
    try:
        return subs, [(t.get('languageCode') or '', t.get('kind') or 'manual') for t in subs.caption_tracks or []]
    except Exception:
        return subs, []


def read_captions(video, loader=None, log=None):
    """What a job is made of: ('hebrew', cues) for a Hebrew track a person wrote; ('manual', cues, lang) or
    ('asr', words, lang); ('hebrew_speech',); ('listen',) when there is nothing to read (or YouTube refused it)."""
    if loader is not None:
        wrong = load_tracks(video, loader)
        if wrong and log:
            log('trailer subtitles: the captions of %s were not read (%s)' % (video, wrong))
    subs, tracks = captured_tracks(video)
    if subs is None or not tracks:
        if log:
            log('trailer subtitles: %s has %s' % (video, 'no caption tracks' if subs is not None else 'no captions read'))
        return ('listen',)
    try:
        subs.pre_download = True
        subs.FORMATS['_default'] = subs.FORMATS['_fallback'] = 'vtt'
        original = (getattr(subs, 'defaults', None) or {}).get('original_lang') or ''
        if (original or '').split('-')[0] in ('he', 'iw'):
            return ('hebrew_speech',)
        for lang in ('he', 'iw'):
            track, _tl, _n, kind = subs._get_track(lang, use_asr=False)
            if track and kind != 'translation':
                path, _f = subs._get_url(track=track, lang=None)
                cues = vtt_cues(_read(path))
                if cues:
                    return ('hebrew', cues)
        for lang in [l for l in ('en', 'en-US', 'en-GB', original) if l]:
            for use_asr in (False, True):
                track, track_lang, _n, kind = subs._get_track(lang, use_asr=use_asr)
                if not track or kind == 'translation':
                    continue
                path, _f = subs._get_url(track=track, lang=None)
                text = _read(path)
                if kind == 'asr' or use_asr:
                    words = vtt_words(text)
                    if words:
                        return ('asr', words, track_lang or lang)
                cues = vtt_cues(text)
                if cues:
                    return ('manual', cues, track_lang or lang)
    except Exception:
        pass
    return ('listen',)


def _read(path):
    if not path:
        return ''
    with open(path, encoding='utf-8', errors='replace') as handle:
        return handle.read()


# ---------------------------------------------------------------- subtitles as a file
def srt(cues_ms):
    """[[start_ms, end_ms, text]] as an .srt, each line in a right-to-left embedding."""
    def stamp(ms):
        ms = int(ms)
        return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
    out = []
    for n, (a, b, text) in enumerate(cues_ms, 1):
        lines = '\n'.join(RLE + line.strip(RLE + PDF) + PDF for line in str(text).split('\n') if line.strip())
        out.append('%d\n%s --> %s\n%s\n' % (n, stamp(a), stamp(b), lines))
    return '\n'.join(out)


def is_hebrew_trailer(stream, translated=False):
    """A trailer that carries Hebrew already: picked as a translated or dubbed upload, or its YouTube title is
    Hebrew (an Israeli distributor's upload: its subtitles are in the picture)."""
    if translated or (stream or {}).get('hebrew'):
        return True
    meta = (stream or {}).get('meta') or {}
    title = meta.get('title') or ((meta.get('video') or {}).get('title')) or ''
    return bool(_HEBREW.search(title))


class Subs(object):
    """One per Wizard service. started()/gone() follow the trailer the desk plays; alone() the skin's word."""

    def __init__(self, home, player, log, translate_path, notify, fetch=None, describe=None, clock=time.time,
                 setting=lambda name: False, waiting=None, captions=None, answers=lambda: False, draws=lambda: False):
        self.home, self.player, self.log = home, player, log
        self.translate_path, self.notify = translate_path, notify
        self.fetch = fetch or self._fetch
        self.describe = describe or (lambda video, key: {})
        self.captions = captions          # captions(video): reads the stream's information with subtitles asked for
        self.answers = answers            # answers(): this MoranSubs always gives the word (WORD_FROM), so none = not yet
        self.draws = draws                # draws(): the skin draws the lines (DRAWN_FROM): no subtitle file for the player
        self.clock, self.setting = clock, setting
        self.waiting = waiting or threading.Event()
        self.lock = threading.Lock()
        self.current = self.path = None
        self.loaded = self.shown = self.is_alone = False
        self.misses, self.config, self.config_at, self.drop = {}, {}, None, set()

    # ------------------------------------------------ the trailer
    def started(self, stream, key, translated=False):
        video = (stream or {}).get('video') or ''
        with self.lock:
            self.current, self.path, self.loaded, self.shown = video or None, None, False, False
        if not _VIDEO.match(video) or self.setting(OFF_SWITCH):
            self.log('trailer subtitles: none (%s)' % ('switched off' if _VIDEO.match(video) else 'no video id'))
            return
        if is_hebrew_trailer(stream, translated):
            self.log('trailer subtitles: none (%s carries Hebrew already)' % video)
            return
        self.log('trailer subtitles: looking for %s' % video)
        threading.Thread(target=self._prepare, args=(video, stream, key), name='POVILTrailerSubs').start()

    def gone(self):
        with self.lock:
            self.current, self.path, self.loaded, self.shown = None, None, False, False
        self.home.clearProperty(LINE)
        self.home.clearProperty(LINES_ON)

    def alone(self, on):
        self.is_alone = bool(on)
        self._apply()

    def _ours(self):
        try:
            return self.player.isPlayingVideo() and self.player.getPlayingFile() == self.home.getProperty('povil.tr.file')
        except Exception:
            return False

    def _apply(self):
        with self.lock:
            path, loaded, shown = self.path, self.loaded, self.shown
            if not path or not self._ours():
                return
            try:
                if self.is_alone and not loaded:
                    self.player.setSubtitles(path)          # (Kodi turns them on as it loads them)
                    self.loaded = self.shown = True
                elif self.is_alone and not shown:
                    self.player.showSubtitles(True)
                    self.shown = True
                elif not self.is_alone and shown:
                    self.player.showSubtitles(False)
                    self.shown = False
            except Exception as exc:
                self.log('subtitles: %s' % type(exc).__name__)

    def _ready(self, video, path, cues=None):
        with self.lock:
            if self.current != video:
                return
            drawn = bool(cues) and self.draws()
            if not drawn:
                self.path = path
        if drawn:
            threading.Thread(target=self._lines, args=(video, cues), name='POVILTrailerLines').start()
        else:
            self._apply()

    def _lines(self, video, cues):
        """The line of the moment into LINE while this trailer plays; the skin shows it while the trailer has the
        screen to itself (TRAILER_ALONE)."""
        cues = sorted([int(a), int(b), t] for a, b, t in cues)
        self.home.setProperty(LINES_ON, video)
        said = ''
        try:
            while not self.waiting.wait(LINE_TICK_S):
                if self.current != video:
                    break
                if not self._ours():
                    continue
                try:
                    text = line_at(cues, self.player.getTime() * 1000.0)
                except Exception:
                    continue
                if text != said:
                    said = text
                    if text:
                        self.home.setProperty(LINE, label_text(text))
                    else:
                        self.home.clearProperty(LINE)
        finally:
            if self.home.getProperty(LINES_ON) == video:
                self.home.clearProperty(LINE)
                self.home.clearProperty(LINES_ON)

    # ------------------------------------------------ finding them
    def _prepare(self, video, stream, key):
        try:
            # the owner's word first -- before this device's own copy: off for everyone, or this trailer withdrawn
            config = self._config()
            if not config.get('read', True):
                self.log('trailer subtitles: none (switched off for everyone)')
                return
            if video in self.withdrawn(config):
                self.forget(video)
                self.log('trailer subtitles: none (%s withdrawn)' % video)
                return
            cues, where = self.cached(video), 'this device'
            if cues is None:
                cues, where = self.from_pages(video), 'Pages'
            if cues and outdated(self.cached_data(video)) and self.home.getProperty(ABLE) == '1':
                # timed the old way: made again here, and shared (the old one if that fails)
                renewed = self.translated_here(video, stream, key, config)
                if renewed:
                    cues, where = renewed, 'MoranSubs (renewed)'
            if cues is None:
                where = 'MoranSubs'
                cues = self.translated_here(video, stream, key, config)
            if cues:
                self._ready(video, self._write(video, cues), cues)
                self.log('trailer subtitles: %s from %s (%d lines)' % (video, where, len(cues)))
            elif where == 'MoranSubs' and self.home.getProperty(ABLE) != '1':
                said = self.home.getProperty(ABLE)
                self.log('trailer subtitles: none for %s (not on Pages; %s)'
                         % (video, 'this device does not translate' if said == '0' or not self.answers()
                            else 'MoranSubs gave no word yet'))
        except Exception as exc:
            self.log('trailer subtitles: %s %s' % (type(exc).__name__, str(exc)[:120]))

    def _folder(self, where):
        path = self.translate_path(where)
        os.makedirs(path, exist_ok=True)
        return path

    def cached(self, video):
        sub, name = path_of(video)
        try:
            with open(os.path.join(self._folder(CACHE), sub + name), encoding='utf-8') as handle:
                return json.load(handle).get('c')
        except (OSError, ValueError):
            return None

    def forget(self, video):
        sub, name = path_of(video)
        try:
            os.remove(os.path.join(self._folder(CACHE), sub + name))
        except OSError:
            pass

    def cached_data(self, video):
        sub, name = path_of(video)
        try:
            with open(os.path.join(self._folder(CACHE), sub + name), encoding='utf-8') as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def keep(self, video, data):
        sub, name = path_of(video)
        folder = self._folder(CACHE)
        try:
            with open(os.path.join(folder, sub + name), 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False)
            files = sorted((f for f in os.listdir(folder) if f.endswith('.json')),
                           key=lambda f: os.path.getmtime(os.path.join(folder, f)))
            for old in files[:-KEEP]:
                os.remove(os.path.join(folder, old))
        except OSError:
            pass

    def _fetch(self, url):
        import urllib.error
        import urllib.request
        request = urllib.request.Request(url, headers={'User-Agent': 'KodiPOVIL-trailers'})
        try:
            with urllib.request.urlopen(request, timeout=FETCH_S) as answer:
                return 200, answer.read(256 * 1024)
        except urllib.error.HTTPError as exc:
            return exc.code, b''
        except Exception:
            return 0, b''

    def _config(self):
        """tsubs/config.json -- the owner's switch: {"read": bool, "translate": bool, "drop": [video ids]} -- and
        tsubs/drop.json, the translations he withdrew (the Worker's /tsub/ban page; trailer-subs.yml writes it). Read
        again after CONFIG_S; when Pages does not answer, the last ones stay (both switches on when none was ever
        read) and they are asked again after CONFIG_RETRY_S."""
        if self.config_at is not None and self.clock() - self.config_at < CONFIG_S:
            return self.config
        self.config_at = self.clock()
        status, body = self.fetch(PAGES + 'tsubs/config.json')
        if status == 200:
            try:
                config = json.loads(body.decode('utf-8'))
                self.config = config if isinstance(config, dict) else {}
            except ValueError:
                self.config = {}
        elif status == 404:
            self.config = {}
        else:
            self.config_at = self.clock() - CONFIG_S + CONFIG_RETRY_S
        status, body = self.fetch(PAGES + 'tsubs/drop.json')
        if status == 200:
            try:
                drop = json.loads(body.decode('utf-8')).get('drop')
                self.drop = {str(v) for v in drop if _VIDEO.match(str(v))} if isinstance(drop, list) else self.drop
            except (ValueError, AttributeError):
                pass
        elif status == 404:
            self.drop = set()
        else:
            self.config_at = self.clock() - CONFIG_S + CONFIG_RETRY_S
        return self.config

    def withdrawn(self, config):
        listed = config.get('drop') if isinstance(config.get('drop'), list) else ()
        return self.drop | {str(v) for v in listed}

    def from_pages(self, video):
        if self.clock() - self.misses.get(video, -MISS_S) < MISS_S:
            return None
        sub, name = path_of(video)
        status, body = self.fetch(PAGES + 'tsubs/%s/%s' % (sub, name))
        if status == 404:
            self.misses[video] = self.clock()
            for old in sorted(self.misses, key=self.misses.get)[:-2000]:
                self.misses.pop(old, None)
            return None
        if status != 200:
            return None
        try:
            data = json.loads(body.decode('utf-8'))
        except ValueError:
            return None
        if not data.get('c'):
            return None
        self.keep(video, data)
        return data['c']

    def translated_here(self, video, stream, key, config):
        """MoranSubs translates it -- when it may, and the owner's switch is on. The cues, or None."""
        if not config.get('translate', True) or not self.able(video):
            return None
        read = read_captions(video, self.captions, self.log)
        if read[0] == 'hebrew_speech':
            return None
        if read[0] == 'hebrew':
            cues = [[int(a * 1000), int(b * 1000), t] for a, b, t in read[1]]
            self.keep(video, {'c': cues, 's': 'he'})
            return cues
        job = dict(self.describe(video, key) or {}, v=video, src=read[0])
        meta = (stream or {}).get('meta') or {}
        job.setdefault('youtube_title', meta.get('title') or ((meta.get('video') or {}).get('title')) or '')
        job['duration'] = (stream or {}).get('seconds') or 0
        if read[0] == 'asr':
            job.update(words=read[1], lang=read[2])
        elif read[0] == 'manual':
            job.update(cues=read[1], lang=read[2])
        folder = self._folder(JOBS)
        answer = os.path.join(folder, video + '.he.json')
        try:
            os.remove(answer)
        except OSError:
            pass
        with open(os.path.join(folder, 'job.json'), 'w', encoding='utf-8') as handle:
            json.dump(job, handle, ensure_ascii=False)
        self.notify('NotifyAll(%s,job)' % SENDER)
        self.log('trailer subtitles: asked MoranSubs to translate %s (%s)' % (video, read[0]))
        began = self.clock()
        while self.clock() - began < JOB_WAIT_S:
            if self.waiting.wait(0.5) or self.current != video:
                return None
            if self.home.getProperty(READY) == video and os.path.exists(answer):
                try:
                    with open(answer, encoding='utf-8') as handle:
                        got = json.load(handle)
                except (OSError, ValueError):
                    return None
                # (MoranSubs 0.3.103 answers {"c": lines, "f": version}; before, the lines alone)
                cues, version = (got.get('c'), got.get('f') or 1) if isinstance(got, dict) else (got, 1)
                if not cues:
                    return None
                self.keep(video, {'c': cues, 's': read[0], 'f': version})
                return cues
        return None

    def able(self, video):
        """MoranSubs' word: '1' translates, '0' does not. Right after Kodi's start there is none yet: waited for (up to
        ABLE_WAIT_S, while the trailer still plays) when this MoranSubs always gives it -- the owner, 20 Nov 2026: the
        first trailer after a start was left untranslated, MoranSubs said "this device translates" 11 s later. (An
        older MoranSubs leaves "no" empty: none is "no" then.)"""
        said = self.home.getProperty(ABLE)
        if said == '' and self.answers():
            self.log('trailer subtitles: waiting for MoranSubs\' word (%s)' % video)
            for _ in range(int(ABLE_WAIT_S * 2)):
                if self.waiting.wait(0.5) or self.current != video:
                    return False
                said = self.home.getProperty(ABLE)
                if said:
                    break
        return said == '1'

    def _write(self, video, cues):
        path = os.path.join(self._folder(JOBS), video + '.show.he.srt')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(srt(cues))
        return path
