# Which of our repairs are actually applied right now, and which stopped.
#
# THE PROBLEM THIS EXISTS FOR, stated from the incident that produced it.
# POV auto-updated 6.08.13 -> 6.08.14 and renamed folders. FIVE of our repairs
# stopped applying. Nothing said so. The devices kept booting, the log kept
# saying nothing was wrong, and the first anyone knew was a user reporting a
# symptom days later. One of the five was the TorBox restore repair, which had
# in fact been dead even longer -- a duplicate `def` in our own file raised
# TypeError on every boot into an `except Exception` that logged at WARNING
# and moved on.
#
# THE MECHANISM IS NOT SUBTLE and it is worth writing down exactly, because it
# is the reason a health report is the right fix rather than more careful
# patchers. service.py runs its repair pass like this:
#
#     for step in steps:
#         try: step()
#         except Exception as e: log('... failed: %s' % e, 'WARNING')
#
# `step()`. The return value is DISCARDED. And every one of the 123 step
# functions computes a verdict -- 'patched', 'unmatched', 'no_file' -- and
# returns None. The patchers are honest; nobody is listening. An anchor that
# stops matching is not an exception, so it does not even reach the WARNING
# branch: it is a completely silent, completely normal-looking boot.
#
# WHY THIS DOES NOT INTERCEPT THE CALLS. The obvious fix is to make those 123
# functions return their verdict and have the loop record it. That is a large
# diff across the most safety-critical file in the add-on, and worse, it
# measures the wrong thing: what a patcher RETURNED, not what the host add-on
# actually contains. A patcher that returns 'patched' and whose write silently
# failed would still read green.
#
# So this asks the host instead. Every patcher gates on a versioned marker it
# writes into the file it edits -- that is the invariant `_MARKER_RES` below
# encodes and that tools/test_patcher_upgrade_path.py already enforces for the
# whole tree. If the marker is in the host's files, the patch is applied. If it
# is not, it is not. No interception, no bookkeeping, no trusting a caller.
#
# THE HARD PART IS NOT DETECTION, IT IS SILENCE.
# A marker being absent is not by itself news. Most devices do not have most
# hosts -- a skin patcher for a skin nobody installed is absent forever, and
# reporting it every boot trains everyone to ignore the report, which is worse
# than not having one. So absence is only interesting against HISTORY:
#
#     marker present                        -> ok, and remember the host
#                                              version it was present at
#     absent, and never once seen present   -> quiet. Probably not applicable
#                                              to this device at all.
#     absent, but seen present before       -> LAPSED. This is the whole point.
#
# LAPSED is the 6.08.14 case exactly, and it is loud. It also catches the case
# nobody would think to look for -- a repair that stops applying WITHOUT the
# host changing version, which is what a host reinstall or a half-written file
# looks like -- because the test is "was it ever there", not "did the version
# move".
#
# WHAT IT DELIBERATELY DOES NOT DO. It does not repair anything, it does not
# reorder or re-run the pass, and it never raises into it. A health report that
# can itself break the boot is not a health report. Every failure path here
# ends in returning less information, never in an exception escaping.

import io
import json
import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from . import kodi_utils
except Exception:  # pragma: no cover - direct import outside the package
    try:
        from resources.lib import kodi_utils
    except Exception:
        kodi_utils = None


STATE_NAME = 'patcher_health.json'
REPORT_NAME = 'patcher_health.txt'

# The two marker shapes this tree uses, kept identical to the ones
# tools/test_patcher_upgrade_path.py pins against. A patcher whose marker
# matches neither is not discoverable here -- and that harness fails the build
# if such a patcher exists, so the two files hold each other honest.
_MARKER_RES = (
    re.compile(r'(?<![A-Za-z0-9_])_*[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*'
               r'_v\d+(?:_[A-Za-z0-9]+)*\b'),
    re.compile(r'\b[A-Za-z][A-Za-z0-9_]*_VERSION\s*=\s*\d+'),
)

# An uppercase module constant holding an add-on id is how every patcher in
# this tree names the add-on it edits. Same expression the harness uses to
# assert that every host is declared.
_HOST_RE = re.compile(
    r"(?m)^[A-Z][A-Z0-9_]*\s*=\s*'((?:plugin\.(?:video|program)"
    r"|skin|service\.subtitles)\.[A-Za-z0-9._]+)'")

OURS = 'service.subtitles.kodipovilai'

# Read once per host, searched many times. A host tree is a few MB; re-reading
# it per marker would turn a cheap check into a boot cost.
_SCAN_EXT = ('.py', '.xml', '.json')

_FAMILY_RE = re.compile(r'^(.*?)_v(\d+)((?:_[A-Za-z0-9]+)*)$')
_VERSION_CONST_RE = re.compile(
    r'(?m)^\s*([A-Za-z][A-Za-z0-9_]*_VERSION)\s*=\s*(\d+)\s*$')

# Markers that live in OUR OWN settings rather than in a host file -- one-shot
# migration gates. They are real markers and the harness pins them, but there
# is no host tree to find them in, so looking would report every one of them
# lapsed forever. Recognised by shape: a marker a patcher stores through
# set_setting is not written into anybody's source.
_OURS_ONLY_HINT = ('_seeded', '_done', '_migrated', '_bump')


def _popup_wanted():
    """Whether to put a toast on screen, as opposed to only in the log.

    WHO CAN ACT ON THIS decides the answer, and it is not the viewer. A
    regression here means an anchor stopped matching inside somebody else's
    add-on; the person watching a film can do exactly nothing about it, and a
    popup saying the build is broken would be alarming and useless to them.

    The maintainer runs this build too, so the split is: the WARNING lines go
    to the log ALWAYS -- which means every log anyone uploads carries the
    diagnosis, turning a vague symptom report into a named patcher -- and the
    toast appears only where the log level has been turned up, which is a
    maintainer's device by definition.
    """
    if kodi_utils is None:
        return False
    try:
        return str(kodi_utils.get_setting('log_level', 'INFO')).upper() == 'DEBUG'
    except Exception:
        return False


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('patcher_health: ' + msg, level=level)
    except Exception:
        pass


def _lib_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _addons_root():
    if xbmcvfs is None:
        return ''
    try:
        p = xbmcvfs.translatePath('special://home/addons/')
    except Exception:
        return ''
    return p if os.path.isdir(p) else ''


def _state_path():
    if kodi_utils is None:
        return ''
    try:
        return os.path.join(kodi_utils.addon_profile_path(), STATE_NAME)
    except Exception:
        return ''


def _report_path():
    if kodi_utils is None:
        return ''
    try:
        return os.path.join(kodi_utils.addon_profile_path(), REPORT_NAME)
    except Exception:
        return ''


def _read_state():
    p = _state_path()
    if not p or not os.path.isfile(p):
        return {}
    try:
        with io.open(p, encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        # A corrupt state file must not cost the boot. Starting over means the
        # first boot after it reports nothing lapsed, which is the safe way to
        # be wrong: it under-reports once rather than crying wolf forever.
        return {}


def _write_state(state):
    p = _state_path()
    if not p:
        return False
    tmp = p + '.tmp'
    try:
        with io.open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(state, indent=1, sort_keys=True))
        os.replace(tmp, p)
        return True
    except Exception as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('could not save state: {0}'.format(exc), level='WARNING')
        return False


def host_version(addon_id, root=''):
    """Whatever the host calls itself, or '' if it is not installed.

    Anchored on `<addon`, never on a bare version=, because an addon.xml is
    full of <import addon="xbmc.python" version="3.0.0"/> lines and the first
    bare match is usually one of those.
    """
    root = root or _addons_root()
    if not root:
        return ''
    path = os.path.join(root, addon_id, 'addon.xml')
    if not os.path.isfile(path):
        return ''
    try:
        with io.open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except Exception:
        return ''
    m = re.search(r'<addon\b[^>]*?\bversion="([^"]+)"', text, re.S)
    return m.group(1) if m else 'installed'


def _host_text(addon_id, root='', _cache=None):
    """Every scannable byte of a host add-on, concatenated once."""
    if _cache is not None and addon_id in _cache:
        return _cache[addon_id]
    root = root or _addons_root()
    out = []
    base = os.path.join(root, addon_id) if root else ''
    if base and os.path.isdir(base):
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d != '__pycache__']
            for fn in fns:
                if not fn.endswith(_SCAN_EXT):
                    continue
                try:
                    with io.open(os.path.join(dp, fn), encoding='utf-8',
                                 errors='replace') as fh:
                        out.append(fh.read())
                except Exception:
                    pass
    text = '\n'.join(out)
    if _cache is not None:
        _cache[addon_id] = text
    return text


def markers_and_hosts(source):
    """(markers, hosts) a patcher module declares, read from its source.

    Source text rather than an import: this runs inside the boot pass, and
    importing ninety modules to read their attributes would both cost real
    time and run module-level code a second time. The cost is that a marker
    built from an integer constant -- '# ..._v{0}'.format(INJECT_VERSION) --
    is not spelled out anywhere, so it is invisible here. That is a known and
    accepted gap, reported as `unknown` rather than as healthy, and named in
    the report so it cannot pass for coverage.
    """
    # ONLY the first shape is searchable. The second, `NAME_VERSION = 3`, is
    # how a patcher HOLDS a version, not a string it ever writes into a host --
    # `INJECT_VERSION = 12` was being looked for inside POV and reported
    # missing on every boot, which is true and useless. It still matters, but
    # as the signal that a marker is constructed; live_markers reads it from
    # the source itself for that.
    markers = set(_MARKER_RES[0].findall(source))
    hosts = set(_HOST_RE.findall(source))
    hosts.discard(OURS)
    return markers, hosts


def live_markers(markers, source):
    """Collapse each marker family to the one version that is actually live.

    THIS IS THE DIFFERENCE BETWEEN A REPORT AND A WALL OF NOISE, and it was
    found by running the thing rather than reasoning about it.
    pov_services_patcher keeps ELEVEN superseded markers of one family in an
    OLD_MARKERS list so it can strip its own previous work. None of them is
    supposed to be in POV; the first version of this file dutifully looked for
    all eleven and reported them missing. That one patcher produced twelve of
    the twenty-two "absent" rows in the first real run.

    (Deliberately not quoting those marker strings here. A marker-shaped
    literal anywhere in this module makes tools/test_patcher_upgrade_path.py
    classify THIS file as a patcher and demand a pin for it -- which happened,
    on the first run, from an earlier draft of this very paragraph. The rule
    there is shape-based on purpose and is worth more than the example.)

    So: group by family, keep the highest version, drop the rest.

    AND REFUSE THE FAMILY OUTRIGHT when the live marker is CONSTRUCTED. Three
    patchers here build theirs as '# ..._v{0}'.format(INJECT_VERSION), so the
    live string appears nowhere in the source and the highest LITERAL is a
    retired one. Reporting on that literal would be worse than saying nothing:
    it is guaranteed absent, so it would read as a permanent failure of a
    patcher that is working. Detected by a _VERSION constant whose value is
    higher than any literal in its family, and reported as unmeasurable.
    """
    fams = {}
    for m in markers:
        mm = _FAMILY_RE.match(m)
        if not mm:
            fams.setdefault(('=' + m, ''), []).append((-1, m))
            continue
        head, num, tail = mm.group(1), int(mm.group(2)), mm.group(3)
        fams.setdefault((head, tail), []).append((num, m))
    consts = {n: int(v) for n, v in _VERSION_CONST_RE.findall(source)}
    highest_const = max(consts.values()) if consts else None
    live, unmeasurable = set(), set()
    for (head, tail), items in fams.items():
        items.sort()
        top_num, top = items[-1]
        if (highest_const is not None and top_num >= 0
                and highest_const > top_num):
            unmeasurable.add('%s_v%d%s' % (head, highest_const, tail))
            continue
        live.add(top)
    return live, unmeasurable


def _looks_ours_only(marker):
    low = marker.lower()
    return any(h in low for h in _OURS_ONLY_HINT)


def collect(lib_dir='', addons_root=''):
    """Every (patcher, marker, host) triple and whether the marker is there.

    Returns a list of dicts. Never raises.
    """
    lib_dir = lib_dir or _lib_dir()
    addons_root = addons_root or _addons_root()
    cache = {}
    rows = []
    try:
        names = sorted(n for n in os.listdir(lib_dir) if n.endswith('.py'))
    except Exception as exc:
        _log('cannot list {0}: {1}'.format(lib_dir, exc), level='WARNING')
        return rows
    for name in names:
        stem = name[:-3]
        if stem in ('__init__', 'patcher_health'):
            continue
        try:
            with io.open(os.path.join(lib_dir, name), encoding='utf-8',
                         errors='replace') as fh:
                src = fh.read()
        except Exception:
            continue
        markers, hosts = markers_and_hosts(src)
        markers, unmeasurable = live_markers(markers, src)
        if not hosts:
            continue
        for marker in sorted(unmeasurable):
            rows.append({'patcher': stem, 'marker': marker,
                         'host': sorted(hosts)[0], 'host_version': '',
                         'installed': False, 'present': False,
                         'unmeasurable': True})
        if not markers:
            continue
        for host in sorted(hosts):
            version = host_version(host, addons_root)
            text = _host_text(host, addons_root, cache) if version else ''
            for marker in sorted(markers):
                if _looks_ours_only(marker):
                    continue
                rows.append({
                    'patcher': stem,
                    'marker': marker,
                    'host': host,
                    'host_version': version,
                    'installed': bool(version),
                    'present': bool(version) and marker in text,
                })
    return rows


def classify(rows, state):
    """Fold this boot's readings against what previous boots saw.

    Returns (rows_with_status, new_state). The only status that is news is
    'lapsed': present before, absent now.
    """
    seen = dict(state.get('seen') or {})
    out = []
    for r in rows:
        key = '{0}|{1}|{2}'.format(r['patcher'], r['host'], r['marker'])
        prior = seen.get(key) or {}
        was = prior.get('last_ok_version')
        if r.get('unmeasurable'):
            status = 'unmeasurable'
        elif not r['installed']:
            status = 'not_installed'
        elif r['present']:
            status = 'ok'
            seen[key] = {'last_ok_version': r['host_version']}
        elif was:
            status = 'lapsed'
            # The record is KEPT, deliberately. Clearing it would make the
            # second boot after a regression report 'unknown' and the alarm
            # would silence itself while still broken.
            seen[key] = {'last_ok_version': was, 'lapsed_at': r['host_version']}
        else:
            status = 'unknown'
        row = dict(r)
        row['status'] = status
        row['was_ok_at'] = was or ''
        out.append(row)
    new_state = dict(state)
    new_state['seen'] = seen
    new_state['hosts'] = {h: v for h, v in
                          sorted({(r['host'], r['host_version'])
                                  for r in rows if r['installed']})}
    return out, new_state


def _render(rows):
    order = {'lapsed': 0, 'unknown': 1, 'unmeasurable': 2, 'ok': 3,
             'not_installed': 4}
    rows = sorted(rows, key=lambda r: (order.get(r['status'], 9),
                                       r['patcher'], r['marker']))
    lines = []
    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    lines.append('patcher health: ' + ', '.join(
        '%s=%d' % (k, counts[k]) for k in sorted(counts)))
    hosts = {}
    for r in rows:
        if r['installed']:
            hosts[r['host']] = r['host_version']
    for h in sorted(hosts):
        lines.append('  host %s %s' % (h, hosts[h]))
    lines.append('')
    for r in rows:
        extra = ''
        if r['status'] == 'lapsed':
            extra = '  (was applied at %s %s)' % (r['host'], r['was_ok_at'])
        lines.append('%-13s %-38s %-30s %s%s' % (
            r['status'], r['patcher'], r['marker'], r['host'], extra))
    return '\n'.join(lines)


def lapsed(rows):
    return [r for r in rows if r['status'] == 'lapsed']


def run(lib_dir='', addons_root='', notify=True):
    """The boot entry point. Returns a short status string. Never raises."""
    try:
        rows = collect(lib_dir, addons_root)
        if not rows:
            return 'nothing_to_check'
        state = _read_state()
        rows, new_state = classify(rows, state)
        _write_state(new_state)
        text = _render(rows)
        p = _report_path()
        if p:
            try:
                with io.open(p, 'w', encoding='utf-8') as fh:
                    fh.write(text + '\n')
            except Exception:
                pass
        bad = lapsed(rows)
        if bad:
            # Named individually and at WARNING, because the whole failure this
            # file exists for is a repair going quiet. A count alone would be
            # one more line nobody greps for.
            _log('{0} repair(s) STOPPED APPLYING:'.format(len(bad)),
                 level='WARNING')
            for r in bad:
                _log('  {0} -> {1} {2} (was applied at {3})'.format(
                    r['patcher'], r['host'], r['host_version'],
                    r['was_ok_at']), level='WARNING')
            if notify and _popup_wanted() and kodi_utils is not None:
                try:
                    kodi_utils.notify(
                        '%d build repairs stopped applying' % len(bad),
                        title='Kodi POV IL')
                except Exception:
                    pass
        n_ok = sum(1 for r in rows if r['status'] == 'ok')
        return 'checked={0}, ok={1}, lapsed={2}'.format(
            len(rows), n_ok, len(bad))
    except Exception as exc:
        # A health report that breaks the boot is worse than no health report.
        _log('health check failed: {0}'.format(exc), level='WARNING')
        return 'failed'
