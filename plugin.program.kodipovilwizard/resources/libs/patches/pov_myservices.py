# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_myservices.py
"""
POV MyServices Patch
--------------------
Replaces the native POV authorization UI with a centralized Account Manager
(script.module.acctmgr) interface and custom add-on integrations.
"""

import sys
import xbmc
import xbmcaddon

# Addon IDs
ACCOUNT_MANAGER_ID = 'script.module.acctmgr'
SUBTITLES_ADDON_ID = 'service.subtitles.kodipovilai'

# UI Dialog Labels
DIALOG_TITLE = 'חיבור שירותים'
LABEL_CONNECTED_ALL = 'מחובר ✓ · מסונכרן לכל התוספים'
LABEL_DISCONNECTED_ALL = 'לא מחובר · לחץ לחיבור בכל התוספים'
LABEL_CONNECTED_POV_ONLY = 'מחובר ל-POV בלבד · לחץ לחיבור בכל התוספים'
LABEL_CONNECTED_POV = 'מחובר ✓ · לחץ לניהול'
LABEL_DISCONNECTED_POV = 'לא מחובר · לחץ לחיבור'
LABEL_ADVANCED_POV_ONLY = 'חיבור ל-POV בלבד (מתקדם)'
LABEL_ADVANCED_POV_SUB = 'התפריט המקורי של POV, ללא סנכרון לשאר התוספים'


def get_subtitles_addon():
    """Returns the Kodi POV IL AI subtitles addon instance if installed."""
    try:
        return xbmcaddon.Addon(SUBTITLES_ADDON_ID)
    except Exception:
        return None


def get_account_manager_addon():
    """Returns the Account Manager addon instance if installed."""
    try:
        return xbmcaddon.Addon(ACCOUNT_MANAGER_ID)
    except Exception:
        return None


def get_authorize_override(orig_authorize):
    """
    Returns the replacement authorize function.
    Captures orig_authorize in a closure to allow fallback to native POV UI.
    """

    def authorize_wrapper():
        # Lazy load Kodi utilities and POV's internal myservices module
        from modules import kodi_utils
        pov_myservices_mod = sys.modules.get('modules.myservices')

        def run_account_manager(action):
            """Executes a specific action script within Account Manager."""
            try:
                xbmc.executebuiltin('RunScript(%s,action=%s)' % (ACCOUNT_MANAGER_ID, action))
                return True
            except Exception as e:
                kodi_utils.notification('Account Manager failed to start: %s' % str(e)[:60])
                return False

        class GeminiService:
            """Handler for Gemini AI Subtitles integration."""
            icon = 'gemini.png'

            def __init__(self):
                self.addon = get_subtitles_addon()
                try:
                    v = self.addon.getSetting('api_key') if self.addon else ''
                except Exception:
                    v = ''
                self.token = (v or '').strip()

            def set(self):
                """Launches Gemini setup action via subtitles addon."""
                if not self.addon:
                    kodi_utils.notification('Kodi POV IL AI subtitles addon not installed')
                    return False
                try:
                    xbmc.executebuiltin('RunScript(%s,action=connect_gemini)' % SUBTITLES_ADDON_ID)
                    return True
                except Exception as e:
                    kodi_utils.notification('Failed to launch Gemini setup: %s' % str(e)[:60])
                    return False

        class MDBListService:
            """Use the QR/typed-key flow, then mirror the verified key to AM."""
            icon = 'mdblist.png'

            def __init__(self):
                try:
                    pov = xbmcaddon.Addon('plugin.video.pov')
                    self.token = (pov.getSetting('mdblist.token') or '').strip()
                except Exception:
                    self.token = ''

            def label2(self):
                return LABEL_CONNECTED_POV if self.token else LABEL_DISCONNECTED_POV

            def set(self):
                if not get_subtitles_addon():
                    kodi_utils.notification('Kodi POV IL AI subtitles addon not installed')
                    return False
                try:
                    xbmc.executebuiltin(
                        'RunScript(%s,action=connect_mdblist)' % SUBTITLES_ADDON_ID)
                    return True
                except Exception as exc:
                    kodi_utils.notification('MDBList setup failed: %s' % str(exc)[:60])
                    return False

        def get_pov_service_class(names):
            """Retrieves a service class from POV's native myservices module."""
            for name in (names or ()):
                cls = getattr(pov_myservices_mod, name, None)
                if cls:
                    return cls
            return None

        def get_pov_service_token(names):
            """Retrieves the active token string for a service directly from POV."""
            cls = get_pov_service_class(names)
            if cls is None:
                return ''
            try:
                return cls().token or ''
            except Exception:
                return ''

        def create_am_service_class(prefix, icon_name, keys, title, pov_names):
            """Factory that generates wrapper classes for Account Manager services."""

            class AccountManagerService(object):
                icon = icon_name

                def __init__(self):
                    self.token = ''
                    self.pov_token = ''
                    am = get_account_manager_addon()
                    if am is not None:
                        try:
                            vals = [(am.getSetting(k) or '').strip() for k in keys]
                        except Exception:
                            vals = []
                        if vals and all(vals):
                            self.token = ''.join(vals)
                    if not self.token:
                        self.pov_token = get_pov_service_token(pov_names)

                def label2(self):
                    """Returns the status string shown in the Kodi UI list item."""
                    if self.token:
                        return LABEL_CONNECTED_ALL
                    if self.pov_token:
                        return LABEL_CONNECTED_POV_ONLY
                    return LABEL_DISCONNECTED_ALL

                def set(self):
                    """Handles user interaction: Authorize, ReSync, or Revoke service."""
                    if get_account_manager_addon() is None:
                        kodi_utils.notification('Account Manager is not installed')
                        return False
                    if not self.token:
                        return run_account_manager(prefix + 'Auth')

                    choice = kodi_utils.dialog.select(title, [
                        'סנכרון החשבון לכל התוספים',
                        'ניתוק החשבון מכל התוספים'
                    ])
                    if choice < 0:
                        return None

                    action = 'ReSync' if choice == 0 else 'Revoke'
                    return run_account_manager(prefix + action)

            return AccountManagerService

        class NativePovAuthOption:
            """Fallback entry allowing users to open original POV authorization menu."""
            icon = 'settings.png'

            def __init__(self):
                self.token = ''

            def set(self):
                return orig_authorize()

        # Table structure: (service_name, provider_type, icon, am_prefix, am_keys, pov_class_names)
        SERVICE_INTEGRATIONS = (
            ('trakt',         'pov',  'trakt.png',       None,        (),                                     ('Trakt',)),
            ('mdblist',       'ours', 'mdblist.png',     None,        (),                                     ('MDBList',)),
            ('tmdblist',      'pov',  'tmdb.png',        None,        (),                                     ('TMDBList', 'TMDbList')),
            ('real-debrid',   'am',   'realdebrid.png',  'realdebrid',('realdebrid.token',),                  ('RealDebrid',)),
            ('premiumize.me', 'am',   'premiumize.png',  'premiumize',('premiumize.token',),                  ('Premiumize',)),
            ('alldebrid',     'am',   'alldebrid.png',   'alldebrid', ('alldebrid.token',),                   ('AllDebrid',)),
            ('torbox',        'am',   'torbox.png',      'torbox',    ('torbox.token',),                      ('TorBox',)),
            ('offcloud',      'am',   'offcloud.png',    'offcloud',  ('offcloud.token',),                    ('Offcloud',)),
            ('easydebrid',    'pov',  'easydebrid.png',  None,        (),                                     ('EasyDebrid',)),
            ('easynews',      'am',   'easynews.png',    'easynews',  ('easynews.username', 'easynews.password'), ('EasyNews',)),
            ('gemini-ai',     'ours', 'gemini.png',      None,        (),                                     None),
        )

        custom_services = {'gemini-ai': GeminiService,
                           'mdblist': MDBListService}
        am_available = get_account_manager_addon() is not None

        available_services = []
        for name, kind, icon, pfx, keys, pov_names in SERVICE_INTEGRATIONS:
            if kind == 'ours':
                cls_ours = custom_services.get(name)
                if cls_ours is not None:
                    available_services.append((name, cls_ours))
                continue

            if kind == 'am' and am_available:
                service_cls = create_am_service_class(pfx, icon, keys, name.upper(), pov_names)
                available_services.append((name, service_cls))
                continue

            # Fallback to POV's native class if AM is unavailable or not used
            pov_cls = get_pov_service_class(pov_names)
            if pov_cls is not None:
                available_services.append((name, pov_cls))

        if am_available:
            available_services.append((LABEL_ADVANCED_POV_ONLY, NativePovAuthOption))

        def build_dialog_items():
            """Yields list items configured for Kodi's select dialog."""
            icon_path = kodi_utils.media_path()
            for name, service_cls in services:
                item = kodi_utils.make_listitem()
                item.setLabel(name.upper())

                try:
                    inst = service_cls()
                except Exception:
                    inst = None

                if inst is None:
                    subtitle = ''
                elif service_cls is NativePovAuthOption:
                    subtitle = LABEL_ADVANCED_POV_SUB
                elif hasattr(inst, 'label2'):
                    subtitle = inst.label2()
                else:
                    subtitle = LABEL_CONNECTED_POV if getattr(inst, 'token', None) else LABEL_DISCONNECTED_POV

                item.setLabel2(subtitle)
                item.setArt({'icon': '%s%s' % (icon_path, service_cls.icon)})
                yield item

        services = tuple(available_services)
        selected_index = kodi_utils.dialog.select(DIALOG_TITLE, list(build_dialog_items()), useDetails=True)
        if selected_index < 0:
            return None

        try:
            return services[selected_index][1]().set()
        except Exception as e:
            kodi_utils.logger('myservices error', str(e))
            return None

    return authorize_wrapper
