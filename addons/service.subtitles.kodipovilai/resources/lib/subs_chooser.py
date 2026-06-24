# MoranSubs subtitle-chooser window (pyxbmct), opened from the player's
# "בחר כתוביות" button. It lists the SAME Hebrew candidates the search dialog
# offers -- WITH a Hebrew match % per real Hebrew sub -- and applies the picked
# one immediately, staying open so the user can try another. This is the
# MoranSubs replacement for DarkSubs's MySubs window (service.subtitles.All_Subs
# is disabled once the built-in engine is on, which left that button dead).
#
# pyxbmct is a programmatic (code-built) window, so it renders the same on EVERY
# skin -- no per-skin XML needed. Every entry point is guarded; on any failure
# show() returns False so the skin button can fall back to Kodi's native
# subtitle selector instead of a dead/black-screen button.

import os

try:
    import xbmc
    import xbmcgui
except Exception:
    xbmc = xbmcgui = None

ADDON_ID = 'service.subtitles.kodipovilai'


def _log(msg, level='INFO'):
    try:
        from resources.lib import kodi_utils
        kodi_utils.log('subs_chooser: ' + msg, level=level)
    except Exception:
        pass


def _video_ref(info):
    return (info.get('picked_release') or info.get('tagline')
            or info.get('label') or info.get('title') or '')


# Real flag images (32x32, bundled in resources/media/flags) shown in the list's
# icon column. Images never depend on the skin font, so they ALWAYS render -- the
# old ★/◆/■ glyphs showed as empty boxes in some skins (e.g. FENtastic). The flag
# tells the subtitle's language at a glance; foreign rows ALSO get a Hebrew
# language tag in the text, so they're unmistakable even if an image is missing.
_FLAG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'media', 'flags')

_LANG2FLAG = {
    'he': 'he', 'iw': 'he', 'heb': 'he',
    'en': 'en', 'eng': 'en',
    'es': 'es', 'spa': 'es',
    'de': 'de', 'ger': 'de', 'deu': 'de',
    'fr': 'fr', 'fre': 'fr', 'fra': 'fr',
    'pt': 'pt', 'por': 'pt', 'pb': 'pb', 'pob': 'pb',
    'ru': 'ru', 'rus': 'ru',
    'ar': 'ar', 'ara': 'ar',
    'it': 'it', 'ita': 'it',
    'nl': 'nl', 'dut': 'nl', 'nld': 'nl',
    'pl': 'pl', 'pol': 'pl',
    'tr': 'tr', 'tur': 'tr',
    'zh': 'zh', 'chi': 'zh', 'zho': 'zh',
    'ja': 'ja', 'jpn': 'ja',
    'ko': 'ko', 'kor': 'ko',
    'hi': 'hi', 'hin': 'hi',
    'ro': 'ro', 'rum': 'ro', 'ron': 'ro',
    'sv': 'sv', 'swe': 'sv',
    'cs': 'cs', 'cze': 'cs', 'ces': 'cs',
    'da': 'da', 'dan': 'da',
    'fi': 'fi', 'fin': 'fi',
    'no': 'no', 'nor': 'no',
    'el': 'el', 'gre': 'el', 'ell': 'el',
    'hu': 'hu', 'hun': 'hu',
}
_LANG_HE = {
    'en': 'אנגלית', 'es': 'ספרדית', 'de': 'גרמנית', 'fr': 'צרפתית',
    'pt': 'פורטוגזית', 'pb': 'פורטוגזית', 'ru': 'רוסית', 'ar': 'ערבית',
    'it': 'איטלקית', 'nl': 'הולנדית', 'pl': 'פולנית', 'tr': 'טורקית',
    'zh': 'סינית', 'ja': 'יפנית', 'ko': 'קוריאנית', 'hi': 'הינדית',
    'ro': 'רומנית', 'sv': 'שוודית', 'cs': "צ'כית", 'da': 'דנית',
    'fi': 'פינית', 'no': 'נורווגית', 'el': 'יוונית', 'hu': 'הונגרית',
}


def _norm_lang(lang):
    l = (lang or '').strip().lower()
    return _LANG2FLAG.get(l) or _LANG2FLAG.get(l[:2]) or ''


def _flag_path(lang):
    code = _norm_lang(lang) or 'unknown'
    p = os.path.join(_FLAG_DIR, code + '.png')
    if os.path.isfile(p):
        return p
    g = os.path.join(_FLAG_DIR, 'unknown.png')
    return g if os.path.isfile(g) else ''


# Legend: plain text + colours only (no glyphs that some skin fonts can't draw).
_LEGEND = ('[COLOR FFB8D6E8]דגל = שפת הכתובית[/COLOR]   '
           '[COLOR FFFFD700]זהב/ירוק = עברית מוכנה[/COLOR]   '
           '[COLOR FFE0A040]כתום = שפה זרה (תתורגם)[/COLOR]')


def _row_item(c, info, translate, xbmcgui):
    """Build a list row with a REAL flag icon (resources/media/flags) for the
    subtitle's language -- images render on every skin, unlike the old box
    glyphs. Foreign-language rows also get a Hebrew language tag in the text so
    they're unmistakable. Match % goes to the right column; the row is tinted by
    kind/quality (gold/green = ready Hebrew, orange = foreign-to-be-translated,
    magenta = currently applied)."""
    import re as _re
    lang = (c.get('language') or '').strip()
    name = (c.get('filename') or '').strip()
    current = name.startswith('» נוכחית')
    payload = {}
    try:
        payload = translate._decode_link(c.get('link') or '') or {}
    except Exception:
        payload = {}

    # match % already embedded in the label (list_candidates computed it).
    pct = None
    m = _re.search(r'(\d{1,3})%', name)
    if m:
        try:
            pct = int(m.group(1))
        except ValueError:
            pct = None

    # Keep the FULL label text INCLUDING its inline match % -- do NOT move the %
    # to label2: pyxbmct's ControlList doesn't reliably render label2, which made
    # the % disappear on device. Only drop the "» נוכחית ·" prefix (the magenta
    # colour already marks the current sub).
    disp = name
    if current and '· ' in disp:
        disp = disp.split('· ', 1)[1]

    code = _norm_lang(lang)
    is_he = (code == 'he') or (lang.lower() in ('he', 'iw', 'heb'))
    # Foreign (non-Hebrew) row -> prepend a clear Hebrew language tag.
    he_name = _LANG_HE.get(code or lang[:2].lower())
    if not is_he and he_name:
        disp = '[{0}] {1}'.format(he_name, disp)

    if current:
        col = 'FFFF00FE'                    # magenta -- applied now
    elif is_he:
        if pct is not None and pct >= 80:
            col = 'FFFFD700'                # gold -- strong match / 101%
        elif pct is not None and pct >= 50:
            col = 'FF7BE38C'                # green
        else:
            col = 'FFBFE9CF'               # pale green -- ready Hebrew
    elif lang:
        col = 'FFF0A93A'                    # amber -- foreign (will translate)
    else:
        col = 'FFFFFFFF'

    # Make the match % pop: bright white, inside the row's colour.
    disp = _re.sub(r'(\d{1,3}%)', '[COLOR FFFFFFFF]\\1[/COLOR]', disp)
    label = '[B][COLOR {0}]{1}[/COLOR][/B]'.format(col, disp)
    flag = _flag_path('he' if is_he else lang)
    try:
        li = xbmcgui.ListItem(label)
        if flag:
            li.setArt({'icon': flag, 'thumb': flag})
        return li
    except Exception:
        # Fall back to a plain coloured string row if ListItem isn't available.
        return label


def _start_ai_apply(link, info):
    """Deliver an AI translation EXACTLY like the search dialog's fast path:
    show the English source immediately (when the source is English -- readable
    while it cooks), then translate to Hebrew in a SEPARATE background process
    (bg_translate_picker) that swaps the Hebrew in progressively.

    We fire a RunScript rather than a thread on purpose: this chooser runs in a
    short-lived script process that ends when the window closes, so a worker
    thread would be killed mid-translation. The background RunScript runs in its
    own process and survives. Fully guarded."""
    try:
        import base64
        from resources.lib import (kodi_utils, translate,
                                    subs_engine_bridge)
        payload = translate._decode_link(link) or {}
        ai_link = link
        ai_payload = payload
        # engine_ai: download the foreign SOURCE sub now, then continue as 'ai'
        # (same first step the search dialog does).
        if payload.get('type') == 'engine_ai':
            try:
                kodi_utils.notify('AI: מוריד את כתובית המקור...', time_ms=2500)
                src_path = subs_engine_bridge.download(payload)
            except Exception:
                src_path = None
            if not (src_path and os.path.isfile(src_path)):
                try:
                    kodi_utils.notify('AI: לא ניתן להוריד את כתובית המקור',
                                      time_ms=4000)
                except Exception:
                    pass
                return
            ai_payload = {
                'type': 'ai',
                'source_lang': payload.get('src_lang') or 'en',
                'local_path': src_path,
                # carry the source release so the delivered file + pool upload
                # show the full release name instead of a hash / Title.Year.
                'release': payload.get('filename') or '',
                'force_ai': True,
            }
            ai_link = translate._encode_link(ai_payload)
        # English source -> show it immediately (broadly readable); other
        # languages get no intermediate, exactly like the fast path.
        src_lang = ai_payload.get('source_lang') or 'en'
        local_src = ai_payload.get('local_path')
        if src_lang == 'en' and local_src and os.path.isfile(local_src):
            try:
                if xbmc.Player().isPlayingVideo():
                    xbmc.Player().setSubtitles(local_src)
                    xbmc.Player().showSubtitles(True)
            except Exception:
                pass
        # Hand the Hebrew translation to a background process that swaps it in
        # progressively (writes versioned .srt + setSubtitles), same handler the
        # search dialog's fast path uses.
        try:
            sid = translate._source_id_for_ai(ai_payload) or ''
        except Exception:
            sid = ''
        try:
            lk = base64.b64encode(ai_link.encode('utf-8')).decode('ascii')
            sd = base64.b64encode(sid.encode('utf-8')).decode('ascii')
            xbmc.executebuiltin(
                'RunScript(service.subtitles.kodipovilai,'
                'action=bg_translate_picker,link_b64={0},source_id_b64={1})'
                .format(lk, sd))
            # (the chooser already recorded the original picked link as the
            # current sub, so it's marked "» נוכחית" on the next open.)
            kodi_utils.notify('AI: מתרגם לעברית ברקע', time_ms=3000)
        except Exception as _e:
            _log('ai bg fire failed: {0}'.format(_e), level='WARNING')
    except Exception as e:
        _log('ai apply failed: {0}'.format(e), level='WARNING')


def show():
    """Open the chooser for whatever is playing. Returns True if the window was
    shown, False on any failure (so the caller can fall back)."""
    if xbmc is None:
        return False
    try:
        if not xbmc.Player().isPlayingVideo():
            return False
    except Exception:
        return False
    try:
        from resources.lib import kodi_utils, translate
    except Exception:
        return False

    info = kodi_utils.current_video_info()
    try:
        cands = translate.list_candidates(info, modal_progress=False) or []
    except Exception as e:
        _log('list_candidates failed: {0}'.format(e), level='WARNING')
        cands = []
    items = [c for c in cands if c.get('link') and c.get('filename')]
    if not items:
        try:
            kodi_utils.notify('לא נמצאו כתוביות לכותר הזה', time_ms=3500)
        except Exception:
            pass
        return False

    try:
        from resources.lib import pyxbmct
    except Exception as e:
        _log('pyxbmct import failed: {0}'.format(e), level='WARNING')
        return False

    class Chooser(pyxbmct.AddonDialogWindow):
        def __init__(self):
            super(Chooser, self).__init__('MoranSubs — בחר כתוביות')
            self.info = info
            self.items = items
            self.setGeometry(950, 620, 9, 2)
            head = _video_ref(info) or ''
            # Header (A): "נמצאו N כתוביות" + the title/release, with a compact
            # colour/symbol legend underneath so the row glyphs are decodable.
            n_found = len(self.items)
            htxt = '[B][COLOR deepskyblue]נמצאו {0} כתוביות[/COLOR][/B]'.format(
                n_found)
            if head:
                htxt += '[CR][COLOR FFB8D6E8]{0}[/COLOR]'.format(head)
            htxt += '[CR][COLOR FF9AA0A6]{0}[/COLOR]'.format(_LEGEND)
            self.header = pyxbmct.Label(htxt)
            self.placeControl(self.header, 0, 0, rowspan=2, columnspan=2)
            # Taller rows with a flag icon column on the left (the subtitle's
            # language); the match % stays inline in the row text (bright white).
            self.lst = pyxbmct.List(font='font13', _itemHeight=44, _space=2,
                                    _imageWidth=36, _imageHeight=36,
                                    _itemTextXOffset=12)
            self.placeControl(self.lst, 2, 0, rowspan=6, columnspan=2)
            self.lst.addItems(
                [_row_item(c, info, translate, xbmcgui) for c in self.items])
            self.connect(self.lst, self.on_pick)
            # Full native Kodi subtitle search/download -- for users who want the
            # regular "download subtitles" flow, not just this picker. Skin-
            # agnostic (the OSD layout is untouched, so no NOX button collision).
            self.dl = pyxbmct.Button('[B]הורדת כתוביות (Kodi)[/B]')
            self.placeControl(self.dl, 8, 0)
            self.connect(self.dl, self.on_download)
            self.btn = pyxbmct.Button('[B]סגור[/B]')
            self.placeControl(self.btn, 8, 1)
            self.connect(self.btn, self.close)
            self.connect(pyxbmct.ACTION_NAV_BACK, self.close)
            # Up/Down CYCLE within the subtitle list (wrap-around): the list's
            # own up/down navigation points back at itself so focus never leaves
            # it on a plain move, and onAction() does the actual top<->bottom
            # wrap. The action buttons are reached with Left/Right instead.
            self.lst.controlUp(self.lst)
            self.lst.controlDown(self.lst)
            self.lst.controlLeft(self.dl)
            self.lst.controlRight(self.btn)
            self.dl.controlUp(self.lst)
            self.dl.controlDown(self.lst)
            self.dl.controlRight(self.btn)
            self.dl.controlLeft(self.lst)
            self.btn.controlUp(self.lst)
            self.btn.controlDown(self.lst)
            self.btn.controlLeft(self.dl)
            self.btn.controlRight(self.lst)
            self._last_pos = 0
            self.setFocus(self.lst)

        def onAction(self, action):
            """Wrap-around for the subtitle list: Down on the last row jumps to
            the first, Up on the first row jumps to the last. Kodi runs the
            window's default navigation BEFORE this callback, so by here the
            selection has already settled; a row that was on a boundary and
            stayed there (same position as last time) means the user tried to
            step past the edge -- so we wrap. Falls through to pyxbmct for
            everything else (e.g. Back -> close)."""
            try:
                aid = action.getId()
                if (aid in (pyxbmct.ACTION_MOVE_DOWN, pyxbmct.ACTION_MOVE_UP)
                        and self.getFocusId() == self.lst.getId()):
                    n = self.lst.size()
                    cur = self.lst.getSelectedPosition()
                    if n > 1:
                        if (aid == pyxbmct.ACTION_MOVE_DOWN
                                and cur == n - 1 and self._last_pos == n - 1):
                            self.lst.selectItem(0)
                        elif (aid == pyxbmct.ACTION_MOVE_UP
                              and cur == 0 and self._last_pos == 0):
                            self.lst.selectItem(n - 1)
                    self._last_pos = self.lst.getSelectedPosition()
            except Exception:
                pass
            super(Chooser, self).onAction(action)

        def on_download(self):
            """Close the picker and open Kodi's native subtitle search/download
            dialog -- the same dialog the OSD's "download subtitle" reaches."""
            try:
                self.close()
            except Exception:
                pass
            try:
                xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')
            except Exception as e:
                _log('open SubtitleSearch failed: {0}'.format(e),
                     level='WARNING')

        def _set_head(self, text):
            try:
                self.header.setLabel(text)
            except Exception:
                pass

        def on_pick(self):
            try:
                i = self.lst.getSelectedPosition()
            except Exception:
                return
            if i is None or i < 0 or i >= len(self.items):
                return
            c = self.items[i]
            self._set_head('[B]מוריד...[/B]')
            try:
                from resources.lib import translate as _t
                link = c.get('link') or ''
                # Remember this as the applied sub upfront (the ORIGINAL link, so
                # it matches this same candidate next time) -- so reopening the
                # chooser shows it at the top marked "» נוכחית".
                try:
                    kodi_utils.set_current_subtitle(link)
                except Exception:
                    pass
                payload = _t._decode_link(link) or {}
                kind = payload.get('type')
                # Embedded pick: switch Kodi's stream, no file to deliver.
                if kind == 'engine' and payload.get('embedded'):
                    try:
                        from resources.lib import subs_engine_bridge
                        subs_engine_bridge.select_embedded(
                            payload.get('stream_index'),
                            payload.get('lang') or 'he')
                    except Exception as _e:
                        _log('embedded select failed: {0}'.format(_e),
                             level='WARNING')
                    self._set_head('[B][COLOR lightgreen]הופעל תרגום '
                                   'מובנה[/COLOR][/B]')
                    return
                # AI translation (English/Spanish/German/... -> Hebrew) takes
                # 1-2 minutes, so it must NOT block the window. CLOSE the window
                # and translate in the background, applying when ready, with a
                # progress banner -- exactly like picking it from the search.
                if kind in ('engine_ai', 'ai'):
                    self.close()
                    _start_ai_apply(link, self.info)
                    return
                # Ready Hebrew subs (passthrough / pool / human engine): quick
                # download -> apply and CLOSE the window. On failure, keep it
                # open so the user can pick another.
                path = _t.resolve(link, self.info)
                if path and os.path.isfile(path):
                    p = xbmc.Player()
                    if p.isPlayingVideo():
                        p.setSubtitles(path)
                        p.showSubtitles(True)
                    try:
                        kodi_utils.set_current_subtitle(link)
                    except Exception:
                        pass
                    self.close()
                else:
                    self._set_head('[B][COLOR red]ההורדה נכשלה, נסה '
                                   'אחרת[/COLOR][/B]')
            except Exception as e:
                _log('on_pick failed: {0}'.format(e), level='WARNING')
                self._set_head('[B][COLOR red]שגיאה[/COLOR][/B]')

    # Flag that the chooser is open on a shared window property, so the skin can
    # hide overlays (e.g. FENtastic's pause-info panel) while it's up. Kodi does
    # NOT report a pyxbmct script window via System.HasActiveModalDialog, so a
    # property is the reliable signal. Always cleared in finally.
    try:
        try:
            xbmcgui.Window(10000).setProperty('MoranSubsChooserOpen', '1')
        except Exception:
            pass
        w = Chooser()
        w.doModal()
        del w
        return True
    except Exception as e:
        _log('window failed: {0}'.format(e), level='WARNING')
        return False
    finally:
        try:
            xbmcgui.Window(10000).clearProperty('MoranSubsChooserOpen')
        except Exception:
            pass
