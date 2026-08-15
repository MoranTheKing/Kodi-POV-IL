"""The installers bundle a build zip named by a HARDCODED string. Catch it stale.

build-apk.yml builds the Android APK, the webOS IPK and the Windows installer,
and each one copies `dist/Kodi-POV-IL-FENtastic-test-<version>.zip` in by name.
The wizard beside it is parameterised -- "${WIZARD_VERSION}" -- but the build
zip is typed out literally, three times, and nothing reads it back.

It went stale. 0.1.107 and 0.1.108 both shipped without touching it, so the
workflow sat pinned at 0.1.106 while the live manifest served 0.1.108: anyone
who built a fresh installer got a build three releases behind, and the failure
is silent, because a stale pin names a file that really does exist.

This asserts the pins match what wizard/assets/build.txt actually serves --
the same source a device reads -- so the pin cannot drift from the release
again without a red test. ANDROID_TESTING.md quotes the same filename to a
human tester and is checked with it.

Run: python3 tools/test_installer_pins_current.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_TXT = ROOT / 'wizard' / 'assets' / 'build.txt'
PINNED = [ROOT / '.github' / 'workflows' / 'build-apk.yml',
          ROOT / 'ANDROID_TESTING.md']
ZIP_RE = re.compile(r'Kodi-POV-IL-FENtastic-test-(\d+\.\d+\.\d+)\.zip')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def served_version(build_txt_text):
    """The full-build version the live manifest hands out, read out of url=.
    Not the highest number in dist/ -- an artifact can sit there unreleased."""
    for line in build_txt_text.splitlines():
        if line.startswith('url='):
            m = ZIP_RE.search(line)
            return m.group(1) if m else None
    return None


def pins_in(text):
    return sorted(set(ZIP_RE.findall(text)))


served = served_version(BUILD_TXT.read_text(encoding='utf-8'))
check('build.txt names a full build in url=', served is not None,
      'no url= line matching the build-zip name')

if served:
    for path in PINNED:
        text = path.read_text(encoding='utf-8')
        found = pins_in(text)
        rel = path.relative_to(ROOT)
        check('%s pins a build zip at all' % rel, bool(found),
              'no Kodi-POV-IL-FENtastic-test-*.zip reference found -- either '
              'the filename changed shape, or this file no longer needs a pin '
              'and should come off the list')
        if found:
            check('%s pins exactly what build.txt serves (%s)' % (rel, served),
                  found == [served],
                  'pins %r, build.txt serves %r -- a fresh installer built '
                  'from this would bundle the wrong build' % (found, served))

    # --- SABOTAGE: the comparison has to be able to fail -------------------
    stale = BUILD_TXT.read_text(encoding='utf-8').replace(
        'test-%s.zip' % served, 'test-0.0.0.zip')
    check('SABOTAGE: a drifted manifest is detected',
          served_version(stale) == '0.0.0' and served_version(stale) != served,
          'rewriting the served version did not change the reading -- the '
          'checks above are not comparing anything')

    check('SABOTAGE: a drifted pin is detected',
          pins_in('bundle Kodi-POV-IL-FENtastic-test-0.0.0.zip here') == ['0.0.0'],
          'the pin scan does not see a version it should')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
