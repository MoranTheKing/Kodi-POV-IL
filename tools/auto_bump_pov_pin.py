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
Prints one line: "current <ver>", "bumped <old> <new> <zip path>" or
"blocked <ver>: <reason>" (exit 2).
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
PIN = ROOT / '.github' / 'pov-host-migration.json'
UPSTREAM = ROOT / 'UPSTREAM_VERSIONS.txt'
REPO = 'MoranTheKing/Kodi-POV-IL'
HOSTS = ('kodifitzwell', 'kodiyashimaru')
MAX_BYTES = 25 * 1024 * 1024


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
    return checker.upstream_versions(**kwargs).get('plugin.video.pov'), checker.version_key


def official_zip(version, getter=_get):
    """(bytes, upstream url) of the official zip, checked to be that POV."""
    filename = 'plugin.video.pov-%s.zip' % version
    errors = []
    for host in HOSTS:
        url = 'https://%s.github.io/repo/plugin.video.pov/%s' % (host, filename)
        try:
            data = getter(url)
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                if package.testzip() is not None:
                    raise ValueError('CRC error')
                names = package.namelist()
                if not names or any(not n.startswith('plugin.video.pov/') or '..' in n
                                    for n in names):
                    raise ValueError('unexpected member paths')
                head = package.read('plugin.video.pov/addon.xml').decode('utf-8', 'replace')
            tag = re.search(r'<addon\b[^>]*>', head, re.S)
            attrs = dict(re.findall(r'\b(id|version)\s*=\s*"([^"]*)"', tag.group(0) if tag else ''))
            if attrs.get('id') != 'plugin.video.pov' or attrs.get('version') != version:
                raise ValueError('addon.xml says %r' % attrs)
            return data, url
        except Exception as exc:
            errors.append('%s: %s' % (url, exc))
    raise ValueError('; '.join(errors))


def pin_for(version, data, upstream_url):
    filename = 'plugin.video.pov-%s.zip' % version
    return {
        'id': 'plugin.video.pov',
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
    hits = [i for i, line in enumerate(lines) if line.startswith('plugin.video.pov:')]
    if len(hits) != 1:
        raise ValueError('UPSTREAM_VERSIONS.txt must name plugin.video.pov exactly once')
    lines[hits[0]] = 'plugin.video.pov: %s' % version
    return '\n'.join(lines)


def run(outdir, fetcher=None, getter=_get, verifier=None):
    pin = json.loads(PIN.read_text('utf-8'))
    latest, version_key = newest_pov(fetcher)
    if not latest or version_key(latest) <= version_key(pin['version']):
        return 0, 'current %s' % pin['version']
    try:
        data, upstream_url = official_zip(latest, getter)
    except Exception as exc:
        return 2, 'blocked %s: official zip unusable: %s' % (latest, exc)
    candidate = pin_for(latest, data, upstream_url)
    old_pin_text = PIN.read_text('utf-8')
    _write_text_keep_eol(PIN, json.dumps(candidate, indent=2) + '\n')
    try:
        if verifier is None:
            verifier = _load('verify_pov_patches', ROOT / '.github' / 'scripts' / 'verify_pov_patches.py').verify
        # The verifier reports its counts on stdout; keep stdout to our one line.
        with contextlib.redirect_stdout(sys.stderr):
            verifier(ROOT, data)
    except Exception as exc:
        _write_text_keep_eol(PIN, old_pin_text)
        return 2, 'blocked %s: patches do not fit: %s' % (latest, exc)
    _write_text_keep_eol(UPSTREAM, set_upstream_pov(UPSTREAM.read_text('utf-8'), latest))
    out = Path(outdir) / ('official-' + candidate['filename'])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return 0, 'bumped %s %s %s' % (pin['version'], latest, out)


if __name__ == '__main__':
    code, line = run(sys.argv[1] if len(sys.argv) > 1 else 'pov-pin-out')
    print(line)
    sys.exit(code)
