"""Self-contained Tonight living-room window, identical across Kodi skins."""
from . import experience


def show(xbmc, xbmcgui, addon_path, picks, state, provider, watched, selected_index=0):
    """Return (action, selected-index-or-mode), or ('close', None)."""
    class TonightWindow(xbmcgui.WindowXMLDialog):
        def onInit(self):
            self.result=('close',None)
            self.setProperty('tonight.provider',provider.upper())
            sources=' / '.join(watched.get('signal_sources',[]))
            personal=' / '.join('MDBList' if source=='mdblist' else 'Trakt'
                                for source in watched.get('personal_sources',[]))
            count=len(watched.get('seed_keys',watched.get('keys',[])))
            if count and personal:
                summary='לומד אוטומטית מ־%s צפיות ומהרשימות שלך ב־%s' % (count,personal)
            elif count:
                summary='לומד אוטומטית מ־%s צפיות ב־%s' % (count,sources or 'היסטוריית הבית')
            elif personal:
                summary='לומד אוטומטית מהרשימות שלך ב־'+personal
            else:
                summary='אפשר להתחיל מיד ולדייק תוך כדי'
            self.setProperty('tonight.history',summary)
            self.setProperty('tonight.hint','← → עוד  •  OK לצפייה  •  ↓ פעולות')
            self.setProperty('tonight.empty','אין כרגע הצעות למצב הזה. בחרו רענון או מצב ערב אחר.')
            profile=state['profiles']['household']
            saved=set(profile.get('saved',[]));feedback=profile.get('feedback',{})
            rows=[]
            for row in picks:
                item=row['item'];display=experience.card(row,state['catalog'],watched.get('seed_keys',watched.get('keys',[])))
                li=xbmcgui.ListItem(label='[B]%s[/B]'%item['title'],label2=display['role'])
                li.setArt(item.get('art',{}))
                li.setProperty('role',display['role'])
                li.setProperty('reason',display['reason'])
                li.setProperty('meta',display['meta'])
                li.setProperty('plot',item.get('plot') or 'אין תקציר זמין כרגע.')
                li.setProperty('save_label','נשמר ברשימה' if item['key'] in saved or item.get('personal_source') or item.get('personal_sources') else 'שמור')
                li.setProperty('like_label','מסומן כאהוב' if feedback.get(item['key'],{}).get('value')==1 else 'אהבתי')
                rows.append(li)
            self.getControl(100).addItems(rows)
            modes=self.getControl(110);modes.addItems(experience.mode_rows(xbmcgui,state['session']))
            try:
                selected=experience.active_mode(state['session'])
                modes.selectItem([key for key,_ in experience.MODES].index(selected))
            except Exception:pass
            if rows:
                try:self.getControl(100).selectItem(min(max(0,selected_index),len(rows)-1))
                except Exception:pass
                self.setFocusId(100)
            else:
                self.setFocusId(206)

        def _selected(self):
            try:
                index=self.getControl(100).getSelectedPosition()
                return index if 0<=index<len(picks) else None
            except Exception:return None

        def _finish(self,action,value=None):
            self.result=(action,value);self.close()

        def onClick(self,control_id):
            if control_id==209:self._finish('close');return
            if control_id==206:self._finish('refresh');return
            if control_id==207:self._finish('more',self._selected());return
            if control_id==110:
                try:
                    item=self.getControl(110).getSelectedItem()
                    self._finish('mode',item.getProperty('mode'))
                except Exception:self._finish('close')
                return
            selected=self._selected()
            if selected is None:return
            actions={100:'play',200:'play',201:'trailer',202:'replace',
                     203:'save',204:'like',205:'similar'}
            if control_id in actions:self._finish(actions[control_id],selected)

        def onAction(self,action):
            try:
                if action.getId() in (9,10,92,216,247):self._finish('close')
            except Exception:self._finish('close')

    window=TonightWindow('script.moransubs.tonight.xml',addon_path,'Default','1080i')
    window.doModal();result=window.result;del window
    return result
