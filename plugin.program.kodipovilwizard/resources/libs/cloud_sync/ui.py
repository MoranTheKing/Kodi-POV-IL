"""The settings tile "סנכרון בין מכשירים" (Onyx), Wizard mode cloud_sync: connecting this device to the viewer's
Google Drive, a sync on demand, what is kept, and letting this device go."""
import os
import threading
import time

from . import config, engine

HEADING = 'סנכרון בין מכשירים'
INTRO = ('המועדפים, סימוני הצפייה ו"המשך צפייה" של POV ושל Umbrella יסתנכרנו בין כל המכשירים שלכם, מכל מקום, '
         'בלי Trakt ובלי MDBList.[CR][CR]'
         'הנתונים נשמרים בגוגל דרייב שלכם, בקובץ אחד שהבילד יוצר. הבילד לא רואה שום קובץ אחר בדרייב, '
         'ושום דבר לא עובר דרך שרת שלנו.[CR][CR]'
         'מחברים כל מכשיר פעם אחת, עם קוד קצר בטלפון.')
STEPS = ('[B]1.[/B] בטלפון או במחשב, היכנסו אל:[CR][B]{url}[/B][CR][CR]'
         '[B]2.[/B] הקלידו את הקוד:[CR][B][COLOR gold]{code}[/COLOR][/B][CR][CR]'
         '[B]3.[/B] בחרו את חשבון הגוגל שלכם ואשרו.[CR][CR]'
         'החלון ייסגר לבד כשהחיבור יושלם.')
LISTS = (('pov.fav.', 'מועדפים (POV)'), ('pov.drop.', 'סדרות שנזנחו (POV)'), ('pov.watched.', 'סימוני צפייה (POV)'),
         ('pov.progress.', 'המשך צפייה (POV)'), ('umb.fav.', 'מועדפים (Umbrella)'), ('umb.watched.', 'סימוני צפייה (Umbrella)'),
         ('umb.progress.', 'המשך צפייה (Umbrella)'))


def counts(records_map):
    """(name, how many) for each list the map holds anything of."""
    alive = [key for key, rec in records_map.items() if not rec.get('d')]
    return [(name, sum(1 for key in alive if key.startswith(prefix))) for prefix, name in LISTS
            if any(key.startswith(prefix) for key in alive)]


def _log(text):
    import xbmc
    xbmc.log('[POV IL sync] %s' % text, xbmc.LOGINFO)


def _code_window(flow):
    """The address and the code on the screen, with a QR of the address (the Wizard's own QR window); returns the
    window and a function that says whether the viewer closed it."""
    import xbmcgui
    from resources.libs.common.config import CONFIG
    closed = threading.Event()
    image = ''
    try:
        import segno
        folder = os.path.join(CONFIG.PLUGIN_DATA, 'qrcodes')
        os.makedirs(folder, exist_ok=True)
        image = os.path.join(folder, 'cloud_sync.png')
        segno.make_qr(flow['verification_url'], error='m').save(image, scale=10, border=2)
    except Exception:
        image = ''

    class CodeWindow(xbmcgui.WindowXMLDialog):
        def onInit(self):
            if image:
                self.getControl(501).setImage(image, False)
            self.getControl(502).setText(STEPS.format(url=flow['verification_url'], code=flow['user_code']))
            self.getControl(504).setLabel(HEADING)
            try:
                self.getControl(503).setLabel('ביטול')
            except Exception:
                pass
            self.setFocusId(503)

        def onClick(self, control_id):
            if control_id == 503:
                closed.set()
                self.close()

        def onAction(self, action):
            if action.getId() in (9, 10, 13, 92, 216, 247, 257, 275, 61467, 61448):
                closed.set()
                self.close()

    window = CodeWindow('loguploader.xml', CONFIG.ADDON_PATH, 'Default')
    window.show()
    return window, closed.is_set


def connect(folder):
    """Google's flow for TVs; True when this device is connected."""
    import xbmc
    import xbmcgui
    from .drive import DriveError, poll_device_flow, start_device_flow
    dialog = xbmcgui.Dialog()
    try:
        flow = start_device_flow(config.CLIENT_ID)
    except DriveError as exc:
        dialog.ok(HEADING, 'גוגל לא ענה כרגע (%s). נסו שוב בעוד כמה דקות.' % exc.status)
        return False
    window, closed = _code_window(flow)
    monitor = xbmc.Monitor()
    try:
        tokens = poll_device_flow(config.CLIENT_ID, config.CLIENT_SECRET, flow,
                                  wait=lambda seconds: monitor.waitForAbort(seconds),
                                  cancelled=lambda: closed() or monitor.abortRequested())
    except DriveError:
        tokens = None
    finally:
        try:
            window.close()
        except Exception:
            pass
        del window
    if not tokens:
        if not closed():
            dialog.ok(HEADING, 'החיבור לא הושלם (הקוד פג או שהגישה לא אושרה). אפשר לנסות שוב מהאריח.')
        return False
    folder.save_tokens(tokens)
    _log('this device was connected')
    return True


def sync_now(dialog, first=False):
    import xbmcgui
    progress = xbmcgui.DialogProgress()
    progress.create(HEADING, 'מסנכרן...')
    try:
        summary = engine.run_once(_log, 'first round' if first else 'sync from the tile')
    finally:
        progress.close()
    if summary is None:
        dialog.ok(HEADING, 'הסנכרון לא הצליח כרגע. נסו שוב בעוד כמה דקות.')
        return
    lines = ['הסנכרון הושלם.']
    if summary['put'] or summary['removed']:
        lines.append('נוספו או עודכנו כאן %d, הוסרו כאן %d.' % (summary['put'], summary['removed']))
    lines.append('בסך הכול %d פריטים מסונכרנים.' % summary['records'])
    if first:
        lines.append('מעכשיו המכשיר מסתנכרן לבד: כשקודי עולה, כל 10 דקות ובסוף כל צפייה.')
    dialog.ok(HEADING, '[CR]'.join(lines))


def what_is_kept(dialog, folder):
    _base, remote = folder.maps()
    found = counts(remote)
    if not found:
        dialog.ok(HEADING, 'עוד לא סונכרן שום דבר.')
        return
    dialog.ok(HEADING, '[CR]'.join('%s: %d' % item for item in found))


def open_tile():
    import xbmcgui
    dialog = xbmcgui.Dialog()
    if not config.ready():
        dialog.ok(HEADING, 'הסנכרון בין מכשירים עוד לא זמין בגרסה הזו.')
        return
    folder, _stores = engine.kodi_parts()
    if folder.tokens() is None:
        if not dialog.yesno(HEADING, INTRO, nolabel='ביטול', yeslabel='חיבור המכשיר'):
            return
        if connect(folder):
            sync_now(dialog, first=True)
        return
    while True:
        last = folder.state().get('last')
        when = time.strftime('%d/%m %H:%M', time.localtime(last / 1000.0)) if last else 'עוד לא'
        choice = dialog.select('%s (סונכרן לאחרונה: %s)' % (HEADING, when),
                               ['סנכרון עכשיו', 'מה מסונכרן', 'ניתוק המכשיר הזה'])
        if choice < 0:
            return
        if choice == 0:
            sync_now(dialog)
        elif choice == 1:
            what_is_kept(dialog, folder)
        elif choice == 2:
            if dialog.yesno(HEADING, 'לנתק את המכשיר הזה מהסנכרון?[CR]הרשימות שכבר נמצאות בו נשארות, '
                                     'והמכשירים האחרים שלכם ממשיכים להסתנכרן.'):
                folder.disconnect()
                _log('this device was disconnected by the viewer')
                dialog.ok(HEADING, 'המכשיר נותק.')
                return
