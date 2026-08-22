# -*- coding: utf-8 -*-
"""Why an add-on with an available update is never installed.

THE REPORT: "sometimes there are updates and it does not update, and then I
have to go to the add-ons list by hand and update it there. Usually it does
not happen, but on some devices it does."

That description is unusually precise, and it rules out most explanations by
itself: the update is FOUND (it shows in the manual list) and installing it by
hand WORKS. Something is filtering the list between "found" and "installed",
and Kodi has exactly two such filters.

FILTER 1 -- the mode. `general.addonupdates`: 0 install automatically,
1 notify only, 2 never. The build ships 0. It is a level-0 setting sitting in
Settings > Add-ons, so a user can move it without meaning to, and at 1 the
symptom is exactly the report: updates are found, announced, and never
installed.

FILTER 2 -- the pins, and this is the one nobody would guess. Kodi 19+ keeps
an `update_rules` table, and CAddonMgr::GetAddonUpdateCandidates drops every
add-on that has ANY row in it:

    updates = GetAvailableUpdates();                 <-- the manual list
    updates.erase(... !IsAutoUpdateable(addon->ID()) ...);   <-- the auto list

    bool CAddonUpdateRules::IsAutoUpdateable(id) const
    { return m_updateRules.find(id) == m_updateRules.end(); }

Three rule types exist:

    1  USER_DISABLED_AUTO_UPDATE   somebody turned auto-update off
    2  PIN_OLD_VERSION             set BY THE INSTALLER, see below
    3  PIN_ZIP_INSTALL             set BY THE INSTALLER, see below

Types 2 and 3 are not choices anyone made. CAddonInstallJob adds them at the
end of every install:

    if (m_addon->Version() == latestVersionOfItsOriginRepo) unpin;
    else AddUpdateRuleToList(id, PIN_OLD_VERSION);

Read that against a repository that has gone away. A field log from this build
has one -- `repository.709`, whose index answers 404 -- and an add-on whose
origin is a repo that cannot be read has NO versions to compare against, so
`latestVersionOfItsOriginRepo` stays empty, the installed version is not equal
to it, and the add-on is PINNED. Permanently, silently, and only on the
devices that happen to carry that repo. It still appears in the manual list,
because that list never consults the rules -- which is why updating by hand
works and also un-pins it, and why the fault looks random.

WHAT THIS DOES.

  * Every start: reads the table and LOGS it. One line naming each pinned
    add-on and which rule pinned it. The next log from an affected device
    answers the question instead of raising it -- there is no other way to
    see this, because Kodi logs the pinning at debug level.
  * Every start: removes rules 2 and 3 from the add-ons THIS BUILD SHIPS.
    Those two are machine-set; clearing them restores Kodi's own default
    behaviour for add-ons the build is responsible for keeping current.
  * Never touches rule 1. That one means somebody said no -- including the
    build itself, which ships it on resource.language.he_il and skin.estuary
    on purpose -- and an update that overrides a no is the complaint this
    codebase already has a marker to avoid.
  * Never touches an add-on the build does not ship. Somebody who pinned
    their own add-on to an old version keeps it.

THE EDIT LANDS AT THE NEXT START, not this one, and this is read out of
Kodi's own source rather than inferred. CAddonUpdateRules::RefreshRulesMap
fills m_updateRules from the table and is called only from CAddonMgr's load
paths; AddUpdateRuleToList / RemoveFromUpdateRuleslist write ONE row for ONE
add-on id and adjust the same single entry in memory. There is no path that
flushes the whole map back over the table, so rows deleted here stay deleted.
CAddonMgr::DeInit, for the same reason, only closes the database. That is fine -- it makes the
device correct from then on -- and it is why this writes the table rather than
trying to make Kodi act now. The mode (filter 1) is different: that goes
through JSON-RPC, which Kodi applies immediately.
"""

import os
import re

try:
    import xbmc
    import xbmcvfs
except Exception:
    xbmc = None
    xbmcvfs = None

try:
    import json
except Exception:
    json = None

try:
    import sqlite3
except Exception:
    sqlite3 = None

from resources.lib import kodi_utils


RULE_NAMES = {
    1: 'auto-update turned off by hand',
    2: 'pinned as an old version by the installer',
    3: 'pinned to a hand-installed zip',
}
# ONLY RULE 2. This was (2, 3), on the reading that CAddonInstallJob writes
# both and therefore neither is anybody's choice. Half right: rule 3 is only
# ever written when a person used Kodi's own "Install from zip file" on a
# version older than the repository's -- somebody deliberately holding an
# add-on back. The wizard's own installs cannot produce it at all; they
# extract files and write the database row directly, never going through
# CAddonInstallJob. So clearing rule 3 would silently defeat a deliberate
# choice on every boot, which is the exact thing rule 1 is protected from.
#
# Rule 2 is different, and it is the one the report is about: it is written
# automatically whenever the installed version is not the newest its ORIGIN
# repository offers -- including when that repository offers nothing at all
# because it has stopped answering, which is the dead-repo case a field log
# from this build actually shows.
#
# AND ONE CASE THE ARGUMENT DOES NOT COVER, said rather than glossed. Kodi's
# add-on browser can also install an older version straight from a
# repository's version list, and that is a deliberate downgrade which also
# writes rule 2. The table cannot tell the two apart -- both are just
# (addon_id, 2) -- so somebody who pinned a build add-on to an older version
# that way has it undone here. Nobody has reported doing it, the log line
# names every rule it clears so it is never silent, and the alternative is
# leaving the dead-repo case unfixed for everyone; but it is a real cost, not
# an imaginary one.
MACHINE_RULES = (2,)

UPDATE_MODE_SETTING = 'general.addonupdates'
UPDATE_MODE_NAMES = {
    0: 'install automatically',
    1: 'notify but do not install',
    2: 'never check',
}

# One-shot, its own marker. NOT the shared UI-prefs marker: bumping that one
# would re-seed the audio language, the keyboard layout and two FENtastic
# settings on every device that already has them, which is the "an update
# reset my settings" complaint, not a fix for it.
_MODE_SEED_FLAG = '_addon_update_mode_seeded'
_MODE_SEED_VERSION = 'v1'

# The add-ons this build ships or installs, and is therefore responsible for
# keeping current. Anything outside this set is somebody else's business.
# resource.language.he_il and skin.estuary are deliberately absent: the build
# ships rule 1 on both, and rule 1 is never touched anyway -- leaving them out
# says so twice.
MANAGED = frozenset((
    'context.otaku',
    'metadata.album.universal',
    'metadata.artists.universal',
    'metadata.generic.albums',
    'metadata.themoviedb.org.python',
    'metadata.tvshows.themoviedb.org.python',
    'plugin.close.kodi',
    'plugin.program.autocompletion',
    'plugin.program.kodipovilwizard',
    'plugin.program.orderfavourites-hebrew',
    'plugin.video.idanplus',
    'plugin.video.otaku',
    'plugin.video.pov',
    'plugin.video.umbrella',
    'plugin.video.youtube',
    'repository.Fishenzon',
    'repository.KodiRealDebridIsrael',
    'repository.burekasKodi',
    'repository.kodifitzwell',
    'repository.otaku',
    'repository.peno64',
    'script.common.plugin.cache',
    'script.fentastic.helper',
    'script.module.autocompletion',
    'script.module.beautifulsoup4',
    'script.module.bossanova808',
    'script.module.certifi',
    'script.module.chardet',
    'script.module.cocoscrapers',
    'script.module.idna',
    'script.module.inputstreamhelper',
    'script.module.pysubs2',
    'script.module.requests',
    'script.module.six',
    'script.module.soupsieve',
    'script.module.urllib3',
    'script.module.xmltodict',
    'script.speedtester',
    'script.xbmc.unpausejumpback',
    'service.subtitles.All_Subs',
    'service.subtitles.all_subs_plus',
    'service.subtitles.kodipovilai',
    'service.subtitles.localsubtitle',
    'service.xbmc.versioncheck',
    'skin.arcticfuse3',
    'skin.fentastic',
    'skin.povil.nox',
))


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('addon_autoupdate_repair: ' + msg, level=level)
    except Exception:
        pass


# Addons<digits>.db and nothing else. The first version pulled digits out of
# ANYWHERE in the name, so `Addonsfoo9.db` scored 9 and `Addons3x30.db` scored
# 330 -- a stray backup or a half-renamed file could outrank the live database
# and be repaired instead of it. And ties were broken by whatever order
# glob happened to return, which is filesystem-dependent and documented as
# undefined: `Addons33_bak.db` beside `Addons33.db` was a coin toss. Both were
# reproduced rather than imagined.
_DB_NAME = re.compile(r'^Addons(\d+)\.db$')


def addons_db():
    """The newest Addons<N>.db, or ''.

    Kodi bumps the number with the schema, so the name is not a constant --
    the wizard picks the highest for the same reason. Ties go to the name that
    sorts last, so the answer is the same on every device rather than the same
    on one.
    """
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://database/')
        names = os.listdir(base)
    except Exception:
        return ''
    best, best_key = '', None
    for name in names:
        m = _DB_NAME.match(name)
        if not m:
            continue
        path = os.path.join(base, name)
        try:
            # A DIRECTORY called Addons99.db used to win and be returned, and
            # the caller then reported the whole device unreadable while a
            # perfectly good Addons27.db sat next to it.
            if not os.path.isfile(path):
                continue
        except Exception:
            continue
        key = (int(m.group(1)), name)
        if best_key is None or key > best_key:
            best, best_key = path, key
    return best


def _jsonrpc(method, params):
    if xbmc is None or json is None:
        return None
    try:
        raw = xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}))
        return json.loads(raw)
    except Exception as exc:
        _log('JSON-RPC {0} failed: {1}'.format(method, exc), level='WARNING')
        return None


def update_mode():
    data = _jsonrpc('Settings.GetSettingValue',
                    {'setting': UPDATE_MODE_SETTING})
    if not isinstance(data, dict):
        return None
    value = (data.get('result') or {}).get('value')
    return value if isinstance(value, int) else None


def _set_update_mode(value):
    data = _jsonrpc('Settings.SetSettingValue',
                    {'setting': UPDATE_MODE_SETTING, 'value': value})
    if not isinstance(data, dict):
        return False
    result = data.get('result')
    return result is True or result == 'OK'


def read_rules(path):
    """[(addonID, rule)], or None if the table cannot be read.

    None and [] are different answers and the caller acts on the difference:
    an empty table is a clean device, an unreadable one is a device we know
    nothing about and must not claim to have repaired.
    """
    if sqlite3 is None or not path or not os.path.isfile(path):
        return None
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=5)
        rows = conn.execute(
            'SELECT addonID, updateRule FROM update_rules').fetchall()
        return [(str(a or ''), int(r or 0)) for a, r in rows]
    except Exception as exc:
        _log('could not read update_rules: {0}'.format(exc), level='WARNING')
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _clear_rules(path, victims):
    """Delete the named (addonID, rule) pairs. Returns how many rows went.

    The isfile check is not redundant with read_rules'. sqlite3.connect
    CREATES an empty database at a path that does not exist, so a file removed
    between the read and this call would leave us having planted a stray empty
    Addons33.db where the real one belongs.
    """
    if sqlite3 is None or not path or not os.path.isfile(path):
        return 0
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=5)
        cur = conn.cursor()
        gone = 0
        for addon_id, rule in victims:
            cur.execute(
                'DELETE FROM update_rules WHERE addonID = ? AND updateRule = ?',
                (addon_id, rule))
            gone += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
        return gone
    except Exception as exc:
        _log('could not clear update_rules: {0}'.format(exc), level='WARNING')
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _seeded():
    try:
        return kodi_utils.get_setting(_MODE_SEED_FLAG, '') == _MODE_SEED_VERSION
    except Exception:
        return False


def _mark_seeded():
    try:
        kodi_utils.set_setting(_MODE_SEED_FLAG, _MODE_SEED_VERSION)
    except Exception:
        pass


def ensure_repaired():
    """Idempotent. Never raises. Returns a short status string."""
    out = []
    fixed = False

    # -- filter 1: the mode
    #
    # THE SEED IS ONLY RECORDED WHEN THE MODE WAS ACTUALLY READ. It used to be
    # written unconditionally at the end of this section, including on the
    # branch below where the JSON-RPC read FAILED and nothing was inspected at
    # all. One transient failure -- the RPC not being up yet on a slow boot is
    # entirely ordinary this early -- therefore burned the one-shot repair
    # forever: the next boot, on a device genuinely stuck on "notify only",
    # took the "already seeded, leave it" branch and warned about it every
    # start without ever fixing it. Proved by running the module, not read off
    # the page.
    mode = update_mode()
    if mode is None:
        out.append('mode=unknown')
    elif mode == 0:
        out.append('mode=ok')
    else:
        # SAID OUT LOUD EVERY START, even after the seed. If a device is
        # sitting on "notify only", that single line is the whole answer to
        # "why does this one never update", and it costs one line a boot.
        _log('add-on updates are set to "{0}" ({1}) -- nothing will install '
             'itself on this device'.format(
                 UPDATE_MODE_NAMES.get(mode, mode), mode), level='WARNING')
        if _seeded():
            # Seeded already, so this is the user's own choice. Report it,
            # leave it. Reverting a setting somebody set is the complaint,
            # not the fix.
            out.append('mode=%s:left' % mode)
        elif _set_update_mode(0):
            _log('set add-on updates back to "install automatically"')
            fixed = True
            out.append('mode=%s:fixed' % mode)
        else:
            out.append('mode=%s:failed' % mode)
    # SEEDED ONLY WHEN SOMETHING WAS ACTUALLY SETTLED. Two rounds of review
    # found two different ways this line burned the one-shot for nothing.
    # First it ran unconditionally, so a JSON-RPC READ that failed counted as
    # a repair. Then it ran whenever the mode had been read -- so a WRITE that
    # failed counted too, and a device whose settings store refuses the write
    # was abandoned after a single attempt and warned at, every boot, forever.
    #
    # The marker means "this device has had its one automatic correction".
    # A device that is already correct has had it. A device we corrected has
    # had it. A device we could not read, or could not write to, has not, and
    # gets another try tomorrow.
    if not _seeded() and (mode == 0 or fixed):
        _mark_seeded()

    # -- filter 2: the pins
    path = addons_db()
    if not path:
        out.append('rules=no_db')
        return ', '.join(out)
    rules = read_rules(path)
    if rules is None:
        out.append('rules=unreadable')
        return ', '.join(out)
    if not rules:
        out.append('rules=none')
        return ', '.join(out)

    for addon_id, rule in sorted(rules):
        _log('pinned: {0} -- {1} (rule {2})'.format(
            addon_id, RULE_NAMES.get(rule, 'unknown rule'), rule))

    victims = [(a, r) for a, r in rules if r in MACHINE_RULES and a in MANAGED]
    if not victims:
        out.append('rules=%d:none_ours' % len(rules))
        return ', '.join(out)

    gone = _clear_rules(path, victims)
    if gone:
        _log('cleared {0} installer-set pin(s) on {1} -- they will auto-update '
             'again from the next start'.format(
                 gone, ', '.join(sorted({a for a, _ in victims}))),
             level='WARNING')
    out.append('rules=%d:cleared_%d' % (len(rules), gone))
    return ', '.join(out)
