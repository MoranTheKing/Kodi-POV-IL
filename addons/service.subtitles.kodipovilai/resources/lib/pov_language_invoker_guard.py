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
# disagree, and only one of the two orders converges on what we want. POV's
# check is what decides that, and it always copies THE SETTING onto the xml,
# so:
#   setting first -> the half that survived is the one POV believes. It
#       rewrites the xml from it and lands on our value, at the cost of one
#       POV dialog.
#   xml first     -> the half that survived is the one POV OVERWRITES. It puts
#       the xml back to the stale setting, and does it again after every boot
#       until we win.
# Writing the xml second also means the common path never shows that dialog:
# both halves already agree, so POV's check finds nothing to do.
# (An earlier version of this passage spelled the two cases out as
# (setting=false, xml=true) and (setting=true, xml=false). That was correct
# only while the target was always 'false'; with pov_fast_navigation on, the
# literals swap and the passage read as if the right outcome were the wrong
# one. The rule never depended on which value we were writing, so it is stated
# without them now.)
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
# WHAT IT COSTS, STATED HONESTLY: every POV invocation gets a fresh
# interpreter, so POV repays its imports each time instead of once. In the very
# scenario this exists for -- several home widgets refreshing together -- the
# trade is one shared interpreter under contention for N interpreters cold-
# starting at the same moment. On the cheap Android boxes this build actually
# runs on, that peak is not free. It is still the right side of the trade,
# because the failure it replaces is the whole application dying, but if POV
# starts feeling heavy after this release, this is the first thing to suspect.
#
# AND IT DID, AND HERE IS THE NUMBER. Field log 2026-08-23, a device on
# 0.2.506 running Estuary, instrumented by pov_directory_timing_patcher next
# door. Sixteen navigations, and the shape of them is the answer:
#
#   * five unrelated routes inside a 0.17s band -- tmdb_tv_networks 1.72s
#     (its floor over twelve samples), tmdb_movies_popular 1.77s,
#     trakt_tv_trending 1.77s, tmdb_movies_latest_releases 1.82s,
#     tmdb_tv_premieres 1.89s. popular and trending are different modules
#     hitting different companies' servers and agree to the hundredth. Stated
#     as the band and not as "a 1.72-1.78s floor under all of them", which is
#     what this passage said first and which the last two figures contradict.
#   * repeat visits do not move it. FOX 2.46s then 1.78s; Amazon 2.24s then
#     1.73s. Roughly 0.6s of each first visit is cacheable network; the floor
#     underneath is not, and never improves.
#
# A route-independent, cache-immune floor is a fixed per-invocation cost. And
# POV pays it in an unusually visible place, which is worth writing down
# because it is why POV feels this and other add-ons do not. Every route
# defers the real weight into the call itself:
#
#     'build_tvshow_list': lambda p: _import('menus.tvshows', 'Menu')(p).run()
#
# Counted over top-level imports on POV 6.08.13, entry.py's own module-level
# closure is 4 local modules / 53KB and 10 external ones. Reaching that route
# then adds TWENTY MORE local modules and 210KB, and twenty-seven more
# externals -- requests, concurrent.futures, xml.etree, unicodedata, hashlib,
# html, importlib, pkgutil, queue, gzip, urllib.request among them. With the
# invoker reused that is paid once for the session. Without it, on every press.
#
# (Two corrections here, both caught by a fact-check before release and both
# worth leaving visible. The figures first written were "2 local modules,
# 19KB" and "20 modules, 218KB": 19597 is entry.py's OWN file size, not the
# size of what it imports, and the walk behind both numbers never followed
# `from modules import kodi_utils` through to the submodule, so it was
# crediting an empty package __init__ instead of the 18KB module. And sqlite3
# was listed among what the route drags in -- entry.py already imports it at
# module level, so it is paid either way and proves nothing here.) Same-device calibration from the same log: our
# own he_warm line reports 3.7 SECONDS to pre-import one engine on that box.
#
# SO THIS IS NOW A SWITCH, AND SAFE IS STILL THE DEFAULT. The owner's call:
# SETTING_FAST below, off out of the box, so nothing changes for anyone who
# does not go looking. Turning it on is choosing the July behaviour and the
# July crash together, knowingly, on one device.
#
# WHAT THE SWITCH DOES NOT DO, SAID BEFORE SOMEBODY ASSUMES IT: it does not
# make reuse safe. Nothing here fixes the crash; it only lets a person decide
# to accept it.
#
# AND THE NARROWING THAT LOOKS OBVIOUS AND IS WRONG. The crash was reported on
# Arctic Fuse 3, so "keep this off for AF3 only and give everyone else their
# speed back" is the first idea anybody has, and this file nearly shipped it.
# The 2026-08-23 log kills it: that device is on ESTUARY, with one person
# pressing buttons, and it still produced two overlapping POV invocations
# (08:39:22-08:39:29, one route stuck at 7.31s while the next press started
# underneath it). Concurrency is not a property of a skin. It is a property of
# a call being slow enough for the next one to land inside it -- which turning
# reuse OFF makes MORE likely, not less. Do not narrow this by skin.
#
# POV'S OWN SERVICE CAN RACE US, AND THAT IS TOLERATED, NOT PREVENTED.
# reuseLanguageInvokerCheck() runs when POV's service starts; this runs from
# our repair pass, which is ~29 steps and several seconds later, so in practice
# POV has long finished. But if POV ever read the setting BEFORE our write and
# wrote the xml AFTER it, it would put back `true` from the stale value it
# read. Nothing here locks against that, for the same reason nothing locks
# against a read-only filesystem: this runs at every start and writes only
# what is wrong, so the next boot repairs it. The cost of losing that race is
# one more restart, not a wrong state that persists.
#
# UNDOING IT IS NOT THE USUAL REMEDY, AND THAT IS WHY THE SWITCH IS HERE.
# Every other POV patcher in this add-on is undone by switching POV patching
# off and reinstalling POV. That does NOT undo this one: `reuse_language_
# invoker` lives in POV's per-profile settings, which a reinstall does not
# touch, and POV's own check then rewrites addon.xml from it regardless of our
# switch. Flipping it by hand in POV's own menu does not last either -- this
# pass turns it straight back around at the next start.
#
# So the remedy is SETTING_FAST, and it is the only one that holds: this
# module enforces whichever side it names, at every boot, in both halves. A
# user who wants POV's reused interpreter turns that on and gets it kept; a
# user who wants it back off turns it off and gets THAT kept. Neither has to
# fight anything.
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

# The two values POV's flag can take, named for what they buy rather than for
# the boolean, because the boolean reads backwards: 'false' -- reuse OFF -- is
# the SAFE side, and it is the one this module used to hard-code.
SAFE = 'false'
FAST = 'true'

# Our own setting, added after the measurement in the header. OFF by default,
# so a device nobody has touched behaves exactly as it did before the switch
# existed.
SETTING_FAST = 'pov_fast_navigation'

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


def _wanted():
    """Which side of the trade this device has asked for.

    SAFE unless our own setting says otherwise, and SAFE through every way of
    failing to find out -- kodi_utils absent, the settings store unreadable,
    the setting undeclared, empty, or holding something that is neither. The
    asymmetry is the whole point. The value we fall back to is the one whose
    failure mode is a slow menu; the value we only ever reach by an explicit
    'true' is the one whose failure mode is the application dying. Nothing
    here may ever be widened into "assume FAST when unsure".

    `is True`, NOT PLAIN TRUTHINESS, and the difference is not pedantry.
    kodi_utils.get_bool returns a real bool today, so both spellings agree --
    but the guarantee above is about what happens when something ELSE breaks,
    and a get_bool that one day returned Kodi's raw string would hand us
    'false', which is truthy, and turn reuse ON on every device on earth. A
    promise that depends on another module keeping its contract is not the
    promise this docstring makes.
    """
    if kodi_utils is None:
        return SAFE
    try:
        return FAST if kodi_utils.get_bool(SETTING_FAST, False) is True \
            else SAFE
    except Exception:
        return SAFE


def describe(wanted):
    """Why this device is on the side it is on, as a log-line clause.

    Here rather than at the call site because the call site is service.py,
    which needs a whole Kodi to import and therefore cannot be tested. A
    ternary over SAFE/FAST written there is a coin-flip nobody would notice
    landing wrong -- and a log that confidently explains the OPPOSITE of what
    was written is worse than no log at all, in a project that reads field
    logs to decide what shipped.

    Tolerant of a value it does not recognise, because a caller that could not
    work out the direction still deserves a line.
    """
    if wanted == SAFE:
        return 'prevents the concurrent-invocation native crash'
    if wanted == FAST:
        return ('the owner turned on %s and accepted that crash risk'
                % SETTING_FAST)
    return 'direction not recognised'


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


def _write_setting(wanted):
    try:
        import xbmcaddon
        xbmcaddon.Addon(POV_ADDON_ID).setSetting(SETTING_ID, wanted)
        return True
    except Exception as exc:
        _log('could not write POV\'s {0} setting: {1}'.format(SETTING_ID, exc),
             level='WARNING')
        return False


def _xml_state(raw):
    """(the element's text as bytes, match) for the one tag, or (None, None).

    None means "do not touch this file", and there are three ways to get it:
    the document does not parse, POV's own reader would not see exactly one
    such element, or the byte pattern cannot describe it uniquely. A file we
    cannot describe exactly is a file we have no business rewriting.

    TWO READERS, ON PURPOSE. ElementTree decides WHETHER there is an element,
    because it is the same reader POV uses (`root.iter('reuselanguageinvoker')`
    in entry.py) and it is blind to comments -- a byte pattern is not, and on
    a hand-corrupted file whose only remaining copy of the tag sits inside an
    XML comment, a pattern-only guard would happily rewrite the comment,
    report success, and leave POV showing its mismatch dialog forever. The
    byte pattern then decides WHERE to write, so the rest of the file survives
    untouched instead of being re-serialised.

    THE TWO EMPTY FORMS ARE TREATED DIFFERENTLY, AND THAT IS DELIBERATE.
    `<reuselanguageinvoker></reuselanguageinvoker>` is matchable, so it gets
    rewritten to whichever value we want; a self-closing
    `<reuselanguageinvoker />` -- which
    ElementTree emits whenever the text is empty -- is not, so it is left
    alone. They are XML-equivalent, so the asymmetry needs a reason, and it is
    NOT "one is already off": Kodi reads both empty forms as not-true, so
    reuse is already off in both. The reason we rewrite at all is to make
    POV's own check silent, because that check is an exact string compare --
    the xml's text against POV's OWN SETTING, not against any fixed word -- so
    an xml that does not spell out exactly what the setting says leaves POV
    re-showing its dialog every boot. (This sentence used to name `false` as
    the value in question. That was only ever true because the target was
    hard-coded to `false`.)
    Only the pair form can be given that text without inventing structure the
    file does not have; the self-closing one is left for POV to reconcile from
    the setting we have just corrected, which costs one dialog and settles.
    """
    try:
        import xml.etree.ElementTree as ET
        elements = list(ET.fromstring(raw).iter('reuselanguageinvoker'))
    except Exception:
        return None, None
    if len(elements) != 1:
        return None, None
    found = _TAG_RE.findall(raw)
    if len(found) != 1:
        return None, None
    return found[0][2], _TAG_RE.search(raw)


def _write_xml(path, raw, match, wanted):
    """Replace only the tag's text, atomically. True on success."""
    out = (raw[:match.start()]
           + match.group(1) + wanted.encode('ascii') + match.group(5)
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
        except Exception as cleanup_exc:
            # Say so. The line above this one logs why the write failed; a
            # silent second failure here would leave a stray file next to
            # POV's addon.xml with nothing in the log to explain it.
            _log('and its temp file could not be removed either: {0}'.format(
                cleanup_exc), level='WARNING')
        return False


def ensure_patched(wanted=None):
    """Hold POV's reuse-language-invoker flag at the value this device has
    asked for, in both places POV keeps it.

    `wanted` lets a caller that has ALREADY read the direction pass it in, so
    the setting is read once for the whole step instead of once here and once
    again to write a log line about it. Anything that is not exactly SAFE or
    FAST is ignored and the direction is worked out here -- a caller must not
    be able to widen the answer by passing something odd.

    Returns one of:
      'no_pov'        POV is not installed -> nothing to do
      'unreadable'    POV's setting could not be read -> nothing written
      'already_set'   both halves already agree with us -> nothing written
      'patched'       setting and addon.xml now both say what we want
      'setting_only'  the setting was written, addon.xml was not (POV's own
                      check will finish the job, with its dialog)
      'no_tag'        addon.xml has no single REWRITABLE reuselanguageinvoker
                      element -- absent, duplicated, self-closing, or in a
                      document that does not parse. The setting is still
                      written, and POV reconciles the xml from it.
      'write_failed'  nothing was written
    Never raises.

    ONE VALUE, DECIDED ONCE, AT THE TOP. _wanted() is read a single time and
    threaded through every write below. Reading it again per half would let a
    setting changed mid-pass leave the two halves disagreeing -- which is the
    one state POV reacts to with a dialog at every boot.
    """
    path = _addon_xml_path()
    if not path:
        return 'no_pov'

    if wanted not in (SAFE, FAST):
        wanted = _wanted()

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

    xml_val, match = (None, None) if raw is None else _xml_state(raw)

    setting_ok = cur == wanted
    # EXACT BYTES, not a case-folded compare, because POV's check is exact:
    # `item.text != current_addon_setting` in entry.py. An addon.xml reading
    # `False` would satisfy a lenient guard, which would then leave POV
    # detecting a mismatch and re-showing its reload dialog at every single
    # boot, forever, with nothing on either side ever fixing the casing.
    xml_ok = xml_val == wanted.encode('ascii')
    if setting_ok and xml_ok:
        return 'already_set'

    wrote_setting = setting_ok or _write_setting(wanted)
    if not wrote_setting:
        return 'write_failed'

    if xml_ok:
        return 'patched'
    if match is None:
        # Either unreadable or not a file we can describe. The setting is
        # correct now, and POV's reuseLanguageInvokerCheck reconciles from the
        # setting, so the outcome still lands -- just not silently.
        return 'no_tag' if raw is not None else 'setting_only'
    if _write_xml(path, raw, match, wanted):
        return 'patched'
    return 'setting_only'
