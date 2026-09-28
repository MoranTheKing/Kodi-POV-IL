# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_debrid_error_guard.py

from threading import Thread

def run(instance, unchecked_hashes):
    """
    Intercepts the cache check strictly for direct providers (Premiumize, TorBox, Offcloud).
    RD and AD are bypassed (returns None) to allow native flow.
    For direct providers, wraps the network call and returns early to short-circuit native logic.
    """
    if instance.debrid in ('rd', 'realdebrid', 'ad', 'alldebrid'):
        return None  # Signal inline hook to continue to native logic

    try:
        # Wrap the vulnerable network check
        checked_hashes = instance.function().check_cache(unchecked_hashes)
    except BaseException as e:
        try:
            from modules import kodi_utils
            kodi_utils.logger('POV_WIZARD', 'Debrid cache check failed, reporting unchecked: %s' % e)
        except Exception:
            pass
        # Sentinel tuple triggers non-destructive handling in sources.py
        return tuple(instance.cached_list)

    # If the network check succeeds, we finalize the logic here and return the list early
    # to safely bypass the native if/elif/else block.
    if not checked_hashes:
        return instance.cached_list

    checked_hashes = set(checked_hashes)
    hashes_to_cache = []
    process_append = hashes_to_cache.append
    cached_append = instance.cached_list.append

    for h in unchecked_hashes:
        if h in checked_hashes:
            cached_append(h)
            process_append((h, 'True'))
        else:
            process_append((h, 'False'))

    if hashes_to_cache:
        Thread(target=instance.cache_write, args=(hashes_to_cache,)).start()

    return instance.cached_list