# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_translations.py

try:
    from resources.libs.common.logging import log_info, log_error
except ImportError:
    import xbmc
    def log_info(msg):
        xbmc.log(f"POV Translations: {msg}", xbmc.LOGINFO)
    def log_error(msg):
        xbmc.log(f"POV Translations Error: {msg}", xbmc.LOGERROR)

# Mapping of TMDB Genre IDs to localized Hebrew labels.
GENRE_HE = {
    '28': 'אקשן',
    '12': 'הרפתקאות',
    '16': 'אנימציה',
    '35': 'קומדיה',
    '80': 'פשע',
    '99': 'דוקומנטרי',
    '18': 'דרמה',
    '10751': 'משפחה',
    '14': 'פנטזיה',
    '36': 'היסטוריה',
    '27': 'אימה',
    '10402': 'מוזיקה',
    '9648': 'מסתורין',
    '10749': 'רומנטיקה',
    '878': 'מדע בדיוני',
    '10770': 'סרט טלוויזיה',
    '53': 'מתח',
    '10752': 'מלחמה',
    '37': 'מערבון',
    '10759': 'אקשן והרפתקאות',
    '10762': 'ילדים',
    '10763': 'חדשות',
    '10764': 'ריאליטי',
    '10765': 'מדע בדיוני ופנטזיה',
    '10766': 'אופרת סבון',
    '10767': 'אירוח',
    '10768': 'מלחמה ופוליטיקה',
}

def translate_genres(genre_dict):
    """
    Takes the upstream genre dictionary (e.g., meta_lists.movie_genres)
    and returns a new dictionary with English keys translated to Hebrew
    based on their underlying TMDB ID, leaving the values perfectly intact.
    This safely translates the UI without modifying core logic.
    """
    try:
        translated = {}
        for eng_key, val in genre_dict.items():
            # Validate expected upstream format: ['tmdb_id', 'icon_name.png']
            if not isinstance(val, (list, tuple)) or len(val) == 0:
                translated[eng_key] = val
                continue

            tmdb_id = str(val[0])
            heb_key = GENRE_HE.get(tmdb_id, eng_key)
            translated[heb_key] = val

        return translated
    except Exception as e:
        log_error(f"Failed to translate genres in-memory: {e}")
        return genre_dict  # Clean fallback to original dictionary