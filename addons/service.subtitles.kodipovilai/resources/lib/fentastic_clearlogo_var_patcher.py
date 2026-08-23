# Missing brackets that made the skin hide things it was written to show.
#
# FOUND IN A USER'S LOG, one line after the video window opened:
#
#     error <general>: unmatched parentheses in
#                      string.isempty(listitem.art(clearlogo)
#
# `String.IsEmpty(` is opened and never closed -- `ListItem.Art(clearlogo)`
# closes only its own bracket. Kodi cannot parse the condition, says so once,
# and treats it as FALSE. That is the whole failure mode, and it repeats:
# a scan of the shipped skin finds twenty-three conditions with exactly this
# shape, across eight files.
#
# TWO SITES ARE REPAIRED HERE, AND THE REST ARE NOT. What separates them is
# whether the correct fix is a fact or a guess.
#
# SITE 1 -- Includes_VideoOsd4.xml, and this is the one anybody will notice.
# The video OSD draws a complementary pair: the title's clear-logo, and the
# studio logo when there is no clear-logo.
#
#     <texture>$VAR[PlayerClearLogoVar]</texture>
#     <visible>!String.IsEmpty(Player.Art(clearlogo)</visible>
#     ...
#     <texture>$VAR[StudiologoShortCutPath]...</texture>
#     <visible>String.IsEmpty(Player.Art(clearlogo)</visible>
#
# Both are unparseable, so both are false, so NEITHER image is ever drawn.
# One of the two is meant to be showing at all times; on every device, on
# every title, the OSD shows neither. Closing the bracket restores exactly
# the author's own alternative -- there is nothing to decide, because the two
# conditions are logical complements and one of them must hold.
#
# SITE 2 -- Variables.xml, the ClearArtLogo variable, which is the expression
# in the log above. Same defect in both of its conditions, same fix.
#
# AND WHAT IT DOES NOT DO, said plainly because the first version of this file
# claimed otherwise. ClearArtLogo's only consumer is a `Poster_View_Art_Logo`
# include, and in View_51_Poster.xml the line that invokes it is COMMENTED
# OUT:
#
#     <!-- <include content="Poster_View_Art_Logo"> -->
#     <!-- </include> -->
#
# So repairing the variable makes it correct and changes nothing on screen.
# It reads as somebody trying the logo, finding it blank -- because of these
# brackets -- and commenting the include out rather than debugging it.
# Un-commenting it is a visible change to everybody's poster view that nobody
# asked for, so it is left to the owner; the repair is here because the
# variable is now right if that decision is ever made, and because it is the
# line the user's log actually complains about.
#
# AND THEN ESTUARY, WHICH IS WHY THE MODULE NAME IS NOW TOO NARROW. A
# fact-check on release 0.2.507 caught this file being credited with a
# clearlogo error in a field log it could not possibly have produced: the log
# was from a device running ESTUARY, and everything here was rooted under
# skin.fentastic. Scanning the shipped build for the defect instead of
# assuming where it lived:
#
#     skin.fentastic/xml/Includes_VideoOsd4.xml   2   sites 1 and 2 below
#     skin.fentastic/xml/Variables.xml            2   site 3 below
#     skin.estuary/xml/Variables.xml              2   NOTHING TOUCHED THESE
#
# Estuary's is the same `ClearArtLogo` variable with the same two unclosed
# brackets -- byte-for-byte the same shape, CRLF and all. But it is the WORSE
# of the two, for precisely the reason given above for not bothering with
# FENtastic's: there the only consumer is commented out, so repairing it
# changes nothing on screen. Estuary's consumer is live.
#
#     skin.estuary/xml/View_51_Poster.xml:256   <texture>$VAR[ClearArtLogo]</texture>
#
# Both conditions unparseable, both therefore false, the variable resolves to
# nothing, and that texture has been drawing nothing -- in the default poster
# view, on every Estuary device, for as long as the skin has shipped. Site 4
# repairs it. The fix is the same fact-not-guess the OSD pair is: two
# complementary conditions, one of them must hold.
#
# The name stays `fentastic_clearlogo_var_patcher` on purpose. It is the
# prefix every field log carries, and being able to grep a year of logs for
# one string is worth more than a file name that reads correctly.
#
# THE OTHER NINETEEN ARE LEFT ALONE, and not for lack of noticing. Some are
# compound (`!String.IsEmpty(A(b) + String.IsEqual(C,d)`), where the bracket
# could close after `b` or at the end and the two mean different things.
# Others gate a control or an onclick that has never fired, so repairing them
# makes something appear or something happen that no user of this build has
# ever seen -- on a skin nobody here can put on a television. The pair above
# is the opposite case: it makes something appear that is ALREADY meant to be
# there and demonstrably is not. A list of the rest belongs in a report to the
# owner, not in a patch nobody can test.
#
# IT LANDS AT THE NEXT KODI START. Kodi parses skin XML once; only ReloadSkin
# re-reads it, and an unconditional skin reload on every boot is exactly what
# this codebase already refuses to do elsewhere.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


# (label, skin add-on id, file relative to that skin, broken block, repaired
# block)
#
# The skin is per-SITE and not a module-level constant, because two different
# skins ship the same defect and a device has only one of them installed. A
# site whose skin is absent reports `no_skin` and costs nothing.
#
# Whole blocks, not the two attributes alone: a skin somebody has edited into
# another shape is one this must not touch, and matching the block is what
# says so.
SITES = (
    ('video OSD logo', 'skin.fentastic', 'xml/Includes_VideoOsd4.xml',
     '\t\t\t<texture>$VAR[PlayerClearLogoVar]</texture>\n'
     '\t\t\t<aspectratio>keep</aspectratio>\n'
     '\t\t\t<visible>!String.IsEmpty(Player.Art(clearlogo)</visible>\n',
     '\t\t\t<texture>$VAR[PlayerClearLogoVar]</texture>\n'
     '\t\t\t<aspectratio>keep</aspectratio>\n'
     '\t\t\t<visible>!String.IsEmpty(Player.Art(clearlogo))</visible>\n'),
    ('video OSD studio logo', 'skin.fentastic',
     'xml/Includes_VideoOsd4.xml',
     '\t\t\t<texture>$VAR[StudiologoShortCutPath]$VAR[Studiologotextureinfo]'
     '</texture>\n'
     '\t\t\t<visible>String.IsEmpty(Player.Art(clearlogo)</visible>\n',
     '\t\t\t<texture>$VAR[StudiologoShortCutPath]$VAR[Studiologotextureinfo]'
     '</texture>\n'
     '\t\t\t<visible>String.IsEmpty(Player.Art(clearlogo))</visible>\n'),
    ('poster-view clear-logo variable', 'skin.fentastic',
     'xml/Variables.xml',
     '\t<variable name="ClearArtLogo">\r\n'
     '\t\t<value condition="!String.IsEmpty(ListItem.Art(clearlogo)">'
     '$INFO[ListItem.Art(clearlogo)]</value>\r\n'
     '\t\t<value condition="String.IsEmpty(ListItem.Art(clearlogo)">'
     '$INFO[ListItem.Art(clearart)]</value>\r\n'
     '\t</variable>',
     '\t<variable name="ClearArtLogo">\r\n'
     '\t\t<value condition="!String.IsEmpty(ListItem.Art(clearlogo))">'
     '$INFO[ListItem.Art(clearlogo)]</value>\r\n'
     '\t\t<value condition="String.IsEmpty(ListItem.Art(clearlogo))">'
     '$INFO[ListItem.Art(clearart)]</value>\r\n'
     '\t</variable>'),
    # The one that is actually on screen. Same variable, same defect, live
    # consumer -- see the Estuary paragraph in the header.
    ('estuary poster-view clear-logo variable', 'skin.estuary',
     'xml/Variables.xml',
     '\t<variable name="ClearArtLogo">\r\n'
     '\t\t<value condition="!String.IsEmpty(ListItem.Art(clearlogo)">'
     '$INFO[ListItem.Art(clearlogo)]</value>\r\n'
     '\t\t<value condition="String.IsEmpty(ListItem.Art(clearlogo)">'
     '$INFO[ListItem.Art(clearart)]</value>\r\n'
     '\t</variable>',
     '\t<variable name="ClearArtLogo">\r\n'
     '\t\t<value condition="!String.IsEmpty(ListItem.Art(clearlogo))">'
     '$INFO[ListItem.Art(clearlogo)]</value>\r\n'
     '\t\t<value condition="String.IsEmpty(ListItem.Art(clearlogo))">'
     '$INFO[ListItem.Art(clearart)]</value>\r\n'
     '\t</variable>'),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('fentastic_clearlogo_var_patcher: ' + msg, level=level)
    except Exception:
        pass


def _path(skin, rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + skin + '/')
    except Exception:
        return ''
    full = os.path.join(base, *rel.split('/'))
    return full if os.path.isfile(full) else ''


def _fit(text, block):
    """`block` rendered in whatever line endings `text` uses.

    The two files disagree: Variables.xml is CRLF and Includes_VideoOsd4.xml
    is LF, and both have been through extractors and skin updates on devices
    nobody here has seen. Matching one style would report the other unmatched
    and leave it broken for good.
    """
    if '\r\n' in text[:8192]:
        return block.replace('\r\n', '\n').replace('\n', '\r\n')
    return block.replace('\r\n', '\n')


def _patch_one(skin, rel, broken, fixed):
    """'no_skin' | 'unchanged' | 'patched' | 'unmatched' | 'read_failed'
    | 'write_failed'."""
    path = _path(skin, rel)
    if not path:
        return 'no_skin'
    try:
        with open(path, encoding='utf-8', newline='') as fh:
            text = fh.read()
    except Exception as exc:
        _log('{0}: read failed: {1}'.format(rel, exc), level='WARNING')
        return 'read_failed'

    want = _fit(text, fixed)
    if want in text:
        return 'unchanged'
    have = _fit(text, broken)
    # count, not `in`: two copies means a skin somebody has edited, and the
    # right answer there is to leave it alone.
    if text.count(have) != 1:
        _log('{0}: not the shape this repairs; leaving it alone'.format(rel),
             level='WARNING')
        return 'unmatched'

    new_text = text.replace(have, want, 1)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as fh:
            fh.write(new_text)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(rel, exc), level='WARNING')
        return 'write_failed'
    return 'patched'


def ensure_patched():
    """Idempotent. Never raises. A comma-joined per-site status.

    Per SITE, not all-or-none: four independent conditions across two skins,
    and a skin update that moves one is no reason to leave the rest broken.
    Only one of the two skins is installed on any given device, so `no_skin`
    for the other is the normal, healthy answer -- not a failure.
    """
    out = []
    for label, skin, rel, broken, fixed in SITES:
        try:
            st = _patch_one(skin, rel, broken, fixed)
        except Exception as exc:
            _log('{0}: unexpected failure: {1}'.format(rel, exc),
                 level='WARNING')
            st = 'read_failed'
        out.append('%s=%s' % (label.replace(' ', '_'), st))
    if any(o.endswith('=patched') for o in out):
        _log('skin conditions Kodi could not parse are closed; they take '
             'effect at the next Kodi start')
    return ', '.join(out)
