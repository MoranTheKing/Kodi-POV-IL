"""Integrated RunScript action. Standard dialogs: arrows + OK + Back in every skin.

No service loop, credential reads, preference export or playback before explicit selection.
"""
import os
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from . import engine, storage, catalog, history, providers

TITLE='הערב שלי — גרסת התנסות'
_CANCELLED=object()


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


def _load_catalog(xbmc,xbmcgui,folder,anchors=(),provider='pov',query=None):
    replies=queue.Queue(maxsize=1)
    stopped=threading.Event()
    def work():
        try:
            # The worker owns this OS lock after the user closes the progress
            # dialog, so retrying cannot start overlapping POV requests.
            with exclusive(os.path.join(folder,'tonight','catalog.lock')) as acquired:
                if not acquired:replies.put((None,'already_loading'));return
                items=[]
                requests=[('movie',None),('tvshow',None)]+([] if query is not None else [(a['kind'],a) for a in anchors[:2]])
                for kind,anchor in requests:
                    if stopped.is_set() or providers.current()!=provider:break
                    try:
                        if query is None:items+=catalog.fetch(xbmc.executeJSONRPC,kind,anchor,provider)
                        else:items+=catalog.fetch(xbmc.executeJSONRPC,kind,provider=provider,query=query)
                    except (ValueError,TypeError):pass
                replies.put((catalog.merge(items),None))
        except Exception:replies.put((None,'catalog_unavailable'))
    threading.Thread(target=work,daemon=True).start()
    progress=xbmcgui.DialogProgress();progress.create(TITLE,'מחפש הצעות בקטלוג…')
    start=time.monotonic();monitor=xbmc.Monitor()
    try:
        while time.monotonic()-start<20:
            if progress.iscanceled() or monitor.abortRequested():return _CANCELLED
            try:
                items,error=replies.get(timeout=.1)
                return items if not error and providers.current()==provider else None
            except queue.Empty:pass
        return None
    finally:
        stopped.set();progress.close()


def _history(xbmcaddon,xbmcvfs,provider='pov'):
    try:
        from .. import addon_presence
        if provider=='umbrella':
            addon=addon_presence.addon('plugin.video.umbrella')
            if addon is None:return dict(status='unknown',keys=[])
            config={k:addon.getSetting(k) for k in ('indicators.alt','dev.enable.custom')}
            if not history.umbrella_local_selected(config):return dict(status='native_catalog_only',keys=[])
            return history.read_umbrella_local(os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')),'watched.db'))
        pov=addon_presence.addon('plugin.video.pov')
        if pov is None:return dict(status='unknown',keys=[])
        config={k:pov.getSetting(k) for k in ('watched_indicators','trakt_user','mdblist_user')}
        name=history.selected_database(config)
        path=xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'+name) if name else None
        return history.read_watched(path)
    except Exception:return dict(status='unknown',keys=[])


def _item(xbmcgui,item,reason=''):
    duration=(' · %s דק׳' % ((item['runtime']+59)//60)) if item['runtime'] and item['kind']=='movie' else ''
    identity=(' · '+str(item['year'])) if item.get('year') else ''
    identity+=' · '+('סרט' if item['kind']=='movie' else 'סדרה')
    li=xbmcgui.ListItem(label=item['title']+identity+duration,label2=reason)
    li.setArt(item.get('art',{}))
    li.setInfo('video',dict(title=item['title'],plot=item['plot'],year=item['year'],mediatype=item['kind']))
    return li


def _viewer(dialog,state):
    keys=state['viewers']
    if len(keys)==1:return keys[0]
    i=dialog.select('למי לשמור את המשוב?', [state['profiles'][k]['name'] for k in keys])
    return keys[i] if i>=0 else None


def _refresh(state,xbmc,xbmcgui,folder,provider,dialog,preferred=None):
    profiles=[state['profiles'][k] for k in state['viewers']]
    liked={k for p in profiles for k,f in p['feedback'].items() if f['value']>0}
    anchor_key=state['session'].get('anchor')
    anchor_key=preferred or anchor_key
    anchors=[x for x in state['catalog'] if x['key']==anchor_key][:1]
    for p in profiles:
        match=next((x for x in state['catalog'] if x['key'] not in {a['key'] for a in anchors} and p['feedback'].get(x['key'],{}).get('value')==1),None)
        if match:anchors.append(match)
        if len(anchors)>=2:break
    items=_load_catalog(xbmc,xbmcgui,folder,anchors,provider)
    if items is _CANCELLED:return state
    if items:
        saved={k for p in state['profiles'].values() for k in p['saved']} | liked | ({anchor_key} if anchor_key else set())
        present={x['key'] for x in items}
        state['catalog']=items+[x for x in state['catalog'] if x['key'] in saved and x['key'] not in present]
        state['catalog_fetched']=time.time()
    else:dialog.ok(TITLE,'הקטלוג לא נטען. ההצעות הקודמות נשמרו. אפשר לנסות שוב.')
    return state


def _act_and_refresh(dialog,xbmc,xbmcgui,item,reasons,state,folder):
    old_anchor=state['session'].get('anchor')
    old_likes={k for k in state['viewers'] if state['profiles'][k]['feedback'].get(item['key'],{}).get('value')==1}
    state,playing=_actions(dialog,xbmc,xbmcgui,item,reasons,state)
    new_like=any(k not in old_likes and state['profiles'][k]['feedback'].get(item['key'],{}).get('value')==1 for k in state['viewers'])
    if not playing and new_like:
        state=_refresh(state,xbmc,xbmcgui,folder,providers.current(),dialog,preferred=item['key'])
    elif not playing and state['session'].get('anchor')!=old_anchor and state['session'].get('anchor'):
        state=_refresh(state,xbmc,xbmcgui,folder,providers.current(),dialog)
    return state,playing


def _actions(dialog,xbmc,xbmcgui,item,reasons,state):
    while True:
        active=providers.current()
        labels=['צפייה' if item['kind']=='movie' else 'בחירת פרק', 'פרטים ולמה בחרנו', 'לא הערב — הצעה אחרת', 'אהבתי את הכותר הזה', 'לא מתאים לטעם שלי', 'כבר ראיתי', 'שמור לערב אחר','כמעט, אבל…','בחר טריילר' if active=='umbrella' else 'טריילר ותוספות ב־POV','שינוי הסימונים שלי']
        # Keep common discovery actions within two Down presses; map display
        # positions explicitly so moving a label cannot change its action.
        display_order=(0,1,8,2,7,6,3,4,5,9)
        choice=dialog.select(item['title'],[labels[i] for i in display_order])
        if choice<0:return state,False
        choice=display_order[choice]
        if choice==0:
            # Construct only allowlisted POV routes from validated numeric identity.
            route=providers.playback_route(providers.current(),item)
            if item['kind']=='movie':xbmc.executebuiltin('RunPlugin("%s")'%route)
            else:xbmc.executebuiltin('ActivateWindow(Videos,"%s",return)'%route)
            return state,True
        if choice==1:
            dialog.textviewer(item['title'],item['plot']+'\n\n'+'\n'.join(reasons)+'\n\nזמינות מקורות וכתוביות עדיין לא נבדקה. מצב צפייה חסר אינו הוכחה שהכותר לא נצפה.')
            continue
        if choice==7:
            choices=[('similar','משהו דומה לזה'),('different','כיוון אחר להערב')]
            if item['kind']=='movie' and item['runtime']:choices.insert(0,('shorter','משהו קצר יותר'))
            selected=dialog.select('מה נשנה?', [c[1] for c in choices])
            if selected<0:continue
            return engine.refine(state,item,choices[selected][0]),False
        if choice==9:
            viewer=_viewer(dialog,state)
            if viewer is None:continue
            p=state['profiles'][viewer];key=item['key'];choices=[]
            if key in p['saved']:choices.append(('unsave','הסר מהשמורים'))
            if key in p['feedback']:choices.append(('clear_feedback','מחק את דירוג הטעם שלי'))
            if key in p['seen']:choices.append(('unseen','בטל את הסימון שלי ככבר ראיתי'))
            if not choices:
                dialog.ok(TITLE,'אין סימון אישי לבטל עבור הצופה הזה.');continue
            selected=dialog.select('שינוי הסימונים שלי',[c[1] for c in choices])
            if selected<0:continue
            action=choices[selected][0]
            changed=engine.feedback(state,viewer,item,action)
            _feedback_notice(dialog,changed,viewer,action)
            return changed,False
        if choice==8:
            route=providers.trailer_route(providers.current(),item)
            xbmc.executebuiltin('RunPlugin("%s")'%route)
            return state,True
        action={2:'not_tonight',3:'like',4:'dislike',5:'seen',6:'save'}[choice]
        viewer=state['viewers'][0] if action=='not_tonight' else _viewer(dialog,state)
        if viewer is None:continue
        changed=engine.feedback(state,viewer,item,action)
        _feedback_notice(dialog,changed,viewer,action)
        return changed,False


def _feedback_notice(dialog,state,viewer,action):
    messages={'like':'נוסף לאהובים','dislike':'הטעם עודכן','seen':'סומן ככבר נצפה',
              'save':'נוסף לשמורים','unsave':'הוסר מהשמורים',
              'clear_feedback':'דירוג הטעם בוטל','unseen':'סימון הצפייה בוטל',
              'not_tonight':'הכותר הוסר מההצעות להערב'}
    message=messages[action]
    if action!='not_tonight':message+=' · '+state['profiles'][viewer]['name']
    dialog.notification(TITLE,message,time=2500,sound=False)


def _session_summary(session):
    kind={'all':'סרטים וסדרות','movie':'סרטים','tvshow':'סדרות'}.get(session.get('kind','all'),'סרטים וסדרות')
    minutes=session.get('minutes',0);shorter=session.get('max_runtime')
    if shorter and (not minutes or shorter<minutes*60):
        duration='עד כ־%s דקות'%((shorter+59)//60)
    else:duration=('עד %s דקות'%minutes) if minutes else 'ללא מגבלת זמן'
    return kind+' · '+duration


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
        provider=None;watched=dict(status='unknown',keys=[])
        undo=[]
        notice=providers.fallback_notice()
        if notice:dialog.ok(TITLE,notice)
        while not xbmc.Monitor().abortRequested():
            active=providers.current()
            if provider!=active:
                provider=active;watched=_history(xbmcaddon,xbmcvfs,provider)
            profiles=[state['profiles'][k] for k in state['viewers']]
            current_catalog=[x for x in state['catalog'] if x.get('provider','pov')==provider]
            # Imported shared cache is not assigned to a named person's history.
            seen=(watched['keys']+[x['key'] for x in current_catalog if x.get('watched')]) if 'household' in state['viewers'] else []
            picks=engine.choose_three(engine.rank(current_catalog,profiles,state['session'],seen))
            names=' + '.join(p['name'] for p in profiles)
            rows=[_item(xbmcgui,r['item'],r['reasons'][0]) for r in picks]
            options=['טען הצעות מ־'+providers.NAMES[provider], 'מי צופה: '+names, 'מה מתאים לערב — '+_session_summary(state['session']), 'היכרות — מה אהבתם?', 'השמורים שלי', 'עוד אפשרויות']
            rows += [xbmcgui.ListItem(label=s,label2='שלוש הצעות להתחלה; סמנו מה אהבתם כדי לדייק' if i==0 and not current_catalog else '') for i,s in enumerate(options)]
            heading=TITLE
            if not picks:
                heading+=' — '+('צריך לטעון הצעות' if not current_catalog else 'אין התאמה לבחירות הנוכחיות')
                if current_catalog:rows.append(xbmcgui.ListItem(label='פתח מחדש את הבחירות לערב',label2='בטל סינון זמני; הטעם, השמורים וסימוני הצפייה יישמרו'))
            chosen=dialog.select(heading,rows,useDetails=True)
            if chosen<0:return
            before=engine.checkpoint(state)
            if chosen<len(picks):
                r=picks[chosen];state,playing=_act_and_refresh(dialog,xbmc,xbmcgui,r['item'],r['reasons'],state,folder)
                if engine.checkpoint(state)!=before:undo=(undo+[before])[-5:]
                storage.save(state_path,state)
                if playing:return
                continue
            action=chosen-len(picks)
            if not picks and current_catalog and action==6:
                state['session']=dict(minutes=0,excluded=[],started=time.time())
                undo=(undo+[before])[-5:];storage.save(state_path,state);continue
            if action in (2,3,5):
                menus={2:('מה מתאים לערב?', [('כמה זמן יש?',2),('סרט, סדרה או שניהם?',7)]),
                       3:('איך נכיר את הטעם?', [('חיפוש כותר שאהבתם',10),('כמה אהובים בבת אחת',8),('עיון בכותרים שכבר נטענו',3)]),
                       5:('עוד אפשרויות', [('בטל את השינוי האחרון',9),('התחל ערב חדש',5),('על ההמלצות והפרטיות',6)])}
                title,choices=menus[action];selection=dialog.select(title,[x[0] for x in choices])
                if selection<0:continue
                action=choices[selection][1]
            if action==0:
                state=_refresh(state,xbmc,xbmcgui,folder,providers.current(),dialog)
            elif action==1:
                keys=list(state['profiles'])
                can_add=len(keys)<8
                selected=dialog.multiselect('מי צופה? אפשר לבחור יחד', [state['profiles'][k]['name'] for k in keys]+(['הוסף צופה'] if can_add else []),preselect=[keys.index(k) for k in state['viewers']])
                if selected is not None:
                    viewers=[keys[i] for i in selected if i<len(keys)]
                    if can_add and len(keys) in selected:
                        name=dialog.input('שם הצופה').strip()[:40]
                        if name and len(keys)<8:
                            key=uuid.uuid4().hex
                            state['profiles'][key]=dict(name=name,feedback={},seen=[],saved=[]);viewers.append(key)
                    if viewers:state['viewers']=viewers
            elif action==2:
                minutes=[0,45,60,90,120,150,180]
                i=dialog.select('כמה זמן יש? סדרות דורשות בחירת פרק', ['ללא מגבלת זמן']+[str(n)+' דקות' for n in minutes[1:]])
                if i>=0:
                    state['session']['minutes']=minutes[i];state['session'].pop('max_runtime',None)
                    if minutes[i] and state['session'].get('kind')=='tvshow':
                        dialog.ok(TITLE,'משך הפרק הבא אינו ידוע. עם מגבלת זמן יוצגו סרטים בלבד; אפשר לחזור לסדרות בבחירת סוג הצפייה.')
                        state['session']['kind']='movie'
            elif action in (3,4):
                saved=set(k for p in profiles for k in p['saved'])
                items=[x for x in state['catalog'] if action==3 or x['key'] in saved]
                if not items:
                    dialog.ok(TITLE,'אין כותרים להצגה כרגע. טענו הצעות, ואז אפשר להכיר או לשמור.');continue
                i=dialog.select('בחרו כותר',[_item(xbmcgui,x) for x in items],useDetails=True)
                if i>=0:
                    state,playing=_act_and_refresh(dialog,xbmc,xbmcgui,items[i],['כותר שנבחר מהקטלוג'],state,folder)
                    if playing:
                        storage.save(state_path,state);return
            elif action==5:
                state['session']=dict(minutes=0,excluded=[],started=time.time())
            elif action==7:
                kinds=['all','movie','tvshow']
                i=dialog.select('מה מחפשים הערב?', ['סרטים וסדרות','סרט','סדרה'])
                if i>=0:
                    state['session']['kind']=kinds[i]
                    if kinds[i]=='tvshow' and (state['session']['minutes'] or state['session'].get('max_runtime')):
                        dialog.ok(TITLE,'משך סדרה אינו משך הפרק הבא. כדי להציג סדרות, מגבלת הזמן תוסר.')
                        state['session']['minutes']=0;state['session'].pop('max_runtime',None)
            elif action==8:
                viewer=_viewer(dialog,state)
                if viewer is not None:
                    items=current_catalog
                    if not items:dialog.ok(TITLE,'טענו הצעות כדי לבחור כותרים מוכרים.')
                    else:
                        selected=dialog.multiselect('סמנו רק כותרים שאהבתם — אפשר לדלג', [x['title'] for x in items])
                        if selected:
                            for i in selected:state=engine.feedback(state,viewer,items[i],'like')
                            state=_refresh(state,xbmc,xbmcgui,folder,providers.current(),dialog)
            elif action==10:
                query=dialog.input('שם סרט או סדרה שאהבתם').strip()[:200]
                if query:
                    items=_load_catalog(xbmc,xbmcgui,folder,provider=providers.current(),query=query)
                    if items is _CANCELLED:continue
                    if not items:dialog.ok(TITLE,'החיפוש לא החזיר כותרים. אפשר לנסות שם מקורי או לבדוק את הספק הפעיל.')
                    else:
                        i=dialog.select('בחרו את הכותר והפעולה',[_item(xbmcgui,x) for x in items],useDetails=True)
                        if i>=0:
                            chosen_item=items[i]
                            changed,playing=_actions(dialog,xbmc,xbmcgui,chosen_item,['תוצאת חיפוש שבחרת'],state)
                            if playing:return
                            if engine.checkpoint(changed)!=engine.checkpoint(state):
                                state=changed
                                state['catalog']=catalog.merge([chosen_item]+state['catalog'])
                                state=_refresh(state,xbmc,xbmcgui,folder,providers.current(),dialog)
            elif action==9:
                if undo:
                    state=engine.restore_checkpoint(state,undo.pop());storage.save(state_path,state);continue
                dialog.notification(TITLE,'אין שינוי לבטל בכניסה הנוכחית')
            else:
                dialog.textviewer(TITLE,'הפיצ׳ר משתמש בבחירת POV / Umbrella שבאריח הבית. ההעדפות והשמורים שייכים לצופה ונשמרים במעבר; הקטלוג והניגון מותאמים לספק הפעיל.\n\nההתאמה מבוססת משוב מפורש, המלצות קטלוג, קשרי ז׳אנר, זמן וגיוון; זו עדיין לא הבנת טעם עמוקה. ההעדפות נשמרות מקומית ולא נשלחות למודל.\n\nסינון נצפה של הבית נשען על המטמון המתאים ועל סימונים חיוביים מהקטלוג הפעיל. היסטוריה חסרה או ישנה אינה הוכחה שכותר לא נצפה. באמברלה עם ספק היסטוריה מרוחק קוראים כרגע רק סימוני נצפה שהקטלוג מחזיר, ולא מטמון מקומי לא קשור.\n\nצפייה אינה אהבה. אצל צופה אישי ההיסטוריה נבנית מסימון מפורש. אין עדיין בדיקת זמינות מקור או סנכרון מלא של היסטוריית פרקים.')
            if engine.checkpoint(state)!=before:undo=(undo+[before])[-5:]
            storage.save(state_path,state)
