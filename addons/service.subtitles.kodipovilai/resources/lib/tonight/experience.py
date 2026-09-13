"""Pure presentation and one-tap evening modes for the Tonight hub."""
import copy


MODES = (
    ('all', 'הכול'),
    ('movie', 'סרט'),
    ('tvshow', 'סדרה'),
    ('quick', 'עד 90 דק׳'),
    ('light', 'קליל'),
    ('tense', 'מותח'),
    ('moving', 'מרגש'),
    ('surprise', 'תפתיע אותי'),
)


def apply_mode(state, mode):
    """Apply a complete, predictable preset; one tap never leaves hidden filters."""
    if mode not in {key for key, _ in MODES}:
        raise ValueError('Unknown Tonight mode')
    state = copy.deepcopy(state)
    session = state['session']
    for key in ('anchor', 'anchor_genres', 'avoid_genres', 'max_runtime',
                'discovery_mode', 'avoid_creators', 'vibe'):
        session.pop(key, None)
    session['kind'] = 'all'
    session['minutes'] = 0
    if mode == 'movie':
        session['kind'] = 'movie'
    elif mode == 'tvshow':
        session['kind'] = 'tvshow'
    elif mode == 'quick':
        session['kind'] = 'movie'
        session['minutes'] = 90
    elif mode in ('light', 'tense', 'moving', 'surprise'):
        session['vibe'] = mode
    return state


def active_mode(session):
    vibe = session.get('vibe')
    if vibe in ('light', 'tense', 'moving', 'surprise'):
        return vibe
    if session.get('kind') == 'movie' and session.get('minutes') == 90:
        return 'quick'
    if session.get('kind') in ('movie', 'tvshow') and not session.get('minutes'):
        return session['kind']
    return 'all'


def mode_rows(xbmcgui, session):
    selected = active_mode(session)
    rows = []
    for key, label in MODES:
        shown = ('● '+label) if key == selected else label
        row = xbmcgui.ListItem(label=shown)
        row.setProperty('mode', key)
        row.setProperty('active', 'true' if key == selected else 'false')
        rows.append(row)
    return rows


def metadata(item):
    parts = ['סרט' if item['kind'] == 'movie' else 'סדרה']
    if item.get('year'):
        parts.append(str(item['year']))
    if item.get('runtime') and item['kind'] == 'movie':
        parts.append('%s דק׳' % ((item['runtime'] + 59) // 60))
    if item.get('rating'):
        parts.append('★ %.1f' % item['rating'])
    return '  •  '.join(parts)


def _anchor_title(item, catalog, history_seeds):
    by_key = {candidate['key']: candidate['title'] for candidate in catalog}
    for key in item.get('recommended_from', []):
        if key in history_seeds and key in by_key:
            return by_key[key]
    return ''


def card(row, catalog=(), history_seeds=()):
    """Turn internal evidence into one short, honest sentence for the living room."""
    item = row['item']
    lane = row.get('lane', '')
    personal = (item.get('personal_source') or
                ' / '.join(item.get('personal_sources',[])))
    if lane == 'מהשמורים שלך' or personal:
        role = 'מהרשימה שלך'
        reason = ('שמרת אותו ב־%s — אולי זה הערב' % personal
                  if personal else 'כבר שמרת אותו — אולי זה הערב')
    elif lane in ('קרוב לטעם שלך', 'בחירה מהקטלוג'):
        role = 'הבחירה הבטוחה' if lane == 'קרוב לטעם שלך' else 'שווה לנסות'
        anchor = _anchor_title(item, catalog, set(history_seeds))
        reason = 'כי צפית ב־%s' % anchor if anchor else ''
    elif lane == 'כיוון קצת אחר':
        role = 'משהו חדש בשבילך'
        reason = 'קרוב מספיק לטעם שלך, עם כיוון קצת אחר'
    else:
        role = 'עוד אפשרות טובה'
        reason = ''
    if not reason:
        candidates = row.get('reasons', [])[1:]
        for candidate in candidates:
            if 'אותו במאי:' in candidate and ', כמו ב־' in candidate:
                title = candidate.split(', כמו ב־', 1)[1].split(' שאהבת', 1)[0]
                reason = 'מאותו במאי של %s' % title
                break
            if 'יוצר משותף בתסריט:' in candidate and ', כמו ב־' in candidate:
                title = candidate.split(', כמו ב־', 1)[1].split(' שאהבת', 1)[0]
                reason = 'יוצר משותף ל־%s שאהבת' % title
                break
            if 'קשר ז׳אנרי ל־' in candidate:
                title = candidate.split('קשר ז׳אנרי ל־', 1)[1].split(' שסימנת', 1)[0]
                reason = 'באותו כיוון של %s שאהבת' % title
                break
            if 'כיוון קומי' in candidate:
                reason = 'מתאים לערב הקליל שבחרת'
                break
            if 'כיוון מותח' in candidate:
                reason = 'מתאים לכיוון המותח שבחרת'
                break
            if 'כיוון רגשי' in candidate:
                reason = 'מתאים לכיוון המרגש שבחרת'
                break
            if 'פחות צפויה' in candidate:
                reason = 'הפתעה מחוץ למסלול הרגיל שלך'
                break
            if 'היסטוריית הצפייה' in candidate:
                reason = 'בהשראת מה שכבר ראית'
                break
        if not reason:
            reason = 'הצעה חדשה מתוך הקטלוג שלך'
    return dict(role=role, reason=reason, meta=metadata(item))
