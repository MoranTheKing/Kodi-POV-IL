# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_combined_discover.py

import xbmc
from urllib.parse import quote_plus
from indexers.tmdb_api import base_url, get_tmdb, EXPIRES_4_HOURS
from caches.main_cache import cache_object

def _build_url(endpoint):
    """
    Safely builds the TMDB API URL.
    Handles POV >= 6.08 updates where '/3' was removed from the core base_url.
    """
    # The new shared-session client accepts paths; the previous client
    # accepted full URLs. Use its loaded module, never a second namespace.
    import indexers.tmdb_api as tmdb
    if hasattr(tmdb, 'get_tmdb') and 'requests' not in tmdb.__dict__:
        return '/3' + endpoint
    api_base = base_url if base_url.endswith('/3') else f"{base_url}/3"
    return f"{api_base}{endpoint}"

def tmdb_search_multi(query, page_no=1):
    """Fetches combined search results (Movies & TV), utilizing POV's native cache."""
    string = f'tmdb_search_multi_{query}_{page_no}'
    url = _build_url(f'/search/multi?language=en-US&query={quote_plus(query)}&page={page_no}')
    
    data = cache_object(get_tmdb, string, url, expiration=EXPIRES_4_HOURS)
    try:
        results = data.get('results', [])
    except Exception:
        results = []
        
    return [i for i in results if i.get('media_type') in ('movie', 'tv')]

def tmdb_trending_all(page_no=1):
    """Fetches combined trending results (Movies & TV), utilizing POV's native cache."""
    string = f'tmdb_trending_all_{page_no}'
    url = _build_url(f'/trending/all/week?language=en-US&page={page_no}')
    
    data = cache_object(get_tmdb, string, url, expiration=EXPIRES_4_HOURS)
    try:
        results = data.get('results', [])
    except Exception:
        results = []
        
    return [i for i in results if i.get('media_type') in ('movie', 'tv')]

def handle_fetch(params):
    """
    Evaluates the list builder parameters. If a unified discover action is requested,
    routes the data fetch through the custom TMDB handlers. Otherwise returns None 
    so upstream POV logic can handle standard list requests normally.
    """
    try:
        if not isinstance(params, dict):
            return None
#
#         # Early check against centralized Visibility Manager
#         try:
#             import pov_visibility_mgr
#             if not pov_visibility_mgr.is_service_active('tmdb'):
#                 return None
#         except Exception:
#             pass

        action = params.get('action')
        query = (params.get('query') or '').strip()
        
        if action == 'search_multi':
            if query:
                xbmc.log(f"[POV Wizard] Unified Discover routing to Search Multi (Query: {query})", xbmc.LOGINFO)
                return tmdb_search_multi(query)
            else:
                xbmc.log("[POV Wizard] Unified Discover routing to Trending All (Empty Query)", xbmc.LOGINFO)
                return tmdb_trending_all()
                
        elif action == 'trending_all':
            xbmc.log("[POV Wizard] Unified Discover routing to Trending All (Direct)", xbmc.LOGINFO)
            return tmdb_trending_all()
            
        return None
    except Exception as e:
        xbmc.log(f"[POV Wizard] ERROR (handle_fetch): {e}", xbmc.LOGERROR)
        return None