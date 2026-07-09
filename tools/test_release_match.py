#!/usr/bin/env python3
"""Offline regression tests for resources/lib/release_match.py (SubSync S1).

Run: python3 tools/test_release_match.py
Asserts tier semantics on realistic release-name pairs, including the
false-positive cases the legacy difflib scorers got wrong.
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..',
    'addons', 'service.subtitles.kodipovilai', 'resources', 'lib'))

import release_match as rm  # noqa: E402

FAILS = []


def check(desc, cond, extra=''):
    if cond:
        print('  ok  - ' + desc)
    else:
        FAILS.append(desc)
        print('  FAIL- ' + desc + (' [' + extra + ']' if extra else ''))


def t(video, sub, want_tier, pct_min=None, pct_max=None):
    pct, tier, reasons = rm.score(video, sub)
    extra = 'pct={0} tier={1} reasons={2}'.format(pct, tier, reasons)
    check('{0!r} vs {1!r} -> {2}'.format(video, sub, want_tier),
          tier == want_tier, extra)
    if pct_min is not None:
        check('    pct >= {0}'.format(pct_min), pct >= pct_min, extra)
    if pct_max is not None:
        check('    pct <= {0}'.format(pct_max), pct <= pct_max, extra)


print('== exact ==')
t('Show.S01E05.1080p.WEB-DL.DDP5.1.H.264-NTb.mkv',
  'Show.S01E05.1080p.WEB-DL.DDP5.1.H.264-NTb.srt', rm.TIER_EXACT, 100, 100)
t('Show S01E05 1080p WEB-DL DDP5 1 H 264-NTb',
  'show.s01e05.1080p.web-dl.ddp5.1.h.264-ntb.mkv', rm.TIER_EXACT, 100, 100)

print('== group (same group + source, different fields) ==')
t('Show.S01E05.2160p.WEB-DL.DDP5.1.HDR.H.265-NTb',
  'Show.S01E05.1080p.WEB-DL.DDP5.1.H.264-NTb', rm.TIER_GROUP, 88)

print('== cross source: the legacy false positive ==')
pct_legacy_trap = rm.score('Movie.2024.1080p.BluRay.x264-SPARKS',
                           'Movie.2024.1080p.WEB-DL.x264-SPARKS')
t('Movie.2024.1080p.BluRay.x264-SPARKS',
  'Movie.2024.1080p.WEB-DL.x264-SPARKS', rm.TIER_CROSS, None, 35)
t('Movie.2024.2160p.UHD.BluRay.x265-B0MBARDiERS',
  'Movie.2024.720p.HDTV.x264-KILLERS', rm.TIER_CROSS, None, 35)

print('== edition mismatch ==')
t('Movie.2020.EXTENDED.1080p.BluRay.x264-GRP',
  'Movie.2020.THEATRICAL.1080p.BluRay.x264-GRP', rm.TIER_CROSS, None, 25)

print('== proper mismatch ==')
t('Show.S02E03.PROPER.1080p.WEB.h264-GRP',
  'Show.S02E03.1080p.WEB.h264-OTHERGRP', rm.TIER_CROSS, None, 40)

print('== same source, different group ==')
t('Movie.2023.1080p.WEB-DL.DDP5.1.x264-FLUX',
  'Movie.2023.1080p.WEBRip.x264-RARBG', rm.TIER_SOURCE, 40, 84)

print('== fuzzy (no source info) ==')
t('Some Movie 2019', 'Some.Movie.2019.Hebrew', rm.TIER_FUZZY, None, 79)

print('== ordering sanity: exact > group > same-source > cross ==')
v = 'Show.S01E05.1080p.WEB-DL.DDP5.1.H.264-NTb'
p_exact = rm.match_pct(v, v + '.mkv')
p_group = rm.match_pct(v, 'Show.S01E05.720p.WEB-DL.H.264-NTb')
p_src = rm.match_pct(v, 'Show.S01E05.1080p.WEBRip.x265-MiNX')
p_cross = rm.match_pct(v, 'Show.S01E05.1080p.BluRay.x264-NTb')
check('exact {0} > group {1} > source {2} > cross {3}'.format(
    p_exact, p_group, p_src, p_cross),
    p_exact > p_group > p_src > p_cross)

print('== parse fields ==')
p = rm.parse('Movie.2024.2160p.REPACK.WEB-DL.DDP5.1.Atmos.HDR.H.265-FLUX.mkv')
check('resolution 2160p', p['resolution'] == '2160p', repr(p))
check('source web', p['source'] == 'web', repr(p))
check('group flux', p['group'] == 'flux', repr(p))
check('codec h265', p['codec'] == 'h265', repr(p))
check('proper True', p['proper'] is True, repr(p))
p2 = rm.parse('Movie.2021.1080p.BluRay.DTS.x264-CMRG')
check('source bluray', p2['source'] == 'bluray', repr(p2))
check('group cmrg', p2['group'] == 'cmrg', repr(p2))

print('== synthetic release detection ==')
check('synthetic Title.S01E02.1080p.mkv',
      rm.is_synthetic('Some Show.S01E02.1080p.mkv') is True)
check('real release NOT synthetic',
      rm.is_synthetic('Show.S01E05.1080p.WEB-DL.H.264-NTb.mkv') is False)

print('== empties / junk never crash ==')
check('empty', rm.match_pct('', 'x') == 0)
check('none-ish', rm.match_pct('   ', '') == 0)
check('junk', isinstance(rm.match_pct('!!!', '???'), int))

print()
if FAILS:
    print('FAILED ({0}):'.format(len(FAILS)))
    for f in FAILS:
        print('  - ' + f)
    sys.exit(1)
print('ALL TESTS PASSED')
