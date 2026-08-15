"""Auto-on-play must never pick "עברית מסונכרנת למובנה" by itself.

That row delivers a DIFFERENT translation from the one inside the file, which
is exactly why it is offered as a row to choose rather than applied for you.
Resolving it also costs a 45-second alignment that reads the debrid token,
where auto-on-play is supposed to be immediate.

It was reachable, and not obviously so. autosub's fast path matches a subtitle
stream labelled exactly 'heb'; embedded_candidates() normalises 'Hebrew', 'HE'
and 'iw' as well. So a file whose Hebrew track is spelled ANY other way falls
past the fast path into the candidate loop -- where the new row sorts to the
FRONT and would have been the first thing picked, by default, on an ordinary
install. A pre-release review found it; nothing in the suite did, because
nothing in the suite ran autosub.

So this runs the REAL autosub_on_play() against the REAL defect shape: a
stream list saying 'Hebrew', not 'heb'.

Run: python3 tools/test_autosub_never_auto_syncs.py
"""
import importlib.util
import json
import os
import sys
import types
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def link(payload):
    return urllib.parse.quote(json.dumps(payload, ensure_ascii=False))


SYNC_LINK = link({'type': 'embedded_sync', 'lang': 'he', 'stream_index': 0})
EMB_LINK = link({'type': 'engine', 'embedded': True, 'stream_index': 0,
                 'lang': 'he'})
HUMAN_LINK = link({'type': 'engine', 'source': 'ktuvit',
                   'filename': 'Movie.2024.1080p'})


def run(stream_labels, sabotage=False):
    """Run the real autosub_on_play(); return what it resolved and applied."""
    resolved, streams_set = [], []
    for name in list(sys.modules):
        if name.split('.')[0] in ('resources', 'xbmc', 'xbmcgui', 'xbmcaddon',
                                  'xbmcvfs'):
            sys.modules.pop(name, None)

    xbmc = types.ModuleType('xbmc')

    class _Player(object):
        def isPlayingVideo(self):
            return True

        def getPlayingFile(self):
            return 'http://cdn/movie.mkv'

        def getAvailableSubtitleStreams(self):
            return list(stream_labels)

        def setSubtitleStream(self, i):
            streams_set.append(i)

        def showSubtitles(self, on):
            pass

        def setSubtitles(self, p):
            pass

        def getTotalTime(self):
            return 5400.0
    xbmc.Player = _Player
    xbmc.log = lambda *a, **k: None
    xbmc.sleep = lambda ms: None
    xbmc.getInfoLabel = lambda k: ''
    xbmc.getCondVisibility = lambda k: False
    xbmc.executebuiltin = lambda *a, **k: None

    class _Monitor(object):
        def abortRequested(self):
            return False

        def waitForAbort(self, t=0):
            return False
    xbmc.Monitor = _Monitor
    sys.modules['xbmc'] = xbmc

    gui = types.ModuleType('xbmcgui')

    class _W(object):
        def __init__(self, *a):
            pass

        def getProperty(self, k):
            return ''

        def setProperty(self, k, v):
            pass

        def clearProperty(self, k):
            pass
    gui.Window = _W
    gui.DialogProgressBG = None
    sys.modules['xbmcgui'] = gui

    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib

    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    ku.notify = lambda *a, **k: None
    ku.get_bool = lambda k, d=False: True
    ku.get_setting = lambda k, d='': d
    ku.set_setting = lambda k, v: None
    ku.get_int = lambda k, d=0: d
    ku.hebrew_subtitle_wanted = lambda: True
    ku.current_video_info = lambda: {'imdb_id': 'tt1234567', 'title': 'Movie',
                                     'year': '2024', 'season': '', 'episode': '',
                                     'filepath': 'http://cdn/movie.mkv',
                                     'picked_release': 'Movie.2024.1080p'}
    ku.set_current_subtitle = lambda link: None
    ku.get_current_subtitle = lambda: ''
    ku.cache_dir = lambda: '/tmp'
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku

    tr = types.ModuleType('resources.lib.translate')
    tr.set_quiet = lambda v: None

    def _decode(l):
        try:
            return json.loads(urllib.parse.unquote(l))
        except Exception:
            return None
    tr._decode_link = _decode

    # The order list_candidates really produces: the embedded rows go to the
    # FRONT, the new sync row first.
    ROWS = [{'language': 'he', 'link': SYNC_LINK,
             'filename': 'עברית מסונכרנת למובנה · 101%'},
            {'language': 'he', 'link': EMB_LINK,
             'filename': 'תרגום מובנה בעברית · 101%'},
            {'language': 'he', 'link': HUMAN_LINK,
             'filename': 'Movie.2024.1080p'}]
    tr.list_candidates = lambda info, modal_progress=True: list(ROWS)

    def _resolve(l, info):
        resolved.append((_decode(l) or {}).get('type'))
        return None            # embedded picks return None; that IS success
    tr.resolve = _resolve
    sys.modules['resources.lib.translate'] = tr
    lib.translate = tr

    seb = types.ModuleType('resources.lib.subs_engine_bridge')
    seb.ensure_engine_settings = lambda: None
    seb.note_playback_streams = lambda info, streams: None
    seb._release_ready = lambda info: True
    seb.select_embedded = lambda idx, lang=None: True
    seb.LAST_DOWNLOAD_FROM_CACHE = False
    sys.modules['resources.lib.subs_engine_bridge'] = seb
    lib.subs_engine_bridge = seb

    for extra in ('pool', 'he_sub_match', 'local_subs', 'cache', 'srt'):
        m = types.ModuleType('resources.lib.' + extra)
        sys.modules['resources.lib.' + extra] = m
        setattr(lib, extra, m)
    sys.modules['resources.lib.pool'].share_enabled = lambda: False
    sys.modules['resources.lib.pool'].enqueue_harvest = lambda *a, **k: None

    src_path = os.path.join(LIB, 'autosub_service.py')
    if sabotage:
        import tempfile
        text = open(src_path, encoding='utf-8').read()
        anchor = "            if pl.get('type') == 'embedded_sync':\n"
        assert anchor in text, 'sabotage anchor not found'
        cut = text.index(anchor)
        end = text.index("            is_embedded =", cut)
        text = text[:cut] + text[end:]
        src_path = os.path.join(tempfile.mkdtemp(), 'autosub_service.py')
        with open(src_path, 'w', encoding='utf-8') as f:
            f.write(text)
    spec = importlib.util.spec_from_file_location(
        'resources.lib.autosub_service', src_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['resources.lib.autosub_service'] = mod
    spec.loader.exec_module(mod)
    try:
        mod.autosub_on_play()
    except Exception as e:
        print('   (autosub_on_play raised: %r)' % (e,))
    return resolved, streams_set


# --- the defect shape: a Hebrew track NOT spelled 'heb' ---------------------
resolved, streams_set = run(['Hebrew', 'English'])
print('   resolved types: %r   streams set: %r' % (resolved, streams_set))
check("the fast path really does miss a 'Hebrew'-spelled track",
      not streams_set or resolved,
      'nothing fell through -- this test is not exercising the defect')
check('autosub NEVER resolves the embedded_sync row',
      'embedded_sync' not in resolved, repr(resolved))
check('autosub still applies the plain embedded track instead',
      'engine' in resolved, repr(resolved))

# --- and the fast path itself still works when the label IS 'heb' ----------
resolved2, streams_set2 = run(['heb', 'eng'])
check("a 'heb' track is applied by the fast path, no candidate loop",
      streams_set2 == [0] and not resolved2,
      'streams=%r resolved=%r' % (streams_set2, resolved2))

# --- SABOTAGE: without the guard, autosub picks the sync row ---------------
# If removing it does NOT make autosub resolve embedded_sync, then the checks
# above are green for some other reason and prove nothing about the guard.
sab_resolved, _ = run(['Hebrew', 'English'], sabotage=True)
check('SABOTAGE: without the guard autosub DOES auto-resolve the sync row',
      sab_resolved and sab_resolved[0] == 'embedded_sync',
      'resolved=%r -- the checks above are not testing the guard'
      % (sab_resolved,))

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
