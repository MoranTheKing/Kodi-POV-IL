# POV renamed the folder third-party scrapers install into, and the source add-on's
# its scraper stopped arriving.
#
# THE FIELD SYMPTOM, reported 2026-08-26: "the private streaming add-on's
# sources should show at the top, and they are gone entirely." The log says it
# in one line, six seconds into the boot:
#
#     warning <general>: [the source add-on] patch error: [Errno 2] No such file or
#     directory: '.../plugin.video.pov/resources/lib/scrapers/<scraper>.py.tmp'
#
# the source add-on installs its scraper by writing `<scraper>.py.tmp` into POV's
# internal-scraper folder and renaming it into place. POV 6.08.14 deleted that
# folder. It was not restructured -- it was RENAMED, with a byte-identical file
# list:
#
#     6.08.13  resources/lib/scrapers/   ad_cloud aiostreams easynews oc_cloud
#     6.08.14  resources/lib/debrids/    pm_cloud rd_cloud tb_cloud __init__
#
# and POV's own pointer moved with it:
#
#     6.08.13  scrapers_path = '.../resources/lib/scrapers/'
#     6.08.14  internal_path = '.../resources/lib/debrids/'
#
# So the source add-on's write fails, no <scraper>.py exists anywhere, and POV finds
# nothing to load. Nothing is broken inside either add-on; they simply
# disagree about one path.
#
# WHY A SHIM AND NOT A PATCH TO EITHER SIDE. Patching POV to look in the old
# folder would fight the direction its author is going. Patching the source add-on would
# need an anchor in a private add-on we do not ship, cannot test against, and
# which will move the moment its author notices. What both versions DO agree on
# is the loader:
#
#     for loader, module_name, is_pkg in pkgutil.iter_modules([source_path]):
#         if module_name not in self.source.active_internal_scrapers: continue
#         append(('internal', loader.find_spec(module_name)
#                 .loader.load_module(module_name).source, module_name))
#
# READ THE LINE ABOVE IT, THOUGH, BECAUSE THE FIRST VERSION OF THIS FILE DID
# NOT AND SAID SOMETHING FALSE. It claimed "any .py in the folder POV scans is
# loaded". It is not. `active_internal_scrapers()` in modules/settings.py is a
# HARDCODED whitelist built from POV's own `provider.*` settings --
# aiostreams, external, easynews, pm_cloud, oc_cloud, tb_cloud, rd_cloud,
# ad_cloud -- and `that scraper` cannot appear in it. Executing POV's own loader
# over a folder containing <scraper>.py confirms it: iter_modules sees the
# file, the gate skips it, POV never loads it. That is true of 6.08.13 too --
# the function is identical in both but for the order of two lines.
#
# SO ITS SCRAPER NEVER LOADED FROM THAT FOLDER ON ITS OWN, in any version, and
# the source add-on must be registering the name inside POV as well. Its log prefix is
# literally "patch error". We do not ship the source add-on, it is not on this disk, and
# nobody here has read it.
#
# WHAT THAT MEANS FOR THIS FILE, stated plainly rather than glossed:
#   * Creating the folder is a real fix for a real, logged error. the source add-on's
#     write fails at ENOENT; whatever it does after that write never runs.
#     Unblocking it is the only part of this supported by evidence.
#   * The mirror is a HEDGE, not a proven fix. It covers exactly one case:
#     the source add-on registers the name successfully but writes the file to the old
#     folder. If instead its registration patch is also stale against 6.08.14,
#     the mirror changes nothing and its scraper stays gone until the source add-on's
#     author updates it.
# Neither step is claimed to restore its scraper, and the release note must not
# say that it does.
#
# WHAT THIS DOES, in that order and for that reason:
#   1. Re-creates the legacy folder (with the __init__.py POV's own copy had),
#      so the source add-on's write SUCCEEDS instead of erroring. It does not matter
#      that POV no longer reads it -- the source add-on needs somewhere to land.
#   2. Copies anything third-party that appears there into the folder POV
#      actually scans, read from POV's own kodi_utils rather than guessed, so
#      this keeps working when the name changes again.
#
# It therefore takes TWO Kodi starts on a device that has already failed once:
# the first creates the folder, the source add-on writes into it on the next boot, and
# that same pass mirrors it. Nothing can be done about the first one -- by the
# time our repair pass runs, the source add-on's service has already tried and failed.
#
# WHAT IT REFUSES TO COPY. Only files POV does not ship itself. The legacy
# folder is one we create empty, so in practice everything in it is
# third-party -- but the shipped names are excluded by name anyway, because
# copying POV's own ad_cloud.py over POV's own ad_cloud.py is the kind of
# harmless-looking thing that stops being harmless the day the two versions
# differ.

import os
import shutil

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'

# The folder the source add-on (and anything else written against POV <= 6.08.13) still
# writes into.
LEGACY_REL = 'resources/lib/scrapers'

# Where POV looked before it started telling us. Only used if its kodi_utils
# cannot be read at all.
FALLBACK_INTERNAL_REL = 'resources/lib/debrids'

# POV's own internal scrapers, by module name. Identical in both folders across
# 6.08.13 and 6.08.14, which is what makes the rename a rename.
POV_OWN = frozenset((
    '__init__', 'ad_cloud', 'aiostreams', 'easynews', 'oc_cloud', 'pm_cloud',
    'rd_cloud', 'tb_cloud',
))


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_internal_scraper_shim: ' + msg, level=level)
    except Exception:
        pass


def _pov_root():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    return base if os.path.isdir(base) else ''


def _internal_rel(root):
    """The folder POV CURRENTLY scans, read out of POV's own source.

    Parsed, not assumed: POV states it as a one-line assignment in
    modules/kodi_utils.py, and reading it there means the next rename needs no
    change here. `internal_path` is 6.08.14's name and `scrapers_path` was
    6.08.13's; whichever is present wins, newest first.
    """
    ku = os.path.join(root, 'resources', 'lib', 'modules', 'kodi_utils.py')
    try:
        with open(ku, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except Exception:
        return FALLBACK_INTERNAL_REL
    for name in ('internal_path', 'scrapers_path'):
        for line in text.splitlines():
            s = line.strip()
            if not s.startswith(name):
                continue
            if '=' not in s:
                continue
            val = s.split('=', 1)[1].strip().strip('\'"')
            marker = 'addons/' + POV_ADDON_ID + '/'
            if marker in val:
                return val.split(marker, 1)[1].strip('/')
    return FALLBACK_INTERNAL_REL


def _ensure_legacy_dir(root):
    """'exists' | 'created' | 'failed' -- somewhere for the source add-on to land."""
    d = os.path.join(root, *LEGACY_REL.split('/'))
    init = os.path.join(d, '__init__.py')
    if os.path.isdir(d) and os.path.isfile(init):
        return 'exists'
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
        if not os.path.isfile(init):
            # POV's own copy of this folder carried one; a package without it
            # is not importable on every Python path configuration.
            with open(init, 'w', encoding='utf-8') as fh:
                fh.write('')
        return 'created'
    except Exception as exc:
        _log('could not create {0}: {1}'.format(LEGACY_REL, exc),
             level='WARNING')
        return 'failed'


def _inside(root, path):
    """True only if `path` really is under POV's own folder.

    POV's kodi_utils is the input to _internal_rel, and POV is a third-party
    add-on that auto-updates from someone else's repository -- its
    restructuring is the reason this file exists at all. A declared path
    containing `..` walked straight out of the add-on and, two levels up,
    into `addons/`, where Kodi executes whatever Python it finds. A review
    demonstrated it writing to `<home>/addons/evil/<scraper>.py`. realpath on
    both sides, because a symlinked folder defeats a string comparison.
    """
    try:
        r = os.path.realpath(root)
        p = os.path.realpath(path)
    except Exception:
        return False
    return p == r or p.startswith(r + os.sep)


def _mirror(root, internal_rel):
    """Copy third-party scrapers from the legacy folder into the live one.

    Returns a status naming what moved, so a field log says whether its scraper
    is actually present rather than whether this ran.
    """
    src = os.path.join(root, *LEGACY_REL.split('/'))
    dst = os.path.join(root, *internal_rel.split('/'))
    if not _inside(root, dst) or not _inside(root, src):
        _log('refusing to mirror outside the add-on: {0}'.format(internal_rel),
             level='WARNING')
        return 'outside_addon'
    if os.path.normpath(src) == os.path.normpath(dst):
        return 'same_dir'
    if not os.path.isdir(src):
        return 'no_legacy'
    if not os.path.isdir(dst):
        _log('POV scans {0}, which does not exist'.format(internal_rel),
             level='WARNING')
        return 'no_internal'
    moved, failed = [], []
    try:
        names = sorted(os.listdir(src))
    except Exception as exc:
        _log('could not list {0}: {1}'.format(LEGACY_REL, exc),
             level='WARNING')
        return 'list_failed'
    for name in names:
        if not name.endswith('.py'):
            continue
        stem = name[:-3]
        if stem in POV_OWN:
            continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        try:
            if os.path.isfile(d) and os.path.getsize(d) == os.path.getsize(s):
                with open(s, 'rb') as a, open(d, 'rb') as b:
                    if a.read() == b.read():
                        continue
            tmp = d + '.aitmp'
            shutil.copyfile(s, tmp)
            os.replace(tmp, d)
            moved.append(stem)
        except Exception as exc:
            # Appended to `failed`, never silently skipped: a mirror that
            # reports success after the copy raised is worse than one that
            # reports nothing, because service.py greps this string to decide
            # whether to warn.
            failed.append(stem)
            _log('could not mirror {0}: {1}'.format(name, exc), level='WARNING')
    if failed:
        return 'failed:' + '+'.join(failed)
    if moved:
        _log('mirrored %s into %s -- POV will load %s on its next invocation'
             % ('+'.join(moved), internal_rel, '+'.join(moved)))
        return 'mirrored:' + '+'.join(moved)
    return 'nothing_to_mirror'


def ensure_patched():
    """Idempotent. Never raises. Returns a comma-joined status.

    Order matters and is the one thing to preserve: the legacy folder is
    created FIRST, because the mirror has nothing to do until the source add-on has been
    given somewhere its write can succeed.
    """
    root = _pov_root()
    if not root:
        return 'no_pov'
    try:
        internal_rel = _internal_rel(root)
    except Exception as exc:
        _log('could not read POV\'s internal path: {0}'.format(exc),
             level='WARNING')
        internal_rel = FALLBACK_INTERNAL_REL
    out = ['scans=' + internal_rel.rsplit('/', 1)[-1]]
    try:
        out.append('legacy=' + _ensure_legacy_dir(root))
    except Exception as exc:
        _log('unexpected failure creating the legacy folder: {0}'.format(exc),
             level='WARNING')
        out.append('legacy=failed')
        return ', '.join(out)
    try:
        out.append('mirror=' + _mirror(root, internal_rel))
    except Exception as exc:
        _log('unexpected failure mirroring: {0}'.format(exc), level='WARNING')
        out.append('mirror=failed')
    return ', '.join(out)
