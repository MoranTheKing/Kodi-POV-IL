# -*- coding: utf-8 -*-
"""Register third-party add-ons to the repository that serves them.

WHY POV NEVER UPDATED. The headless installer downloads a content add-on's
zip from its repository and writes the `installed` row itself -- without an
origin. Kodi 21 reads an empty origin as "installed from a zip" and checks it
against the OFFICIAL repositories only (xbmc/addons/AddonRepos.cpp,
CAddonRepos::DoAddonUpdateCheck: "addons with an empty origin have at least
been checked against official repositories"; the origin-repo branch runs
only `if (!addon->Origin().empty())`). So POV, Otaku and Account Manager,
which no official repository carries, were never offered an update: a device
installed with POV 6.10.03 stayed on 6.10.03 while repository.kodifitzwell
published 6.10.05. The build's own design says the opposite -- these add-ons
are provisioned through their repositories precisely so they "keep receiving
OTA updates straight from their own developers".

THE SAME RULE IS WHAT KEEPS THE BUILD'S OWN ADD-ONS SAFE, and that is why
this never touches them. repository.709 publishes its own FENtastic under the
build's ids (skin.fentastic 100.0.34, script.fentastic.helper 100.6.28a); an
empty origin is exactly what stops Kodi from "updating" the build's skin to
it. Everything the manifest ships stays as it is, and so do repositories,
which the manifest also ships.

EVIDENCE, NOT A GUESS. An origin is written only when Kodi's own database
says exactly ONE installed, enabled, non-official repository offers the
add-on. An add-on no repository lists keeps its empty origin (pointing it at
a repository that does not carry it would pin it -- see MoranSubs'
addon_autoupdate_repair), one the official repository carries already gets
updates, and one two repositories offer is ambiguous and left alone. Only an
EMPTY origin is ever filled, so a choice Kodi or the user made is never
overwritten.
"""

import os

try:
    import sqlite3
except Exception:
    sqlite3 = None

OFFICIAL = 'repository.xbmc.org'

# Add-ons the build ships together with their developer's own repository
# (the Umbrella pack carries repository.umbrella and repository.cocoscrapers
# precisely so the developers are the update channel). Such an add-on is
# registered to that repository even when another repository also lists it.
# Field (Oct 2026): CocoScrapers is also listed by the long-dead
# repository.KodiRealDebridIsrael, the "one repository" rule saw two, and
# every device stayed on the pack's 1.0.39 while the developer published
# 1.0.43 (the Magneto changes Umbrella's developer moved into it).
DEVELOPER_REPOSITORY = {
    'script.module.cocoscrapers': 'repository.cocoscrapers',
    'plugin.video.umbrella': 'repository.umbrella',
}

# What the manifest ships, for a boot where the manifest could not be read.
BUILD_OWNED = frozenset((
    'plugin.program.autocompletion',
    'plugin.program.kodipovilwizard',
    'plugin.program.orderfavourites-hebrew',
    'script.fentastic.helper',
    'script.module.autocompletion',
    'service.subtitles.kodipovilai',
    'skin.estuary',
    'skin.fentastic',
    'skin.povil.nox',
    'skin.povil.onyx',
))


def plan(conn, owned=()):
    """[(addon_id, repo_id)] to register. Reads only."""
    owned = BUILD_OWNED | set(owned or ())
    empty = [r[0] for r in conn.execute(
        "SELECT addonID FROM installed WHERE origin = '' OR origin IS NULL")]
    enabled_repos = {r[0] for r in conn.execute(
        "SELECT addonID FROM installed WHERE addonID LIKE 'repository.%' "
        "AND enabled = 1")}
    offers = {}
    for addon_id, repo_id in conn.execute(
            'SELECT a.addonID, r.addonID FROM addons a '
            'JOIN addonlinkrepo l ON l.idAddon = a.id '
            'JOIN repo r ON r.id = l.idRepo'):
        offers.setdefault(addon_id, set()).add(repo_id)
    out = []
    for addon_id in sorted(set(empty)):
        if (not addon_id or addon_id in owned
                or addon_id.startswith('repository.')):
            continue
        repos = offers.get(addon_id) or set()
        if not repos or OFFICIAL in repos:
            continue
        own = DEVELOPER_REPOSITORY.get(addon_id)
        if own and own in repos and own in enabled_repos:
            out.append((addon_id, own))
            continue
        live = repos & enabled_repos
        if len(repos) == 1 and len(live) == 1:
            out.append((addon_id, next(iter(live))))
    return out


def register(db_path, sources, log=None, timeout=2.0):
    """Record the repository each add-on was just downloaded from.

    `sources` maps addon_id -> repository id, as the headless installer
    resolved it -- the same origin Kodi's native installer would have
    written. Fills empty origins only; skips the build's own add-ons and
    repositories. Never raises; returns what was set.
    """
    pairs = [(a, r) for a, r in sorted((sources or {}).items())
             if a and r and a not in BUILD_OWNED
             and not a.startswith('repository.')]
    return _write(db_path, pairs, log, timeout,
                  'recorded where they were installed from')


def repair(db_path, owned=(), log=None, timeout=2.0):
    """Fill empty origins per plan(). Never raises; returns what was set."""
    return _write(db_path, None, log, timeout,
                  'registered to their repositories', owned)


def _write(db_path, pairs, log, timeout, verb, owned=()):
    # isfile first: sqlite3.connect CREATES a missing database, and a stray
    # empty Addons33.db where Kodi's belongs is worse than no repair.
    if sqlite3 is None or not db_path or not os.path.isfile(db_path):
        return []
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=timeout)
        todo = plan(conn, owned) if pairs is None else pairs
        done = []
        for addon_id, repo_id in todo:
            cur = conn.execute(
                "UPDATE installed SET origin = ? WHERE addonID = ? "
                "AND (origin = '' OR origin IS NULL)", (repo_id, addon_id))
            if cur.rowcount and cur.rowcount > 0:
                done.append((addon_id, repo_id))
        conn.commit()
        if done and log:
            log('[AddonOrigins] {0} (updates apply from '
                'the next start): {1}'.format(verb, ', '.join(
                    '{0}<-{1}'.format(a, r) for a, r in done)))
        return done
    except Exception as exc:
        if log:
            log('[AddonOrigins] skipped: {0}'.format(exc))
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
