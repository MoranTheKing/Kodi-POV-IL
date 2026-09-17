#!/usr/bin/env python3
"""The 32-bit artwork migration is narrow, lossless and idempotent."""
import importlib.util
import os
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
MODULE = os.path.join(
    ROOT, 'addons', 'service.subtitles.kodipovilai', 'resources', 'lib',
    'kodi_32bit_artwork.py')
SERVICE = os.path.join(
    ROOT, 'addons', 'service.subtitles.kodipovilai', 'service.py')
spec = importlib.util.spec_from_file_location('art32_test', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
FAIL = []


def check(label, condition, detail=''):
    print('%-4s %s%s' % ('ok' if condition else 'FAIL', label,
                         (' -- ' + detail) if detail and not condition else ''))
    if not condition:
        FAIL.append(label)


def run(body, bit=True):
    folder = tempfile.mkdtemp(prefix='kodi-art32-')
    path = os.path.join(folder, 'advancedsettings.xml')
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(body)
    status = mod.ensure_optimized(path, is_32bit=bit)
    with open(path, 'r', encoding='utf-8', newline='') as handle:
        return status, handle.read(), path


ORIGINAL = ('<advancedsettings>\r\n'
            '\t<cache><memorysize>139460608</memorysize></cache>\r\n'
            '\t<imageres>9999</imageres> <!-- keep comment -->\r\n'
            '\t<packagefoldersize>50</packagefoldersize>\r\n'
            '</advancedsettings>\r\n')

status, changed, path = run(ORIGINAL)
check('the shipped 9999 value is patched on 32-bit',
      status == 'patched' and '<imageres>720</imageres>' in changed, status)
check('unrelated settings, comments and CRLF bytes are preserved',
      '<memorysize>139460608</memorysize>' in changed
      and '<!-- keep comment -->' in changed
      and changed.count('\r\n') == ORIGINAL.count('\r\n'))
second = mod.ensure_optimized(path, is_32bit=True)
check('the migration is byte-idempotent', second == 'already_optimized', second)

status64, same64, _ = run(ORIGINAL, bit=False)
check('64-bit keeps the build policy untouched',
      status64 == 'not_32bit' and same64 == ORIGINAL, status64)

CUSTOM = ORIGINAL.replace('9999', '1080')
custom_status, custom_body, _ = run(CUSTOM)
check('a user-selected resolution is preserved byte-for-byte',
      custom_status == 'custom_preserved' and custom_body == CUSTOM,
      custom_status)

NO_SETTING = '<advancedsettings><cache><readfactor>10</readfactor></cache></advancedsettings>'
none_status, none_body, _ = run(NO_SETTING)
check('a profile without imageres is not opted in',
      none_status == 'no_setting' and none_body == NO_SETTING, none_status)

BAD = '<advancedsettings><imageres>9999</advancedsettings>'
bad_status, bad_body, _ = run(BAD)
check('malformed XML is left byte-for-byte intact',
      bad_status == 'invalid_xml' and bad_body == BAD, bad_status)

service = open(SERVICE, encoding='utf-8').read()
check('startup registers the migration exactly once',
      service.count('_maybe_optimize_32bit_artwork,') == 1)
check('it runs after both cache-schema safety repairs',
      service.index('_maybe_optimize_32bit_artwork,')
      > service.index('_maybe_repair_pov_cache_schema,'))

print('\nFAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
raise SystemExit(1 if FAIL else 0)
