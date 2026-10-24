"""Keep POV's search results when its results cache cannot be written.

POV's ExternalSource.get_movie_source / get_episode_source write a provider's
results to providerscache.db (ExternalProvidersCache.set) BEFORE adding them
to the list. When that write raises -- "database disk image is malformed"
after the disk filled up, or the disk still full -- results()'s bare
`except: pass` swallows it and the provider returns nothing. The progress
counters have already climbed, so the search looks like it found thousands
and then shows "No Results", with nothing in the log.

Field report (24 Oct 2026, LG webOS TV, POV 6.10.22): over 2,000 results
counted, "No Results" shown; providerscache.db was malformed since the disk
filled. guard() makes a failed cache write cost only the cache: the results
are kept and the failure is logged once.
"""
import xbmc

_logged = []


def guard(cls):
    original = getattr(cls, 'set', None)
    if original is None or getattr(original, '_povil_guarded', False):
        return

    def set(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        except Exception as exc:
            if not _logged:
                _logged.append(True)
                xbmc.log('[POV IL] results cache write failed ({0}: {1}); '
                         'the results are kept'.format(type(exc).__name__, exc),
                         xbmc.LOGWARNING)
            return None

    set._povil_guarded = True
    cls.set = set
