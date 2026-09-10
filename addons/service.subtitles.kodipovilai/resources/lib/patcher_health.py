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

import ast
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

# A repair whose BUG THE HOST FIXED is not a repair that stopped working, and
# reporting it as one destroys the only thing this file is for. `lapsed` is a
# WARNING and it means "something is wrong"; the moment it also means "upstream
# fixed it, nothing to do", nobody reads it.
#
# Two arrived in the same week. POV 6.09.02 rewrote its resume-cancel path to
# call progress_media() itself, and Umbrella 6.7.87 rewrote its MDBList sync
# cursor to store the SERVER's checkpoint instead of the device wall clock --
# both are the defects our patchers were written for, fixed at the root by the
# people who own the code. Re-anchoring onto a correct implementation would be
# adding redundant edits to working code; leaving them silent would be crying
# wolf on every device that ever had them applied.
#
# So a patcher may declare the host version from which its bug is gone:
#
#     HOST_FIXED_IN = '6.09.02'          # or {'plugin.video.pov': '6.09.02'}
#
# and an absent marker on a host AT OR ABOVE that version is `superseded` --
# reported, never warned about. BELOW it, an absent marker is still `lapsed`,
# because a device on an older host genuinely does need the repair. The gate is
# the version, not a boolean: retiring a patcher outright would strand everyone
# who has not updated yet.
# READ WITH ast, NOT A REGEX. A regex anchored at column 0 also matches inside
# a triple-quoted string whose content starts there, and scans commented-out
# pairs inside the braces -- so a docstring quoting this constant could silence
# a real alarm. That is the same trap as the phantom marker this file already
# guards against, pointed the other way, and here it is avoidable: a
# module-level constant is exactly what ast reads exactly. A file that will not
# parse yields {}, which keeps the warning.
def host_fixed_in(src):
    """{host_id: version} a patcher declares its bug fixed from, or {}.

    A bare string applies to every host the module names, which is the common
    case -- these patchers each target one add-on."""
    # CHEAP TEST FIRST. ast.parse of every module on every boot cost 234ms
    # across the 152 files here -- roughly doubling collect() -- and four of
    # them contain this constant. The substring test can only SKIP, never
    # accept: any file carrying the literal anywhere, comment or docstring
    # included, still goes to ast, so none of the traps the ast walk exists to
    # close is reopened. Verified result-identical across all 152 files.
    if 'HOST_FIXED_IN' not in (src or ''):
        return {}
    try:
        tree = ast.parse(src or '')
    except Exception:
        return {}
    for node in tree.body:                    # module level only, by construction
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == 'HOST_FIXED_IN'
                   for t in node.targets):
            continue
        val = node.value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            return {'*': val.value}
        if isinstance(val, ast.Dict):
            out = {}
            for k, v in zip(val.keys, val.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)):
                    out[k.value] = v.value
            return out
        return {}
    return {}


def _version_tuple(v):
    """(ints,) or None when any segment is not purely numeric.

    Stripping non-digits INVERTS the order on pre-release strings: '6.7.9~rc2'
    became (6, 7, 92) and compared ABOVE 6.7.87, silencing a repair a device
    still needed. Refusing to rank what we cannot read keeps the warning, which
    is the only safe direction for a suppression gate."""
    out = []
    for part in (v or '').split('.'):
        if not part.isdigit():
            return None
        out.append(int(part))
    return tuple(out) if out else None


def _at_or_above(have, want):
    """True when host version `have` is >= `want`. Unreadable -> False, which
    keeps the old `lapsed` behaviour rather than silencing a real regression."""
    if not have or not want:
        return False
    a, b = _version_tuple(have), _version_tuple(want)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a >= b



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

    AND RECONSTRUCT THE FAMILY when the live marker is CONSTRUCTED. Three
    patchers build theirs as '# ..._v{0}'.format(INJECT_VERSION), so the live
    string appears nowhere in the source and the highest LITERAL is a retired
    one. Searching for that literal would be worse than silence -- guaranteed
    absent forever, against a patcher that works.

    But the live marker is not unknowable: the family head comes from the
    retired literals and the number from the _VERSION constant, so it can be
    rebuilt. Rebuilt is not proven, though, so such a marker starts life
    UNVERIFIED: if the host turns out to contain it, the reconstruction was
    right and it is treated as any other marker from then on -- history makes
    it alarmable. If it is never found, it stays unverified and never raises,
    because "absent" and "I guessed the name wrong" are indistinguishable and
    only one of them is worth waking anybody for.

    This matters more than three patchers sounds. One of the three is what
    builds the Connect Services window, which is the single most visible thing
    this add-on injects into POV.
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
    live, rebuilt = set(), set()
    for (head, tail), items in fams.items():
        items.sort()
        top_num, top = items[-1]
        if (highest_const is not None and top_num >= 0
                and highest_const > top_num):
            rebuilt.add('%s_v%d%s' % (head, highest_const, tail))
            continue
        live.add(top)
    return live, rebuilt


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
        fixed = host_fixed_in(src)
        markers, rebuilt = live_markers(markers, src)
        if not hosts:
            continue
        markers = markers | rebuilt
        if not markers:
            continue
        for host in sorted(hosts):
            version = host_version(host, addons_root)
            text = _host_text(host, addons_root, cache) if version else ''
            for marker in sorted(markers):
                if _looks_ours_only(marker):
                    continue
                fixed_in = fixed.get(host) or fixed.get('*') or ''
                rows.append({
                    'patcher': stem,
                    'marker': marker,
                    'host': host,
                    'host_version': version,
                    'installed': bool(version),
                    'present': bool(version) and marker in text,
                    'rebuilt': marker in rebuilt,
                    'fixed_in': fixed_in,
                    'host_fixed': bool(version)
                                  and _at_or_above(version, fixed_in),
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
        if not r['installed']:
            status = 'not_installed'
        elif r['present']:
            status = 'ok'
            seen[key] = {'last_ok_version': r['host_version']}
        elif r.get('host_fixed'):
            # The host shipped the fix itself. Absent is EXPECTED here, so this
            # is reported and never warned about -- and the `last_ok_version`
            # record is left untouched, so a user who rolls the host BACK below
            # the fixed-in version gets a real `lapsed` again rather than a
            # patcher that has quietly forgiven itself forever.
            #
            # TWO LIMITS, both accepted, both worth stating rather than
            # discovering:
            #
            # 1. THE GATE IS MONOTONE. Once the host is at or above the
            #    declared version this marker can never warn again -- not if
            #    upstream REINTRODUCES the defect, and not if a later refactor
            #    breaks the patcher for some unrelated reason. Only a rollback
            #    re-alarms. Narrowing it to an exact range would mean
            #    predicting which future version re-breaks, which is not
            #    knowable; a declaration is a statement about the past.
            # 0. TWO SPELLINGS, AND ONLY TWO: a bare string, or a dict of
            #    host id -> version. `HOST_FIXED_IN: str = '6.0'` is an
            #    annotated assignment and is silently ignored, which fails
            #    safe (the warning stays) but looks like it worked.
            # 2. THE DECLARATION IS PER-MODULE, not per-marker. A bare string
            #    suppresses EVERY marker in the file on every host it names.
            #    Fine for the three patchers that declare it today (one marker,
            #    one host each) and wrong for a multi-marker patcher, which
            #    would silence repairs that are still needed. Use the per-host
            #    dict, or split the module, before declaring one of those.
            status = 'superseded'
        elif r.get('rebuilt') and not was:
            # Rebuilt, never confirmed. Absent here is as likely to mean the
            # reconstruction is wrong as that the repair broke, and only one of
            # those is worth an alarm.
            status = 'unverified'
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
    order = {'lapsed': 0, 'unknown': 1, 'unverified': 2, 'superseded': 3,
             'ok': 4, 'not_installed': 5}
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
        elif r['status'] == 'superseded':
            extra = '  (%s fixed this itself in %s)' % (r['host'],
                                                        r.get('fixed_in', '?'))
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
        # `superseded` is counted here too. It was introduced without touching
        # this line, so `ok` silently dropped by two with no replacement -- and
        # THIS is the line people grep; the full table in the report file is
        # not what reaches a pasted log. A status that exists but never appears
        # in the summary reads as repairs going missing.
        n_sup = sum(1 for r in rows if r['status'] == 'superseded')
        out = 'checked={0}, ok={1}, lapsed={2}'.format(len(rows), n_ok,
                                                       len(bad))
        if n_sup:
            out += ', superseded={0} (the host fixed those itself)'.format(
                n_sup)
        return out
    except Exception as exc:
        # A health report that breaks the boot is worse than no health report.
        _log('health check failed: {0}'.format(exc), level='WARNING')
        return 'failed'
