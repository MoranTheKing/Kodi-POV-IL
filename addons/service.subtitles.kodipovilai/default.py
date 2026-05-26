# Kodi subtitle service entry point.
#
# Kodi launches this with action=search or action=download in the
# query string. For search, we hand back a list of available subs
# via ListItem objects. For download, we return the path of an SRT
# file on disk via a single ListItem with the file path.
#
# Everything we do here is wrapped in try/except: a crash in this
# script is invisible to the user except as "no subtitles found",
# but it would leak stack traces into kodi.log. We catch and log
# gracefully so the rest of Kodi keeps running.

import os
import sys
import urllib.parse

try:
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcplugin
    import xbmcvfs
except ImportError:
    # Allow `python -m default --action=search` for local debug.
    xbmc = xbmcaddon = xbmcgui = xbmcplugin = xbmcvfs = None

# We import lazily inside handlers so a bad import path doesn't
# prevent the plugin from registering at all.

ADDON_ID = 'service.subtitles.kodipovilai'


def _parse_query():
    """Pull params from the query string Kodi handed us.

    Two invocation styles share this script:
      plugin: sys.argv = [url, handle, '?action=download&link=...']
      runscript: sys.argv = [path, 'action=test_connection', ...]

    We sniff which one we're in by looking at argv[0] -- plugin
    invocations start with 'plugin://'. For runscript we fold each
    'key=value' arg into the params dict.
    """
    out = {}
    if not sys.argv:
        return out

    argv0 = sys.argv[0] or ''
    if argv0.startswith('plugin://'):
        if len(sys.argv) >= 3:
            q = sys.argv[2] or ''
            if q.startswith('?'):
                q = q[1:]
            for k, v in urllib.parse.parse_qsl(q, keep_blank_values=True):
                out[k] = v
        return out

    # RunScript: each remaining arg is "key=value" (or just "key").
    for a in sys.argv[1:]:
        if not a:
            continue
        if '=' in a:
            k, v = a.split('=', 1)
            out[k.strip()] = v.strip()
        else:
            out[a.strip()] = '1'
    return out


def _safe_log(msg, level='INFO'):
    try:
        from resources.lib import kodi_utils
        kodi_utils.log(msg, level=level)
    except Exception:
        try:
            if xbmc:
                xbmc.log('[{0}] {1}'.format(ADDON_ID, msg), xbmc.LOGINFO)
        except Exception:
            pass


def _handle_search(handle, params):
    """List available subtitles. Kodi calls this when the user opens
    the subtitle search dialog."""
    from resources.lib import kodi_utils, translate

    # Make sure DarkSubs's machine-translate hook is in place. The
    # service runs this on Kodi startup too, but doing it here as
    # well catches the case where DarkSubs was installed (or
    # updated) AFTER Kodi started -- the patch goes in immediately,
    # without needing a reboot. Idempotent.
    try:
        from resources.lib import dark_subs_integration
        dark_subs_integration.maybe_patch_darksubs()
    except Exception as e:
        _safe_log('darksubs patch skipped: {0}'.format(e),
                  level='DEBUG')

    info = kodi_utils.current_video_info()
    _safe_log('search: ' + repr({k: v for k, v in info.items() if v}))

    try:
        candidates = translate.list_candidates(info)
    except Exception as e:
        _safe_log('list_candidates crashed: {0}'.format(e), level='ERROR')
        candidates = []

    for c in candidates:
        try:
            label = c.get('filename', 'AI Hebrew')
            listitem = xbmcgui.ListItem(label=c.get('language', 'he'),
                                        label2=label)
            listitem.setArt({'icon': str(c.get('rating', '3')),
                             'thumb': c.get('language', 'he')})
            listitem.setProperty('sync', c.get('sync', 'false'))
            listitem.setProperty('hearing_imp',
                                 'true' if c.get('is_hi') else 'false')
            url = ('plugin://{0}/?action=download&link={1}'
                   .format(ADDON_ID,
                           urllib.parse.quote(c.get('link', ''), safe='')))
            xbmcplugin.addDirectoryItem(handle=handle, url=url,
                                        listitem=listitem,
                                        isFolder=False)
        except Exception as e:
            _safe_log('addDirectoryItem failed: {0}'.format(e),
                      level='WARNING')

    xbmcplugin.endOfDirectory(handle)


def _handle_download(handle, params):
    """User picked one of our entries -- deliver the SRT path."""
    from resources.lib import kodi_utils, translate

    link = params.get('link', '')
    info = kodi_utils.current_video_info()

    progress = None
    try:
        progress = xbmcgui.DialogProgressBG()
        progress.create('Kodi POV IL', 'AI Hebrew')
    except Exception:
        progress = None

    def report(stage, total):
        if not progress:
            return
        try:
            pct = int(stage * 100 / max(1, total))
            progress.update(pct, 'Kodi POV IL',
                            kodi_utils.localised(33001, stage, total))
        except Exception:
            pass

    try:
        path = translate.resolve(link, info, progress_cb=report)
    except Exception as e:
        _safe_log('resolve crashed: {0}'.format(e), level='ERROR')
        path = None

    if progress is not None:
        try:
            progress.close()
        except Exception:
            pass

    if path and os.path.isfile(path):
        listitem = xbmcgui.ListItem(label=path)
        xbmcplugin.addDirectoryItem(handle=handle, url=path,
                                    listitem=listitem,
                                    isFolder=False)
    xbmcplugin.endOfDirectory(handle)


def _handle_manualsearch(handle, params):
    # Kodi sometimes invokes manualsearch when the user types a
    # query in the search dialog. We treat it the same as search;
    # the title/year still flow through getInfoLabel.
    _handle_search(handle, params)


# ---- RunScript handlers (settings buttons) --------------------------

def _handle_open_aistudio(_params):
    """Open the AI Studio key-creation page in the user's browser
    when they tap "Get a free Gemini API key" in settings."""
    url = 'https://aistudio.google.com/apikey'
    try:
        xbmc.executebuiltin('System.Exec("xdg-open {0}")'.format(url))
    except Exception:
        pass
    # Always show a fallback dialog with the URL so users on
    # platforms without a usable browser (Fire TV, Shield) can copy
    # it down manually.
    try:
        from resources.lib import kodi_utils
        xbmcgui.Dialog().ok(
            'Kodi POV IL',
            'פתח בדפדפן:\n{0}\n\nצור API key (חינמי), העתק, '
            'והדבק בשדה "Gemini API Key" בהגדרות.'.format(url),
        )
    except Exception:
        pass


def _handle_open_wyzie_signup(_params):
    """User clicked 'Claim a free Wyzie key' in settings."""
    url = 'https://store.wyzie.io/redeem'
    # Check whether DarkSubs is installed -- if it is, Wyzie is
    # redundant for most users and we should say so up front so they
    # don't waste time signing up.
    has_darksubs = False
    try:
        import xbmcaddon as _xa
        _xa.Addon('service.subtitles.All_Subs')
        has_darksubs = True
    except Exception:
        pass
    try:
        if has_darksubs:
            msg = (
                'שים לב: יש לך תוסף DarkSubs מותקן, '
                'אז Wyzie בעצם לא נחוץ - לחיצה על כתובית באנגלית '
                '(או כל שפה לא-עברית) ב-DarkSubs כבר מפעילה את '
                'התרגום AI אוטומטית.\n\nאם בכל זאת אתה רוצה key '
                '(למשל למקור אונליין נוסף מתוך התוסף שלי, בלי '
                'לעבור דרך DarkSubs):\n{0}\n\n1000 בקשות ביום, חינם.'
            ).format(url)
        else:
            msg = (
                'פתח בדפדפן:\n{0}\n\nתקבל API key חינמי '
                '(1000 בקשות/יום). העתק לשדה Wyzie API Key '
                'בהגדרות.\n\n(אופציונלי - אם תתקין בעתיד את '
                'התוסף DarkSubs, תוכל לוותר על Wyzie לגמרי.)'
            ).format(url)
        xbmcgui.Dialog().ok('Kodi POV IL', msg)
    except Exception:
        pass
    try:
        xbmc.executebuiltin('System.Exec("xdg-open {0}")'.format(url))
    except Exception:
        pass


def _handle_connect_gemini(_params):
    """Full Gemini auth flow invoked from POV's My Services menu
    (or from anywhere via RunScript). Provides two onboarding
    paths -- pair-from-phone via local HTTP server, or type the
    key directly -- and validates against Gemini's /models
    endpoint INLINE before writing to settings, so a bad key
    never lands in the addon's persistent state."""
    try:
        from resources.lib import kodi_utils, gemini, gemini_pair
    except Exception as e:
        try:
            xbmcgui.Dialog().ok('Kodi POV IL',
                                'Internal error: {0}'.format(e))
        except Exception:
            pass
        return

    current = (kodi_utils.get_setting('api_key', '') or '').strip()
    if current:
        _gemini_menu_existing(kodi_utils, gemini, gemini_pair, current)
    else:
        _gemini_menu_new(kodi_utils, gemini, gemini_pair)


def _gemini_menu_existing(kodi_utils, gemini, gemini_pair, current_key):
    """User clicked Gemini in My Services and already has a key
    set. Offer Test / Usage / Replace / Remove."""
    options = [
        '🔍 בדוק חיבור (Test connection)',
        '📊 ניצול היום (Daily usage)',
        '🔄 החלף key (Replace)',
        '❌ מחק key (Remove)',
    ]
    try:
        choice = xbmcgui.Dialog().select(
            'Gemini AI - מה לעשות?', options)
    except Exception:
        choice = -1
    if choice < 0:
        return
    if choice == 0:
        _test_key_show_result(kodi_utils, gemini, current_key)
        return
    if choice == 1:
        _show_gemini_usage()
        return
    if choice == 2:
        # Don't clear the existing key here -- if the user cancels
        # mid-flow (closes the QR dialog, dismisses the keyboard,
        # taps outside the screen) they'd lose a working key with
        # no replacement. The new key, once validated, overwrites
        # the old one via set_setting in _test_save_or_retry, so
        # replace happens atomically on success; on cancel the old
        # key stays put.
        _gemini_menu_new(kodi_utils, gemini, gemini_pair)
        return
    if choice == 3:
        confirm = xbmcgui.Dialog().yesno(
            'Kodi POV IL', 'למחוק את ה-Gemini API key?')
        if confirm:
            kodi_utils.set_setting('api_key', '')
            kodi_utils.notify('Gemini key נמחק', time_ms=3000)


def _show_gemini_usage():
    """Render the daily quota status in a Dialog().ok(). Used by
    the 'ניצול היום' menu entry and the runscript action."""
    try:
        from resources.lib import gemini_quota
    except Exception as e:
        try:
            xbmcgui.Dialog().ok('Kodi POV IL',
                                'Internal error: {0}'.format(e))
        except Exception:
            pass
        return
    try:
        body = gemini_quota.format_status_long()
    except Exception as e:
        body = 'שגיאה בקריאת הנתונים: {0}'.format(e)
    try:
        xbmcgui.Dialog().ok('Gemini AI - ניצול היום', body)
    except Exception:
        pass


def _handle_show_gemini_usage(_params):
    """RunScript entry point so the dialog can be opened from
    anywhere, e.g. a Wizard button or a remote shortcut."""
    _show_gemini_usage()


def _gemini_menu_new(kodi_utils, gemini, gemini_pair):
    """No key set yet. Let the user pick onboarding method."""
    options = [
        '📱 התאמה מטלפון / מכשיר אחר (QR + URL)',
        '⌨️ הזנת ה-key ידנית כאן',
    ]
    try:
        choice = xbmcgui.Dialog().select(
            'Gemini AI - איך להתחבר?', options)
    except Exception:
        choice = -1
    if choice < 0:
        return
    if choice == 0:
        _gemini_pair_flow(kodi_utils, gemini, gemini_pair)
        return
    if choice == 1:
        _gemini_type_flow(kodi_utils, gemini)


class _PairWindow(xbmcgui.WindowDialog):
    """Full-screen-ish dialog showing a real scannable QR image
    (fetched from qrserver.com), the URL as fallback text, and a
    countdown. The previous implementation used DialogProgress
    which is text-only -- the QR was a URL printed as text, which
    is useless for non-technical users.

    Closes on Back/Esc (cancellation) or via close() called
    externally when the main flow detects the key arrived."""

    ACTION_PREVIOUS_MENU = 10
    ACTION_NAV_BACK = 92
    ACTION_STOP = 13

    def __init__(self, *args, **kwargs):
        # WindowDialog quirk: don't pass args to super, just init state
        self.cancelled = False
        self._countdown_lbl = None

    def setup(self, qr_url, url_lines, instructions_header):
        # WindowDialog coordinate space is 1280x720 by default.
        # Layout:
        #   y=0-720    full-screen semi-opaque dark background
        #   y=30-90    title
        #   y=120-500  QR image (380x380, centered)
        #   y=520-650  instruction text + URL fallback
        #   y=670-700  countdown + cancel hint

        # Dim background so QR is readable and Kodi behind is muted.
        bg_path = ('special://home/addons/service.subtitles.kodipovilai/'
                   'resources/lib/icons/dark_bg.png')
        bg = xbmcgui.ControlImage(0, 0, 1280, 720, bg_path,
                                  colorDiffuse='EE000000', aspectRatio=2)
        self.addControl(bg)

        # Title bar
        title = xbmcgui.ControlLabel(
            340, 30, 600, 60,
            '[B][COLOR=ffd166]Gemini AI - התאמה מטלפון[/COLOR][/B]',
            alignment=2 | 4, font='font30')
        self.addControl(title)

        # QR image (large, centered) -- this is the real fix. Kodi
        # fetches the URL on first display and caches the PNG.
        qr_size = 380
        qr_x = (1280 - qr_size) // 2
        qr = xbmcgui.ControlImage(qr_x, 110, qr_size, qr_size, qr_url,
                                  aspectRatio=2)
        self.addControl(qr)

        # Instructions + URL fallback. Bigger font (font14 vs font13)
        # because some users read this from across the room before
        # typing the URL into their phone manually. The instructions
        # header is now BOLD red to draw attention to the
        # "include the yellow port" warning -- common failure mode
        # for OEM Android scanners that truncate URLs at colons.
        # We also include Android-Chrome-specific troubleshooting
        # because modern Chrome (113+) defaults to "Always use
        # secure connections" which refuses HTTP loads to private
        # IPs -- failure is silent for the user, browser just
        # spins or shows an error page. iOS doesn't do this so
        # iPhone users typically don't hit it.
        instr = xbmcgui.ControlTextBox(120, 480, 1040, 210, font='font13')
        self.addControl(instr)
        text = '[B]סרוק את ה-QR עם המצלמה של הטלפון[/B] '
        text += '(אפליקציית מצלמה רגילה — לא צריך אפליקציה מיוחדת).\n\n'
        text += ('[B][COLOR=bf7f7f]' + instructions_header
                 + ':[/COLOR][/B]\n')
        for line in url_lines:
            text += '   • ' + line + '\n'
        text += ('\n[B][COLOR=ffd166]ה-Chrome של אנדרואיד '
                 'לא נפתח?[/COLOR][/B] כבה ב-Chrome: '
                 'Settings → Privacy → "Always use secure '
                 'connections", או נסה דפדפן אחר (Firefox/Brave/'
                 'Samsung Internet). או חזור ל-Kodi ובחר "הזנה '
                 'ידנית".\n')
        text += ('[B][COLOR=ffd166]באייפון קיבלת 400?[/COLOR][/B] '
                 'הסתכל ב-fingerprint בעמוד "ה-key נשלח" וודא '
                 'שתואם בדיוק למפתח שהעתקת מ-AI Studio. אם תואם '
                 'אבל עדיין נדחה — המפתח עצמו לא תקין; צור חדש.')
        instr.setText(text)

        # Countdown / cancel hint
        self._countdown_lbl = xbmcgui.ControlLabel(
            340, 668, 600, 30, '',
            alignment=2 | 4, font='font12')
        self.addControl(self._countdown_lbl)

    def update_countdown(self, seconds_left):
        if self._countdown_lbl is None:
            return
        try:
            mm, ss = divmod(int(max(0, seconds_left)), 60)
            self._countdown_lbl.setLabel(
                '[COLOR=b7c4cf]ממתין לקבלת ה-key... '
                '({0:02d}:{1:02d} עד פג תוקף)  •  '
                'לביטול: Back[/COLOR]'.format(mm, ss))
        except Exception:
            pass

    def onAction(self, action):
        if action.getId() in (
            self.ACTION_PREVIOUS_MENU,
            self.ACTION_NAV_BACK,
            self.ACTION_STOP,
        ):
            self.cancelled = True
            self.close()


def _gemini_pair_flow(kodi_utils, gemini, gemini_pair):
    """Spin up the local pair server, show a scannable QR image in
    a custom window, poll for the submitted key, validate."""
    import time as _time
    try:
        ps = gemini_pair.PairServer()
    except Exception as e:
        xbmcgui.Dialog().ok(
            'Kodi POV IL',
            'נכשלה הפעלת שרת התאמה: {0}\n\n'
            'אפשר לחזור לתפריט ולבחור "הזנה ידנית" במקום.'
            .format(str(e)[:80]))
        return

    # Primary URL: prefer LAN IP (works for other devices on the
    # same WiFi AND on the same device's browser via localhost
    # because the pair server binds 0.0.0.0). Fall back to
    # localhost-only when LAN detection failed (e.g. cellular).
    primary = ps.url_lan or ps.url_local
    qr_url = ('https://api.qrserver.com/v1/create-qr-code/'
              '?size=380x380&qzone=1&data=' +
              _url_quote(primary))

    # The QR encodes the full URL with port -- we've verified this
    # with a real QR decoder. The text fallback below the QR is what
    # we worry about, because some Android OEM camera apps (Samsung
    # Bixby Vision, Xiaomi MIUI scanner) display the URL truncated
    # at the colon -- the user sees "http://10.0.0.5" and types
    # that, missing the port. So we render the port in a bright
    # accent colour and add an explicit note about it.
    def _highlight_port(url):
        # url is 'http://host:port' or 'http://[v6]:port' etc.
        # Find the LAST colon (port separator). If there's no port
        # we just return the URL as-is.
        if url.count(':') < 2:
            return url
        host_part, port_part = url.rsplit(':', 1)
        return '{0}[COLOR=ffd166]:{1}[/COLOR]'.format(host_part, port_part)

    # Show EVERY detected LAN IP. On devices with multiple network
    # interfaces (Android TV with WiFi+Ethernet, laptop with VPN+WiFi)
    # the single default-route IP we used to pick can be on a
    # different subnet from the user's phone -- the phone tries to
    # reach it, fails with "address not found", and the user assumes
    # the addon is broken. Listing all candidates lets them try each.
    lan_urls = ps.url_lans or []
    if lan_urls:
        url_lines = []
        if len(lan_urls) == 1:
            url_lines.append('מטלפון אחר ב-WiFi:  '
                             + _highlight_port(lan_urls[0]))
        else:
            url_lines.append('מטלפון אחר ב-WiFi (נסה כל אחת עד שאחת '
                             'תיפתח):')
            for u in lan_urls:
                url_lines.append('     • ' + _highlight_port(u))
        url_lines.append('מאותו מכשיר:  '
                         + _highlight_port(ps.url_local))
        instructions_header = (
            'או פתח את אחת מהכתובות בדפדפן (חובה כולל החלק הצהוב — '
            'הפורט)')
    else:
        url_lines = (
            'פתח בדפדפן:  ' + _highlight_port(ps.url_local),
            '(לא זוהתה כתובת LAN -- נגיש רק מאותו מכשיר)',
        )
        instructions_header = (
            'או פתח את הכתובת בדפדפן (חובה כולל החלק הצהוב — '
            'הפורט)')

    deadline = _time.time() + 300  # 5 min cap
    window = None
    try:
        window = _PairWindow()
        window.setup(qr_url, url_lines, instructions_header)
        window.show()

        while _time.time() < deadline:
            if window.cancelled:
                break
            key = ps.received_key()
            if key:
                break
            window.update_countdown(deadline - _time.time())
            xbmc.sleep(500)
    finally:
        try:
            if window:
                window.close()
                del window
        except Exception:
            pass
        ps.shutdown()

    key = ps.received_key()
    if not key:
        return  # user cancelled or timeout
    _test_save_or_retry(kodi_utils, gemini, key, retry_cb=None)


def _gemini_type_flow(kodi_utils, gemini):
    """Original typed-input flow, but with inline validation
    before save and a retry loop on failure."""
    xbmcgui.Dialog().ok(
        'Gemini AI - איך משיגים API key',
        'כדי שתרגום ה-AI יעבוד צריך API key חינמי של Gemini:\n\n'
        '1) פתח בדפדפן (במחשב/טלפון):\n'
        '   https://aistudio.google.com/apikey\n\n'
        '2) התחבר עם חשבון Google. לחץ Create API key.\n\n'
        '3) העתק את המחרוזת והדבק במסך הבא.\n\n'
        'התוכנית החינמית מאפשרת ~500 בקשות ביום של Flash Lite.')
    while True:
        try:
            key = (xbmcgui.Dialog().input('Gemini API Key:') or '').strip()
        except Exception:
            key = ''
        if not key:
            return
        ok = _test_save_or_retry(kodi_utils, gemini, key,
                                  retry_cb='loop')
        if ok != 'retry':
            return


def _test_save_or_retry(kodi_utils, gemini, api_key, retry_cb):
    """Run gemini.test_key on the supplied key. On success: save
    to settings + show success + nudge TMDB. On failure: show the
    specific reason and (if retry_cb='loop') ask whether to try
    again, returning 'retry' if yes."""
    kodi_utils.notify('Gemini: בודק...', time_ms=2000)
    err = None
    try:
        matched = gemini.test_key(api_key)
    except gemini.InvalidKey as e:
        err = 'ה-key נדחה ע"י Gemini ({0})'.format(str(e)[:80])
    except gemini.GeminiError as e:
        err = 'בדיקה נכשלה: {0}'.format(str(e)[:80])
    except Exception as e:
        err = 'שגיאה בלתי צפויה: {0}'.format(str(e)[:80])

    if err is None:
        # Success -- save the key, show confirmation. TMDB no
        # longer needs nudging: the addon ships with a bundled
        # TMDB key, so the user is fully set up the moment Gemini
        # connects.
        saved = kodi_utils.set_setting('api_key', api_key)
        if not saved:
            # Kodi silently rejected our setSetting -- happens on
            # some Kodi/Android combos where the addon UI doesn't
            # commit to settings.xml. Surface the failure instead
            # of showing a false success dialog.
            xbmcgui.Dialog().ok(
                'Gemini AI - שמירה נכשלה',
                'ה-key אומת בהצלחה מול Gemini, אבל Kodi לא שמר '
                'אותו בקובץ ההגדרות.\n\n'
                'נסה לסגור את Kodi לחלוטין ולהפעיל מחדש, ואז לחזור '
                'לכאן ולהריץ שוב את ההתאמה.')
            return 'cancel'
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✓ החיבור הצליח. מודל: {0}\n\n'
            'מוכן לתרגם. אין צורך בהגדרות נוספות.'.format(matched))
        return 'ok'

    # Failure. DON'T save. Optionally offer retry.
    if retry_cb == 'loop':
        retry = xbmcgui.Dialog().yesno(
            'Gemini AI - בדיקה נכשלה',
            err + '\n\nלנסות שוב?',
            nolabel='ביטול', yeslabel='נסה שוב')
        return 'retry' if retry else 'cancel'
    xbmcgui.Dialog().ok('Gemini AI - בדיקה נכשלה', err)
    return 'cancel'


def _test_key_show_result(kodi_utils, gemini, api_key):
    """Re-test an existing key and show the result in a dialog.
    Does NOT change the saved key either way (this is the
    "🔍 Test connection" entry point from the existing-key
    menu)."""
    kodi_utils.notify('Gemini: בודק...', time_ms=2000)
    try:
        matched = gemini.test_key(api_key)
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✓ החיבור תקין. מודל: {0}'.format(matched))
    except gemini.InvalidKey as e:
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✗ ה-key נדחה ע"י Gemini: {0}'.format(str(e)[:120]))
    except gemini.GeminiError as e:
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✗ בדיקה נכשלה: {0}'.format(str(e)[:120]))
    except Exception as e:
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✗ שגיאה בלתי צפויה: {0}'.format(str(e)[:120]))


def _url_quote(s):
    try:
        return urllib.parse.quote(s, safe='')
    except Exception:
        return s


def _handle_test_connection(_params):
    """User clicked "Test connection" in settings."""
    try:
        from resources.lib import kodi_utils, gemini
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    api_key = kodi_utils.get_setting('api_key', '')
    model   = kodi_utils.get_setting('model', 'gemini-3.1-flash-lite') \
              or 'gemini-3.1-flash-lite'

    if not api_key:
        xbmcgui.Dialog().ok('Kodi POV IL', kodi_utils.localised(33002))
        return

    try:
        matched = gemini.test_key(api_key, model=model)
        # Test-connection is the canonical "I've adopted this addon"
        # moment; make sure DarkSubs's hook is in place right now so
        # the next subtitle pick already routes through our AI.
        try:
            from resources.lib import dark_subs_integration
            dark_subs_integration.maybe_patch_darksubs()
        except Exception:
            pass
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33003, matched))
    except gemini.InvalidKey as e:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33004, str(e)[:120]))
    except gemini.GeminiError as e:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33004, str(e)[:120]))
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33004, str(e)[:120]))


def _handle_open_tmdb_notice(_params):
    """Explain the current TMDB state. Since v0.2.13 the addon
    ships with a bundled fallback key from the upstream
    tmdbhelper project, so gender-aware translation works out of
    the box. Connecting a personal key remains optional and
    unchanged -- a user key, if present, takes precedence over
    the bundled one."""
    try:
        from resources.lib import tmdb_helper
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    try:
        using_bundled = tmdb_helper.using_bundled_key()
    except Exception:
        using_bundled = True

    if using_bundled:
        status_line = ('✓ TMDB עובד אוטומטית (key מובנה).\n'
                       'אין צורך לעשות כלום — תרגום AI כבר יודע '
                       'לבחור צורות זכר/נקבה לפי הדמויות.\n\n')
    else:
        status_line = ('✓ נמצא TMDB API key אישי דרך תוסף TMDB '
                       'Helper. הוא בשימוש במקום ה-key המובנה.\n\n')

    body = (
        status_line +
        'תרגום AI משתמש ב-TMDB כדי לזהות את מין כל דמות (זכר / '
        'נקבה) ולבחור צורות עברית נכונות.\n\n'
        'אופציונלי: אם תרצה להשתמש ב-key משלך (למשל אם ה-key '
        'המשותף נחסם זמנית, או אם אתה משתמש ב-TMDB Helper '
        'באופן כללי), פתח את ה-Wizard → "חיבור שירותים" → TMDB '
        'וחבר key אישי. הוא יוחל אוטומטית מאותו רגע, בלי '
        'restart, וידרוס את ה-key המובנה.'
    )
    xbmcgui.Dialog().ok('Kodi POV IL — TMDB', body)


def _handle_test_wyzie_connection(_params):
    """User clicked 'Test Wyzie connection' in settings. Mirrors
    _handle_test_connection for Gemini."""
    try:
        from resources.lib import kodi_utils, wyzie
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    key = kodi_utils.get_setting('wyzie_api_key', '')
    if not (key or '').strip():
        xbmcgui.Dialog().ok(
            'Kodi POV IL',
            'לא הוגדר Wyzie API key. לחץ על "השג מפתח Wyzie" '
            'בהגדרות וקבל אחד חינמי (1000 בקשות ליום).')
        return

    result = wyzie.test_key(key)
    if result.get('ok'):
        xbmcgui.Dialog().ok('Kodi POV IL',
                            '✓ Wyzie: ' + result.get('message', 'OK'))
    else:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            '✗ Wyzie: ' + result.get('message', 'נכשל'))


def _handle_clear_cache(_params):
    """Wipe all cached translations + metadata."""
    try:
        from resources.lib import cache, kodi_utils
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return
    confirm = xbmcgui.Dialog().yesno(
        'Kodi POV IL',
        'נקה את כל ה-cache של התרגומים?\n(תרגומים עתידיים יתבצעו מחדש.)',
    )
    if not confirm:
        return
    n = cache.clear_all()
    xbmcgui.Dialog().ok('Kodi POV IL', kodi_utils.localised(33007, n))


def _handle_translate_file(params):
    """Translate an SRT file to Hebrew on disk.

    Invoked by the DarkSubs engine.py hook via RunScript when the
    user picks a non-Hebrew subtitle from DarkSubs and has a Gemini
    key set. Reads input, translates, writes output, then touches
    a `.ai_done` sentinel next to the output so DarkSubs knows to
    pick it up instead of falling through to Google Translate.

    Params (base64-encoded so they survive RunScript's parameter
    parsing intact -- paths can contain commas, parens, quotes):
      input_b64  : path to source SRT
      output_b64 : path to write Hebrew SRT
    """
    import base64
    try:
        from resources.lib import kodi_utils, translate, srt
    except Exception as e:
        _safe_log('translate_file: import failed: {0}'.format(e),
                  level='ERROR')
        return

    def _decode(b):
        try:
            return base64.b64decode(b.encode('ascii')).decode('utf-8')
        except Exception:
            return ''

    in_path = _decode(params.get('input_b64', ''))
    out_path = _decode(params.get('output_b64', ''))
    if not in_path or not out_path:
        _safe_log('translate_file: missing input/output paths',
                  level='WARNING')
        return
    if not os.path.isfile(in_path):
        _safe_log(
            'translate_file: input not found: {0}'.format(in_path),
            level='WARNING')
        return

    # Read source SRT.
    try:
        with open(in_path, 'r', encoding='utf-8', errors='replace') as f:
            src_text = f.read()
    except OSError as e:
        _safe_log('translate_file: read failed: {0}'.format(e),
                  level='ERROR')
        return

    if not src_text.strip():
        _safe_log('translate_file: source empty', level='WARNING')
        return

    # We don't have video info here (the hook is running inside
    # DarkSubs's process), so synthesize what we can. Cast metadata
    # and proper title come from VideoPlayer InfoLabels if the
    # video is currently playing; otherwise we degrade gracefully.
    info = kodi_utils.current_video_info()

    # Reuse the core orchestration: translate via a temp link payload
    # that points at the source file we already have. resolve() does
    # its own caching, chunking, Gemini calls, etc.
    import json
    import urllib.parse
    payload = {
        'type': 'ai',
        'source_lang': 'en',  # DarkSubs's auto_translate only fires
                              # on non-Hebrew; English is by far the
                              # common case and the prompt is robust
                              # to a misidentified source language.
        'local_path': in_path,
    }
    link = urllib.parse.quote(
        json.dumps(payload, ensure_ascii=False))

    translated_path = None
    # Background progress dialog -- matches what _handle_download
    # already shows when the user picks our AI Subs service
    # directly. Without this, a user picking an English subtitle
    # via DarkSubs sees NOTHING while the 30-90s translation runs
    # in the background -- they don't even know AI is working,
    # which is exactly the "is the hook even firing?" confusion
    # we kept getting. DialogProgressBG is non-blocking and shows
    # in the bottom-right banner area, doesn't interfere with
    # DarkSubs's own UI.
    progress = None
    try:
        progress = xbmcgui.DialogProgressBG()
        progress.create('Kodi POV IL - AI Subtitles',
                        'תרגום AI מתחיל...')
    except Exception:
        progress = None

    def report(stage, total):
        if not progress:
            return
        try:
            from resources.lib import kodi_utils as _ku
            pct = int(stage * 100 / max(1, total))
            progress.update(pct, 'Kodi POV IL - AI Subtitles',
                            _ku.localised(33001, stage, total))
        except Exception:
            pass

    try:
        translated_path = translate.resolve(link, info,
                                            progress_cb=report)
    except Exception as e:
        _safe_log('translate_file: resolve crashed: {0}'.format(e),
                  level='ERROR')
    finally:
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass

    if not translated_path or not os.path.isfile(translated_path):
        _safe_log('translate_file: resolve returned nothing',
                  level='WARNING')
        return

    # Copy translated content to the output path DarkSubs expects.
    try:
        with open(translated_path, 'r', encoding='utf-8',
                  errors='replace') as f:
            hebrew = f.read()
        # Belt-and-suspenders: re-apply the RTL punctuation fix
        # right before delivery. resolve() does this on cache hits
        # too, but applying it again here catches the case where
        # the cache file slipped through (e.g., a write race or a
        # file the migration hasn't reached yet).
        try:
            from resources.lib import srt as _srt
            hebrew = _srt.fix_rtl_punctuation(hebrew)
        except Exception:
            pass
        # Write atomically: temp file in same dir, then rename. This
        # avoids a half-written file being picked up by the hook.
        tmp_out = out_path + '.aitmp'
        with open(tmp_out, 'w', encoding='utf-8') as f:
            f.write(hebrew)
        os.replace(tmp_out, out_path)
    except OSError as e:
        _safe_log('translate_file: write failed: {0}'.format(e),
                  level='ERROR')
        return

    # Touch the sentinel last -- the hook polls for it. Only after
    # the output is complete on disk.
    try:
        open(out_path + '.ai_done', 'w').close()
    except OSError as e:
        _safe_log('translate_file: sentinel write failed: {0}'
                  .format(e), level='WARNING')


def _handle_darksubs_status(_params):
    """User-triggered self-test of the DarkSubs hook integration.
    Pops a dialog with a checklist explaining exactly what's
    working and what isn't. Triggered by the settings-menu entry
    that calls RunPlugin/RunScript with action=darksubs_status.
    """
    try:
        from resources.lib import darksubs_hook_diagnostics
    except Exception as e:
        xbmcgui.Dialog().ok(
            'Kodi POV IL', 'Internal error: {0}'.format(e))
        return
    darksubs_hook_diagnostics.run_full_check()


def _handle_purge_temp(_params):
    """Wipe ALL .srt files in special://temp/. Used to clear out
    stale subtitle leftovers from previous movies that Kodi keeps
    in temp and would otherwise leak into the next movie's
    subtitle search dialog."""
    try:
        from resources.lib import local_subs
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return
    n = local_subs.purge_temp_subs()
    xbmcgui.Dialog().ok(
        'Kodi POV IL',
        'נמחקו {0} קבצי כתוביות מ-temp.'.format(n))


def main():
    if xbmc is None:
        _safe_log('default.py invoked outside Kodi -- nothing to do',
                  level='WARNING')
        return

    try:
        handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    except (ValueError, TypeError):
        handle = -1

    params = _parse_query()
    action = (params.get('action') or 'search').lower()

    try:
        if action == 'search':
            _handle_search(handle, params)
        elif action == 'manualsearch':
            _handle_manualsearch(handle, params)
        elif action == 'download':
            _handle_download(handle, params)
        elif action == 'open_aistudio':
            _handle_open_aistudio(params)
        elif action == 'open_wyzie_signup':
            _handle_open_wyzie_signup(params)
        elif action == 'test_connection':
            _handle_test_connection(params)
        elif action == 'connect_gemini':
            _handle_connect_gemini(params)
        elif action == 'show_gemini_usage':
            _handle_show_gemini_usage(params)
        elif action == 'test_wyzie_connection':
            _handle_test_wyzie_connection(params)
        elif action == 'open_tmdb_notice':
            _handle_open_tmdb_notice(params)
        elif action == 'clear_cache':
            _handle_clear_cache(params)
        elif action == 'purge_temp':
            _handle_purge_temp(params)
        elif action == 'translate_file':
            _handle_translate_file(params)
        elif action == 'darksubs_status':
            _handle_darksubs_status(params)
        else:
            _safe_log('unknown action: ' + action, level='WARNING')
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle)
    except Exception as e:
        _safe_log('main crashed: {0}'.format(e), level='ERROR')
        try:
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle)
        except Exception:
            pass


if __name__ == '__main__':
    main()
