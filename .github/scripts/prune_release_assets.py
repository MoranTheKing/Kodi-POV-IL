#!/usr/bin/env python3
"""Remove superseded packages from the rolling release.

Every build uploads the new version of whatever changed and nothing ever took
the old ones away: the release kept every Wizard, skin and subtitle package it
had ever served (228 assets before they were cleared by hand on 17 Nov 2026).

What stays:
  * every file the CURRENT manifest names (what devices install now);
  * every file the PREVIOUS manifest named -- raw.githubusercontent serves the
    old manifest for a few minutes after a build, and a device that read it
    must still find its packages;
  * the stable names that are not versioned (``*-latest.zip``);
  * anything this script does not recognise as a versioned package of the
    build: it is reported and left for a person.
Everything else -- an older version of an add-on the manifests name -- goes.

Nothing is deleted when a manifest cannot be read, when the current manifest
names a file the release does not hold, or when the list to delete is
implausibly long: a wrong guess here breaks installs, a skipped clean-up costs
nothing.

    prune_release_assets.py --manifest manifest.json --previous old.json \
        --assets assets.txt [--delete] [--max 40]

``assets.txt`` holds one asset name per line (``gh release view TAG --json
assets -q '.assets[].name'``). Without ``--delete`` the names are only printed.
With it, ``gh release delete-asset`` is run for each (REPO_SLUG / RELEASE_TAG
from the environment).
"""
import argparse
import json
import os
import re
import subprocess
import sys

RELEASE_TAG = os.environ.get('RELEASE_TAG', 'addons-latest')
# <add-on id>-<version>.zip, the mirrored official packages, and the config pack
# (an add-on id may carry a hyphen -- plugin.program.orderfavourites-hebrew -- a version here never does)
VERSIONED = re.compile(r'^(?P<stem>[A-Za-z][A-Za-z0-9_.-]*?)-(?P<version>\d[0-9A-Za-z.+~_]*)\.zip$')
LINK = re.compile(r'/releases/download/' + re.escape(RELEASE_TAG) + r'/([^/?#"\s]+)')


def named(manifest):
    """Every file of the rolling release a manifest refers to, anywhere in it."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            found.update(LINK.findall(value))
    walk(manifest)
    return found


def plan(assets, current, previous):
    """(delete, keep, unknown): names by what happens to them."""
    wanted = named(current) | named(previous)
    stems = {match.group('stem') for match in map(VERSIONED.match, wanted) if match}
    delete, keep, unknown = [], [], []
    for name in sorted(assets):
        match = VERSIONED.match(name)
        if name in wanted or name.endswith('-latest.zip'):
            keep.append(name)
        elif match and match.group('stem') in stems:
            delete.append(name)         # an older version of something the manifests name
        else:
            unknown.append(name)        # not ours to judge
    return delete, keep, unknown


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--previous', required=True)
    parser.add_argument('--assets', required=True)
    parser.add_argument('--delete', action='store_true')
    parser.add_argument('--max', type=int, default=40)
    args = parser.parse_args(argv)
    try:
        with open(args.manifest, encoding='utf-8') as source:
            current = json.load(source)
        with open(args.previous, encoding='utf-8') as source:
            previous = json.load(source)
        with open(args.assets, encoding='utf-8') as source:
            assets = [line.strip() for line in source if line.strip()]
    except (OSError, ValueError) as exc:
        print('prune: nothing deleted, a file could not be read: %s' % exc)
        return 0
    missing = sorted(named(current) - set(assets))
    if not named(current) or missing:
        print('prune: nothing deleted, the current manifest names %s' % (
            'no release file' if not named(current) else 'files the release does not hold: ' + ', '.join(missing)))
        return 0
    delete, keep, unknown = plan(assets, current, previous)
    print('prune: %d assets, %d kept, %d superseded, %d left alone' % (len(assets), len(keep), len(delete), len(unknown)))
    for name in unknown:
        print('  left alone (not a versioned package the manifests name): %s' % name)
    if len(delete) > args.max:
        print('prune: nothing deleted, %d is more than a build can supersede (limit %d)' % (len(delete), args.max))
        return 0
    for name in delete:
        if not args.delete:
            print('  would delete: %s' % name)
            continue
        done = subprocess.run(['gh', 'release', 'delete-asset', RELEASE_TAG, name, '--yes'])
        print('  %s: %s' % ('deleted' if done.returncode == 0 else 'NOT deleted', name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
