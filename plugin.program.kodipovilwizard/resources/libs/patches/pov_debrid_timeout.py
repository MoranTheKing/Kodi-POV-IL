# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_debrid_timeout.py

def run(manager, threads_set, torrent_sources):
    """
    Evaluates debrid thread checks, defaulting to an empty tuple on timeout,
    and then completely empties the native threads_set to safely bypass the upstream loop.
    """
    answered = [i for i in threads_set if i.done() and not i.exception()]
    replies = [(fut.name, fut.result()) for fut in answered]
    _answered = {fut.name for fut in answered}

    # Inject timeouts as an empty tuple
    replies.extend((i, ()) for i in manager.debrid_torrents if i not in _answered)

    for name, hashes in replies:
        if not isinstance(hashes, list):
            hashes, unconfirmed = (), True
        else:
            unconfirmed = name in ('realdebrid', 'alldebrid')

        uncached = '%s %s' % ('Unchecked' if unconfirmed else 'Uncached', name)

        manager.final_sources.extend(
            {**i, 'cache_provider': name if i['hash'] in hashes else uncached, 'debrid': name}
            for i in torrent_sources
        )

    # Clears the native set so `threads = [i for i in threads if ...]` yields []
    # preventing upstream native iterations while preserving the state cleanly.
    threads_set.clear()