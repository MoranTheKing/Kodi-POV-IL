"""The visual Tonight hub and personal-list discovery stay simple and read-only."""
import copy
import json
from pathlib import Path
import sys
import types
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'addons/service.subtitles.kodipovilai'))
from resources.lib.tonight import catalog,discovery,engine,entrypoints,experience,hub,providers,storage,taste,ui
from resources.lib import af3_home_patcher


def media(n=1,genres=('Drama',),provider='pov'):
    route=('plugin://plugin.video.pov/?mode=play_media&mediatype=movie&tmdb_id=%s'%n
           if provider=='pov' else 'plugin://plugin.video.umbrella/?action=play_Item&tmdb=%s'%n)
    return engine.normalize(dict(file=route,title='Title %s'%n,genre=list(genres),
                                 runtime=5400,rating=8,year=2025,plot='Plot'))


class Control:
    def __init__(self):self.items=[];self.position=0
    def addItems(self,items):self.items.extend(items)
    def getSelectedPosition(self):return self.position
    def getSelectedItem(self):return self.items[self.position]
    def selectItem(self,position):self.position=position


class Item:
    def __init__(self,label='',label2=''):self.label=label;self.label2=label2;self.props={};self.art={}
    def setArt(self,value):self.art=value
    def setProperty(self,key,value):self.props[key]=value
    def getProperty(self,key):return self.props.get(key,'')


class Dialog:
    def __init__(self,*choices):self.choices=list(choices);self.notices=[]
    def select(self,*args,**kwargs):return self.choices.pop(0)
    def notification(self,*args,**kwargs):self.notices.append(args)


class Window:
    click=100;position=0
    def __init__(self,*args):self.controls={100:Control(),110:Control()};self.properties={};self.closed=False
    def setProperty(self,key,value):self.properties[key]=value
    def getControl(self,key):return self.controls[key]
    def setFocusId(self,key):self.focus=key
    def close(self):self.closed=True
    def doModal(self):
        self.onInit();self.controls[100].position=self.position
        if self.click==110:self.controls[110].position=4
        self.onClick(self.click)


class HubTests(unittest.TestCase):
    def test_one_tap_modes_are_complete_and_reversible(self):
        state=engine.initial_state();state['session'].update(anchor='movie:7',anchor_genres=['Drama'],
            avoid_genres=['Horror'],max_runtime=5000,discovery_mode='lighter',avoid_creators=['X'])
        before=copy.deepcopy(state['profiles'])
        quick=experience.apply_mode(state,'quick')
        self.assertEqual((quick['session']['kind'],quick['session']['minutes']),('movie',90))
        self.assertFalse(set(('anchor','avoid_genres','discovery_mode','vibe'))&set(quick['session']))
        light=experience.apply_mode(quick,'light')
        self.assertEqual(light['session']['vibe'],'light');self.assertEqual(light['session']['kind'],'all')
        self.assertEqual(light['profiles'],before);self.assertEqual(experience.active_mode(light['session']),'light')

    def test_vibes_change_ranking_only_from_known_genres(self):
        profile=engine.initial_state()['profiles']['household']
        comedy=media(1,('Comedy',));horror=media(2,('Horror',));thriller=media(3,('Thriller',))
        light=engine.rank([horror,comedy,thriller],[profile],dict(minutes=0,vibe='light'))
        tense=engine.rank([horror,comedy,thriller],[profile],dict(minutes=0,vibe='tense'))
        self.assertEqual(light[0]['item']['key'],comedy['key'])
        self.assertEqual(tense[0]['item']['key'],thriller['key'])

    def test_modes_build_distinct_shelves_and_one_like_cannot_own_them(self):
        state=engine.feedback(engine.initial_state(),'household',media(900,('Horror',)),'like')
        rows=[]
        for start,genre in ((1,'Comedy'),(11,'Thriller'),(21,'Drama')):
            rows.extend(media(start+i,(genre,)) for i in range(4))
        for i in range(6):
            candidate=media(31+i,('Horror',));candidate['recommended_from']=['movie:900'];rows.append(candidate)
        shelves={}
        for mode in ('all','light','tense','moving','surprise'):
            session=experience.apply_mode(state,mode)['session']
            shelves[mode]=engine.choose_shelf(engine.rank(rows,[state['profiles']['household']],session),9)
            self.assertEqual(len(shelves[mode]),9)
        self.assertTrue(all(row['item']['genres']==['Comedy'] for row in shelves['light'][:3]))
        self.assertTrue(all(row['item']['genres']==['Thriller'] for row in shelves['tense'][:3]))
        self.assertTrue(all(row['item']['genres']==['Drama'] for row in shelves['moving'][:3]))
        first_pages={mode:tuple(row['item']['key'] for row in shelf[:3]) for mode,shelf in shelves.items()}
        self.assertEqual(len(set(first_pages.values())),len(first_pages))
        self.assertLessEqual(sum(bool(row['explicit_origins']) for row in shelves['all'][:3]),1)
        self.assertLessEqual(sum(bool(row['explicit_origins']) for row in shelves['all']),2)

    def test_one_like_genre_similarity_without_provenance_is_also_capped(self):
        state=engine.feedback(engine.initial_state(),'household',media(900,('Action',)),'like')
        rows=[media(i,('Action',)) for i in range(1,5)]+[media(i,('Comedy',)) for i in range(11,15)]
        shelf=engine.choose_shelf(engine.rank(rows,[state['profiles']['household']],state['session']),8)
        self.assertLessEqual(sum(row['item']['genres']==['Action'] for row in shelf[:3]),1)
        self.assertLessEqual(sum(row['item']['genres']==['Action'] for row in shelf),2)
        tense=experience.apply_mode(state,'tense')['session']
        tense_shelf=engine.choose_shelf(engine.rank(rows,[state['profiles']['household']],tense),8)
        self.assertEqual(len(tense_shelf),6)
        self.assertEqual(sum(row['item']['genres']==['Action'] for row in tense_shelf),2)
        self.assertEqual(sum(row['item']['genres']==['Comedy'] for row in tense_shelf),4)

    def test_explicit_dislike_is_never_positive_automatic_evidence(self):
        state=engine.initial_state();bad1=media(90,('Horror',));bad2=media(91,('Horror',))
        state=engine.feedback(state,'household',bad1,'dislike')
        horror=media(1,('Horror',));comedy=media(2,('Comedy',))
        ranked=engine.rank([bad1,bad2,horror,comedy],[state['profiles']['household']],dict(minutes=0),
                           watched=[bad1['key'],bad2['key']],history_seeds=[bad1['key'],bad2['key']])
        self.assertFalse(any('דפוס שחוזר' in reason for row in ranked for reason in row['reasons']))

    def test_repeated_history_metadata_personalizes_without_manual_feedback(self):
        profile=engine.initial_state()['profiles']['household']
        watched=[media(90,('Comedy',)),media(91,('Comedy','Adventure'))]
        comedy=media(1,('Comedy',));horror=media(2,('Horror',))
        ranked=engine.rank(watched+[horror,comedy],[profile],dict(minutes=0),
                           watched=[x['key'] for x in watched],
                           history_seeds=[x['key'] for x in watched])
        self.assertEqual(ranked[0]['item']['key'],comedy['key'])
        self.assertTrue(any('דפוס שחוזר' in reason for reason in ranked[0]['reasons']))
        self.assertFalse(profile['feedback'])

    def test_multiple_independent_history_anchors_outweigh_one(self):
        profile=engine.initial_state()['profiles']['household'];seeds=['movie:90','movie:91','movie:92']
        one=media(1);one['recommended_from']=[seeds[0]]
        several=media(2);several['recommended_from']=seeds
        ranked=engine.rank([one,several],[profile],dict(minutes=0),history_seeds=seeds)
        self.assertEqual(ranked[0]['item']['key'],several['key'])
        self.assertIn('כמה כותרים',' '.join(ranked[0]['reasons']))

    def test_repeated_series_exposure_is_bounded_but_more_informative(self):
        profile=engine.initial_state()['profiles']['household'];seeds=['movie:90','tvshow:91']
        movie=media(1);movie['recommended_from']=[seeds[0]]
        series=media(2);series['recommended_from']=[seeds[1]]
        ranked=engine.rank([movie,series],[profile],dict(minutes=0),history_seeds=seeds,
                           history_strengths={'movie:90':1,'tvshow:91':8})
        scores={row['item']['key']:row['score'] for row in ranked}
        self.assertGreater(scores[series['key']],scores[movie['key']])
        self.assertLess(scores[series['key']]-scores[movie['key']],.3)

    def test_personal_routes_are_active_provider_allowlists(self):
        self.assertIn('action=mdblist_watchlist',providers.personal_route('pov','movie','mdblist'))
        self.assertIn('action=mdbUserWatchListTVShows',providers.personal_route('umbrella','tvshow','mdblist'))
        self.assertIn('url=traktwatchlist',providers.personal_route('umbrella','movie','trakt'))
        with self.assertRaises(ValueError):providers.personal_route('foreign','movie','trakt')

    def test_personal_catalog_is_marked_and_merge_keeps_it(self):
        def rpc(raw):
            request=json.loads(raw);self.assertEqual(request['method'],'Files.GetDirectory')
            return json.dumps({'result':{'files':[dict(file=engine.provider_route('movie',1),title='One')]}})
        rows=catalog.fetch(rpc,'movie',provider='pov',personal='mdblist')
        self.assertEqual(rows[0]['personal_source'],'MDBList')
        self.assertEqual(rows[0]['personal_sources'],['MDBList'])
        trakt=dict(rows[0],personal_source='Trakt',personal_sources=['Trakt'])
        plain=media(1);merged=catalog.merge([plain,rows[0],trakt])[0]
        self.assertEqual(merged['personal_source'],'MDBList / Trakt')
        self.assertEqual(merged['personal_sources'],['MDBList','Trakt'])
        ranked=engine.rank([merged],[engine.initial_state()['profiles']['household']],dict(minutes=0))[0]
        self.assertTrue(ranked['saved'])

    def test_successful_personal_refresh_clears_removed_list_badge(self):
        old=media(1);old['personal_source']='MDBList / Trakt';old['personal_sources']=['MDBList','Trakt']
        plan=dict(provider='pov',queries=[dict(kind='movie',anchor=None,personal='mdblist')],
                  anchors=[],cursor=0,popular=[],personal=[],sources=['mdblist'])
        out=catalog.collect(lambda raw:json.dumps({'result':{'files':[]}}),
                            plan,[old],clock=lambda:0)
        self.assertEqual(out['items'][0]['personal_source'],'Trakt')
        self.assertEqual(out['items'][0]['personal_sources'],['Trakt'])

    def test_paginated_personal_refresh_never_claims_later_items_were_removed(self):
        old=media(1);old['personal_source']='MDBList';old['personal_sources']=['MDBList']
        plan=dict(provider='pov',queries=[dict(kind='movie',anchor=None,personal='mdblist')],
                  anchors=[],cursor=0,popular=[],personal=[],sources=['mdblist'])
        next_page='plugin://plugin.video.pov/?mode=build_movie_list&action=mdblist_watchlist&new_page=2'
        rpc=lambda raw:json.dumps({'result':{'files':[dict(file=next_page,label='Next page')]}})
        out=catalog.collect(rpc,plan,[old],clock=lambda:0)
        self.assertEqual(out['items'][0]['personal_sources'],['MDBList'])

    def test_discovery_reserves_first_refresh_for_personal_lists_and_stays_capped(self):
        state=engine.initial_state();planned=discovery.plan(state,['movie:1','tvshow:2'],'pov',personal_sources=['mdblist','trakt'])
        self.assertLessEqual(len(planned['queries']),4)
        self.assertEqual([(q.get('personal'),q['kind']) for q in planned['queries'][:2]],
                         [('mdblist','movie'),('mdblist','tvshow')])
        advanced=discovery.advance(planned,[0,1])
        state['discovery']={'pov':advanced}
        second=discovery.plan(state,['movie:1','tvshow:2'],'pov',personal_sources=['mdblist','trakt'])
        self.assertEqual([(q.get('personal'),q['kind']) for q in second['queries'][:2]],
                         [('trakt','movie'),('trakt','tvshow')])
        refreshed=discovery.plan(state,['movie:1','tvshow:2'],'pov',
            personal_sources=['mdblist','trakt'],refresh_personal=True)
        self.assertEqual([(q.get('personal'),q['kind']) for q in refreshed['queries']],
                         [('mdblist','movie'),('mdblist','tvshow'),
                          (None,'movie'),(None,'tvshow')])
        rotated=discovery.advance(refreshed,range(4));state['discovery']={'pov':rotated}
        next_refresh=discovery.plan(state,['movie:1','tvshow:2'],'pov',
            personal_sources=['mdblist','trakt'],refresh_personal=True)
        self.assertEqual([(q.get('personal'),q['kind']) for q in next_refresh['queries'][:2]],
                         [('trakt','movie'),('trakt','tvshow')])
        existing=engine.initial_state();existing['catalog']=[media()]
        first_upgrade=discovery.plan(existing,['movie:1'],'pov',
            personal_sources=['mdblist','trakt'])
        self.assertEqual([(q.get('personal'),q['kind']) for q in first_upgrade['queries']],
                         [('mdblist','movie'),('mdblist','tvshow'),
                          ('trakt','movie'),('trakt','tvshow')])
        storage.validate(state)

    def test_connected_personal_lists_force_one_automatic_refresh(self):
        state=engine.initial_state()
        self.assertTrue(ui._personal_refresh_needed(state,'pov',['mdblist']))
        state['discovery']={'pov':dict(anchors=[],cursor=0,popular=[],
            personal=['mdblist:movie','mdblist:tvshow'],sources=['mdblist'])}
        self.assertFalse(ui._personal_refresh_needed(state,'pov',['mdblist']))
        self.assertTrue(ui._personal_refresh_needed(state,'pov',['mdblist','trakt']))

    def test_undo_restore_is_not_recorded_as_a_new_action(self):
        state=engine.initial_state();changed=engine.feedback(state,'household',media(),'like')
        undo=[engine.checkpoint(state)]
        restored,playing,remember=ui._rich_more(
            Dialog(4),None,None,'',changed,None,[],undo)
        self.assertFalse(playing);self.assertFalse(remember);self.assertEqual(undo,[])
        self.assertEqual(engine.checkpoint(restored),engine.checkpoint(state))

    def test_card_copy_is_short_personal_and_truthful(self):
        item=media();item['personal_source']='MDBList'
        view=experience.card(dict(item=item,lane='מהשמורים שלך',reasons=[]),[item],[])
        self.assertEqual(view['role'],'מהרשימה שלך');self.assertIn('MDBList',view['reason'])
        self.assertLess(len(view['reason']),80)

    def test_card_explains_active_mode_then_automatic_taste_before_one_like(self):
        item=media(1,('Comedy',))
        row=dict(item=item,lane='קרוב לטעם שלך',reasons=[
            'קרוב לטעם שלך','קשר ז׳אנרי ל־One שסימנת באהבתי — זו הערכה ראשונית',
            'מתאים לדפוס שחוזר בצפייה','כיוון קומי או משפחתי יותר לפי סיווג הקטלוג'])
        self.assertEqual(experience.card(row)['reason'],'מתאים לערב הקליל שבחרת')
        row['reasons']=row['reasons'][:-1]
        self.assertEqual(experience.card(row)['reason'],
                         'מתאים לדפוסים שחוזרים בצפייה וברשימות שלך')

    def test_hub_ok_plays_selected_card_and_mode_click_returns_preset(self):
        gui=types.SimpleNamespace(WindowXMLDialog=Window,ListItem=Item)
        state=engine.initial_state();candidate=media();state['catalog']=[candidate]
        picks=[dict(item=candidate,lane='בחירה מהקטלוג',reasons=['בחירה מהקטלוג'])]
        watched=dict(keys=[],seed_keys=[])
        Window.click=100;Window.position=0
        self.assertEqual(hub.show(None,gui,'x',picks,state,'pov',watched),('play',0))
        Window.click=110
        self.assertEqual(hub.show(None,gui,'x',picks,state,'pov',watched),('mode','light'))
        Window.click=207;Window.position=0
        self.assertEqual(hub.show(None,gui,'x',picks,state,'pov',watched),('more',0))
        Window.click=205
        self.assertEqual(hub.show(None,gui,'x',picks,state,'pov',watched),('similar',0))

    def test_xml_has_unique_controls_and_no_skin_specific_dependencies(self):
        path=ROOT/'addons/service.subtitles.kodipovilai/resources/skins/Default/1080i/script.moransubs.tonight.xml'
        root=ET.parse(path).getroot();ids=[c.attrib['id'] for c in root.iter('control') if 'id' in c.attrib]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue({'100','110','200','201','202','203','204','205','206','207','209'}<=set(ids))
        text=path.read_text(encoding='utf-8')
        self.assertNotIn('skin.',text);self.assertNotIn('גרסת התנסות',text)
        self.assertIn('עוד בכיוון הזה',text)
        self.assertIn('resources/media/tonight.png',text)
        hub_text=(ROOT/'addons/service.subtitles.kodipovilai/resources/lib/tonight/hub.py').read_text(encoding='utf-8')
        self.assertIn('OK לצפייה',hub_text);self.assertNotIn('✓',hub_text)
        self.assertIn('CurrentItem',text);self.assertIn('NumItems',text)

    def test_dedicated_tile_icon_exists_and_all_entrypoints_use_it(self):
        icon=ROOT/'addons/service.subtitles.kodipovilai/resources/media/tonight.png'
        self.assertGreater(icon.stat().st_size,10000)
        self.assertTrue(entrypoints.ICON.endswith('/resources/media/tonight.png'))
        self.assertEqual(af3_home_patcher.HOME_SUBMENU[0]['icon'],entrypoints.ICON)


if __name__=='__main__':unittest.main()
