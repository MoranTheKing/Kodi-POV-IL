import os
import pkgutil
import importlib.util

def enabled_settings(settings):
    """Preserve explicitly enabled installed providers across host whitelists."""
    result = list(settings)
    if result == ['provider.aiostreams']:
        return result
    try:
        from modules import kodi_utils
        base = kodi_utils.translate_path('special://home/addons/plugin.video.pov/resources/lib/')
        for folder in ('debrids', 'scrapers'):
            for _, name, is_pkg in pkgutil.iter_modules([os.path.join(base, folder)]):
                key = 'provider.' + name
                if not is_pkg and key not in result and kodi_utils.get_setting(key) == 'true':
                    result.append(key)
    except Exception:
        pass
    return result

def run(scraper_proc, native_source_path, append_func, prescrape):
    """
    Safely pre-loads legacy scrapers into POV's active pool prior to native execution.
    """
    try:
        from modules import kodi_utils
        
        pov_addon_id = 'plugin.video.pov'
        legacy_rel = 'resources/lib/scrapers'
        legacy_dir = kodi_utils.translate_path(f'special://home/addons/{pov_addon_id}/{legacy_rel}/')
        
        # 1. Ensure the legacy directory exists to prevent ENOENT for 3rd party installers
        if not os.path.isdir(legacy_dir):
            os.makedirs(legacy_dir, exist_ok=True)
        
        init_file = os.path.join(legacy_dir, '__init__.py')
        if not os.path.isfile(init_file):
            with open(init_file, 'w', encoding='utf-8') as fh:
                fh.write('')
                
        # 2. Pre-calculate native modules for deduplication (POV gets priority)
        native_modules = {name for _, name, _ in pkgutil.iter_modules([native_source_path])}
        
        # 3. Scan and load legacy modules
        for loader, module_name, is_pkg in pkgutil.iter_modules([legacy_dir]):
            if is_pkg:
                continue
            
            # Deduplicate: POV native folder wins
            if module_name in native_modules:
                continue
                
            if module_name not in scraper_proc.source.active_internal_scrapers:
                continue
            
            # Pre-scrape verification
            if prescrape:
                from modules.settings import check_prescrape_sources
                if not check_prescrape_sources(module_name, scraper_proc.source.mediatype):
                    continue
                    
            # 4. Safe import bypassing the hardcoded `package='debrids'`
            try:
                _spec = loader.find_spec(module_name)
                if _spec is None:
                    continue
                
                _mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                module_source = _mod.source
                
                # Push into POV's active list
                append_func(('internal', module_source, module_name))
            except Exception as e:
                kodi_utils.logger('POV_WIZARD', f'Error Loading Legacy Module "{module_name}": {e}')
                
    except Exception as e:
        # Failsafe: Catch all exceptions to guarantee the native loop executes uninterrupted
        try:
            from modules import kodi_utils
            kodi_utils.logger('POV_WIZARD', f'Critical failure in legacy scraper run: {e}')
        except Exception:
            pass