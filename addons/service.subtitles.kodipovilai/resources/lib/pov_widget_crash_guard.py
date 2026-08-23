# Prevent the POV "add to Trakt/MDBList -> refresh widgets -> native crash".
#
# Root cause, confirmed from a field crash log (2026-07-16):
#   1. The user adds a title to a Trakt watchlist/favourites/collection.
#   2. POV's SyncMonitor detects the change and -- ONLY when the setting
#      `trakt.sync_refresh_widgets` is ON -- runs
#      UpdateLibrary(video,special://skin/foo) (POV's widget_refresh()).
#   3. That forces EVERY home widget to refresh at once, spawning many
#      plugin.video.pov/router.py invocations concurrently.
#   4. POV ships <reuselanguageinvoker>true</reuselanguageinvoker>, so those
#      concurrent invocations share ONE Python interpreter. The concurrent
#      access corrupts CPython dict internals:
#        SystemError: Objects/dictobject.c:1756: bad argument to internal
#        function
#      -> the whole Kodi app dies (native crash).

# THE "ONE SHARED INTERPRETER" STEP ABOVE IS NOT WHAT KODI DOES, measured
# 2026-08-23 on a device running with reuse ON. Across 32 timed invocations
# there were 11 concurrent pairs and NOT ONE of them shared an invoker thread;
# all 8 threads that ever arrived as the second caller started cold, at
# len(sys.modules)==81. Kodi does not hand a busy reusable invoker to a second
# concurrent caller -- it declines reuse and builds a fresh sub-interpreter.
# Warm reuse only ever appears sequentially, down one thread.
#
# WHAT THAT DOES AND DOES NOT OVERTURN. It does NOT make the crash imaginary:
# the 2026-07-16 log is a real SystemError in dictobject.c and Kodi's Python
# sub-interpreters share one GIL and a great deal of runtime state, so a
# concurrency-induced fault across them stays entirely possible. What it
# overturns is the stated MECHANISM, and therefore the confidence that turning
# reuse off addresses it -- because concurrent callers get separate
# interpreters either way, so that setting does not change the concurrency
# picture at all. The one difference it does make is sequential: with reuse ON
# an interpreter is not torn down between calls, so any thread POV started
# during call N is still running inside it when call N+1 is handed the same
# interpreter. That is a shared-interpreter race, it only exists with reuse on,
# and it is a better candidate than the one written above -- but it is an
# inference, not a measurement, and nobody should treat it as settled either.
#
# NOT ACTED ON HERE. The mitigation in this file does not depend on which of
# those is right, and a crash nobody can reproduce on demand is the worst
# possible thing to go loosening on the strength of a corrected footnote. This
# note exists so the next person re-derives it instead of inheriting it.
#
# `widget_refresh()` (the special://skin/foo UpdateLibrary) is called from
# exactly ONE place in POV (entry.py SyncMonitor.refresh_widgets), gated by
# this single setting -- so turning it OFF removes the crash trigger entirely.
# The feature is fundamentally unsafe on this build (reuselanguageinvoker +
# many home widgets); with it off, widgets simply refresh on the next
# navigation instead of in an instant crash-inducing burst.
#
# Self-healing: runs every startup, but only WRITES when the setting is
# actually 'true' (a plain no-op otherwise), so it never fights a device that
# is already safe and never touches POV's source files.

POV_ADDON_ID = 'plugin.video.pov'
SETTING_ID = 'trakt.sync_refresh_widgets'


def ensure_patched():
    """Force POV's crash-inducing widget-refresh setting OFF. Returns
    'no_xbmcaddon' | 'no_pov' | 'read_failed' | 'already_off' | 'patched' |
    'write_failed'. Never raises."""
    try:
        import xbmcaddon
    except Exception:
        return 'no_xbmcaddon'
    try:
        addon = xbmcaddon.Addon(POV_ADDON_ID)
    except Exception:
        # POV not installed (e.g. a non-POV build) -> nothing to guard.
        return 'no_pov'
    try:
        cur = (addon.getSetting(SETTING_ID) or '').strip().lower()
    except Exception:
        return 'read_failed'
    if cur != 'true':
        # Off or unset -> no crash risk. Do NOT write (leave POV untouched).
        return 'already_off'
    try:
        addon.setSetting(SETTING_ID, 'false')
    except Exception:
        return 'write_failed'
    return 'patched'
