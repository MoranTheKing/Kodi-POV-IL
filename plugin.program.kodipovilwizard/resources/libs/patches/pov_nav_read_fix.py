# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_nav_read_fix.py

import ast
import types
import xbmc

def run(navigator_cache_instance):
    """
    Shadows the jsloads method on the instantiated navigator_cache singleton.
    Provides a safe fallback to ast.literal_eval for legacy Python repr() formatted DB rows.
    """
    try:
        if not hasattr(navigator_cache_instance, 'jsloads'):
            return

        # Capture the original bound method
        original_jsloads = navigator_cache_instance.jsloads

        def safe_jsloads(self, raw):
            try:
                # 1. Attempt standard JSON load (native upstream behavior)
                return original_jsloads(raw)
            except Exception:
                # Catch failures caused by repr() formatted single quotes in SQLite
                pass

            try:
                # 2. Fallback to literal evaluation
                obj = ast.literal_eval(raw)

                # 3. Guard: Raising ensures upstream except blocks correctly handle corrupt records
                if not isinstance(obj, (list, dict)):
                    raise ValueError("Evaluated literal is not a valid menu container")

                return obj
            except Exception as e:
                # If everything fails, re-raise to maintain upstream error handling flows
                raise e

        # Bind the wrapped interceptor directly to the instance, shadowing the base class method
        navigator_cache_instance.jsloads = types.MethodType(safe_jsloads, navigator_cache_instance)

        xbmc.log("[WIZARD] POV Navigator Read Fix applied successfully (jsloads shadowed)", xbmc.LOGINFO)

    except Exception as e:
        xbmc.log(f"[WIZARD] POV Navigator Read Fix failed during injection: {e}", xbmc.LOGERROR)