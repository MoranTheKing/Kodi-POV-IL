"""The standalone add-on must not announce fixes it does not carry.

Two packages come out of the same source: the BUILD add-on, which ships every
patcher and runs the full startup repair pass, and the STANDALONE, which is
"AI subtitles + DarkSubs/OpenSubtitles only" -- it drops every pov_* file,
carries no Umbrella patcher, and runs SLIM_SERVICE, which does not run the
build repairs at all.

They share one changelog.txt, filtered down for the standalone by
slim_changelog_text(). That filter is a blocklist of terms, and a blocklist
only holds if something checks it. It did not:

  * slim_changelog_text() had its own tuple of terms, and
  * assert_no_standalone_build_payload() had a SHORTER HAND-COPY of it.

A term in neither passed both, and three did -- Umbrella, MDBList and POV --
so ten bullets across fourteen releases told people who installed the subtitle
add-on alone about fixes to add-ons they do not have. That is the defect
reported as note 598 wearing different clothes: the announcement was shared,
the change was not.

This file pins the three properties that keep it fixed:

  1. There is ONE term list, and the build-time assertion reads it. A subset
     can only ever be wrong in the direction of letting something through.
  2. Every host add-on the standalone does not patch is in that list -- derived
     from what include_standalone() actually keeps, not from a second hand-
     maintained list that could drift the same way.
  3. The newest changelog entry is the version on the tin. Once the hosts
     joined the list, a release whose every bullet was about Umbrella left the
     standalone shipping 0.2.501 with a changelog topping out at 0.2.497 --
     true, but it reads as a stale package rather than as "nothing in those
     releases was for you".

Run: python3 tools/test_standalone_changelog_scope.py
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
BUILDER = os.path.join(HERE, 'build_ai_subtitles_packages.py')
CHANGELOG = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                         'changelog.txt')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# Import the builder WITHOUT running it: it refuses to build without a pool
# credential, and this test has no business having one.
spec = importlib.util.spec_from_file_location('_b', BUILDER)
mod = importlib.util.module_from_spec(spec)
sys.modules['_b'] = mod
spec.loader.exec_module(mod)

SRC = open(BUILDER, encoding='utf-8').read()
TERMS = mod.STANDALONE_SKIP_TERMS

# --- 1. one list, and the assertion reads it -------------------------------
check('there is a single shared term list', bool(TERMS) and len(TERMS) > 5,
      'found %r' % (TERMS,))
check('the build-time assertion reads that list, not a copy of it',
      'for token in STANDALONE_SKIP_TERMS' in SRC,
      'assert_no_standalone_build_payload has its own tuple again -- a subset '
      'can only be wrong in the direction of shipping the leak')
check('and no second changelog blocklist has grown back',
      'forbidden_changelog' not in SRC,
      'two lists is how three terms went missing from one of them')

# --- 2. every host the standalone does not patch is in the list ------------
# Derived from the shipping decision itself. A patcher whose host the
# standalone does not carry is a host the standalone must not talk about.
from pathlib import Path

LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
# stem prefix -> the name a release note would call that host by
HOSTS = {
    'umbrella_': 'Umbrella',
    'pov_': 'POV',
    'darksubs_': 'DarkSubs',
    'all_subs_': 'All_Subs',
    'idanplus_': 'Idan Plus',
}
# AND THE OTHER PREFIXES, BY NAME, BECAUSE THE LOOP USED TO SKIP THEM.
#
# It said `if host is None: continue` -- so a patcher for a host nobody had
# added to HOSTS was not checked at all, and the test passed. Release 603
# found that the hard way: idanplus_youtube_id_patcher.py is not shipped
# standalone and "Idan Plus" was not a filtered term, so a bullet announcing
# a Kan 11 fix was about to reach users who do not receive it. That is note
# 598's defect exactly, walking straight past the guard written to stop it,
# because the guard's own list of hosts was a second list that had to agree
# with reality and did not.
#
# Every *_patcher.py must now match HOSTS or be named here. Adding a patcher
# for a NEW host fails this test until somebody decides which it is. These
# are not third-party add-ons a release note would name -- they are skins,
# Kodi itself, and parts of the build.
# prefix -> (what it is, the PRODUCT NAME a release note would use or None)
#
# THE SECOND HALF IS THE PART THAT MATTERS, and it is here because the first
# version of this dict did not have it. "Not a third-party add-on" is not the
# same as "nothing a bullet would name": NOX is a skin, so it landed in this
# dict, and "NOX" was not among the filtered terms -- unlike Estuary, AF3 and
# FENtastic, which are. Two bullets about the NOX player, 0.2.260 and 0.2.262,
# had been reaching standalone users for a year, about a skin they do not
# have. The review that found it was looking for exactly this and I was not.
#
# So anything with a name of its own must have that name filtered, whether it
# is an add-on or not. None means there is no product name -- it is a part of
# the build, or Kodi, or whichever skin happens to be running.
NOT_A_HOST = {
    'af3_': ('the AF3 skin', 'AF3'),
    'brand_': ("the build's own branding", None),
    'build_icons_': ("the build's own icons", None),
    'change_source_pause_': ('skin-side playback UI', None),
    'choose_subs_rewire_': ('skin-side subtitle entry point', None),
    'estuary_': ('the Estuary skin', 'Estuary'),
    'favourites_': ("the build's favourites", 'favourites'),
    'fentastic_': ('the FENtastic skin', 'FENtastic'),
    'hebrew_build_ui_': ("the build's own UI", None),
    'kodi_playlist_timeout_': ('Kodi itself', None),
    'nox_': ('the Nox skin', 'Nox'),
    'recent_updates_tile_': ("the build's home screen", None),
    # deliberately None: this one is shipped standalone and patches whichever
    # skin is running, so it has no product name of its own. 'skin' is in the
    # terms list for its own reasons, which is a different decision.
    'skin_': ('whichever skin is active', None),
    'update_nag_': ("the build's updater", None),
    'wizard_': ('the Wizard', 'Wizard'),
}
shipped, dropped, unclassified = set(), set(), []
for fn in sorted(os.listdir(LIB)):
    if not fn.endswith('_patcher.py'):
        continue
    host = next((v for k, v in HOSTS.items() if fn.startswith(k)), None)
    if host is None:
        if not any(fn.startswith(k) for k in NOT_A_HOST):
            unclassified.append(fn)
        continue
    rel = Path('resources/lib') / fn
    (shipped if mod.include_standalone(rel) else dropped).add(host)

check('every patcher is classified as a host or knowingly as not-a-host',
      not unclassified,
      'no entry in HOSTS or NOT_A_HOST for %s -- if its host is a third-party '
      'add-on the standalone does not ship, a release note naming it will '
      'reach users who did not get the fix' % unclassified)

# EXACTLY ONE PREFIX PER FILE. `next(...)` over a dict returns the first key
# that matches, in insertion order, so a later, more specific prefix would be
# silently absorbed by an earlier general one -- a future `pov_extra_` read as
# `pov_`. Nothing matches twice today; this is here so nothing starts to.
_prefixes = list(HOSTS) + list(NOT_A_HOST)
_ambiguous = {fn: [k for k in _prefixes if fn.startswith(k)]
              for fn in os.listdir(LIB) if fn.endswith('_patcher.py')}
_ambiguous = {k: v for k, v in _ambiguous.items() if len(v) > 1}
check('no patcher filename matches two prefixes', not _ambiguous,
      'first-match-wins would pick one of these silently: %s' % _ambiguous)

# Anything with a product name of its own must have that name filtered, skin
# or add-on. This is the check NOX slipped past for a year.
for _pfx, (_what, _name) in sorted(NOT_A_HOST.items()):
    if _name is None:
        continue
    check('%s is %s, and its name is filtered' % (_pfx, _what),
          _name in TERMS,
          'a release note naming %s would reach users who do not have it'
          % _name)

check('the derivation found patchers on both sides of the line',
      bool(shipped) and bool(dropped),
      'shipped=%s dropped=%s -- if one side is empty this check is vacuous'
      % (sorted(shipped), sorted(dropped)))
for host in sorted(dropped - shipped):
    check('%s is a host the standalone does not patch, so it is filtered'
          % host, host in TERMS,
          'a release note naming %s would reach users who did not get the fix'
          % host)
for host in sorted(shipped):
    check('%s IS shipped standalone, so it is NOT filtered' % host,
          host not in TERMS,
          'filtering it would hide a fix those users really did receive')

# MDBList is not a patcher stem -- it is the service both hosts talk to, and
# every bullet naming it has been about one of them. Pinned by hand, and the
# reason is written down rather than left to be rediscovered.
check('MDBList is filtered too', 'MDBList' in TERMS,
      'the MDBList bullets are all about POV or Umbrella integrations, '
      'neither of which the standalone has')

# --- 3. the filter actually strips, and keeps the version honest -----------
with open(CHANGELOG, encoding='utf-8') as f:
    full = f.read()
slim = mod.slim_changelog_text(full)

leaked = sorted({t for t in TERMS if t in slim})
check('the filtered changelog contains none of the terms', not leaked,
      'leaked: %s' % leaked)

ver = mod.version()
check('the newest entry is the version actually being shipped',
      slim.startswith('v%s\n' % ver),
      'ships %s, changelog starts %r -- reads as a stale package'
      % (ver, slim.split('\n', 1)[0]))
check('the full changelog still has everything (the filter is not in-place)',
      any(t in full for t in TERMS),
      'the BUILD changelog must keep the bullets the standalone drops')

# AND THE OTHER DIRECTION, which the NOX review found by the same pass. Every
# term added here silences whole bullets, and a term can be right about the
# host it names and still catch a bullet that was never about that host.
# Adding "Idan Plus" dropped 0.2.372 -- the live/IPTV autosub skip, an engine
# feature the standalone genuinely ships -- because the bullet named Idan Plus
# as the example in its exclusion list. That bullet was reworded; this pins
# the outcome, so the next term that re-drops it fails instead of quietly
# hiding a feature those users really did receive.
check('the live/IPTV autosub skip still reaches standalone users',
      'SKIPPED for live/IPTV' in slim,
      'a skip term is hiding an engine feature the standalone ships')

# --- SABOTAGE: the checks must be able to fail -----------------------------
print()
print('=== sabotage ===')
real = mod.STANDALONE_SKIP_TERMS
try:
    mod.STANDALONE_SKIP_TERMS = tuple(t for t in real if t != 'Umbrella')
    # slim_changelog_text reads the module global at call time
    sabotaged = mod.slim_changelog_text(full)
    check('SABOTAGE: dropping a host from the list lets its bullets through',
          'Umbrella' in sabotaged,
          'the leak check cannot detect the leak it exists for')
finally:
    mod.STANDALONE_SKIP_TERMS = real
check('SABOTAGE: and the list was put back',
      mod.STANDALONE_SKIP_TERMS == real)

only_hosts = 'v99.0.0\n- Umbrella got better.\n'
check('SABOTAGE: a release with nothing for the standalone still names itself',
      mod.slim_changelog_text(only_hosts).startswith('v%s\n' % ver),
      'got %r' % mod.slim_changelog_text(only_hosts).split('\n', 1)[0])

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
