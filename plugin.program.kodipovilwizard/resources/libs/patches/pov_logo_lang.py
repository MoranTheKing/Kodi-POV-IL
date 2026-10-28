"""Clear logos in the build's language.

POV shows Hebrew posters (TMDb images in the meta language come first) but
took the first logo TMDb listed, which is usually the English one. pick()
prefers a logo in the meta language and marks it (?lang=he; TMDb's image
server ignores the query). Any skin gets the Hebrew logo when one exists.

for_ui() fills the extra art key povil_logo, which the Onyx skin shows in
place of the title: the logo only when it suits a Hebrew screen, i.e. it is
in the meta language, or the title itself is not Hebrew (an English logo for
an untranslated title). Otherwise the skin writes the Hebrew title.
"""
HEBREW = (chr(0x0590), chr(0x05FF))


def _hebrew(text):
    return any(HEBREW[0] <= ch <= HEBREW[1] for ch in text or '')


def pick(data, lang, path):
    """The logo for TmdbParser.get_image('logo', path)."""
    code = (lang or '').split('-')[0].lower()
    if not code or code == 'en':
        return path
    try:
        for logo in (data.get('images') or {}).get('logos') or []:
            file_path = logo.get('file_path') or ''
            if logo.get('iso_639_1') == code and file_path.endswith('.png'):
                return file_path + '?lang=' + code
    except Exception:
        pass
    return path


def for_ui(meta, clearlogo):
    """The povil_logo art of a list item."""
    if not clearlogo:
        return ''
    if '?lang=' in clearlogo and not clearlogo.endswith('?lang=en'):
        return clearlogo
    title = meta.get('tvshowtitle') or meta.get('title') or ''
    return '' if _hebrew(title) else clearlogo
