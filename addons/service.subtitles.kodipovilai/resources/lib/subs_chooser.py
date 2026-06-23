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


def _entry_label(c, info, translate):
    """Build the list row text: '<lang> | <NN>% · <release>' for real Hebrew
    subs (so the % the user asked for shows here too), or the entry's own
    descriptive name for AI / embedded / foreign rows."""
    lang = (c.get('language') or '').strip()
    name = (c.get('filename') or '').strip()
    try:
        payload = translate._decode_link(c.get('link') or '') or {}
    except Exception:
        payload = {}
    kind = payload.get('type')
    is_real_he = (lang == 'he' and not payload.get('embedded')
                  and kind in ('passthrough', 'pool', 'engine'))
    if is_real_he:
        rel = (payload.get('filename') or name)
        try:
            pct = translate._match_pct(_video_ref(info), rel)
        except Exception:
            pct = 0
        color = ('FF49C46A' if pct >= 66 else
                 'FFE0B23C' if pct >= 33 else 'FFD0594F')
        return ('[B][COLOR blue]עברית[/COLOR] |[/B] '
                '[B][COLOR {0}]{1}%[/COLOR][/B] · {2}'.format(color, pct, name))
    # AI-translate rows already carry their own %; embedded/foreign keep their
    # descriptive label. Tag the language for non-Hebrew rows.
    if lang and lang != 'he':
        return '[B][{0}][/B] {1}'.format(lang.upper(), name)
    return name


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
            try:
                kodi_utils.set_current_subtitle(ai_link)
            except Exception:
                pass
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
            self.setGeometry(950, 620, 9, 1)
            head = _video_ref(info) or ''
            self.header = pyxbmct.Label(
                '[B][COLOR deepskyblue]{0}[/COLOR][/B]'.format(head))
            self.placeControl(self.header, 0, 0)
            self.lst = pyxbmct.List()
            self.placeControl(self.lst, 1, 0, rowspan=7, columnspan=1)
            self.lst.addItems(
                [_entry_label(c, info, translate) for c in self.items])
            self.connect(self.lst, self.on_pick)
            self.btn = pyxbmct.Button('[B]סגור[/B]')
            self.placeControl(self.btn, 8, 0)
            self.connect(self.btn, self.close)
            self.connect(pyxbmct.ACTION_NAV_BACK, self.close)
            self.lst.controlDown(self.btn)
            self.lst.controlUp(self.btn)
            self.btn.controlUp(self.lst)
            self.btn.controlDown(self.lst)
            self.setFocus(self.lst)

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

    try:
        w = Chooser()
        w.doModal()
        del w
        return True
    except Exception as e:
        _log('window failed: {0}'.format(e), level='WARNING')
        return False
