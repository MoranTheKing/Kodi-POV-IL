# Fire the Hebrew-availability warm EARLY -- at the start of POV's source
# scrape, not when the source dialog builds.
#
# he_sub_match's background warm (OpenSubtitles/Wizdom/Ktuvit -> shared cache)
# is what fills the "HEB %" for titles whose Hebrew subs are NOT already in the
# community pool. It used to fire only when the source dialog was BUILT
# (release_names on a cache miss) -- i.e. AFTER scraping finished -- so the warm
# was still running when the dialog opened and the % only appeared on the 2nd/
# 3rd entry.
#
# POV's source_select() sets self.meta and then calls self.get_sources() (the
# ~1.5-3s scrape). We inject a prewarm() call BETWEEN them, so the warm runs
# CONCURRENTLY with the scrape and the cache is ready by the time the dialog
# opens -> % on the FIRST entry. Same one warm per title (no extra reads),
# no added stall (it's fire-and-forget).
#
# Marker-gated, compile()-checked, atomic, .pyc dropped. No-op if POV isn't
# installed or the anchor changed upstream.

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
SOURCES_REL = 'resources/lib/modules/sources.py'
MARKER = '# AI_SUBS_POV_PREWARM_v2'

# The scrape call inside source_select(); we inject right before it (2 tabs).
_ANCHOR = '\t\tresults = self.get_sources()'
_INJECT = (
    '\t\ttry:\n'
    '\t\t\timport sys as _pw_s, xbmcvfs as _pw_v  ' + MARKER + '\n'
    "\t\t\t_pw_p = _pw_v.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')\n"
    '\t\t\tif _pw_p not in _pw_s.path: _pw_s.path.append(_pw_p)\n'
    '\t\t\timport he_sub_match as _pw_m; _pw_m.prewarm(self.meta)\n'
    '\t\texcept Exception: pass\n'
    '\t\tresults = self.get_sources()'
)

# Strip ANY previously-injected version of this block before injecting the
# current one. Without this, bumping the marker leaves the older block in place
# and POV ends up running both -- which is how a superseded form (this one used
# to put our folder at the FRONT of POV's import path, where it could shadow a
# module POV or a scraper imports later) survives the fix meant to replace it.
_REVERT_RE = re.compile(
    r"[ \t]*try:[ \t]*\r?\n"
    r"[ \t]*import sys as _pw_s, xbmcvfs as _pw_v[ \t]*#[ \t]*"
    r"AI_SUBS_POV_PREWARM_v\d+.*?"
    r"[ \t]*except Exception: pass[ \t]*\r?\n",
    re.DOTALL,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_prewarm_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *SOURCES_REL.split('/'))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'compile_failed' | 'read_failed' | 'write_failed'."""
    path = _sources_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'
    content = _REVERT_RE.sub('', content)
    anchor = _ANCHOR
    inject = _INJECT
    if '\r\n' in content[:4096]:
        anchor = anchor.replace('\n', '\r\n')
        inject = inject.replace('\n', '\r\n')
    if anchor not in content:
        _log('source_select scrape anchor not found -- leaving alone',
             level='WARNING')
        return 'unmatched'

    new_content = content.replace(anchor, inject, 1)
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

    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('sources.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('prewarm hooked into source_select (Hebrew % ready on first entry)',
         level='INFO')
    return 'patched'
