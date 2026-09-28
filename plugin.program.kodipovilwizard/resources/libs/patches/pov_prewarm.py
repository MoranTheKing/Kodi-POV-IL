# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_prewarm.py

def run(meta):
    """
    Dispatches a fire-and-forget prewarm execution strictly to the AI subtitles addon.
    """
    try:
        import sys
        import xbmcvfs
        p = xbmcvfs.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')
        if p not in sys.path:
            sys.path.append(p)

        import he_sub_match
        he_sub_match.prewarm(meta)
    except Exception:
        pass