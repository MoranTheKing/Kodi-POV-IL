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
# AND A THIRD EDIT, WHICH IS THE ONE THAT MAKES THE OTHER TWO SAFE TO MAKE.
# Getting a third-party module LOADED is not enough; its rows then flow into
# POV's sorter, and modules/sources.py does this for every row of every result
# set:
#
#     def sort_results(self, results):
#         for item in results:
#             ...
#             item['provider_rank'] = self.get_provider_rank(account_type)
#
#     def get_provider_rank(self, account_type):
#         return self.source.provider_sort_ranks[account_type] or 11
#
# A BARE SUBSCRIPT. A provider name that is not in that dict raises KeyError
# out of sort_results, which is called unguarded from process() -> get_sources()
# -> source_select(), so the whole list dies -- including POV's own sources.
# Reproduced against POV's own function: `rd_cloud` ranks 2, an unregistered
# name raises.
#
# Registering the rank is the installer's job and its edit for it is stale on
# 6.08.14, so without this the shim would turn "some sources missing" into
# "nothing plays at all", which is far worse than the bug being fixed. The fix
# is one token -- `.get(account_type)` instead of `[account_type]` -- and it
# changes nothing for a name that IS registered, because POV already treats a
# falsy rank as 11 and `.get` returns None for a miss. It also protects POV
# from every future provider it does not know about, not just this one.
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

# Identical in 6.08.13 and 6.08.14, so one anchor covers both.
_RANK_ANCHOR = (
    "\t\treturn self.source.provider_sort_ranks[account_type] or 11")
_RANK_REPLACEMENT = (
    "\t\treturn self.source.provider_sort_ranks.get(account_type) or 11  "
    + "# AI_SUBS_POV_RANK_MISS_v1")
_RANK_MARKER = '# AI_SUBS_POV_RANK_MISS_v1'
_RANK_MARKER_ANY = '# AI_SUBS_POV_RANK_MISS_v'

MARKER = '# AI_SUBS_POV_INTERNAL_DIRS_v2'
_MARKER_ANY = '# AI_SUBS_POV_INTERNAL_DIRS_v'

# ---------------------------------------------------------------------------
# TWO SHAPES, because POV 6.09.01 changed both halves of this loop.
#
# SHAPE A (6.08.13 - 6.08.15). Discovery and loading both go through the
# `loader` that pkgutil hands back for the directory the module was found in:
#
#     for loader, module_name, is_pkg in __import__('pkgutil').iter_modules([source_path]):
#         ...
#         append(('internal', loader.find_spec(module_name).loader.load_module(module_name).source, module_name))
#
# Adding a directory to that list is enough: whatever is found there is loaded
# from there. That is all v1 did, and it worked.
#
# SHAPE B (6.09.01+). Two edits upstream, and only the first is cosmetic:
#
#     for loader, module_name, is_pkg in pkgutil.iter_modules([source_path]):   <- pkgutil now imported at the top
#         ...
#         try: module_source = importlib.import_module('.' + module_name, package='debrids').source
#
# THE SECOND EDIT IS THE ONE THAT MATTERS, and patching only the scan line
# would have looked like a fix while fixing nothing. `import_module('.name',
# package='debrids')` resolves through POV's OWN debrids package, not through
# the directory the module was discovered in. So a scraper in the legacy folder
# is now FOUND by the scan and then fails to import -- POV logs
# 'Error: Loading module' and carries on with its own sources only. Extending
# the scan alone would move the failure two lines down and leave the symptom
# identical.
#
# So shape B is anchored on the WHOLE block, scan and load together, and the
# replacement keeps POV's import first and falls back to loading from the
# discovered file only when that raises. POV's own scrapers live in `debrids`,
# take the first branch, and behave exactly as upstream wrote them; nothing
# else can reach the fallback, because a name that imports cleanly never gets
# there.
#
# Both shapes are carried rather than the newest only: 6.08.15 is still on
# devices that have not auto-updated, and it is still the shape our own test
# fixtures pin.
_POINTER_NAMES = ('internal_path', 'scrapers_path')

# The extra-directory prologue, shared by both shapes.
_DIRS_PROLOGUE = (
    "\t\t_ai_dirs = [source_path]\n"
    "\t\ttry:\n"
    "\t\t\t_ai_legacy = kodi_utils.translate_path('special://home/addons/"
    + POV_ADDON_ID + "/" + LEGACY_REL + "/')\n"
    "\t\t\tif __import__('os').path.isdir(_ai_legacy) and _ai_legacy "
    "not in _ai_dirs: _ai_dirs.append(_ai_legacy)\n"
    "\t\texcept Exception: pass\n"
)

# --- shape A -----------------------------------------------------------
_ANCHOR_A_TMPL = (
    "\t\tsource_path = kodi_utils.translate_path(kodi_utils.%s)\n"
    "\t\tfor loader, module_name, is_pkg in "
    "__import__('pkgutil').iter_modules([source_path]):"
)
_REPLACEMENT_A_TMPL = (
    "\t\tsource_path = kodi_utils.translate_path(kodi_utils.%s)  " + MARKER
    + "\n"
    + _DIRS_PROLOGUE
    + "\t\tfor loader, module_name, is_pkg in "
    "__import__('pkgutil').iter_modules(_ai_dirs):"
)

# --- shape B -----------------------------------------------------------
_ANCHOR_B_TMPL = (
    "\t\tsource_path = kodi_utils.translate_path(kodi_utils.%s)\n"
    "\t\tfor loader, module_name, is_pkg in "
    "pkgutil.iter_modules([source_path]):\n"
    "\t\t\tif is_pkg: continue\n"
    "\t\t\tif module_name not in self.source.active_internal_scrapers: "
    "continue\n"
    "\t\t\tif prescrape and not check_prescrape_sources(module_name, "
    "self.source.mediatype): continue\n"
    "\t\t\ttry: module_source = importlib.import_module('.' + module_name, "
    "package='debrids').source"
)
_REPLACEMENT_B_TMPL = (
    "\t\tsource_path = kodi_utils.translate_path(kodi_utils.%s)  " + MARKER
    + "\n"
    + _DIRS_PROLOGUE
    + "\t\tfor loader, module_name, is_pkg in "
    "pkgutil.iter_modules(_ai_dirs):\n"
    "\t\t\tif is_pkg: continue\n"
    "\t\t\tif module_name not in self.source.active_internal_scrapers: "
    "continue\n"
    "\t\t\tif prescrape and not check_prescrape_sources(module_name, "
    "self.source.mediatype): continue\n"
    "\t\t\ttry:\n"
    "\t\t\t\ttry: module_source = importlib.import_module('.' + "
    "module_name, package='debrids').source\n"
    "\t\t\t\texcept Exception:\n"
    "\t\t\t\t\t_ai_spec = loader.find_spec(module_name)\n"
    "\t\t\t\t\t_ai_mod = __import__('importlib.util').util."
    "module_from_spec(_ai_spec)\n"
    "\t\t\t\t\t_ai_spec.loader.exec_module(_ai_mod)\n"
    "\t\t\t\t\tmodule_source = _ai_mod.source"
)

# (anchor template, replacement template) newest first. Each is tried against
# every pointer name; the first pair that matches EXACTLY once wins.
_SHAPES = ((_ANCHOR_B_TMPL, _REPLACEMENT_B_TMPL),
           (_ANCHOR_A_TMPL, _REPLACEMENT_A_TMPL))


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


def _pick(content, fit):
    """The (anchor, replacement) this POV actually has, or None.

    Newest shape first, and each shape is tried against every pointer name POV
    has used for the folder. A shape must match EXACTLY once: two matches means
    the block is not the unique thing this describes, and patching the first
    would be a guess.
    """
    for anchor_tmpl, replacement_tmpl in _SHAPES:
        for name in _POINTER_NAMES:
            anchor = fit(anchor_tmpl % name)
            if content.count(anchor) == 1:
                return anchor, fit(replacement_tmpl % name)
    return None


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

    pair = _pick(content, fit)
    if pair is None:
        _log('sources.py does not read its scraper folder in the shape this '
             'patches; leaving it alone', level='WARNING')
        return 'unmatched'
    anchor, replacement = pair
    new_content = content.replace(anchor, replacement, 1)
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


def _guard_unknown_provider(root):
    """Stop one unknown provider name taking every source down with it.

    'unchanged' | 'patched' | 'unmatched' | 'read_failed' | 'compile_failed'
    | 'write_failed' | 'no_file'. See the header: this is what makes scanning
    a second folder safe rather than dangerous.
    """
    path = os.path.join(root, *SOURCES_REL.split('/'))
    if not os.path.isfile(path):
        return 'no_file'
    try:
        with open(path, encoding='utf-8', newline='') as fh:
            content = fh.read()
    except Exception as exc:
        _log('read failed: {0}'.format(exc), level='WARNING')
        return 'read_failed'
    if _RANK_MARKER in content:
        return 'unchanged'
    if _RANK_MARKER_ANY in content:
        # A bump to v2 finds its own v1 in place and the anchor already gone.
        # Without this it falls through to the count check and reports a shape
        # mismatch -- which reads as "POV refactored" when POV did nothing, and
        # sends the next maintainer looking for a change that never happened.
        # This module is pinned NEVER-UPGRADES for exactly that reason: it
        # refuses a block it no longer describes rather than guessing at it.
        _log('carries an older version of this guard; leaving it alone',
             level='WARNING')
        return 'unchanged'
    eol = '\r\n' if '\r\n' in content[:8192] else '\n'
    fit = (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t)
    anchor = fit(_RANK_ANCHOR)
    if content.count(anchor) != 1:
        _log('the provider-rank lookup is not the shape this guards '
             '({0} match(es)); leaving it alone'.format(content.count(anchor)),
             level='WARNING')
        return 'unmatched'
    new_content = content.replace(anchor, fit(_RANK_REPLACEMENT), 1)
    try:
        compile(new_content.replace('\r\n', '\n'), path, 'exec')
    except SyntaxError as exc:
        _log('guarded sources.py would not compile -- skipping '
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
    _log('an unknown provider name no longer raises out of POV\'s sorter')
    return 'patched'


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
    try:
        out.append('rank=' + _guard_unknown_provider(root))
    except Exception as exc:
        _log('unexpected failure guarding the provider rank: {0}'.format(exc),
             level='WARNING')
        out.append('rank=failed')
    return ', '.join(out)
