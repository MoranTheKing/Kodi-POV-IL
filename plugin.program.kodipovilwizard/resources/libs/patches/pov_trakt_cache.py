# File: plugin.program.kodipovilwizard/resources/lib/patches/pov_trakt_cache.py

import xbmc

def is_empty_result(result, cache_string="unknown"):
    """
    Evaluates if a Trakt API response is empty and prevents it from
    being persistently stored in the Trakt cache database.

    :param result: The data returned by the Trakt API function.
    :param cache_string: The cache identifier string (for logging).
    :return: True if the result is empty, False otherwise.
    """
    try:
        if not result:
            msg = (
                "POV WIZARD PATCH: Prevented an empty Trakt API result from "
                f"being cached forever. Target: {cache_string}"
            )
            xbmc.log(msg, xbmc.LOGINFO)
            return True
        return False
    except Exception as e:
        xbmc.log(f"POV WIZARD PATCH ERROR (is_empty_result): {e}", xbmc.LOGERROR)
        # In case of evaluation failure, safely default to False (allow upstream behavior)
        return False