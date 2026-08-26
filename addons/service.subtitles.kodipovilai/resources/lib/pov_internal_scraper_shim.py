# POV renamed the folder it loads internal scrapers from, so anything a
# third-party add-on installed there stopped being scraped at all.
#
# THE FIELD SYMPTOM, 2026-08-26: "it does not show the internal sources any
# more, only the external ones." A source add-on installs itself into POV by
# writing a scraper module into POV's internal-scraper folder and registering
# its name in POV's settings. The log names the first half in one line, six
# seconds into the boot:
#
#     warning <general>: [<addon>] patch error: [Errno 2] No such file or
#     directory: '.../plugin.video.pov/resources/lib/scrapers/<scraper>.py.tmp'
#
# POV 6.08.14 did not restructure that folder, it RENAMED it, with a
# byte-identical file list, and moved its own pointer with it:
#
#     6.08.13  resources/lib/scrapers/   scrapers_path
#     6.08.14  resources/lib/debrids/    internal_path
#
# and the one line in modules/sources.py that reads it is otherwise unchanged:
#
#     6.08.13  source_path = translate_path(kodi_utils.scrapers_path)
#     6.08.14  source_path = translate_path(kodi_utils.internal_path)
#     both     for loader, module_name, is_pkg in
#                  pkgutil.iter_modules([source_path]):
#
# So POV scans exactly ONE folder, and after 6.08.14 it is not the folder
# third-party installers write to. Their module is never even looked at. That
# is the whole of "internal sources stopped appearing".
#
# TWO THINGS ARE THEREFORE NEEDED, AND THIS FILE DOES BOTH.
#
#   1. The old folder has to EXIST, or the installer's write raises ENOENT.
#      That matters more than it looks: such an installer writes its module as
#      the FIRST of several edits, so the exception aborts everything after it
#      -- including the settings edit that registers the name. That is why the
#      feature vanished outright instead of degrading, and why re-creating an
#      empty folder is a real fix rather than housekeeping.
#
#   2. POV has to LOOK in it. `pkgutil.iter_modules` already takes a LIST of
#      directories, so one edit to that line makes POV scan its own folder and
#      the legacy one together.
#
# WHY THIS REPLACED A MIRROR. The first version copied files from the legacy
# folder into POV's, which only works if our startup pass happens to run after
# the other add-on's service that boot -- and that add-on re-checks on its own
# timer, not ours, so a device could sit for an hour with the file written and
# never copied. Teaching POV to scan both folders removes the race entirely:
# whenever the file appears, the next scrape sees it. It also stops us writing
# into somebody else's add-on directory, which a review had already caught
# escaping POV's tree through a `..` in POV's own declared path.
#
# ORDER IS LOAD-BEARING AND IT IS POV'S FOLDER FIRST. iter_modules dedupes by
# module name and the first directory wins, so a stale `rd_cloud.py` left in
# the legacy folder can never shadow POV's own. Verified rather than assumed:
# iter_modules over two directories holding an overlapping name yields it once,
# from the first.
#
# WHAT THIS STILL DOES NOT DO. POV gates loading with active_internal_scrapers()
# in modules/settings.py -- a hardcoded whitelist built from its own provider.*
# settings -- so a module in the folder is loaded only if something has put its
# name in that list. That registration belongs to the installer, and its own
# edit for it still matches 6.08.14. If a future POV changes THAT function, the
# name stops being registered and no amount of folder-scanning here will help.
# Said plainly so the next person does not assume this file is the whole path.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'

# The folder third-party installers written against POV <= 6.08.13 still use.
LEGACY_REL = 'resources/lib/scrapers'

SOURCES_REL = 'resources/lib/modules/sources.py'

MARKER = '# AI_SUBS_POV_INTERNAL_DIRS_v1'
_MARKER_ANY = '# AI_SUBS_POV_INTERNAL_DIRS_v'

# The line POV reads its internal-scraper folder from. Matched together with
# the `for` beneath it, so it cannot land on another translate_path call, and
# with the pointer name left as a placeholder so BOTH POV versions match.
_ANCHOR_TMPL = (
    "\t\tsource_path = kodi_utils.translate_path(kodi_utils.%s)\n"
    "\t\tfor loader, module_name, is_pkg in "
    "__import__('pkgutil').iter_modules([source_path]):"
)
_POINTER_NAMES = ('internal_path', 'scrapers_path')

_REPLACEMENT_TMPL = (
    "\t\tsource_path = kodi_utils.translate_path(kodi_utils.%s)  " + MARKER
    + "\n"
    "\t\t_ai_dirs = [source_path]\n"
    "\t\ttry:\n"
    "\t\t\t_ai_legacy = kodi_utils.translate_path('special://home/addons/"
    + POV_ADDON_ID + "/" + LEGACY_REL + "/')\n"
    "\t\t\tif __import__('os').path.isdir(_ai_legacy) and _ai_legacy "
    "not in _ai_dirs: _ai_dirs.append(_ai_legacy)\n"
    "\t\texcept Exception: pass\n"
    "\t\tfor loader, module_name, is_pkg in "
    "__import__('pkgutil').iter_modules(_ai_dirs):"
)


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


def _ensure_legacy_dir(root):
    """'exists' | 'created' | 'failed' -- somewhere the installer can land."""
    d = os.path.join(root, *LEGACY_REL.split('/'))
    init = os.path.join(d, '__init__.py')
    if os.path.isdir(d) and os.path.isfile(init):
        return 'exists'
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
        if not os.path.isfile(init):
            # POV's own copy of this folder shipped one, and a package without
            # it is not importable on every Python path configuration.
            with open(init, 'w', encoding='utf-8') as fh:
                fh.write('')
        return 'created'
    except Exception as exc:
        _log('could not create {0}: {1}'.format(LEGACY_REL, exc),
             level='WARNING')
        return 'failed'


def _drop_pyc(path):
    """A stale .pyc would keep the one-folder scan alive after the rewrite."""
    stem = os.path.basename(path)[:-3] + '.'
    cache = os.path.join(os.path.dirname(path), '__pycache__')
    try:
        for name in os.listdir(cache):
            if name.startswith(stem) and name.endswith('.pyc'):
                os.remove(os.path.join(cache, name))
    except Exception:
        pass


def _teach_pov_both_dirs(root):
    """'unchanged' | 'patched' | 'unmatched' | 'read_failed'
    | 'compile_failed' | 'write_failed' | 'no_file'."""
    path = os.path.join(root, *SOURCES_REL.split('/'))
    if not os.path.isfile(path):
        return 'no_file'
    try:
        with open(path, encoding='utf-8', newline='') as fh:
            content = fh.read()
    except Exception as exc:
        _log('read failed: {0}'.format(exc), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'unchanged'
    if _MARKER_ANY in content:
        _log('carries an older version of this patch; leaving it alone',
             level='WARNING')
        return 'unchanged'

    eol = '\r\n' if '\r\n' in content[:8192] else '\n'
    fit = (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t)

    for name in _POINTER_NAMES:
        anchor = fit(_ANCHOR_TMPL % name)
        if content.count(anchor) != 1:
            continue
        new_content = content.replace(
            anchor, fit(_REPLACEMENT_TMPL % name), 1)
        try:
            compile(new_content.replace('\r\n', '\n'), path, 'exec')
        except SyntaxError as exc:
            _log('patched sources.py would not compile -- skipping '
                 '({0})'.format(exc), level='WARNING')
            return 'compile_failed'
        tmp = path + '.aitmp'
        try:
            with open(tmp, 'w', encoding='utf-8', newline='') as fh:
                fh.write(new_content)
            os.replace(tmp, path)
        except Exception as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            _log('write failed: {0}'.format(exc), level='WARNING')
            return 'write_failed'
        _drop_pyc(path)
        _log('POV now scans both internal-scraper folders; third-party '
             'scrapers are seen again at its next scrape')
        return 'patched'

    _log('sources.py does not read its scraper folder in the shape this '
         'patches; leaving it alone', level='WARNING')
    return 'unmatched'


def ensure_patched():
    """Idempotent. Never raises. A comma-joined status.

    The folder is created FIRST. The scan edit alone would find nothing, and
    the installer whose write it unblocks needs somewhere to put its module
    before its own next run.
    """
    root = _pov_root()
    if not root:
        return 'no_pov'
    out = []
    try:
        out.append('legacy=' + _ensure_legacy_dir(root))
    except Exception as exc:
        _log('unexpected failure creating the legacy folder: {0}'.format(exc),
             level='WARNING')
        out.append('legacy=failed')
    try:
        out.append('scan=' + _teach_pov_both_dirs(root))
    except Exception as exc:
        _log('unexpected failure teaching POV both folders: {0}'.format(exc),
             level='WARNING')
        out.append('scan=failed')
    return ', '.join(out)
