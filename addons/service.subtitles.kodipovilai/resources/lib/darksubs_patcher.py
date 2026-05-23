# Idempotent, self-healing patch of DarkSubs's engine.py so that
# when the user picks a non-Hebrew subtitle from DarkSubs, the
# machine-translation step routes through our Gemini AI instead of
# DarkSubs's bundled Google/Bing/Yandex translators -- but only if
# the user has actually set a Gemini API key. No key -> behaviour
# is byte-identical to upstream DarkSubs.
#
# Why patch instead of monkey-patch:
#   DarkSubs runs as a separate addon (often in a separate Python
#   invocation when its subtitle.module is dispatched), so we can't
#   reliably override its functions from our own process at runtime.
#   The file patch lives ON DISK in DarkSubs's tree, so DarkSubs
#   picks it up whether we're loaded or not.
#
# Self-healing:
#   DarkSubs gets updated periodically and the upstream update wipes
#   our injected lines. Our service.py calls ensure_patched() on
#   every Kodi startup. If the marker is missing, we re-inject. If
#   the function we're trying to wrap has been renamed or restructured
#   in a future DarkSubs version, we bail out SILENTLY without
#   touching the file -- the AI shortcut just stops working, but
#   DarkSubs itself keeps functioning normally.
#
# The injected hook itself communicates with our addon via a
# RunScript call + a sentinel file. It does NOT import our Python
# code into DarkSubs's namespace (that would require sys.path tricks
# that could shadow DarkSubs's own `resources` package).

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils

DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
ENGINE_REL_PATH = 'resources/modules/engine.py'

# Bump this number whenever the hook body materially changes. The
# patcher detects an old marker and re-injects the new version.
HOOK_VERSION = 1
MARKER = '# AI_TRANSLATE_HOOK_v{0}'.format(HOOK_VERSION)
END_MARKER = '# END AI_TRANSLATE_HOOK_v{0}'.format(HOOK_VERSION)
# Any previous-version markers we should rewrite over. Add to this
# list when bumping HOOK_VERSION.
OLD_MARKERS = []

# The hook body, indented 4 spaces (DarkSubs uses 4-space indent
# inside function bodies). Inserted as the first statement of
# machine_translate_subs.
#
# Behaviour:
#   1. If no Gemini key set in our addon's settings, do nothing.
#      DarkSubs falls through to its own translator.
#   2. Otherwise base64-encode the input/output paths (paths can
#      contain commas/parens/quotes that would break RunScript's
#      parameter parsing), then fire our addon's `translate_file`
#      action via RunScript.
#   3. Poll for the `<output>.ai_done` sentinel file. Timeout 5
#      minutes -- typical translation of a 2-hour movie with 3-way
#      parallel chunks is 30-90 seconds, so 5 minutes is well above
#      99th percentile.
#   4. On success: read the output file (DarkSubs's caller doesn't
#      use our return value -- it just expects output_file to exist
#      on disk -- but returning the text is consistent with the
#      original function shape).
#   5. On any failure (no key, timeout, exception, empty result):
#      fall through to the original DarkSubs logic. DarkSubs's UX
#      is unchanged in that case.
HOOK_BODY = '''\
    {marker}
    # Injected by service.subtitles.kodipovilai. See darksubs_patcher.py.
    try:
        import xbmcaddon as _aix_a, xbmc as _aix_x, os as _aix_os
        import time as _aix_t, base64 as _aix_b
        _aix_ad = _aix_a.Addon('service.subtitles.kodipovilai')
        _aix_key = (_aix_ad.getSetting('api_key') or '').strip()
        if _aix_key:
            _aix_done = output_file + '.ai_done'
            try: _aix_os.remove(_aix_done)
            except OSError: pass
            _aix_in = _aix_b.b64encode(
                input_file.encode('utf-8')).decode('ascii')
            _aix_out = _aix_b.b64encode(
                output_file.encode('utf-8')).decode('ascii')
            _aix_x.executebuiltin(
                'RunScript(service.subtitles.kodipovilai,'
                'action=translate_file,input_b64={{0}},'
                'output_b64={{1}})'.format(_aix_in, _aix_out))
            _aix_dl = _aix_t.time() + 300.0
            while _aix_t.time() < _aix_dl:
                if _aix_os.path.isfile(_aix_done):
                    try: _aix_os.remove(_aix_done)
                    except OSError: pass
                    if (_aix_os.path.isfile(output_file)
                            and _aix_os.path.getsize(output_file) > 0):
                        try:
                            with open(output_file, 'r',
                                      encoding='utf-8',
                                      errors='replace') as _aix_f:
                                return _aix_f.read()
                        except Exception:
                            break
                    break
                _aix_t.sleep(0.5)
    except Exception as _aix_e:
        try:
            import xbmc as _aix_x
            _aix_x.log('[AI hook] falling back to engine default: '
                       + str(_aix_e), level=2)
        except Exception:
            pass
    {end_marker}
'''.format(marker=MARKER, end_marker=END_MARKER)


# Regex matches the function definition line. Whitespace-tolerant
# (DarkSubs writes it as `def machine_translate_subs(input_file,output_file):`
# with no space after the comma, but we accept either).
_FUNC_DEF_RE = re.compile(
    r'^def\s+machine_translate_subs\s*\(\s*input_file\s*,\s*output_file\s*\)\s*:\s*$',
    re.MULTILINE,
)


def _engine_path():
    """Resolve the on-disk path to DarkSubs's engine.py, or None
    if DarkSubs isn't installed / Kodi paths aren't available."""
    if xbmcvfs is None:
        return None
    try:
        p = xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                DARKSUBS_ADDON_ID, ENGINE_REL_PATH))
        return p
    except Exception:
        return None


def ensure_patched():
    """Inject the hook into DarkSubs's engine.py if it isn't there
    already. Idempotent and safe to call on every Kodi startup.

    Returns one of:
      'patched'           -- we just injected the hook
      'already_patched'   -- marker was present, no change
      'no_engine'         -- DarkSubs not installed (or path unreachable)
      'unmatched'         -- DarkSubs's engine.py has a different shape;
                             we did NOT modify it (safe-fail)
      'write_failed'      -- we couldn't write the file (perms, etc.)
      'read_failed'       -- we couldn't read the file
    """
    engine = _engine_path()
    if not engine or not os.path.isfile(engine):
        return 'no_engine'

    try:
        with open(engine, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        kodi_utils.log(
            'darksubs_patcher: read failed for {0}: {1}'.format(
                engine, e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    # Cleanup of any older-version markers, if we ever bump HOOK_VERSION.
    for old in OLD_MARKERS:
        old_end = old.replace('AI_TRANSLATE_HOOK', 'END AI_TRANSLATE_HOOK', 1)
        # Strip the previous block by removing everything between the
        # old marker line and its matching end marker line.
        pattern = re.compile(
            r'^[ \t]*' + re.escape(old) + r'\b.*?^[ \t]*'
            + re.escape(old_end) + r'\b[^\n]*\n',
            re.MULTILINE | re.DOTALL,
        )
        content = pattern.sub('', content)

    m = _FUNC_DEF_RE.search(content)
    if not m:
        kodi_utils.log(
            'darksubs_patcher: machine_translate_subs signature not '
            'found in {0} -- DarkSubs may have been refactored. '
            'Leaving engine.py untouched.'.format(engine),
            level='WARNING')
        return 'unmatched'

    # Insert hook immediately after the def line. Adds a blank line
    # of separation so the original first statement (global trans_result)
    # stays readable.
    insert_at = m.end()
    new_content = (content[:insert_at] + '\n' + HOOK_BODY
                   + content[insert_at:])

    # Atomic write: write to .aitmp, then rename. Avoids leaving a
    # half-written engine.py if anything goes wrong mid-write.
    tmp_path = engine + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, engine)
    except OSError as e:
        kodi_utils.log(
            'darksubs_patcher: write failed for {0}: {1}'.format(
                engine, e), level='WARNING')
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return 'write_failed'

    kodi_utils.log(
        'darksubs_patcher: injected AI hook v{0} into {1}'.format(
            HOOK_VERSION, engine),
        level='INFO')
    return 'patched'
