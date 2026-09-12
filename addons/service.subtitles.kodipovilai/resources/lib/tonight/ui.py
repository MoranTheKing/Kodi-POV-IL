"""Integrated RunScript action. Standard dialogs: arrows + OK + Back in every skin.

No service loop, credential reads, preference export or playback before explicit selection.
"""
import os
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from . import engine, storage, catalog, history

TITLE='הערב שלי — גרסת התנסות'


@contextmanager
def exclusive(path):
    """OS releases lock even after interpreter crash; another window cannot overwrite state."""
    os.makedirs(os.path.dirname(path),exist_ok=True)
    f=open(path,'a+b')
    acquired=False
    try:
        if os.path.getsize(path)==0:f.write(b'0');f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError:pass
        yield acquired
    finally:
        if acquired:
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        f.close()


def _load_catalog(xbmc,xbmcgui,folder,anchors=()):
    replies=queue.Queue(maxsize=1)
    stopped=threading.Event()
    def work():
        try:
            # The worker owns this OS lock after the user closes the progress
            # dialog, so retrying cannot start overlapping POV requests.
            with exclusive(os.path.join(folder,'tonight','catalog.lock')) as acquired:
                if not acquired:replies.put((None,'already_loading'));return
                items=[]
                requests=[('movie',None),('tvshow',None)]+[(a['kind'],a) for a in anchors[:2]]
                for kind,anchor in requests:
                    if stopped.is_set():break
                    try:items+=catalog.fetch(xbmc.executeJSONRPC,kind,anchor)
                    except (ValueError,TypeError):pass
                replies.put((catalog.merge(items),None))
        except Exception:replies.put((None,'catalog_unavailable'))
    threading.Thread(target=work,daemon=True).start()
    progress=xbmcgui.DialogProgress();progress.create(TITLE,'מחפש הצעות בקטלוג…')
    start=time.monotonic();monitor=xbmc.Monitor()
    try:
        while time.monotonic()-start<20:
            if progress.iscanceled() or monitor.abortRequested():return None
            try:
                items,error=replies.get(timeout=.1)
                return items if not error else None
            except queue.Empty:pass
        return None
    finally:
        stopped.set();progress.close()


def _history(xbmcaddon,xbmcvfs):
    try:
        pov=xbmcaddon.Addon('plugin.video.pov')
        config={k:pov.getSetting(k) for k in ('watched_indicators','trakt_user','mdblist_user')}
        name=history.selected_database(config)
        path=xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'+name) if name else None
        return history.read_watched(path)
    except Exception:return dict(status='unknown',keys=[])


def _item(xbmcgui,item,reason=''):
    duration=(' · %s דק׳' % ((item['runtime']+59)//60)) if item['runtime'] and item['kind']=='movie' else ''
    li=xbmcgui.ListItem(label=item['title']+duration,label2=reason)
    li.setArt(item.get('art',{}))
    li.setInfo('video',dict(title=item['title'],plot=item['plot'],year=item['year'],mediatype=item['kind']))
    return li


def _viewer(dialog,state):
    keys=state['viewers']
    if len(keys)==1:return keys[0]
    i=dialog.select('למי לשמור את המשוב?', [state['profiles'][k]['name'] for k in keys])
    return keys[i] if i>=0 else None


def _actions(dialog,xbmc,xbmcgui,item,reasons,state):
    while True:
        labels=['צפייה' if item['kind']=='movie' else 'בחירת פרק', 'פרטים ולמה בחרנו', 'לא הערב — הצעה אחרת', 'אהבתי את הכותר הזה', 'לא מתאים לטעם שלי', 'כבר ראיתי', 'שמור לערב אחר']
        choice=dialog.select(item['title'],labels)
        if choice<0:return state,False
        if choice==0:
            # Construct only allowlisted POV routes from validated numeric identity.
            route=engine.provider_route(item['kind'],item['tmdb'])
            if item['kind']=='movie':xbmc.executebuiltin('RunPlugin("%s")'%route)
            else:xbmc.executebuiltin('ActivateWindow(Videos,"%s",return)'%route)
            return state,True
        if choice==1:
            dialog.textviewer(item['title'],item['plot']+'\n\n'+'\n'.join(reasons)+'\n\nזמינות מקורות וכתוביות עדיין לא נבדקה. מצב צפייה חסר אינו הוכחה שהכותר לא נצפה.')
            continue
        action={2:'not_tonight',3:'like',4:'dislike',5:'seen',6:'save'}[choice]
        viewer=state['viewers'][0] if action=='not_tonight' else _viewer(dialog,state)
        if viewer is None:continue
        return engine.feedback(state,viewer,item,action),False


def run():
    import xbmc,xbmcaddon,xbmcgui,xbmcvfs
    addon=xbmcaddon.Addon('service.subtitles.kodipovilai');dialog=xbmcgui.Dialog()
    folder=xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    state_path=os.path.join(folder,'tonight','preferences.json')
    with exclusive(os.path.join(folder,'tonight','session.lock')) as acquired:
        if not acquired:
            dialog.notification(TITLE,'הערב שלי כבר פתוח');return
        try:state=storage.load(state_path)
        except storage.StateError:
            dialog.ok(TITLE,'לא ניתן לקרוא את ההעדפות. הקובץ המקורי נשמר ולא אופס.');return
        if time.time()-state['session'].get('started',0)>8*3600:
            state['session']=dict(minutes=0,excluded=[],started=time.time())
        watched=_history(xbmcaddon,xbmcvfs)
        while not xbmc.Monitor().abortRequested():
            profiles=[state['profiles'][k] for k in state['viewers']]
            # Imported shared cache is not assigned to a named person's history.
            seen=watched['keys'] if 'household' in state['viewers'] else []
            picks=engine.choose_three(engine.rank(state['catalog'],profiles,state['session'],seen))
            names=' + '.join(p['name'] for p in profiles)
            rows=[_item(xbmcgui,r['item'],r['reasons'][0]) for r in picks]
            options=['טען הצעות מ־POV', 'מי צופה: '+names, 'כמה זמן יש הערב?', 'היכרות — סמנו כותרים שאהבתם', 'השמורים שלי', 'התחל ערב חדש', 'על ההמלצות והפרטיות']
            rows += [xbmcgui.ListItem(label=s) for s in options]
            chosen=dialog.select(TITLE,rows,useDetails=True)
            if chosen<0:return
            if chosen<len(picks):
                r=picks[chosen];state,playing=_actions(dialog,xbmc,xbmcgui,r['item'],r['reasons'],state)
                storage.save(state_path,state)
                if playing:return
                continue
            action=chosen-len(picks)
            if action==0:
                liked={k for p in profiles for k,f in p['feedback'].items() if f['value']>0}
                anchors=[x for x in state['catalog'] if x['key'] in liked][:2]
                items=_load_catalog(xbmc,xbmcgui,folder,anchors)
                if items:
                    saved={k for p in state['profiles'].values() for k in p['saved']} | liked
                    present={x['key'] for x in items}
                    state['catalog']=items+[x for x in state['catalog'] if x['key'] in saved and x['key'] not in present]
                    state['catalog_fetched']=time.time()
                else:dialog.ok(TITLE,'הקטלוג לא נטען או בוטל. ההצעות הקודמות נשמרו. אפשר לנסות שוב.')
            elif action==1:
                keys=list(state['profiles'])
                selected=dialog.multiselect('מי צופה? אפשר לבחור יחד', [state['profiles'][k]['name'] for k in keys]+['הוסף צופה'],preselect=[keys.index(k) for k in state['viewers']])
                if selected is not None:
                    viewers=[keys[i] for i in selected if i<len(keys)]
                    if len(keys) in selected:
                        name=dialog.input('שם הצופה').strip()[:40]
                        if name and len(keys)<8:
                            key=uuid.uuid4().hex
                            state['profiles'][key]=dict(name=name,feedback={},seen=[],saved=[]);viewers.append(key)
                    if viewers:state['viewers']=viewers
            elif action==2:
                minutes=[0,45,60,90,120,150,180]
                i=dialog.select('כמה זמן יש? סדרות דורשות בחירת פרק', ['ללא מגבלת זמן']+[str(n)+' דקות' for n in minutes[1:]])
                if i>=0:state['session']['minutes']=minutes[i]
            elif action in (3,4):
                saved=set(k for p in profiles for k in p['saved'])
                items=[x for x in state['catalog'] if action==3 or x['key'] in saved]
                if not items:
                    dialog.ok(TITLE,'אין כותרים להצגה כרגע. טענו הצעות, ואז אפשר להכיר או לשמור.');continue
                i=dialog.select('בחרו כותר',[_item(xbmcgui,x) for x in items],useDetails=True)
                if i>=0:
                    state,playing=_actions(dialog,xbmc,xbmcgui,items[i],['כותר שנבחר מהקטלוג'],state)
                    storage.save(state_path,state)
                    if playing:return
            elif action==5:
                state['session']=dict(minutes=0,excluded=[],started=time.time())
            else:
                dialog.textviewer(TITLE,'גרסת התנסות בתוך הבילד. כרגע ההתאמה משתמשת במשוב מפורש, קשרי ז׳אנר, זמן וגיוון. זו עדיין לא הבנת טעם עמוקה.\n\nההעדפות נשמרות רק בפרופיל Kodi הזה; לא נשלחות למודל. צפייה אינה נחשבת לאהבה. מטמון סרטים שנצפו ב־POV מסנן הצעות בפרופיל הבית בלבד; המטמון עלול להיות חלקי או ישן. אצל צופה אישי ההיסטוריה נבנית רק מסימון מפורש.\n\nהקטלוג נטען דרך POV לפי בקשה. טעינתו כפופה להתנהגות POV ולספקי הקטלוג שלו. אין כאן בדיקת זמינות מקור או סנכרון היסטוריית סדרות עדיין.')
            storage.save(state_path,state)
