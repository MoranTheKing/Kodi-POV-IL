# -*- coding: utf-8 -*-
"""
Decoupled TorBox URL Encoder Module for Engine v2.
Percent-encodes only characters that cannot legally appear in a URI.
"""

def safe_url(raw_result):
    """
    Safely encodes TorBox payload URLs to prevent libcurl CURLE_URL_MALFORMAT errors.
    Leaves '%' alone to prevent double-encoding.

    :param raw_result: The raw API response payload from TorBox.
    :return: The API response payload with safely encoded string URLs.
    """
    try:
        if not isinstance(raw_result, str) or '://' not in raw_result:
            return raw_result

        bad_chars = '<>"{}|\\^`[] '
        out = []

        for char in raw_result:
            if char in bad_chars or char < '!' or char > '~':
                # Encode illegal or non-printable ASCII characters safely.
                # 'replace' handles surrogate characters gracefully to prevent UnicodeEncodeError.
                out.append(''.join('%%%02X' % byte_val for byte_val in char.encode('utf-8', 'replace')))
            else:
                out.append(char)

        return ''.join(out)

    except Exception as e:
        # Failsafe: if something catastrophic happens in processing, return raw to prevent hard crashes
        import xbmc
        xbmc.log("Wizard TorBox Patch Error: Failed to encode URL - {}".format(str(e)), xbmc.LOGWARNING)
        return raw_result