"""Profile cards backed by Kodi's native profile creation, locks and loader."""
import json
import os
import time
import xml.etree.ElementTree as ET
import zipfile

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.libs import profile_store
from resources.libs.patches import profile_age_guard

WIZARD = 'plugin.program.kodipovilwizard'
SKINS = (('skin.povil.nox', 'NOX'), ('skin.fentastic', 'FENtastic'),
         ('skin.estuary', 'Estuary'), ('skin.arctic.fuse.3', 'Arctic Fuse 3'))


def _rpc(method, params=None):
    request = dict(jsonrpc='2.0', id=1, method=method)
    if params is not None:
        request['params'] = params
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    if 'error' in reply or 'result' not in reply:
        raise RuntimeError('Profile API failed: ' + method)
    return reply['result']


def _master_path():
    return xbmcvfs.translatePath('special://masterprofile/')


def is_master():
    # JSON-RPC returns a label, not a stable id. Native paths distinguish the
    # master even if someone creates another profile with the same name.
    return (os.path.normcase(os.path.realpath(xbmcvfs.translatePath('special://profile/'))) ==
            os.path.normcase(os.path.realpath(_master_path())))


def _require_master():
    if not is_master():
        xbmcgui.Dialog().ok('פרופילים', 'רק המשתמש הראשי יכול להוסיף ולנהל פרופילים.')
        return False
    return True


def _seed(profile):
    archive = os.path.join(xbmcaddon.Addon(WIZARD).getAddonInfo('path'),
                           'resources', 'bootstrap', 'config.zip')
    return profile_store.seed_profile(_master_path(), profile, archive)


def repair_active():
    """Repair a native-created secondary profile before fresh-install gating."""
    if is_master():
        return
    active = os.path.realpath(xbmcvfs.translatePath('special://profile/'))
    for profile in profile_store.registered_profiles(_master_path()):
        try:
            target = profile_store.profile_path(_master_path(), profile)
        except ValueError:
            continue
        if profile['id'] == 0 or target != active:
            continue
        was_ready = os.path.isfile(os.path.join(active, 'kodipovil.profile_addons_ready'))
        _seed(profile)
        if not was_ready:
            # Addon settings may have been cached before the missing file was
            # seeded. Apply the small wizard bootstrap through Kodi's API.
            addon = xbmcaddon.Addon(WIZARD)
            root = ET.parse(os.path.join(active, 'addon_data', WIZARD, 'settings.xml')).getroot()
            for item in root.findall('setting'):
                if item.get('id') in ('buildname', 'buildversion', 'installed',
                                      'config_applied_version', 'build_skin_switch_notifcation_dismiss'):
                    addon.setSetting(item.get('id'), item.text or '')
        return


def install_login_hooks():
    """Add a no-op-unless-sole-master hook to installed build login screens.

    The owned NOX skin ships it directly. Other installed skins receive the
    same small additive XML hook, without replacing their custom layout.
    Built-in/read-only skins are left to the post-login settings repair.
    """
    import re
    import tempfile
    addons = xbmcvfs.translatePath('special://home/addons/')
    hook = '<onload>RunScript(special://home/addons/plugin.program.kodipovilwizard/single_profile_login.py)</onload>'
    for ident, _label in SKINS:
        for folder in ('xml', '1080i', '720p'):
            path = os.path.join(addons, ident, folder, 'Home.xml')
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding='utf-8-sig') as source:
                    text = source.read()
                if 'profile_bootstrap.py' not in text:
                    bootstrap = '<onload>RunScript(special://home/addons/plugin.program.kodipovilwizard/profile_bootstrap.py)</onload>'
                    changed, count = re.subn(r'(<window(?:\s[^>]*)?>)', r'\1\n    ' + bootstrap, text, count=1)
                    if count == 1:
                        ET.fromstring(changed)
                        fd, temporary = tempfile.mkstemp(prefix='.povil-profile-', dir=os.path.dirname(path))
                        try:
                            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                                output.write(changed)
                            os.replace(temporary, path)
                        finally:
                            if os.path.exists(temporary):
                                os.unlink(temporary)
            except (OSError, ValueError, ET.ParseError):
                xbmc.log('[Profiles] startup hook deferred for ' + ident, xbmc.LOGWARNING)
        for folder in ('xml', '1080i', '720p'):
            path = os.path.join(addons, ident, folder, 'LoginScreen.xml')
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding='utf-8-sig') as source:
                    text = source.read()
                if 'single_profile_login.py' in text:
                    continue
                changed, count = re.subn(r'(<window(?:\s[^>]*)?>)', r'\1\n    ' + hook, text, count=1)
                if count != 1:
                    continue
                ET.fromstring(changed)
                fd, temporary = tempfile.mkstemp(prefix='.povil-login-', dir=os.path.dirname(path))
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as output:
                        output.write(changed)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            except (OSError, ValueError, ET.ParseError):
                xbmc.log('[Profiles] login hook deferred for ' + ident, xbmc.LOGWARNING)


def addon_enabled(ident):
    # System.HasAddon includes installed-but-disabled add-ons in Kodi 21.
    # The native Addons API exposes the actual profile-local enabled state.
    try:
        return _rpc('Addons.GetAddonDetails', dict(addonid=ident, properties=['enabled']))['addon']['enabled'] is True
    except (RuntimeError, KeyError, TypeError):
        return False


def prepare_first_login():
    """Register/enable installed build add-ons in the new profile's own DB.

    Kodi creates a separate Addons DB and initially disables third-party
    add-ons. Never copy the master's DB or undo an established user's choices.
    Dependencies are enabled before their consumers through Kodi's API.
    """
    if is_master():
        return True
    active = xbmcvfs.translatePath('special://profile/')
    receipt = os.path.join(active, 'kodipovil.profile_addons_ready')
    if os.path.isfile(receipt):
        return True
    required = (WIZARD, 'plugin.video.pov', 'skin.povil.nox',
                'script.fentastic.helper', 'service.subtitles.kodipovilai',
                'plugin.program.orderfavourites-hebrew')
    addons = xbmcvfs.translatePath('special://home/addons/')
    graph = {}
    for name in os.listdir(addons):
        manifest = os.path.join(addons, name, 'addon.xml')
        if not os.path.isfile(manifest):
            continue
        try:
            root = ET.parse(manifest).getroot()
            if root.get('id') != name:
                continue
            graph[name] = [row.get('addon') for row in root.findall('requires/import')
                           if row.get('optional') != 'true']
        except (OSError, ET.ParseError):
            continue
    # Enable the installed build and its dependency closure, not arbitrary
    # third-party services the master may have intentionally disabled.
    build_addons = ('script.module.acctmgr', 'plugin.video.umbrella',
                    'plugin.video.idanplus', 'plugin.video.youtube',
                    'plugin.video.themoviedb.helper', 'resource.language.he_il',
                    'skin.estuary', 'skin.fentastic', 'repository.kodipovil')
    required += tuple(ident for ident in build_addons if ident in graph)
    if all(addon_enabled(ident) for ident in required):
        profile_store.write_missing(active, 'kodipovil.profile_addons_ready', b'1')
        return True
    xbmc.executebuiltin('UpdateLocalAddons')
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(0.5):
        return False
    done, visiting = set(), set()
    def enable(ident):
        if ident in done or ident not in graph or ident in visiting:
            return
        visiting.add(ident)
        for dependency in graph[ident]:
            enable(dependency)
        visiting.remove(ident)
        try:
            if not addon_enabled(ident):
                _rpc('Addons.SetAddonEnabled', dict(addonid=ident, enabled=True))
        except RuntimeError:
            return  # failed dependencies can be retried on the next pass
        done.add(ident)
    for ident in required:
        enable(ident)
    for _ in range(15):
        if all(addon_enabled(ident) for ident in required):
            profile_store.write_missing(active, 'kodipovil.profile_addons_ready', b'1')
            return True
        for ident in required:
            done.discard(ident)
            enable(ident)
        if monitor.waitForAbort(0.5):
            return False
    return False


def _native_settings():
    monitor = xbmc.Monitor()
    # Dialog.ok/select return before their close animation releases Kodi's
    # modal window. ActivateWindow during that interval is silently refused.
    closing = time.monotonic() + 3
    while xbmcgui.getCurrentWindowDialogId() not in (0, 9999, 10000):
        if time.monotonic() >= closing or monitor.waitForAbort(0.1):
            return False
    xbmc.executebuiltin('ActivateWindow(10034)')
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if xbmc.getCondVisibility('Window.IsActive(10034)'):
            return True
        if monitor.waitForAbort(0.1):
            break
    return False


def repair_single_login():
    """Use Kodi's native toggle so its cached state and XML stay in agreement.

    Never bypass a master lock, playback, a setup dialog or explicit multi-user
    selection. Runs after Home is ready; next boot opens Home directly.
    """
    if (not is_master() or xbmc.getCondVisibility('Player.Playing') or
            not xbmc.getCondVisibility('System.HasLoginScreen') or
            not xbmc.getCondVisibility('Window.IsActive(home)') or
            xbmcgui.getCurrentWindowDialogId() not in (0, 9999, 10000)):
        return False
    if not profile_store.lone_unlocked(profile_store.registered_profiles(_master_path())):
        return False
    if not _native_settings():
        return False
    # Recheck after activation: user input may have changed the profile list.
    if (is_master() and profile_store.lone_unlocked(profile_store.registered_profiles(_master_path()))
            and xbmc.getCondVisibility('System.HasLoginScreen')):
        xbmc.executebuiltin('SendClick(10034,4)')
    xbmc.executebuiltin('ActivateWindow(home)')
    return True


def resume_single_login():
    """Enter a sole unlocked master through Kodi's normal profile loader."""
    if not is_master() or not xbmc.getCondVisibility('Window.IsActive(loginscreen)'):
        return False
    profiles = profile_store.registered_profiles(_master_path())
    if not profile_store.lone_unlocked(profiles):
        return False
    _rpc('Profiles.LoadProfile', dict(profile=profiles[0]['name'], prompt=True))
    return True


def choose_skin():
    if profile_age_guard.active_policy() is not None:
        xbmcgui.Dialog().ok('סקין הפרופיל', 'מסך הילדים מנוהל דרך בקרת ההורים במשתמש הראשי.')
        return
    if xbmc.getCondVisibility('Player.Playing'):
        xbmcgui.Dialog().ok('סקין הפרופיל', 'יש לעצור את הניגון לפני החלפת סקין.')
        return
    available = [(key, label) for key, label in SKINS
                 if xbmc.getCondVisibility('System.HasAddon({})'.format(key))]
    current = xbmc.getSkinDir()
    choice = xbmcgui.Dialog().select('הסקין של הפרופיל הזה', [v for _, v in available],
                                    preselect=next((i for i, (k, _) in enumerate(available) if k == current), 0))
    if choice < 0 or choice >= len(available) or available[choice][0] == current:
        return
    if not _wait_dialogs():
        return
    # Kodi owns the setting and its normal keep/revert confirmation. Do not
    # edit active guisettings.xml or terminate Kodi for a skin preference.
    from resources.libs import build_skin
    if not build_skin.switch(available[choice][0]):
        xbmcgui.Dialog().ok('סקין הפרופיל', 'לא ניתן להשלים את החלפת הסקין. נסה שוב דרך הוויזרד.')


def add_profile():
    if not _require_master():
        return
    master = _master_path()
    before = profile_store.registered_profiles(master)
    if not os.path.isfile(os.path.join(master, 'kodipovil.provisioned')):
        xbmcgui.Dialog().ok('פרופילים', 'יש להשלים קודם את התקנת הבילד במשתמש הראשי.')
        return
    kind = xbmcgui.Dialog().select('איזה פרופיל להוסיף?', ['פרופיל רגיל', 'פרופיל ילדים עם הגבלת גיל'])
    if kind < 0:
        return
    from resources.libs import profile_connections
    connections = profile_connections.choose(master)
    if connections is None:
        return
    xbmcgui.Dialog().ok('הוספת פרופיל',
        'בחר שם ושמור את הפרופיל בחלון שייפתח. אפשר להשאיר את תיקיית הפרופיל המוצעת.\n'
        'המועדפים והבילד יתווספו אוטומטית, יחד עם החיבורים שסימנת.')
    if not _native_settings():
        return
    # Nox and Estuary show the profile list only on the second left-hand
    # category. Focus that native category before trying to focus its list.
    xbmc.executebuiltin('SetFocus(9000,1,absolute)')
    if xbmc.Monitor().waitForAbort(0.2):
        return
    xbmc.executebuiltin('SetFocus(2,{},absolute)'.format(len(before)))
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(0.2):
        return
    if (not is_master() or not xbmc.getCondVisibility('Window.IsActive(10034)') or
            not xbmc.getCondVisibility('Control.HasFocus(2)') or
            xbmc.getInfoLabel('Container(2).CurrentItem') != str(len(before) + 1)):
        return
    # SendClick has no SELECT action code and cannot activate a native list
    # item. Action(Select) follows Kodi's actual add-profile path instead.
    xbmc.executebuiltin('Action(Select,10034)')
    deadline = time.monotonic() + 600
    saw_dialog = False
    started = time.monotonic()
    idle_since = None
    while not monitor.abortRequested() and time.monotonic() < deadline:
        after = profile_store.registered_profiles(master)
        new = [p for p in after if p['id'] not in {v['id'] for v in before}]
        dialog = xbmcgui.getCurrentWindowDialogId()
        if dialog not in (0, 9999, 10034, 10000):
            saw_dialog = True
            idle_since = None
        elif saw_dialog:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since > 0.8:
                if not new or not is_master():
                    return
                try:
                    _seed(new[0])
                    profile_connections.copy_selected(master, new[0], connections)
                except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
                    xbmcgui.Dialog().ok('פרופילים', 'לא ניתן להשלים את הפרופיל. חזור למשתמש הראשי ונסה שוב.')
                    return
                xbmc.executebuiltin('ActivateWindow(home)')
                if kind == 1:
                    from resources.libs import parental_profiles
                    # An unfinished child setup must never become an
                    # unrestricted profile merely because the parent cancels.
                    profile_store.write_missing(profile_store.profile_path(master, new[0]),
                                                profile_age_guard.CHILD_MARKER, b'1')
                    parental_profiles.setup(new[0])
                    policy = profile_age_guard.policy_for(master, profile_store.profile_path(master, new[0]))
                    if not policy or policy.get('blocked'):
                        xbmcgui.Dialog().ok('פרופיל ילדים', 'הפרופיל נוצר, אך הגבלת הגיל עדיין לא הושלמה. השלם את בקרת ההורים מהמשתמש הראשי לפני השימוש.')
                        return
                if xbmcgui.Dialog().yesno('הפרופיל מוכן', 'לעבור עכשיו לפרופיל החדש?'):
                    load_profile(new[0]['name'])
                return
        elif time.monotonic() - started > 3:
            return  # native creation was not opened (skin navigation/lock)
        if monitor.waitForAbort(0.2):
            return


def load_profile(name):
    profiles = _rpc('Profiles.GetProfiles', dict(properties=['thumbnail', 'lockmode']))['profiles']
    if name not in [p['label'] for p in profiles]:
        return
    if name == _rpc('Profiles.GetCurrentProfile')['label']:
        return
    if xbmc.getCondVisibility('Player.Playing') and not xbmcgui.Dialog().yesno(
            'החלפת פרופיל', 'הניגון ייעצר במעבר לפרופיל אחר. להמשיך?'):
        return
    # Seed only as master, before target startup loads addon settings/favourites.
    if is_master():
        for profile in profile_store.registered_profiles(_master_path()):
            if profile['name'] == name and profile['id'] != 0:
                try:
                    profile_store.profile_path(_master_path(), profile)
                except ValueError:
                    break  # native external profiles remain usable as-is
                _seed(profile)
                break
    if not _wait_dialogs():
        return
    from resources.libs import build_skin
    if not build_skin.persist_live_settings():
        xbmcgui.Dialog().notification('החלפת פרופיל', 'שמירת ההגדרות לא הושלמה. נסה שוב.')
        return
    _rpc('Profiles.LoadProfile', dict(profile=name, prompt=True))
    # Profiles.LoadProfile posts a native GUI message. Return immediately:
    # waiting here races Kodi's shutdown of the departing Python services.
    # The skin's bootstrap hook enables startup in the destination profile.


def _wait_dialogs():
    monitor = xbmc.Monitor()
    deadline = time.monotonic() + 3
    while xbmcgui.getCurrentWindowDialogId() not in (0, 9999, 10000):
        if time.monotonic() >= deadline or monitor.waitForAbort(0.1):
            return False
    return True


def open_child_content(kind):
    import xbmcvfs
    policy = profile_age_guard.active_policy()
    if policy is None:
        return
    if policy.get('blocked') or not profile_age_guard.host_integrity(xbmcvfs.translatePath('special://home/addons/')):
        xbmcgui.Dialog().ok('פרופיל ילדים', 'הסינון אינו מוכן. עבור למשתמש הראשי להשלמת העדכון או הגדרות הנעילה.')
        return
    routes = {
        'movie': 'mode=build_movie_list&action=tmdb_movies_genres&genre_id=10751&name=סרטים',
        'tv': 'mode=build_tvshow_list&action=tmdb_tv_genres&genre_id=10762&name=סדרות'}
    if kind == 'search':
        choice = xbmcgui.Dialog().select('מה לחפש?', ['סרט', 'סדרה'])
        if choice < 0:
            return
        routes['search'] = 'mode=get_search_term&mediatype=' + ('movie', 'tvshow')[choice]
    if kind not in routes or not _wait_dialogs():
        return
    xbmc.executebuiltin('ActivateWindow(10025,"plugin://plugin.video.pov/?{}",return)'.format(routes[kind]))


class ProfileCards(xbmcgui.WindowXMLDialog):
    def onInit(self):
        current = _rpc('Profiles.GetCurrentProfile')['label']
        self.profiles = _rpc('Profiles.GetProfiles', dict(properties=['thumbnail', 'lockmode']))['profiles']
        self.setProperty('master', 'true' if is_master() else 'false')
        self.setProperty('current', current)
        self.setProperty('child', 'true' if profile_age_guard.active_policy() is not None else 'false')
        items = []
        for profile in self.profiles:
            item = xbmcgui.ListItem(label=profile['label'])
            item.setArt({'thumb': profile.get('thumbnail') or 'DefaultUser.png'})
            item.setProperty('status', 'הפרופיל הפעיל' if profile['label'] == current else 'לחץ למעבר')
            items.append(item)
        self.getControl(100).addItems(items)
        self.getControl(100).selectItem(next((i for i, p in enumerate(self.profiles) if p['label'] == current), 0))
        self.setFocusId(100)

    def onClick(self, control):
        if control == 100:
            self.result = ('load', self.profiles[self.getControl(100).getSelectedPosition()]['label'])
        elif control == 201:
            self.result = ('add', None)
        elif control == 202:
            self.result = ('settings', None)
        elif control == 203:
            self.result = ('native', None)
        elif control == 205:
            self.result = ('parental', None)
        elif control != 204:
            return
        self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 92):
            self.close()


def show():
    home = xbmcgui.Window(10000)
    if home.getProperty('POVIL.ProfilesBusy'):
        return
    home.setProperty('POVIL.ProfilesBusy', 'true')
    try:
        addon = xbmcaddon.Addon(WIZARD)
        dialog = ProfileCards('Profiles.xml', addon.getAddonInfo('path'), 'Default', '1080i')
        dialog.result = None
        dialog.doModal()
        result = dialog.result
        del dialog
        if xbmc.Monitor().waitForAbort(0.2) or not result:
            return
        action, name = result
        if action == 'load':
            load_profile(name)
        elif action == 'add':
            add_profile()
        elif action == 'native' and _require_master():
            _native_settings()
        elif action == 'parental':
            from resources.libs import parental_profiles
            parental_profiles.setup()
        elif action == 'settings':
            if profile_age_guard.active_policy() is not None:
                return
            choice = xbmcgui.Dialog().select('הפרופיל הזה', ['בחירת סקין', 'חיבור שירותים', 'הגדרות כתוביות'])
            if choice == 0:
                choose_skin()
            elif choice == 1:
                xbmc.executebuiltin('RunPlugin(plugin://plugin.video.pov/?mode=myservices)')
            elif choice == 2:
                xbmcaddon.Addon('service.subtitles.kodipovilai').openSettings()
    except Exception as exc:
        xbmc.log('[Profiles] operation failed: {}'.format(type(exc).__name__), xbmc.LOGERROR)
        xbmcgui.Dialog().ok('פרופילים', 'לא ניתן להשלים את הפעולה. אפשר לשלוח לוג דרך הוויזרד.')
    finally:
        home.clearProperty('POVIL.ProfilesBusy')
