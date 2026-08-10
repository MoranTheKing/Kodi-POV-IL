# -*- coding: utf-8 -*-
# Hebrew for Umbrella's navigation, on a Hebrew-interface Kodi.
#
# Umbrella ships English, German, Dutch, Polish and Hungarian -- and nothing
# for Hebrew. Kodi resolves an add-on's strings by locale FOLDER, so on a
# Hebrew build it looks for resources/language/resource.language.he_il, does
# not find it, falls back to en_gb (which our legacy_lang_mirror guarantees
# exists), and every menu is English.
#
# So we write the he_il folder ourselves. Purely ADDITIVE -- not one upstream
# byte is modified, which is why Umbrella's own updates keep applying cleanly.
# An update REPLACES the add-on folder and takes our file with it, so this runs
# at every Kodi startup and re-heals.
#
# WHY A PARTIAL TRANSLATION IS THE RIGHT ANSWER. Umbrella defines 1,440
# strings; 831 of them can reach a screen. Translating all of them would be a
# large job with a large surface for mistakes, and gettext does not need it:
# a string with no entry here simply is not in the file, Kodi falls back to
# en_gb, and it renders in English exactly as it does today. Nothing breaks,
# nothing goes blank. That lets us translate the surface a user actually
# touches -- the 169 strings the menus, dialogs and context menu are built
# from -- and leave the 533 settings labels in English, where the terms are
# technical and a translation would more often confuse than help.
#
# The .po is BUILT at install time by pairing each id below with the English
# msgid read out of Umbrella's own strings.po. That way the msgid always
# matches what upstream currently ships, and an id they drop is simply left
# out instead of becoming a stale entry.
#
# Kodi renders the msgstr for a non-source language, so a plain translation
# file is all this needs -- unlike pov_hebrew_ui_patcher, which had to put the
# Hebrew in the msgid because POV has no folder but en_gb, and for the source
# language Kodi shows the msgid.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
ENGLISH_REL = 'resources/language/English/strings.po'
HEBREW_REL = 'resources/language/resource.language.he_il/strings.po'

# First line of every file we write, so a later run can tell our translation
# from one Umbrella might start shipping itself. If the file is there without
# this line, it is theirs and we do not touch it.
MARKER = ('# Hebrew for Umbrella, supplied by the Kodi POV IL build.\n'
          '# Delete this line and the file becomes untouchable.\n')

_HEADER = '''msgid ""
msgstr ""
"Project-Id-Version: Umbrella\\n"
"Report-Msgid-Bugs-To:\\n"
"Language-Team: Kodi POV IL\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: he_IL\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

'''

# Umbrella string id -> Hebrew.
#
# Kodi markup ([B], [I], [COLOR ...], [CR]) and every %s are reproduced
# verbatim and in the same order -- Python's % formatting has no positional
# arguments, so a swapped pair would put the wrong value in the wrong slot.
# Where English word order cannot survive that constraint (the Trakt genre
# rows, "Trending Action Movies"), the qualifier moves to the front with a
# colon instead: "חם עכשיו: אקשן סרטים".
#
# Deliberately NOT translated: brand names (Umbrella, Trakt, Simkl, MDBList,
# TorBox, Real-Debrid, Premiumize, Offcloud, Easy News), and strings that are
# pure punctuation or pure format ("?", "[B]%s[/B] : %s").
HE = {
    # --- top level -------------------------------------------------------
    '32001': 'סרטים',
    '32002': 'סדרות',
    '32008': 'כלים',
    '32010': 'חיפוש',
    '32026': 'מועדפים',
    '32033': 'רשימת צפייה',
    '32054': 'עונות',
    '32055': 'עונה',
    '32326': 'פרקים',
    '32541': 'ספרייה',
    '32053': '[I]העמוד הבא[/I]',
    '32015': 'סריקה ישירה של ההמשכים',
    '32016': 'עיון בהמשכים',
    '32535': 'נגן אקראי',
    '40476': 'חזרה לסרטים',
    '40477': 'חזרה לסדרות',
    # --- dates -----------------------------------------------------------
    # Split on '|' by Umbrella -- the count and the order must stay exactly 12
    # months from January and 7 days from Monday.
    '32060': ('ינואר|פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|'
              'נובמבר|דצמבר'),
    '32061': 'שני|שלישי|רביעי|חמישי|שישי|שבת|ראשון',
    '35032': '[B]משודר[/B]:',
    # --- playback / item actions ----------------------------------------
    '32063': 'בחירת מקור',
    '32064': 'ניגון אוטומטי',
    '32065': 'הוסף לרשימת ההשמעה',
    '32071': 'עיון בסדרה',
    '32184': 'מצא דומים',
    '32185': 'סרוק מחדש',
    '32193': 'סריקה מחדש עם כל הספקים',
    '32194': 'רענן את רשימת ההמשכים',
    '40431': 'נגן טריילר',
    '35516': 'נקה רשימת השמעה',
    '35517': 'הצג רשימת השמעה',
    '35522': 'מנהל רשימות ההשמעה',
    # --- watched state ---------------------------------------------------
    '32066': 'סומן כנצפה ב-Umbrella',
    '32067': 'סומן כלא נצפה ב-Umbrella',
    '32068': 'סומן כנצפה ב-Trakt',
    '32069': 'סומן כלא נצפה ב-Trakt',
    '40554': 'סומן כנצפה ב-Simkl',
    '40555': 'סומן כלא נצפה ב-Simkl',
    '40564': 'סומן כנצפה בשירותים המקוונים',
    '40565': 'סומן כלא נצפה בשירותים המקוונים',
    '40631': 'סמן כנצפה ב-MDBList',
    '40632': 'סמן כלא נצפה ב-MDBList',
    # --- favourites ------------------------------------------------------
    '40463': 'הוסף למועדפים של Umbrella',
    '40468': 'הסר מהמועדפים של Umbrella',
    '40465': 'סרטים מועדפים',
    '40466': 'סדרות מועדפות',
    '40467': 'פרקים מועדפים',
    '40613': 'הוסף לרשימת הצפייה ב-TMDb',
    '40614': 'הסר מרשימת הצפייה ב-TMDb',
    # --- search ----------------------------------------------------------
    '33042': 'חיפוש סרטים...',
    '33043': 'חיפוש סדרות...',
    '33044': 'חיפוש סרטים לפי שחקן...',
    '33045': 'חיפוש סדרות לפי שחקן...',
    '32603': '[COLOR %s][I]חיפוש חדש...[/I][/COLOR]',
    '32605': 'לחץ כדי לנקות את היסטוריית החיפוש',
    '32419': 'חיפוש ברשימות Trakt',
    '40088': 'חיפוש ברשימות MDBList',
    # --- lists -----------------------------------------------------------
    '32417': 'רשימות פופולריות ב-Trakt',
    '32418': 'רשימות חמות ב-Trakt',
    '32186': 'אהבתי את הרשימה',
    '32187': 'בטל אהבתי',
    '40257': 'כי צפית ב',
    '40259': 'דומה ל',
    # Genre rows: English puts the qualifier first ("Trending Action Movies").
    # The two %s are genre and media type, in that order, and % formatting
    # cannot reorder them -- so the qualifier becomes a prefix.
    '40494': 'חם עכשיו: %s %s',
    '40495': 'פופולרי: %s %s',
    '40496': 'הכי מנוגנים: %s %s',
    '40497': 'הכי נצפים: %s %s',
    '40498': 'מצופים: %s %s',
    '40499': 'עשורים: %s %s',
    # --- settings entry points ------------------------------------------
    '32043': '[B]הגדרות[/B] : כללי',
    '32044': '[B]הגדרות[/B] : חשבונות (דבריד)',
    '32045': '[B]הגדרות[/B] : ניגון',
    '32046': '[B]הגדרות[/B] : כתוביות',
    '32048': '[B]הגדרות[/B] : הורדות',
    '40123': '[B]הגדרות[/B] : Trakt',
    '40124': '[B]הגדרות[/B] : חשבונות מטא-דאטה',
    '40162': '[B]הגדרות:[/B] מיון וסינון',
    '40452': '[B]הגדרות[/B] : ספקים',
    '40559': '[B]הגדרות[/B] : Simkl',
    '40611': '[B]הגדרות[/B] : שירותים מקוונים',
    '32506': 'הגדרות [B]תפריט ההקשר של Umbrella[/B]',
    '32609': 'הגדרות [B]החשבונות שלי[/B]',
    '32557': '[B]ספרייה[/B] : הגדרות',
    '32083': 'ניקוי קובץ ההגדרות: [B]UMBRELLA[/B]',
    '40334': 'תיקון הגדרות ריקות: [B]UMBRELLA[/B]',
    # --- view types ------------------------------------------------------
    '32049': '[B]UMBRELLA[/B] : תצוגות',
    '32361': '[B]UMBRELLA[/B] : איפוס סוגי תצוגה',
    '32059': 'לחץ כאן כדי לשמור את התצוגה',
    '40591': 'תצוגת סרטים',
    '40592': 'תצוגת סדרות',
    '40593': 'תצוגת עונות',
    '40594': 'תצוגת פרקים',
    # --- library ---------------------------------------------------------
    '32551': 'הוסף לספרייה',
    '32556': '[B]UMBRELLA[/B] : ספרייה',
    '32558': '[B]UMBRELLA[/B] : עדכון הספרייה...',
    '32559': '[B]UMBRELLA[/B] : תיקיית הסרטים...',
    '32560': '[B]UMBRELLA[/B] : תיקיית הסדרות...',
    '32676': '[B]UMBRELLA[/B] : ניקוי הספרייה...',
    '32561': '[B]TRAKT[/B] : ייבוא אוסף הסרטים...',
    '32562': '[B]TRAKT[/B] : ייבוא רשימת הצפייה לסרטים...',
    '32563': '[B]TRAKT[/B] : ייבוא אוסף הסדרות...',
    '32564': '[B]TRAKT[/B] : ייבוא רשימת הצפייה לסדרות...',
    '32672': '[B]TRAKT[/B] : ייבוא רשימת משתמש - סרטים...',
    '32673': '[B]TRAKT[/B] : ייבוא רשימה אהובה - סרטים...',
    '32674': '[B]TRAKT[/B] : ייבוא רשימת משתמש - סדרות...',
    '32675': '[B]TRAKT[/B] : ייבוא רשימה אהובה - סדרות...',
    '40217': '[B]מנהל ייבוא רשימות - ספרייה[/B]',
    # --- cache -----------------------------------------------------------
    '32510': '[B]פעולות מטמון[/B]',
    '40462': 'פעולות מטמון',
    '32610': 'ניקוי [COLOR yellow]כל [/COLOR]המטמון...',
    '32611': 'ניקוי מטמון [COLOR yellow]הספקים[/COLOR]...',
    '32612': 'ניקוי מטמון [COLOR yellow]המטא-דאטה[/COLOR]...',
    '32613': 'ניקוי [COLOR yellow]המטמון[/COLOR]...',
    '32614': 'ניקוי מטמון [COLOR yellow]החיפוש[/COLOR]...',
    '32615': 'ניקוי מטמון [COLOR yellow]הסימניות[/COLOR]...',
    '40078': 'ניקוי [COLOR yellow]אייקונים ותמונות רקע[/COLOR]...',
    '40402': 'ניקוי מטמון [COLOR yellow]סרטי הספרייה[/COLOR]...',
    '40519': 'ניקוי [COLOR yellow]מטמון תמונות הרקע[/COLOR]...',
    # --- logs ------------------------------------------------------------
    '32523': '[B]כלי לוג[/B]',
    '40460': 'כלי לוג',
    '32524': '[B]Umbrella - הצגת קובץ הלוג[/B]',
    '32525': '[B]Umbrella - ניקוי קובץ הלוג[/B]',
    '32527': '[B]Umbrella - העלאת הלוג ל-pastebin[/B]',
    '32529': '[B]Umbrella - הצגת יומן השינויים המלא[/B]',
    '32532': '[B]הצגת קובץ הלוג של Kodi[/B]',
    '32198': '[B]Kodi - העלאת קובץ הלוג ל-pastebin[/B]',
    # --- management tools ------------------------------------------------
    '35057': '[B]כלי ניהול Trakt[/B]',
    '40461': 'כלי ניהול Trakt',
    '35058': '[COLOR %s][B]מנהל הנטישות[/B][/COLOR]',
    '35059': '[COLOR %s][B]צפיות שלא הושלמו - סרטים[/B][/COLOR]',
    '35060': '[COLOR %s][B]צפיות שלא הושלמו - פרקים[/B][/COLOR]',
    '35061': '[COLOR %s][B]מנהל רשימת הצפייה - סרטים[/B][/COLOR]',
    '35062': '[COLOR %s][B]מנהל רשימת הצפייה - סדרות[/B][/COLOR]',
    '35063': '[COLOR %s][B]מנהל האוסף - סרטים[/B][/COLOR]',
    '35064': '[COLOR %s][B]מנהל האוסף - סדרות[/B][/COLOR]',
    '35065': '[COLOR %s][B]מנהל הרשימות האהובות[/B][/COLOR]',
    '35066': '[COLOR %s][B]אילוץ סנכרון Trakt למסד המקומי[/B][/COLOR]',
    '35067': '[COLOR %s][B]מחיקת מסד הסנכרון של Trakt[/B][/COLOR]',
    '40714': '[COLOR %s][B]מנהל הנטישות - סדרות[/B][/COLOR]',
    '40551': '[B]כלי ניהול Simkl[/B]',
    '40552': 'כלי ניהול Simkl',
    '40553': '[COLOR %s][B]אילוץ סנכרון Simkl למסד המקומי[/B][/COLOR]',
    '40577': '[COLOR %s]מנהל Simkl[/COLOR]',
    '40635': '[B]כלי ניהול MDBList[/B]',
    '40636': 'כלי ניהול MDBList',
    '40637': '[COLOR %s][B]אילוץ סנכרון MDBList למסד המקומי[/B][/COLOR]',
    '40638': '[COLOR %s][B]מנהל רשימת הצפייה - סרטים[/B][/COLOR]',
    '40639': '[COLOR %s][B]מנהל רשימת הצפייה - סדרות[/B][/COLOR]',
    '40606': 'מנהל רשימות TMDb',
    '40669': 'אישור חשבון MDBList',
    '40670': 'ביטול אישור MDBList',
    # --- confirmations ---------------------------------------------------
    '32056': 'האם אתה בטוח?',
    '35531': 'לנקות גם את המטמון וגם את המטא-מטמון?',
    '32076': ('הסרת המטא-מטמון גורמת לכמות גדולה של בקשות ולהאטה של המערכת.'
              '[CR]האם להמשיך?'),
    '32077': ('פעולה זו מוחקת את המטמון, המטא-מטמון, החיפושים ומסד הספקים. '
              'כל המידע יימשך מחדש, מה שיגרום לכמות גדולה של בקשות ולהאטה. '
              'השתמשו בזה רק אם זה הכרחי לחלוטין.[CR]האם להמשיך?'),
    '32182': ('מעבר לעיון בסדרה יסגור את החלון הזה וכל שינוי יאבד. להמשיך?'),
    # --- misc ------------------------------------------------------------
    '40179': 'כיבוי reuselanguageinvoker',
    '40180': 'הפעלת reuselanguageinvoker',
}


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_hebrew_ui_patcher: ' + msg, level=level)
    except Exception:
        pass


def _addon_base():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    return base if os.path.isdir(base) else ''


def _po_escape(text):
    return text.replace('\\', '\\\\').replace('"', '\\"')


def _english_msgids(path):
    """{id: english msgid} straight out of Umbrella's own strings.po, so our
    msgids always match what they currently ship."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
    except OSError:
        return {}
    return dict(re.findall(r'msgctxt "#(\d+)"\s*\nmsgid "(.*?)"\s*\n', src))


def build_po(english):
    """The he_il file as bytes. Ids Umbrella no longer defines are skipped."""
    out = [MARKER, _HEADER]
    for key in sorted(HE, key=int):
        if key not in english:
            continue
        out.append('msgctxt "#%s"\n' % key)
        out.append('msgid "%s"\n' % _po_escape(english[key]))
        out.append('msgstr "%s"\n\n' % _po_escape(HE[key]))
    return ''.join(out).encode('utf-8')


def ensure_patched():
    """Install the Hebrew translation into Umbrella. Additive, idempotent,
    never raises. Returns a short status string."""
    base = _addon_base()
    if not base:
        return 'not_installed'
    src = os.path.join(base, *ENGLISH_REL.split('/'))
    dst = os.path.join(base, *HEBREW_REL.split('/'))
    english = _english_msgids(src)
    if not english:
        _log('could not read Umbrella\'s English strings -- skipping',
             'WARNING')
        return 'no_source'
    payload = build_po(english)
    marker = MARKER.encode('utf-8')
    try:
        if os.path.isfile(dst):
            with open(dst, 'rb') as f:
                existing = f.read()
            if not existing.startswith(marker):
                # Umbrella started shipping its own Hebrew. That is better
                # than ours by definition -- leave it alone.
                return 'upstream'
            if existing == payload:
                return 'unchanged'
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + '.aitmp'
        with open(tmp, 'wb') as f:
            f.write(payload)
        os.replace(tmp, dst)
    except OSError as e:
        try:
            os.remove(dst + '.aitmp')
        except OSError:
            pass
        _log('write failed: {0}'.format(e), 'WARNING')
        return 'write_failed'
    _log('installed Hebrew for {0} of Umbrella\'s menu strings'.format(
        sum(1 for k in HE if k in english)))
    return 'patched'
