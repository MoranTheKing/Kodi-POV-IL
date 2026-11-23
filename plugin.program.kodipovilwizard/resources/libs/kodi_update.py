# -*- coding: utf-8 -*-
"""Whether a newer Kodi exists for this device, and what to tell the viewer about it (Wizard 0.5.48).

Before, the Wizard compared Kodi with xbmc/xbmc's newest release on every start and said "update through your
store or Kodi.tv". Three things were wrong with that (a viewer, Nov 2026: "Kodi 21.2, I want 21.3, the Wizard does
not update it"):
  - Google Play still offers 21.2 (its listing was last updated in Feb 2025: 21.3 was held up there), so "the
    store" leads nowhere, and the Wizard cannot install Kodi by itself -- the menu item promised an update;
  - the message came back on EVERY start;
  - the newest release overall would be Kodi 22 once it is out, a new major version the build is not made for.

Now: only a release of the SAME major version counts (21.x on 21), the start-up check runs at most once a day and
shows a version once, and the text says what works for this install: the official Kodi on Android or Windows is
updated by installing the kodi.tv package over it; our own Kodi POV IL app / installer brings its Kodi with its own
new version, so a start never asks about it.

Kodi-free on purpose: the Wizard's glue (wizard.kodi_version_update_check) passes everything in.
"""
import re

DAY = 24 * 3600
RETRY = 6 * 3600            # after GitHub did not answer
OUR_ANDROID_PACKAGE = 'org.xbmc.povi'
DOWNLOADS_PAGE = 'morantheking.github.io/Kodi-POV-IL/downloads'


def parse_version(text):
    m = re.match(r'\s*(\d+(?:\.\d+)+)', text or '')
    return tuple(int(x) for x in m.group(1).split('.')) if m else None


def latest_same_major(releases, current):
    """The newest final release of Kodi with current's major version, from GitHub's releases list (or None)."""
    best = None
    for rel in releases or ():
        if not isinstance(rel, dict) or rel.get('draft') or rel.get('prerelease'):
            continue
        ver = parse_version(rel.get('tag_name', ''))
        if ver and current and ver[0] == current[0] and (best is None or ver > best):
            best = ver
    return best


def install_kind(platform, xbmc_path, home_path):
    """'ours' for the Kodi POV IL app (Android) or our Windows installer (a portable profile), else 'official'."""
    paths = (xbmc_path or '') + '|' + (home_path or '')
    if platform == 'android' and OUR_ANDROID_PACKAGE in paths:
        return 'ours'
    flat = paths.replace('\\', '/').lower()
    # our installer's portable profile (Program Files\Kodi POV IL\portable_data); an official Kodi run with -p has
    # a portable_data too, without our name
    if platform == 'windows' and 'portable_data' in flat and 'kodipovil' in flat.replace(' ', '').replace('-', ''):
        return 'ours'
    return 'official'


def should_show(state, latest, now, manual):
    """Start-up only: a version is told once. (The network check itself is limited by should_check.)"""
    if manual:
        return True
    return bool(latest) and state.get('shown') != vstr(latest)


def should_check(state, now, manual):
    """The start-up check asks GitHub at most once a day (after no answer, again in RETRY); the menu item always
    asks."""
    if manual:
        return True
    try:
        if 'checked' in state and now - float(state['checked']) < DAY:
            return False
        if 'failed' in state and now - float(state['failed']) < RETRY:
            return False
    except (TypeError, ValueError):
        return True
    return True


def vstr(ver):
    return '.'.join(str(x) for x in ver) if ver else ''


def message(platform, kind, current, latest, bits):
    """The dialog's text, or '' when there is nothing to say (an up-to-date Kodi at start-up is handled by the
    caller)."""
    cur, new = vstr(current), vstr(latest)
    if kind == 'ours':
        what = 'האפליקציה Kodi POV IL' if platform == 'android' else 'ההתקנה של Kodi POV IL'
        return ('%s מבוססת על Kodi %s.\n'
                'גרסת Kodi חדשה מגיעה עם גרסה חדשה של %s באתר שלנו:\n'
                '%s\n'
                'הבילד עצמו מתעדכן לבד, בלי קשר לגרסת Kodi.') % (what, cur, 'האפליקציה' if platform == 'android'
                                                                 else 'ההתקנה', DOWNLOADS_PAGE)
    head = '[B]יש גרסת Kodi חדשה: %s[/B] (אצלך %s)\nזה עדכון תיקונים, והבילד עובד גם על הגרסה שלך.\n' % (new, cur)
    if platform == 'android':
        abi = 'ARMV8A' if bits == 64 else 'ARMV7A'
        return head + ('ה-Wizard לא יכול להתקין את Kodi בעצמו, ו-Google Play לא תמיד מציע את הגרסה האחרונה.\n'
                       'לעדכון: מורידים מ-kodi.tv/download את Kodi לאנדרואיד בגרסת %s (%d ביט) ומתקינים מעל '
                       'הקיים. הבילד וההגדרות נשארים.\n'
                       'אם ההתקנה נכשלת, לא מסירים את Kodi: הסרה מוחקת את ההגדרות.') % (abi, bits)
    return head + ('לעדכון: מורידים מ-kodi.tv/download את Kodi ל-Windows ומתקינים מעל הקיים. '
                   'הבילד וההגדרות נשארים.')


def up_to_date_message(current):
    return '[COLOR limegreen][B]גרסת Kodi מעודכנת[/B][/COLOR]\nגרסה נוכחית: [B]%s[/B]' % vstr(current)
