#!/usr/bin/env python3
"""Move the clean-host POV pin to a newer official POV once our patches fit it.

Why: a device still on the legacy MoranSubs 0.2.x moves to the modular build
only after the Wizard stages the official POV named by
.github/pov-host-migration.json. Kodi updates POV on its own, and the Wizard
never "downgrades" POV, so a pin that falls behind the POV on the device stops
that device's migration for good (field log, 16 Oct 2026: POV 6.10.06
installed, pin 6.10.05 -> "refusing downgrade", legacy MoranSubs kept and its
broken Connect Services menu with it). POV ships about once a week.

What it does (no secret needed):
  1. Reads the newest plugin.video.pov from the developers' repositories
     (the same indexes tools/check_upstream_addons.py watches).
  2. If it is newer than the pin, downloads that official zip and checks it is
     a sane POV package of exactly that version.
  3. Runs the Wizard patch engine over it with .github/scripts/
     verify_pov_patches.py -- the same gate the release workflow uses: every
     enabled patch applies, nothing missing, idempotent on a second run.
  4. Only then rewrites the pin and the plugin.video.pov line of
     UPSTREAM_VERSIONS.txt and leaves the zip in OUTDIR for the release upload.
     On any failure the pin is left untouched and the reason is printed.

Usage:  python3 tools/auto_bump_pov_pin.py OUTDIR
Prints one line: "current <ver>", "bumped <old> <new> <zip path>",
"blocked <ver>: <reason>" (exit 2: our patches do not fit, or not a plain
release version) or "unavailable <ver>: <reason>" (exit 3: the official zip
could not be fetched or is not that POV -- usually transient).
"python3 tools/auto_bump_pov_pin.py --check" only prints "newer <ver>" or
"current <ver>" (no download).
"python3 tools/auto_bump_pov_pin.py --republish-check" compares the official
zip of the pinned version with the pin and audits a republished one (see
republish_check).

"--addon umbrella" before the other arguments does the same for Umbrella's
pin (.github/umbrella-pin.json, read by the Wizard's version gate): Umbrella
carries the kids-profile hooks and, like POV, follows its developer's
repository.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = 'plugin.video.pov'
PIN = ROOT / '.github' / 'pov-host-migration.json'
UPSTREAM = ROOT / 'UPSTREAM_VERSIONS.txt'
REPO = 'MoranTheKing/Kodi-POV-IL'
HOSTS = ('kodifitzwell', 'kodiyashimaru')
MAX_BYTES = 25 * 1024 * 1024
# pinned add-on -> (pin file, official zip URL for a filename; None = HOSTS)
TARGETS = {
    'plugin.video.pov': ('pov-host-migration.json', None),
    'plugin.video.umbrella': (
        'umbrella-pin.json',
        'https://raw.githubusercontent.com/umbrellaplug/umbrellaplug.github.io'
        '/master/omega/zips/plugin.video.umbrella/%s'),
}


def select(addon_id):
    """Point the module at another pinned add-on (command line --addon)."""
    global ADDON, PIN
    ADDON = addon_id
    PIN = ROOT / '.github' / TARGETS[addon_id][0]


def official_urls(filename):
    template = TARGETS[ADDON][1]
    if template:
        return [template % filename]
    return ['https://%s.github.io/repo/%s/%s' % (host, ADDON, filename) for host in HOSTS]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get(url, limit=MAX_BYTES):
    req = urllib.request.Request(url, headers={'User-Agent': 'kodi-povil-pin-bump'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError('%s is larger than %d bytes' % (url, limit))
    return data


def newest_pov(fetcher=None):
    checker = _load('check_upstream_addons', ROOT / 'tools' / 'check_upstream_addons.py')
    kwargs = {'fetcher': fetcher} if fetcher else {}
    return checker.upstream_versions(**kwargs).get(ADDON), checker.version_key


def official_zip(version, getter=_get):
    """(bytes, upstream url) of the official zip, checked to be that add-on."""
    filename = '%s-%s.zip' % (ADDON, version)
    errors = []
    for url in official_urls(filename):
        try:
            data = getter(url)
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                if package.testzip() is not None:
                    raise ValueError('CRC error')
                names = package.namelist()
                if not names or any(not n.startswith(ADDON + '/') or '..' in n
                                    for n in names):
                    raise ValueError('unexpected member paths')
                if sum(i.file_size for i in package.infolist()) > 8 * MAX_BYTES:
                    raise ValueError('unpacks too large')
                # The Wizard's staged installer refuses anything beyond these
                # (staged_addon_install.install); never pin what it cannot install.
                members = [i for i in package.infolist() if not i.is_dir()]
                if (len(members) > 2000 or sum(i.file_size for i in members) > 30 * 1024 * 1024 or
                        any(i.file_size > 16 * 1024 * 1024 for i in members)):
                    raise ValueError('beyond the Wizard installer limits')
                head = package.read(ADDON + '/addon.xml').decode('utf-8', 'replace')
            tag = re.search(r'<addon\b[^>]*>', head, re.S)
            attrs = dict(re.findall(r'\b(id|version)\s*=\s*"([^"]*)"', tag.group(0) if tag else ''))
            if attrs.get('id') != ADDON or attrs.get('version') != version:
                raise ValueError('addon.xml says %r' % attrs)
            return data, url
        except Exception as exc:
            errors.append('%s: %s' % (url, exc))
    raise ValueError('; '.join(errors))


def pin_for(version, data, upstream_url):
    filename = '%s-%s.zip' % (ADDON, version)
    return {
        'id': ADDON,
        'version': version,
        'filename': filename,
        'zip': 'https://github.com/%s/releases/download/addons-latest/official-%s' % (REPO, filename),
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'upstream_zip': upstream_url,
    }


def _write_text_keep_eol(path, text):
    raw = path.read_bytes() if path.exists() else b''
    eol = b'\r\n' if b'\r\n' in raw else b'\n'
    path.write_bytes(text.replace('\r\n', '\n').encode('utf-8').replace(b'\n', eol))


def set_upstream_pov(text, version):
    lines = text.replace('\r\n', '\n').split('\n')
    hits = [i for i, line in enumerate(lines) if line.startswith(ADDON + ':')]
    if len(hits) != 1:
        raise ValueError('UPSTREAM_VERSIONS.txt must name %s exactly once' % ADDON)
    lines[hits[0]] = '%s: %s' % (ADDON, version)
    return '\n'.join(lines)


def _verifier():
    verify = _load('verify_pov_patches', ROOT / '.github' / 'scripts' / 'verify_pov_patches.py').verify
    pin_path = PIN.relative_to(ROOT).as_posix()
    return lambda root, archive: verify(root, archive, pin_path)


def pending(fetcher=None):
    """(pin version, newer upstream POV or None) -- no download."""
    pin = json.loads(PIN.read_text('utf-8'))
    latest, version_key = newest_pov(fetcher)
    if not latest or version_key(latest) <= version_key(pin['version']):
        return pin['version'], None
    return pin['version'], latest


def run(outdir, fetcher=None, getter=_get, verifier=None):
    current, latest = pending(fetcher)
    if not latest:
        return 0, 'current %s' % current
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', latest):
        return 2, 'blocked %s: not a plain release version' % latest
    try:
        data, upstream_url = official_zip(latest, getter)
    except Exception as exc:
        return 3, 'unavailable %s: official zip unusable: %s' % (latest, exc)
    candidate = pin_for(latest, data, upstream_url)
    old_pin_text = PIN.read_text('utf-8')
    old_upstream = UPSTREAM.read_text('utf-8')
    done = False
    try:
        _write_text_keep_eol(PIN, json.dumps(candidate, indent=2) + '\n')
        if verifier is None:
            verifier = _verifier()
        # The verifier reports its counts on stdout; keep stdout to our one line.
        with contextlib.redirect_stdout(sys.stderr):
            verifier(ROOT, data)
        _write_text_keep_eol(UPSTREAM, set_upstream_pov(old_upstream, latest))
        done = True
    except Exception as exc:
        return 2, 'blocked %s: patches do not fit: %s' % (latest, exc)
    finally:
        if not done:
            _write_text_keep_eol(PIN, old_pin_text)
            _write_text_keep_eol(UPSTREAM, old_upstream)
    out = Path(outdir) / ('official-' + candidate['filename'])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return 0, 'bumped %s %s %s' % (current, latest, out)


def republish_check(fetcher=None, getter=_get, verifier=None):
    """(code, line) for a POV republished under the pinned version.

    Field (20 Oct 2026): kodifitzwell replaced plugin.video.pov 6.10.06 with
    different code under the same version. A version compare saw nothing,
    one Wizard hook lost its anchor, and fresh installs stopped at the end.
    When upstream's newest POV is the pinned version, compare the official
    zip with the pin and, if it differs, audit every enabled Wizard patch on
    it. The pin itself stays: legacy migration stages the mirrored copy, and
    Kodi never moves a device between two zips of one version.

    Lines: "newer <ver>" (the pin job handles it), "same <ver>",
    "republished <ver> <sha12> fits: <audit>",
    "republished <ver> <sha12> blocked: <reason>" (exit 2),
    "unavailable <ver>: <reason>" (exit 3, usually transient)."""
    current, latest = pending(fetcher)
    if latest:
        return 0, 'newer %s' % latest
    pin = json.loads(PIN.read_text('utf-8'))
    try:
        data, upstream_url = official_zip(current, getter)
    except Exception as exc:
        return 3, 'unavailable %s: official zip unusable: %s' % (current, exc)
    digest = hashlib.sha256(data).hexdigest()
    if digest == pin['sha256'] and len(data) == pin['size']:
        return 0, 'same %s' % current
    old_pin_text = PIN.read_text('utf-8')
    report = io.StringIO()
    try:
        _write_text_keep_eol(PIN, json.dumps(pin_for(current, data, upstream_url), indent=2) + '\n')
        if verifier is None:
            verifier = _verifier()
        with contextlib.redirect_stdout(report):
            verifier(ROOT, data)
    except Exception as exc:
        return 2, 'republished %s %s blocked: %s' % (current, digest[:12], exc)
    finally:
        _write_text_keep_eol(PIN, old_pin_text)
    audit = ' '.join(report.getvalue().split()) or 'verified'
    return 0, 'republished %s %s fits: %s' % (current, digest[:12], audit)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--addon']:
        select('plugin.video.' + sys.argv[2])
        del sys.argv[1:3]
    if sys.argv[1:] == ['--republish-check']:
        code, line = republish_check()
        print(line)
        sys.exit(code)
    if sys.argv[1:] == ['--check']:
        current, latest = pending()
        print('newer %s' % latest if latest else 'current %s' % current)
        sys.exit(0)
    code, line = run(sys.argv[1] if len(sys.argv) > 1 else 'pov-pin-out')
    print(line)
    sys.exit(code)
