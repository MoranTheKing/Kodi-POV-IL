# Make POV survive the seconds in which Kodi says it does not exist.
#
# Kodi's enabled flag flips the moment Addons.SetAddonEnabled returns, but its
# add-on manager catches up a couple of seconds later -- and in between,
# xbmcaddon.Addon('plugin.video.pov') raises "Unknown addon id". Kodi starts
# the add-on's own service script at the FIRST of those two moments, so POV's
# service runs head-first into a window in which POV cannot read its own
# settings. From a field log (2026-08-13 21:40):
#
#   Error Type: <class 'RuntimeError'>
#   Error Contents: Unknown addon id 'plugin.video.pov'.
#     service.py line 7      POVMonitor().run()
#     entry.py line 313      from indexers.trakt_api import trakt_sync_activities
#     tmdb_api.py line 14    READ_TOKEN = kodi_utils.addon().getSetting(...)
#     kodi_utils.py line 60  return Addon(id=addon_id)
#
# tmdb_api reads that setting at IMPORT time, so the failure is not one call
# that returns nothing -- the import chain dies, POVMonitor never starts, and
# POV's Trakt sync monitor and premium-account notification are gone for the
# rest of the session. The user sees a red error and, later, silently stale
# Trakt data.
#
# WE OPEN THAT WINDOW OURSELVES. pov_reload cycles POV off and on to make it
# re-import after we patch its files, and the log shows the crash landing
# three tenths of a second before our own "cycled POV" line. But the window is
# Kodi's, not ours: anyone toggling POV by hand hits it too, and so does any
# add-on that reads its own settings while importing. Waiting longer before we
# re-enable would not help either, because the wait has to happen INSIDE the
# add-on Kodi has just started.
#
# So the fix goes where the failure is. addon() retries for up to three
# seconds -- the observed window is about 2.7 -- and only after Addon() has
# already raised once, so nothing is slower on the path everybody takes. It
# waits on the abort monitor rather than sleeping, because this runs inside
# POV's own service startup and Kodi force-kills a script that will not stop
# within 5 seconds; a deaf wait would spend most of that budget. If POV really
# is gone, the last attempt raises exactly as before -- the one cost of this
# fix is that a genuinely absent POV takes three seconds to say so instead of
# none, which buys a present-but-not-yet-loaded one its whole service.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
KODI_UTILS_REL = 'resources/lib/modules/kodi_utils.py'
MARKER = '# AI_SUBS_POV_ADDON_WINDOW_v1'

# THE SECOND CALL SITE, and the earlier one. addon() below is the function the
# field log died in, but kodi_utils builds an Addon at MODULE scope too -- on
# the line that runs the moment anything imports it, which for POV's own
# service is about as early as its Python gets to run:
#
#   addon_object, window, execJSONRPC = Addon(), xbmcgui.Window(10000), ...
#
# Kodi's LegacyAddon.cpp settles that this is the same exposure, not a lesser
# one: the constructor with no id fills the id in from the calling script and
# then runs the identical
# GetAddon(id, pAddon, OnlyEnabled::CHOICE_YES) as Addon(id='plugin.video.pov').
# Same line, same filter. If it raises, kodi_utils itself fails to import and
# nothing downstream of it can even be defined -- strictly worse than the
# failure that was reported.
#
# SO WAIT ONCE, AT THE IMPORT, RATHER THAN WRAPPING EVERY USE. A review
# proposed shadowing the imported `Addon` name with a retrying function, which
# would cover every use in the file at once -- and would also turn a class into
# a function inside a third-party file that updates itself on its own
# schedule, where any future `isinstance(x, Addon)` becomes a TypeError we
# would never see coming. Neither copy of POV does that today; "today" is not
# the timescale this patch lives on.
#
# This waits for the window to close BEFORE the first construction, so the
# module-scope line that follows it -- the one that kills the import -- is
# past the window by the time it runs. No name is rebound, no type changes, no
# call site behaves differently. On an ordinary start the first attempt
# succeeds and it costs one discarded object.
#
# WHAT IT DOES NOT COVER, stated because the first version of this comment
# claimed "module scope, get_setting, addon(), all of them -- simply succeed"
# and that is not something this code guarantees. get_setting, set_setting,
# make_settings_dict, get_setting_fallback and local_string each construct
# their own Addon and get no retry from this. They are fine if the window
# never reopens after the import resolves it -- and this codebase knows POV
# runs a REUSED language invoker whose interpreter outlives a single call, and
# that the disable/enable cycle which opens the window happens more than once
# in a session, so "imported once" is a fact about one past moment rather than
# a promise. Whether that combination is actually reachable is unconfirmed.
# The wrapper approach would have covered them and is rejected above for its
# own reasons; patching five more anchors is the alternative, and each new
# anchor is another thing that can silently stop matching on a POV update.
IMPORT_MARKER = '# AI_SUBS_POV_IMPORT_WINDOW_v1'
_IMPORT_ANCHOR = 'from xbmcaddon import Addon\n'
_IMPORT_PATCHED = (
    'from xbmcaddon import Addon\n'
    + IMPORT_MARKER + '\n'
    '# Kodi calls an add-on unknown for a couple of seconds after re-enabling\n'
    '# it, and starts its service inside that window. The next line builds an\n'
    '# Addon at module scope, so landing in the window there kills the import\n'
    '# and every definition below it. Wait the window out once, here, and the\n'
    '# rest of this file constructs normally.\n'
    '#\n'
    '# waitForAbort, not sleep: this runs inside the service\'s own startup and\n'
    '# Kodi force-kills a script that will not stop within 5 seconds of being\n'
    '# asked. Nothing is raised on the way out -- if POV really cannot be\n'
    '# resolved, the line below fails exactly as it did before this patch.\n'
    'try:\n'
    '\tAddon()\n'
    'except Exception:\n'
    '\t_ai_subs_monitor = xbmc.Monitor()\n'
    '\tfor _ in range(30):\n'
    '\t\tif _ai_subs_monitor.waitForAbort(0.1):\n'
    '\t\t\tbreak\n'
    '\t\ttry:\n'
    '\t\t\tAddon()\n'
    '\t\t\tbreak\n'
    '\t\texcept Exception:\n'
    '\t\t\tcontinue\n'
)
# Our own earlier block, so a re-patch replaces rather than stacks. Anchored on
# the import line and the marker, then every line to the end of the injected
# try/except -- which is the only run of non-blank lines that follows it.
_OURS_IMPORT_RE = re.compile(
    r'from xbmcaddon import Addon\n'
    r'# AI_SUBS_POV_IMPORT_WINDOW_v\d+\n'
    r'(?:(?:#|try:|except|\t).*\n)*',
)

# POV indents with tabs. This must match byte for byte.
_STOCK = ("def addon(addon_id='plugin.video.pov'):\n"
          "\treturn Addon(id=addon_id)\n")

_PATCHED = (
    "def addon(addon_id='plugin.video.pov'):\n"
    "\t" + MARKER + "\n"
    "\ttry:\n"
    "\t\treturn Addon(id=addon_id)\n"
    "\texcept Exception:\n"
    "\t\tpass\n"
    "\t# Kodi calls an add-on unknown for a couple of seconds after it is\n"
    "\t# re-enabled -- the enabled flag flips at once, the add-on manager\n"
    "\t# catches up later -- and it starts this add-on's service inside that\n"
    "\t# window. Reading a setting there used to kill the import chain and\n"
    "\t# with it the whole background service, for the rest of the session.\n"
    "\t#\n"
    "\t# waitForAbort, not sleep: this runs inside the service's own startup,\n"
    "\t# and Kodi force-kills a script that does not stop within 5 seconds of\n"
    "\t# being asked. A wait that ignores the ask would spend most of that\n"
    "\t# budget refusing to hear it.\n"
    "\t_monitor = xbmc.Monitor()\n"
    "\tfor _ in range(30):\n"
    "\t\tif _monitor.waitForAbort(0.1):\n"
    "\t\t\tbreak\n"
    "\t\ttry:\n"
    "\t\t\treturn Addon(id=addon_id)\n"
    "\t\texcept Exception:\n"
    "\t\t\tcontinue\n"
    "\t# Out of patience, or Kodi is shutting down. Either way this is not the\n"
    "\t# window: raise the way stock does, so nothing downstream has to change.\n"
    "\treturn Addon(id=addon_id)\n"
)

# Any earlier version of our own block, so a re-patch replaces rather than
# stacks. Anchored on the def line and running to the end of the indented
# body -- indented lines ONLY. Letting it eat blank lines too would swallow
# the separator before the next function, so a re-patched file would differ
# from a freshly patched one by a missing blank line, forever.
_OURS_RE = re.compile(
    r"def addon\(addon_id='plugin\.video\.pov'\):\n"
    r"\t# AI_SUBS_POV_ADDON_WINDOW_v\d+\n"
    r"(?:[ \t].*\n)*",
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_addon_window_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _drop_pyc(path):
    try:
        d = os.path.join(os.path.dirname(path), '__pycache__')
        base = os.path.splitext(os.path.basename(path))[0] + '.'
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.startswith(base):
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass
    except Exception:
        pass


def ensure_patched():
    """'no_file' | 'clean' | 'patched' | 'unmatched' | 'read_failed'
    | 'compile_failed' | 'write_failed'. Never raises."""
    path = _pov_path(KODI_UTILS_REL)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    # TWO INDEPENDENT PATCHES, and either may land without the other. They
    # protect different moments -- the import, and every later call -- and POV
    # rewriting one of the two anchors is no reason to give up the other.
    new_content = content

    if IMPORT_MARKER not in new_content:
        if _OURS_IMPORT_RE.search(new_content):
            new_content = _OURS_IMPORT_RE.sub(
                _IMPORT_ANCHOR, new_content, count=1)
        if _IMPORT_ANCHOR in new_content:
            new_content = new_content.replace(
                _IMPORT_ANCHOR, _IMPORT_PATCHED, 1)
        else:
            _log('kodi_utils no longer imports Addon the way we know; '
                 'leaving the import alone', level='WARNING')

    if MARKER not in new_content:
        if _OURS_RE.search(new_content):
            # An older version of ours. Back to stock first, then forward -- so
            # this never leaves two retry loops wrapped around each other.
            new_content = _OURS_RE.sub(_STOCK, new_content, count=1)
        if _STOCK in new_content:
            new_content = new_content.replace(_STOCK, _PATCHED, 1)
        else:
            # POV rewrote addon(). Guessing at a replacement for a function
            # this central is how a build breaks everything at once.
            _log('addon() is not the function we know; leaving it alone',
                 level='WARNING')

    if new_content == content:
        # THREE ANSWERS, because this commit gave 'clean' two meanings and a
        # review caught it. Both patches present is clean. Neither anchor
        # findable is unmatched. ONE of each -- which is what a POV update
        # rewriting only addon() leaves behind -- was reported as 'clean',
        # and the caller warns on 'unmatched' and says nothing about 'clean'.
        # So the protection that the field log was actually about could go
        # away on a POV self-update and the status would say all is well.
        have = (MARKER in content, IMPORT_MARKER in content)
        if all(have):
            return 'clean'
        if any(have):
            return 'partial'
        return 'unmatched'

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
    _drop_pyc(path)
    _log("addon() now waits out Kodi's unknown-addon window instead of "
         'killing the service')
    return 'patched'
