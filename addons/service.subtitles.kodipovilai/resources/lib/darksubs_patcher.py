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
HOOK_VERSION = 4
MARKER = '# AI_TRANSLATE_HOOK_v{0}'.format(HOOK_VERSION)
END_MARKER = '# END AI_TRANSLATE_HOOK_v{0}'.format(HOOK_VERSION)
# Any previous-version markers we should rewrite over. Add to this
# list when bumping HOOK_VERSION.
OLD_MARKERS = [
    '# AI_TRANSLATE_HOOK_v1',
    '# AI_TRANSLATE_HOOK_v2',
    '# AI_TRANSLATE_HOOK_v3',
]

# The hook body, indented 4 spaces (DarkSubs uses 4-space indent
# inside function bodies). Inserted as the first statement of
# machine_translate_subs.
#
# v3 changes vs v2:
#   * No more Google Translate fallback when our API key IS set. v2
#     fell through to Google on AI timeout / crash / empty output --
#     which surfaced as "I told you I don't want Google" complaints
#     from users who had explicitly set up Gemini and didn't want
#     DarkSubs's bundled Google translator to take over on AI hiccups.
#     v3 honours the AI-key-as-explicit-preference contract: if a
#     key is set and AI fails, we copy the ORIGINAL (English)
#     subtitle to the output path and return -- DarkSubs sees a
#     valid file and the user gets English subs on screen instead
#     of bad Google Hebrew. Google is preserved as the upstream
#     default ONLY when no AI key is configured.
#   * Heartbeat outcomes extended: 'kept_original' is the new
#     "AI failed, keeping English" status.
HOOK_BODY = '''\
    {marker}
    # Injected by service.subtitles.kodipovilai. See darksubs_patcher.py.
    _aix_tried_ai = False
    try:
        import xbmcaddon as _aix_a, xbmc as _aix_x, os as _aix_os
        import time as _aix_t, base64 as _aix_b
        import xbmcgui as _aix_g
        _aix_now = str(int(_aix_t.time()))
        _aix_g.Window(10000).setProperty(
            'ai_subs.hook_last_fire', _aix_now)
        _aix_x.log('[AI hook v4] entered for ' + str(input_file),
                   level=1)
        _aix_ad = _aix_a.Addon('service.subtitles.kodipovilai')
        try:
            _aix_ad.setSetting('_darksubs_hook_last_fire', _aix_now)
        except Exception:
            pass
        _aix_key = (_aix_ad.getSetting('api_key') or '').strip()
        _aix_g.Window(10000).setProperty(
            'ai_subs.hook_last_key_len', str(len(_aix_key)))
        if _aix_key:
            _aix_tried_ai = True
            _aix_x.log('[AI hook v4] key len=' + str(len(_aix_key))
                       + ' -> firing RunScript', level=1)
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
                                _aix_x.log(
                                    '[AI hook v4] AI output ready, '
                                    'returning translated content',
                                    level=1)
                                _aix_g.Window(10000).setProperty(
                                    'ai_subs.hook_last_outcome', 'ok')
                                try:
                                    _aix_ad.setSetting(
                                        '_darksubs_hook_last_outcome', 'ok')
                                except Exception:
                                    pass
                                return _aix_f.read()
                        except Exception:
                            break
                    break
                _aix_t.sleep(0.5)
            # Reached only on timeout or empty/bad output. AI was
            # tried; fall through to the post-try block below which
            # copies English -> output and short-circuits Google.
            _aix_x.log('[AI hook v4] AI did not produce a usable '
                       'output -- will keep original English',
                       level=3)
        else:
            _aix_x.log('[AI hook v4] api_key empty in DarkSubs '
                       'process -- falling through to engine default '
                       '(Google translator)', level=3)
            _aix_g.Window(10000).setProperty(
                'ai_subs.hook_last_outcome', 'no_key')
            try:
                _aix_ad.setSetting(
                    '_darksubs_hook_last_outcome', 'no_key')
            except Exception:
                pass
            try:
                _aix_x.executebuiltin(
                    'Notification(Kodi POV IL - AI Subtitles,'
                    'AI key not visible to DarkSubs -- using Google '
                    'fallback. Open AI Subs settings and re-save '
                    'the key.,8000)')
            except Exception: pass
    except Exception as _aix_e:
        try:
            import xbmc as _aix_x
            import xbmcgui as _aix_g
            _aix_x.log('[AI hook v4] crashed: ' + str(_aix_e),
                       level=3)
            _aix_g.Window(10000).setProperty(
                'ai_subs.hook_last_outcome',
                'crash: ' + str(_aix_e)[:80])
            try:
                _aix_a.Addon('service.subtitles.kodipovilai').setSetting(
                    '_darksubs_hook_last_outcome',
                    'crash: ' + str(_aix_e)[:80])
            except Exception:
                pass
            try:
                _aix_x.executebuiltin(
                    'Notification(Kodi POV IL - AI Subtitles,'
                    'AI hook crashed: '
                    + str(_aix_e).replace(',', ';')[:80]
                    + ',8000)')
            except Exception: pass
        except Exception:
            pass
    # If AI was actually attempted (key was set), the user has opted
    # into AI translation and we must NOT fall through to Google.
    # Copy the English original to output_file so DarkSubs sees a
    # valid file -- user gets English subs on screen, not Google
    # Translate junk. If even that fails, last resort is to let
    # Google run.
    if _aix_tried_ai:
        try:
            import shutil as _aix_shutil
            import xbmc as _aix_x
            import xbmcgui as _aix_g
            _aix_shutil.copyfile(input_file, output_file)
            _aix_g.Window(10000).setProperty(
                'ai_subs.hook_last_outcome', 'kept_original')
            try:
                _aix_a.Addon('service.subtitles.kodipovilai').setSetting(
                    '_darksubs_hook_last_outcome', 'kept_original')
            except Exception:
                pass
            _aix_x.log('[AI hook v4] copied English -> output, '
                       'short-circuiting Google fallback',
                       level=1)
            try:
                _aix_x.executebuiltin(
                    'Notification(Kodi POV IL - AI Subtitles,'
                    'AI translation failed -- keeping original '
                    'English (no Google fallback),8000)')
            except Exception: pass
            return ''
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
        # Binary mode: preserve original line endings exactly.
        # Text mode (open('r', encoding='utf-8') with default newline=None)
        # would convert all \r\n to \n on read, and on Linux the
        # subsequent write would emit only \n -- silently rewriting
        # a CRLF source file to LF and breaking any other patcher
        # that pattern-matches on \r\n.
        with open(engine, 'rb') as f:
            raw = f.read()
        content = raw.decode('utf-8', errors='replace')
    except OSError as e:
        kodi_utils.log(
            'darksubs_patcher: read failed for {0}: {1}'.format(
                engine, e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    # Detect line endings actually in use so we can write HOOK_BODY
    # with matching style. DarkSubs ships engine.py as CRLF; LF-only
    # also exists in the wild (after user edits / git autocrlf).
    eol = '\r\n' if '\r\n' in content[:8192] else '\n'

    # Cleanup of any older-version markers, if we ever bump HOOK_VERSION.
    for old in OLD_MARKERS:
        old_end = old.replace('AI_TRANSLATE_HOOK', 'END AI_TRANSLATE_HOOK', 1)
        # Strip the previous block by removing everything between the
        # old marker line and its matching end marker line.
        pattern = re.compile(
            r'^[ \t]*' + re.escape(old) + r'\b.*?^[ \t]*'
            + re.escape(old_end) + r'\b[^\r\n]*\r?\n',
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

    # Insert hook immediately after the def line. HOOK_BODY is built
    # with LF line terminators; convert to the file's actual EOL so we
    # don't end up with a mixed-EOL file (which Python tolerates but
    # tools like grep -c get confused by).
    insert_at = m.end()
    hook_body = HOOK_BODY if eol == '\n' else HOOK_BODY.replace('\n', eol)
    new_content = (content[:insert_at] + eol + hook_body
                   + content[insert_at:])

    # Atomic write: write to .aitmp, then rename. Binary mode so we
    # preserve the exact line-ending bytes built above.
    tmp_path = engine + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_content.encode('utf-8'))
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

    # Force Python to re-compile from the new .py on next import by
    # wiping any cached .pyc bytecode. Without this, DarkSubs's
    # interpreter (reuselanguageinvoker=true) can keep running the
    # OLD engine.py from its in-memory bytecode cache even though
    # we've replaced the source file. Survives until the .pyc is
    # regenerated from the new .py.
    _invalidate_pyc_cache(engine)

    kodi_utils.log(
        'darksubs_patcher: injected AI hook v{0} into {1}'.format(
            HOOK_VERSION, engine),
        level='INFO')
    return 'patched'


def _invalidate_pyc_cache(py_path):
    """Delete any __pycache__/*.pyc entries that correspond to the
    given .py file. Best-effort; never raises (we're called from a
    hot path that already wrote the .py successfully)."""
    try:
        pkg_dir = os.path.dirname(py_path)
        base = os.path.splitext(os.path.basename(py_path))[0]
        cache_dir = os.path.join(pkg_dir, '__pycache__')
        if not os.path.isdir(cache_dir):
            return
        prefix = base + '.cpython-'
        removed = 0
        for fname in os.listdir(cache_dir):
            if fname.startswith(prefix) and fname.endswith('.pyc'):
                try:
                    os.remove(os.path.join(cache_dir, fname))
                    removed += 1
                except OSError:
                    pass
        if removed:
            try:
                kodi_utils.log(
                    'darksubs_patcher: invalidated {0} stale .pyc '
                    'file(s) for {1}'.format(removed, py_path),
                    level='INFO')
            except Exception:
                pass
    except Exception:
        pass
