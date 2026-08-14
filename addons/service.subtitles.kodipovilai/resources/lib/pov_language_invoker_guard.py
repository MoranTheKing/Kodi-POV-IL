# Turn POV's reuse-language-invoker OFF. It is what turns a burst of
# concurrent widget loads into a native crash that takes the whole app down.
#
# THE CRASH (field report + minidump, 2026-08-14, Arctic Fuse 3):
#   Kodi force-closes when the user returns from a hub window to the home
#   screen. The minidump's faulting thread is a NULL refcount write inside
#   python3.8.dll (`inc qword ptr [r9]`, R9 = 0), and Kodi logs the OS thread
#   id, so that thread could be matched to a log line rather than guessed:
#   it is POV's invoker. Five POV invocations were started within 39 ms of
#   each other -- the home widgets all refreshing at once.
#
# THE MECHANISM, WHICH WE ALREADY DOCUMENTED IN JULY:
#   pov_widget_crash_guard.py, written 2026-07-16 for a crash with the same
#   signature, names it exactly --
#     "POV ships <reuselanguageinvoker>true</reuselanguageinvoker>, so those
#      concurrent invocations share ONE Python interpreter. The concurrent
#      access corrupts CPython dict internals ... -> the whole Kodi app dies."
#
# WHY A THIRD TRIGGER-SPECIFIC GUARD WOULD BE THE WRONG FIX. Two triggers have
# been closed one at a time already: the container_refresh() ping we injected
# ourselves (pov_container_refresh_crash_fix) and POV's Trakt sync refresh
# (pov_widget_crash_guard). Tonight's trigger is neither -- it is the ordinary
# home-screen refresh on returning from Custom_1101_Hub.xml -- and there is no
# reason to believe it is the last one. Every one of those guards lowers the
# PROBABILITY of concurrent invocations. `reuselanguageinvoker` is what makes
# concurrency fatal instead of merely slow, so turning it off closes every
# trigger at once, including the ones nobody has hit yet.
#
# POV OWNS THIS FLAG -- SO WE USE POV'S OWN MECHANISM, NOT A FILE EDIT ALONE.
# Reading POV 6.08.x's source rather than assuming:
#   * resources/settings.xml declares a hidden setting
#         <setting id="reuse_language_invoker" type="text" default="true" .../>
#   * resources/lib/entry.py reuseLanguageInvokerCheck() runs as a POV service
#     at every start: if addon.xml disagrees with that setting, it REWRITES
#     addon.xml to match THE SETTING and offers a profile reload.
#   * modules/kodi_utils.py toggle_language_invoker() is POV's own user-facing
#     switch, and it writes BOTH -- addon.xml and the setting.
# So editing addon.xml alone would have been undone by POV on the next start,
# with an English "SETTING/XML mismatch" dialog thrown at the user for it. We
# write both, exactly as POV's own toggle does.
#
# POV'S OWN OPINION OF THE DIRECTION: toggle_language_invoker() asks for a
# second confirmation ("Changing this setting may cause addon instability")
# only when turning the flag back ON. Off is the side POV itself treats as
# safe.
#
# ORDER MATTERS, AND IT IS SETTING FIRST. If the second write is lost (a
# read-only filesystem, a device pulled at the wrong second) the two halves
# disagree, and only one of the two orders converges on what we want:
#   setting first -> (setting=false, xml=true): POV's own check rewrites the
#       xml to false for us. Right outcome, at the cost of one POV dialog.
#   xml first     -> (setting=true, xml=false): POV's check reverts the xml to
#       TRUE, and does it again after every boot until we win.
# Writing the xml second also means the common path never shows that dialog:
# both halves already agree, so POV's check finds nothing to do.
#
# WHEN IT TAKES EFFECT: the NEXT Kodi start. Kodi parses addon.xml while it
# builds its add-on list, which is long before this repair pass runs, so the
# flag Kodi is using for the current session was read before we changed it.
# We deliberately do NOT force it live: POV applies it with
# LoadProfile(<profile>), which restarts every service and drops the user back
# at the home screen, and Kodi's UpdateLocalAddons() rebuilds the add-on
# database underneath a wizard hot-reload that is polling it. Neither belongs
# in an unattended startup pass. One restart is the whole cost.
#
# WHAT IT COSTS: every POV invocation gets a fresh interpreter, so POV repays
# its imports each time instead of once. Menus and widgets are somewhat slower
# to draw. That is the trade being made on purpose -- against a crash that
# takes the entire application down, on a build whose home screen loads
# several POV widgets at once by design.
#
# Self-healing: runs every startup and WRITES ONLY WHAT IS WRONG, so a device
# that is already safe is a pure no-op, and a POV self-update that restores
# its own addon.xml is repaired on the next start. Never raises.

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
SETTING_ID = 'reuse_language_invoker'
WANTED = 'false'

# Matched on BYTES, and deliberately tolerant about the element's inner
# whitespace: POV's own check writes this file with ElementTree, which is free
# to re-indent it. The tag name itself is the anchor, and it has to appear
# exactly once or we do not touch the file.
_TAG_RE = re.compile(
    br'(<reuselanguageinvoker\s*>)(\s*)([A-Za-z]*)(\s*)(</reuselanguageinvoker\s*>)')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_language_invoker_guard: ' + msg, level=level)
    except Exception:
        pass


def _addon_xml_path():
    """Absolute path of POV's addon.xml, or '' when POV is not installed."""
    if xbmcvfs is None:
        return ''
    # The join and the isfile are INSIDE the try, not after it. Wrapping only
    # the translatePath call was a "never raises" that was not one: a
    # translatePath returning None makes os.path.join raise TypeError, and a
    # path with a null byte makes os.path.isfile raise ValueError -- both
    # straight out through ensure_patched, whose docstring promises otherwise.
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
        path = os.path.join(base, 'addon.xml')
        return path if os.path.isfile(path) else ''
    except Exception:
        return ''


def _read_setting():
    """POV's stored flag, lowercased. Returns None when it cannot be read.

    An unset setting reads back as '', and POV itself resolves that to 'true'
    (get_setting('reuse_language_invoker', 'true')), so we resolve it the same
    way -- guessing 'false' there would make us skip a device that is in fact
    still exposed.
    """
    try:
        import xbmcaddon
    except Exception:
        return None
    try:
        addon = xbmcaddon.Addon(POV_ADDON_ID)
    except Exception:
        return None
    try:
        cur = (addon.getSetting(SETTING_ID) or '').strip().lower()
    except Exception:
        return None
    return cur or 'true'


def _write_setting():
    try:
        import xbmcaddon
        xbmcaddon.Addon(POV_ADDON_ID).setSetting(SETTING_ID, WANTED)
        return True
    except Exception as exc:
        _log('could not write POV\'s {0} setting: {1}'.format(SETTING_ID, exc),
             level='WARNING')
        return False


def _xml_value(raw):
    """('false' | 'true' | ..., match) for the one tag, or (None, None).

    None means "do not touch this file": either the tag is absent (POV warns
    about that itself) or it appears more than once, and a file we cannot
    describe exactly is a file we have no business rewriting.
    """
    found = _TAG_RE.findall(raw)
    if len(found) != 1:
        return None, None
    match = _TAG_RE.search(raw)
    try:
        return found[0][2].decode('ascii', 'replace').strip().lower(), match
    except Exception:
        return None, None


def _write_xml(path, raw, match):
    """Replace only the tag's text, atomically. True on success."""
    out = (raw[:match.start()]
           + match.group(1) + WANTED.encode('ascii') + match.group(5)
           + raw[match.end():])

    # The same rule the .py patchers in this add-on follow -- they compile()
    # what they are about to write and refuse if it does not -- applied to the
    # format this one writes. POV's addon.xml is the file Kodi needs to load
    # POV AT ALL, so shipping an unparseable one would not be a failed patch,
    # it would be a device with no video add-on.
    try:
        import xml.etree.ElementTree as ET
        ET.fromstring(out)
    except Exception as exc:
        _log('the rewritten addon.xml would not parse, leaving it alone: '
             '{0}'.format(exc), level='WARNING')
        return False

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'wb') as fh:
            fh.write(out)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                # fsync is a durability guarantee, not a correctness one, and
                # it is not available on every Android filesystem. Losing it
                # must not lose the write.
                pass
        os.replace(tmp, path)
        return True
    except Exception as exc:
        _log('could not rewrite addon.xml: {0}'.format(exc), level='WARNING')
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return False


def ensure_patched():
    """Force POV's reuse-language-invoker flag off, in both places POV keeps
    it. Returns one of:
      'no_pov'        POV is not installed -> nothing to do
      'unreadable'    POV's setting could not be read -> nothing written
      'already_off'   both halves already say false -> nothing written
      'patched'       setting and addon.xml now both say false
      'setting_only'  the setting was written, addon.xml was not (POV's own
                      check will finish the job, with its dialog)
      'no_tag'        addon.xml has no single reuselanguageinvoker element
      'write_failed'  nothing was written
    Never raises."""
    path = _addon_xml_path()
    if not path:
        return 'no_pov'

    cur = _read_setting()
    if cur is None:
        # POV is on disk but Kodi will not give us its settings. Writing the
        # xml on its own is the one combination POV actively undoes, so the
        # only safe move is to write nothing and try again next start.
        return 'unreadable'

    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except Exception as exc:
        _log('could not read addon.xml: {0}'.format(exc), level='WARNING')
        raw = None

    xml_val, match = (None, None) if raw is None else _xml_value(raw)

    setting_ok = cur == WANTED
    xml_ok = xml_val == WANTED
    if setting_ok and xml_ok:
        return 'already_off'

    wrote_setting = setting_ok or _write_setting()
    if not wrote_setting:
        return 'write_failed'

    if xml_ok:
        return 'patched'
    if match is None:
        # Either unreadable or not a file we can describe. The setting is
        # correct now, and POV's reuseLanguageInvokerCheck reconciles from the
        # setting, so the outcome still lands -- just not silently.
        return 'no_tag' if raw is not None else 'setting_only'
    if _write_xml(path, raw, match):
        return 'patched'
    return 'setting_only'
