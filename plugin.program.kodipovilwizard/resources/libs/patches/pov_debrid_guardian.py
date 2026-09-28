# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_debrid_guardian.py
import xbmc

def log_guard_active(provider):
    """
    Dummy hook entry point for the Unbound Guard logic.
    Variable bindings happen in the hook layer natively.
    """
    pass

def log_debrid_error(provider, response, path=""):
    """
    Safely evaluates debrid JSON responses for HTTP 200 "soft errors"
    (where the status is OK, but the envelope contains an API refusal).
    Logs the exact endpoint and reason so it isn't lost as a generic "no results".
    """
    try:
        msg = None

        if provider == 'alldebrid':
            if isinstance(response, dict) and response.get('status') == 'error':
                msg = response.get('error')

        elif provider == 'torbox':
            if isinstance(response, dict) and response.get('success') is False:
                error = response.get('error', '')
                detail = response.get('detail', '')
                msg = f"{error} - {detail}".strip(' -')

        elif provider == 'premiumize':
            # Premiumize returns HTTP 200 with {"status":"error","message":...}
            if isinstance(response, dict) and 'response' not in response:
                msg = response.get('message', str(response))

        if msg:
            xbmc.log(f"KODI_POV_IL {provider} refused {path} -- {msg}", xbmc.LOGINFO)

    except Exception as e:
        xbmc.log(f"Wizard DebridGuardian Parsing Exception: {str(e)}", xbmc.LOGWARNING)