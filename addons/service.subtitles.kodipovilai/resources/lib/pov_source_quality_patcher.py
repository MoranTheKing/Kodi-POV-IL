# Fix "a source whose NAME says 1080p is shown with an SD badge" -- AND keep the
# list ordered by quality then size -- in POV's source-results window.
#
# Why it happens (stock POV, verified): POV derives the quality badge from a
# scraper-supplied `name_info` field (or the stripped URL), NOT from the release
# name shown on the row. When a provider gives a display name containing
# "1080p"/"2160p"/"720p" but a name_info/URL without a resolution token,
# get_release_quality returns 'SD', so the row shows the 1080p name with an SD
# badge. POV then SORTS the whole list by that stored quality upstream
# (modules/sources.py sort_results), so a misclassified row is also mis-sorted
# -- e.g. a genuinely-1080p release sits down among the SD rows.
#
# Fix: patch windows/sources.py::make_items to, once per window BEFORE the row
# loop: for every result whose stored quality is SD/empty, re-derive it from the
# visible name (URLName/name) with POV's OWN get_release_quality and upgrade the
# badge to it (4K/1080p/720p); then re-order self.results by quality high->low,
# then size (GB) high->low. Never downgrades and never invents a quality the
# name lacks; genuine-SD names stay SD. Every downstream reader (badge icon,
# colour, quality text) reflects the corrected list.
#
# It RELABELS ONLY -- it never removes a row. An earlier version also re-applied
# the user's resolution filter to the rows it relabelled, and that made this the
# one piece of injected code able to make POV's result list SHORTER. A list that
# comes back empty is exactly what POV reports as "no results", with no error
# anywhere to point at, so a single wrong assumption here reads to the user as
# "nothing plays any more" -- and it depended on a POV setting name and value
# format that upstream is free to change. POV has already applied the filter
# upstream; a row that reached this window is one POV chose to show, and
# correcting its label is not a reason to take it away.
#
# Rows flagged with a truthy '_pin_top' (sources that must always stay at the
# top, e.g. built-in-language sources) are kept at the top and are exempt from
# the upgrade, the filter-drop, and the quality/size re-sort -- they retain
# their original order.
#
# Inserted just before the same row-loop line the subtitle-match patcher relies
# on, so it is proven to exist in the installed POV. Idempotent (reverts its own
# marker first), marker-gated, and compile()-checked before writing so it can
# never break POV. POV also wraps each row build in try/except as a backstop.

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
SOURCES_REL_PATH = 'resources/lib/windows/sources.py'
MARKER = 'AI_SUBS_QUALITY_FIX_v5'

# The for-loop that builds each source row (insert our block just before it).
# Same anchor the subtitle-match patcher relies on.
_LOOP_RE = re.compile(
    r'^(?P<indent>[ \t]*)for count, item in enumerate\(self\.results, 1\):[ \t]*$',
    re.MULTILINE,
)
# Revert: our injected block (marker comment .. its trailing `except` line).
_REVERT_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_QUALITY_FIX_v\d+.*?except Exception: pass[ \t]*\r?\n",
    re.DOTALL,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_source_quality_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SOURCES_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _block(indent, eol):
    # indent = the for-loop's own indent (our block is a sibling statement placed
    # just before it). Inner lines nest with tabs, matching POV's tab-indented
    # sources. For each SD/empty row we re-derive quality from the visible name
    # and upgrade the badge to it, then re-order by quality high->low, size (GB)
    # high->low. The row count is never changed.
    t = '\t'
    raw = [
        '# ' + MARKER,
        'try:',
        t + 'from modules.source_utils import get_release_quality as _aq_grq',
        t + "_aq_rank = {'4K': 0, '1080p': 1, '720p': 2, 'SD': 3}",
        t + '_aq_new = []',
        t + 'for _aq_it in self.results:',
        t + t + "if _aq_it.get('_pin_top'):",
        t + t + t + '_aq_new.append(_aq_it); continue',
        t + t + "if (_aq_it.get('quality') or 'SD').upper() == 'SD':",
        t + t + t + "_aq_nm = _aq_it.get('URLName') or _aq_it.get('name') or ''",
        t + t + t + "_aq_q = _aq_grq(_aq_nm) if _aq_nm else ''",
        # RELABEL ONLY -- never drop the row. Re-applying the quality filter
        # here was our own addition, and it is the single place where anything
        # we inject can make the list SHORTER. That is how a mistake of ours
        # turns into "no results" on every title, with no error anywhere,
        # because POV shows that message when the list comes back empty. POV
        # has already applied the user's filter upstream against its own idea
        # of each row's quality; a row that reached this window is one POV
        # chose to show, and correcting its label is not a reason to take it
        # away. The worst a wrong label can now do is sort a row oddly.
        t + t + t + "if _aq_q in ('4K', '1080p', '720p'):",
        t + t + t + t + "_aq_it['quality'] = _aq_q",
        t + t + '_aq_new.append(_aq_it)',
        t + 'self.results[:] = _aq_new',
        t + "self.results.sort(key=lambda _aq_i: (0, 0, 0.0) if _aq_i.get('_pin_top') else (1, _aq_rank.get((_aq_i.get('quality') or 'SD'), 3), -float(_aq_i.get('size') or 0)))",
        'except Exception: pass',
    ]
    return ''.join(indent + ln + eol for ln in raw)


def ensure_patched():
    """Returns 'no_file' | 'read_failed' | 'unmatched' | 'compile_failed'
    | 'write_failed' | 'unchanged' | 'patched'."""
    path = _sources_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    already = MARKER in original

    # Revert any prior version so we re-apply cleanly (idempotent).
    content = _REVERT_RE.sub('', original)

    m = _LOOP_RE.search(content)
    if not m:
        _log('row loop not found -- skipping', level='WARNING')
        return 'unmatched'
    indent = m.group('indent')
    # Insert our block as a sibling statement right before the row loop.
    content = content[:m.start()] + _block(indent, eol) + content[m.start():]

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    if content == original:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
        _log('upgraded SD rows whose name reveals real resolution', level='INFO')
        return 'unchanged' if already else 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
