"""The order of a home screen's rows on Onyx (Wizard 0.5.27 / Onyx 1.0.26): the settings tile "סדר השורות".

A viewer, via the owner, Nov 2026: "I can add a row now, but I cannot change the order"; "in the original Onyx it
exists". On the films, series, kids and favourites screens every row is a slot (tools/skin_onyx/gen_home.py SLOT_TABS):
slot k shows the row the viewer put there -- Skin.String(POVILSlot_<tab>_<k>), the row's place in the screen's list,
once Skin.HasSetting(POVILOrdered_<tab>) -- else the build's own row k. Here a row moves up or down, is hidden or shown
again, and the screen goes back to the build's order. The order is kept compact: a hidden row leaves no slot behind.

What a screen's rows are, and their names, the skin says in extras/povil_rows.json (gen_standalone.py).
"""
import json
import os

HEADING = 'סדר השורות'
ROWS_FILE = 'special://home/addons/skin.povil.onyx/extras/povil_rows.json'
NAMELESS = 'השורה שלי'


def ordered_key(tab):
    return 'POVILOrdered_%s' % tab


def slot_key(tab, k):
    return 'POVILSlot_%s_%d' % (tab, k)


def screens(path=None):
    """[(tab, name, rows)]: rows = [{'title', 'custom'}] in the build's order; [] without the skin's file."""
    if path is None:
        import xbmcvfs
        path = xbmcvfs.translatePath(ROWS_FILE)
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [(tab['id'], tab['name'], tab['rows']) for tab in data.get('tabs', [])]


def current_order(tab, count, ordered, read):
    """The rows the screen shows, in order (places in its list): the viewer's, else the build's (all of them)."""
    if not ordered:
        return list(range(count))
    order = []
    for k in range(count):
        value = read(slot_key(tab, k))
        if value.isdigit() and int(value) < count and int(value) not in order:
            order.append(int(value))
    return order


def write_order(tab, count, order, run):
    """Make `order` the screen's: slot k shows order[k], the slots after it none."""
    run('Skin.SetBool(%s)' % ordered_key(tab))
    for k in range(count):
        if k < len(order):
            run('Skin.SetString(%s,%d)' % (slot_key(tab, k), order[k]))
        else:
            run('Skin.Reset(%s)' % slot_key(tab, k))


def reset(tab, count, run):
    """Back to the build's order."""
    run('Skin.Reset(%s)' % ordered_key(tab))
    for k in range(count):
        run('Skin.Reset(%s)' % slot_key(tab, k))


def move(order, place, step):
    """order with the row at `place` moved one step (-1 up, +1 down); unchanged at an end."""
    other = place + step
    if not 0 <= place < len(order) or not 0 <= other < len(order):
        return list(order)
    out = list(order)
    out[place], out[other] = out[other], out[place]
    return out


def place_custom(tab, custom, read, visible, run, path=None):
    """A row of the viewer's own that just got a source, on a screen whose order the viewer set: it joins the order at
    its end (else it would stand in no slot and never show). Nothing to do in the build's order.
    read: Kodi's getInfoLabel; visible: its getCondVisibility; run: executebuiltin."""
    if not visible('Skin.HasSetting(%s)' % ordered_key(tab)):
        return False
    for tab_id, _name, rows in screens(path):
        if tab_id != tab:
            continue
        index = next((i for i, row in enumerate(rows) if row.get('custom') == custom), None)
        if index is None:
            return False
        order = current_order(tab, len(rows), True, lambda key: read('Skin.String(%s)' % key))
        if index in order:
            return False
        write_order(tab, len(rows), order + [index], run)
        return True
    return False


def drop_custom(tab, custom, visible, read, run, path=None):
    """A row of the viewer's own that was deleted leaves the viewer's order (no empty slot stays behind)."""
    if not visible('Skin.HasSetting(%s)' % ordered_key(tab)):
        return False
    for tab_id, _name, rows in screens(path):
        if tab_id != tab:
            continue
        index = next((i for i, row in enumerate(rows) if row.get('custom') == custom), None)
        order = current_order(tab, len(rows), True, lambda key: read('Skin.String(%s)' % key))
        if index is None or index not in order:
            return False
        write_order(tab, len(rows), [i for i in order if i != index], run)
        return True
    return False


def name_of(row, read):
    if row.get('custom'):
        key = 'POVILRow_%s' % row['custom']
        name = read('Skin.String(%s_name)' % key) or NAMELESS
        return name if read('Skin.String(%s_path)' % key) else '%s (ריקה)' % name
    return row.get('title') or '?'


def choose():
    """The tile "סדר השורות"."""
    import xbmc
    import xbmcgui
    dialog = xbmcgui.Dialog()
    found = screens()
    if not found:
        dialog.ok(HEADING, 'הסקין Onyx לא נמצא, או שהגרסה שלו ישנה מדי לסידור השורות.')
        return
    picked = dialog.select(HEADING + ': באיזה מסך?', [name for _tab, name, _rows in found])
    if picked < 0:
        return
    tab, screen, rows = found[picked]
    count = len(rows)

    def read(key):
        return xbmc.getInfoLabel(key)

    while True:
        ordered = xbmc.getCondVisibility('Skin.HasSetting(%s)' % ordered_key(tab))
        order = current_order(tab, count, ordered, lambda key: read('Skin.String(%s)' % key))
        hidden = [i for i in range(count) if i not in order]
        labels = ['%d. %s' % (n + 1, name_of(rows[i], read)) for n, i in enumerate(order)]
        labels += ['(מוסתרת) %s' % name_of(rows[i], read) for i in hidden]
        labels.append('חזרה לסדר של הבילד')
        n = dialog.select('%s - %s' % (HEADING, screen), labels)
        if n < 0:
            return
        if n == len(labels) - 1:
            reset(tab, count, xbmc.executebuiltin)
        elif n < len(order):
            actions = ['הזזה למעלה', 'הזזה למטה', 'הסתרה']
            a = dialog.select(name_of(rows[order[n]], read), actions)
            if a == 0:
                write_order(tab, count, move(order, n, -1), xbmc.executebuiltin)
            elif a == 1:
                write_order(tab, count, move(order, n, +1), xbmc.executebuiltin)
            elif a == 2:
                write_order(tab, count, order[:n] + order[n + 1:], xbmc.executebuiltin)
        else:
            row = hidden[n - len(order)]
            a = dialog.select(name_of(rows[row], read), ['הצגה בראש המסך', 'הצגה בסוף המסך'])
            if a == 0:
                write_order(tab, count, [row] + order, xbmc.executebuiltin)
            elif a == 1:
                write_order(tab, count, order + [row], xbmc.executebuiltin)
        # (Kodi carries out Skin.SetString a moment later: the list is read again after it)
        xbmc.sleep(300)
