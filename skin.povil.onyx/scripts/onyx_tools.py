# -*- coding: utf-8 -*-
"""
Onyx on-demand tools - runs only when you change a setting, never in the background.

Called from the skin with positional args (no & pairs, so nothing gets split):
    RunScript(special://skin/scripts/onyx_tools.py,menu,CustomMovies.1)
    RunScript(special://skin/scripts/onyx_tools.py,widget,MoviesShelf)
    RunScript(special://skin/scripts/onyx_tools.py,color)
    RunScript(special://skin/scripts/onyx_tools.py,playercolor)
    RunScript(special://skin/scripts/onyx_tools.py,image,CustomBackgroundPath)
    RunScript(special://skin/scripts/onyx_tools.py,folder,CustomSlideshowPath)
    RunScript(special://skin/scripts/onyx_tools.py,changelog)
    RunScript(special://skin/scripts/onyx_tools.py,parentdir)

menu      -> writes <prop>.Path  = a full builtin, e.g. ActivateWindow(Videos,"plugin://...",return)
             writes <prop>.Label / <prop>.Icon
             (Kodi favourites are read straight from Kodi - no helper add-on needed)
             Also offers Kodi PVR (Live TV / Radio) windows and Kodi favourites (the Favourites window
             itself, or any one saved favourite).
             For Custom* menu slots it also offers move up / down / top / bottom, and keeps the section
             compacted: clearing or moving a shortcut never leaves an empty slot between shortcuts.
widget    -> writes <prop>.Path  = the raw directory path used by <content>
             writes <prop>.Label
color     -> picks the skin's focus color. Only stored in the skin strings FocusColor / FocusColorName (user
             data); the skin reads them through the FocusColor variable, so nothing is written to the
             skin folder, an update cannot reset it, and no skin reload is needed.
highlightcolor -> picks the highlight color of headings and descriptions (skin string HighlightColor)
playercolor -> picks the color of focused player (OSD) buttons (skin string PlayerButtonColor, Blue by default)
image     -> picks an image for a skin string (shelf images, backgrounds). Stored as a special:// path so a
             build made on one device (C:\\ on Windows) still works on another (Android, Linux).
             Only new picks are converted; values that are already saved are never rewritten.
folder    -> same for a folder of pictures (the custom slideshow).
changelog -> loads changelog.txt for the Skin Settings > Changelog page
parentdir -> toggles Kodi's own "Show parent folder items" (the ".." entry) setting.
touchkeymap -> phones: writes special://profile/keymaps/kodipovil_onyx_touch.xml: a vertical
             swipe on the home sets Window(home).Property(povil.swipe) (Kodi gives a skin no
             swipe of its own); Onyx's timer povil_swipe turns it into Down/Up. Any other skin
             ignores the property, so the keymap may stay when the skin changes.

Kept compatible with Kodi 21 and 22: only stable xbmc/xbmcgui/xbmcvfs calls are used.
"""
import json
import os
import re
import sys

import xbmc
import xbmcgui
import xbmcvfs

DIALOG = xbmcgui.Dialog()

# (label, root path, window to open it in)
MENU_ROOTS = [
    ("Video add-ons", "addons://sources/video/", "Videos"),
    ("Music add-ons", "addons://sources/audio/", "Music"),
    ("Picture add-ons", "addons://sources/image/", "Pictures"),
    ("Program add-ons", "addons://sources/executable/", "Programs"),
    ("Video library", "library://video/", "Videos"),
    ("Music library", "library://music/", "Music"),
    ("Video playlists", "special://videoplaylists/", "Videos"),
]
WIDGET_ROOTS = [
    ("Video add-ons", "addons://sources/video/", "Videos"),
    ("Video library", "library://video/", "Videos"),
    ("Video playlists", "special://videoplaylists/", "Videos"),
]


def log(msg):
    xbmc.log("[skin.onyx] onyx_tools: %s" % msg, xbmc.LOGINFO)


def clean(label):
    """Strip [B]/[COLOR ..]/etc so stored labels stay plain."""
    return re.sub(r"\[/?[A-Z]+[^\]]*\]", "", label or "").strip()


def set_string(key, value):
    if not value:
        xbmc.executebuiltin("Skin.Reset(%s)" % key)
        return
    # Quote the value so commas/parens/quotes inside it survive builtin parsing.
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    xbmc.executebuiltin('Skin.SetString(%s,"%s")' % (key, value))


def reset(prop):
    for suffix in (".Path", ".Label", ".Icon"):
        xbmc.executebuiltin("Skin.Reset(%s%s)" % (prop, suffix))


def get_directory(path):
    query = {
        "jsonrpc": "2.0", "id": 1, "method": "Files.GetDirectory",
        "params": {"directory": path, "media": "files", "properties": ["title", "thumbnail"]},
    }
    xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
    try:
        result = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
    finally:
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")
    if "error" in result:
        log("GetDirectory failed for %s: %s" % (path, result["error"]))
        return []
    return result.get("result", {}).get("files") or []


def make_item(label, label2="", thumb="", keep_color=False):
    """
    A row for a picker dialog. Add-on names often carry their own [COLOR] formatting, which beats the skin's
    focus color. The skin cannot strip formatting, so a plain copy of the name goes in the PlainLabel property
    and the focused row shows that (see FocusListLabel in Includes_Variables.xml). keep_color=True is for rows
    whose own color is the point (the color pickers' swatches): those get the KeepColor property, which tells
    the select dialog not to redraw them in the focus color (DialogRowColorTagged in Includes.xml), so a swatch
    keeps its own color when focused - the focus box shows where you are.
    """
    li = xbmcgui.ListItem(label, label2)
    if thumb:
        li.setArt({"thumb": thumb, "icon": thumb})
    if keep_color:
        li.setProperty("KeepColor", "true")
    elif re.search(r"\[/?COLOR", label or "", re.I):
        li.setProperty("PlainLabel", clean(label))
    return li


def browse(roots, allow_launch):
    """
    Walk directories. Returns (path, label, thumb, window, is_launcher) or None.
    is_launcher=True means the pick was an executable add-on -> RunAddon().
    """
    root_items = [make_item(r[0], r[1]) for r in roots]
    choice = DIALOG.select("Choose a source", root_items)
    if choice < 0:
        return None
    root_label, root_path, window = roots[choice]
    is_program_root = root_path.startswith("addons://sources/executable")
    if is_program_root and not allow_launch:
        return None

    # stack of (path, label, thumb)
    stack = [(root_path, root_label, "")]
    while stack:
        path, label, thumb = stack[-1]
        entries = []  # (kind, data)
        items = []
        depth = len(stack)

        if depth > 1:
            entries.append(("use", None))
            items.append(make_item("[B]>> Use this folder[/B]", clean(label), thumb))
        entries.append(("up", None))
        items.append(make_item(".. (Back)"))

        for f in get_directory(path):
            is_dir = f.get("filetype") == "directory"
            if is_program_root:
                # program add-ons are launchers, not browsable folders
                entries.append(("launch", f))
            elif is_dir:
                entries.append(("dir", f))
            else:
                continue  # skip playable files / plugin actions
            items.append(make_item(f.get("label", ""), "", f.get("thumbnail", "")))

        heading = " / ".join(clean(s[1]) for s in stack)
        pick = DIALOG.select(heading, items, useDetails=True)
        if pick < 0:
            return None
        kind, data = entries[pick]
        if kind == "use":
            return path, clean(label), thumb, window, False
        if kind == "up":
            stack.pop()
            if not stack:
                return browse(roots, allow_launch)  # back to source list
            continue
        if kind == "launch":
            # listing entries look like plugin://<id>/ or addons://.../<id>/ - the id is the last segment
            addon_id = data.get("file", "").split("://", 1)[-1].strip("/").split("/")[-1]
            return addon_id, clean(data.get("label", "")), data.get("thumbnail", ""), window, True
        stack.append((data.get("file", ""), data.get("label", ""), data.get("thumbnail", "")))
    return None


def ask_label(default):
    label = DIALOG.input("Label", defaultt=default)
    return label or default


def get_favourites():
    query = {"jsonrpc": "2.0", "id": 1, "method": "Favourites.GetFavourites",
             "params": {"properties": ["path", "window", "windowparameter", "thumbnail"]}}
    result = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
    if "error" in result:
        log("Favourites.GetFavourites failed: %s" % result["error"])
        return []
    return result.get("result", {}).get("favourites") or []


def _q(value):
    """Quote a value for use inside a Kodi builtin."""
    return '"%s"' % (value or "").replace('"', '\\"')


def favourite_to_action(fav):
    """Turn a Kodi favourite into the builtin that runs it (same thing Kodi does on click)."""
    kind = fav.get("type")
    if kind == "window":
        param = fav.get("windowparameter") or ""
        return "ActivateWindow(%s,%s,return)" % (fav.get("window", ""), _q(param)) if param else "ActivateWindow(%s)" % fav.get("window", "")
    if kind == "script":
        return "RunScript(%s)" % _q(fav.get("path"))
    if kind == "androidapp":
        return "StartAndroidActivity(%s)" % _q((fav.get("path") or "").rsplit("/", 1)[-1])
    path = fav.get("path") or ""
    return "PlayMedia(%s)" % _q(path) if path else ""


def pick_favourite(prop):
    """
    First row: a shortcut to Kodi's Favourites window itself (works even before any favourite is saved).
    Below it: each saved favourite, to link that one item directly.
    """
    favs = get_favourites()
    rows = [make_item("Favourites", "Open the Favourites window", "DefaultFavourites.png")]
    rows += [make_item(f.get("title", ""), "", f.get("thumbnail", "")) for f in favs]
    choice = DIALOG.select("Choose a favourite", rows, useDetails=True)
    if choice < 0:
        return
    if choice == 0:
        set_string(prop + ".Path", "ActivateWindow(FavouritesBrowser)")
        set_string(prop + ".Label", ask_label(xbmc.getLocalizedString(1036)))
        set_string(prop + ".Icon", "DefaultFavourites.png")
        return
    fav = favs[choice - 1]
    action = favourite_to_action(fav)
    if not action:
        DIALOG.notification("Onyx", "That favourite can't be used as a shortcut", xbmcgui.NOTIFICATION_WARNING)
        return
    set_string(prop + ".Path", action)
    set_string(prop + ".Label", clean(fav.get("title", "")))
    set_string(prop + ".Icon", to_special(fav.get("thumbnail", "")) or fav.get("thumbnail", ""))


# Kodi's built-in Live TV / Radio windows (provided by the user's PVR client)
PVR_ENTRIES = [
    ("TV channels", "TVChannels"), ("TV guide", "TVGuide"), ("TV recordings", "TVRecordings"),
    ("TV timers", "TVTimers"), ("TV timer rules", "TVTimerRules"), ("TV search", "TVSearch"),
    ("Radio channels", "RadioChannels"), ("Radio guide", "RadioGuide"), ("Radio recordings", "RadioRecordings"),
    ("Radio timers", "RadioTimers"), ("Radio timer rules", "RadioTimerRules"), ("Radio search", "RadioSearch"),
]


def pick_pvr(prop):
    if not xbmc.getCondVisibility("System.HasPVRAddon"):
        DIALOG.notification("Onyx", "No PVR client is enabled in Kodi (Settings > Add-ons > PVR clients)",
                            xbmcgui.NOTIFICATION_WARNING)
        return
    choice = DIALOG.select("Live TV & Radio", [make_item(label) for label, _ in PVR_ENTRIES])
    if choice < 0:
        return
    label, window = PVR_ENTRIES[choice]
    set_string(prop + ".Path", "ActivateWindow(%s)" % window)
    set_string(prop + ".Label", ask_label(label))
    xbmc.executebuiltin("Skin.Reset(%s.Icon)" % prop)


# Number of custom shortcut slots per home-menu section (must match the skin XML)
CUSTOM_SLOTS = 20


def split_prop(prop):
    """'CustomMovies.3' -> ('CustomMovies', 3); returns (prop, 0) if it has no slot number."""
    m = re.match(r"^(.*)\.(\d+)$", prop)
    return (m.group(1), int(m.group(2))) if m else (prop, 0)


def read_slot(prefix, n):
    key = "%s.%d" % (prefix, n)
    return {s: xbmc.getInfoLabel("Skin.String(%s.%s)" % (key, s)) for s in ("Path", "Label", "Icon")}


def write_slot(prefix, n, data):
    key = "%s.%d" % (prefix, n)
    for suffix in ("Path", "Label", "Icon"):
        set_string("%s.%s" % (key, suffix), data.get(suffix, ""))


def compact_section(prefix, drop=0):
    """
    Close the gaps in one menu section: the occupied slots keep their order and are moved up to
    slots 1, 2, 3 ..., and the slots after them are emptied. drop=N leaves slot N out (used by Clear).
    Everything is worked out from one read of the slots: Kodi runs Skin.SetString / Skin.Reset a moment
    later, so reading the slots again right after a change would still see the old values.
    Returns the new list of slot contents.
    """
    slots = {i: read_slot(prefix, i) for i in range(1, CUSTOM_SLOTS + 1)}
    filled = [slots[i] for i in range(1, CUSTOM_SLOTS + 1) if slots[i]["Path"] and i != drop]
    for i in range(1, CUSTOM_SLOTS + 1):
        want = filled[i - 1] if i <= len(filled) else {"Path": "", "Label": "", "Icon": ""}
        if want != slots[i]:
            write_slot(prefix, i, want)
    return filled


def move_slot(prop, how):
    """
    Re-order one menu section. The section is compacted first (no empty slots between shortcuts),
    so the shortcuts always sit in slots 1..n and a move never leaves a gap.
    """
    prefix, n = split_prop(prop)
    if not xbmc.getInfoLabel("Skin.String(%s.Path)" % prop):
        return
    # position of this shortcut among the filled slots, before compacting
    pos = sum(1 for i in range(1, n) if xbmc.getInfoLabel("Skin.String(%s.%d.Path)" % (prefix, i)))
    order = compact_section(prefix)
    if how == "up" and pos > 0:
        order[pos - 1], order[pos] = order[pos], order[pos - 1]
    elif how == "down" and pos < len(order) - 1:
        order[pos + 1], order[pos] = order[pos], order[pos + 1]
    elif how == "top":
        order.insert(0, order.pop(pos))
    elif how == "bottom":
        order.append(order.pop(pos))
    else:
        return
    for i, data in enumerate(order, 1):
        write_slot(prefix, i, data)


def pick_menu(prop):
    prefix, n = split_prop(prop)
    can_move = prefix.startswith("Custom") and bool(xbmc.getInfoLabel("Skin.String(%s.Path)" % prop))

    options = [("browse", "Browse add-ons / library"), ("pvr", "Live TV & Radio (Kodi PVR)"), ("fav", "Kodi favourites"), ("manual", "Enter path manually")]
    if can_move:
        options += [("up", "Move up"), ("down", "Move down"), ("top", "Move to top"), ("bottom", "Move to bottom")]
    options.append(("clear", "Clear"))

    choice = DIALOG.select("Set shortcut", [o[1] for o in options])
    if choice < 0:
        return
    action = options[choice][0]

    if action == "browse":
        res = browse(MENU_ROOTS, allow_launch=True)
        if not res:
            return
        path, label, thumb, window, is_launcher = res
        if is_launcher:
            built = "RunAddon(%s)" % path
        else:
            built = 'ActivateWindow(%s,"%s",return)' % (window, path)
        set_string(prop + ".Path", built)
        set_string(prop + ".Label", ask_label(label))
        set_string(prop + ".Icon", to_special(thumb) or thumb)
    elif action == "pvr":
        pick_pvr(prop)
    elif action == "fav":
        pick_favourite(prop)
    elif action == "manual":
        path = DIALOG.input("Path or builtin (plugin://..., ActivateWindow(...))")
        if not path:
            return
        # a bare path gets wrapped; anything that already looks like a builtin is kept as-is
        if "://" in path and not path.rstrip().endswith(")"):
            built = 'ActivateWindow(Videos,"%s",return)' % path
        else:
            built = path
        set_string(prop + ".Path", built)
        set_string(prop + ".Label", ask_label(""))
        xbmc.executebuiltin("Skin.Reset(%s.Icon)" % prop)
    elif action in ("up", "down", "top", "bottom"):
        move_slot(prop, action)
    elif action == "clear":
        if prefix.startswith("Custom") and n:
            # clear this slot and close the gap in one go: the shortcuts below move up one slot
            compact_section(prefix, drop=n)
        else:
            reset(prop)


def pick_widget(prop):
    options = ["Browse add-ons / library", "Enter path manually", "Clear"]
    choice = DIALOG.select("Set widget source", options)
    if choice == 0:
        res = browse(WIDGET_ROOTS, allow_launch=False)
        if not res:
            return
        path, label = res[0], res[1]
        set_string(prop + ".Path", path)
        set_string(prop + ".Label", label)
    elif choice == 1:
        path = DIALOG.input("Directory path (plugin://..., videodb://...)")
        if not path:
            return
        set_string(prop + ".Path", path)
        set_string(prop + ".Label", path)
    elif choice == 2:
        reset(prop)


# ---------------------------------------------------------------- portable image paths
# A path picked with Kodi's own browser is whatever the device calls the file (C:\\Users\\...,
# /storage/emulated/0/...), which means nothing on another device. Everything the skin stores is
# kept as a special:// path instead: a file already inside a Kodi folder is just written in
# special:// form, and a file from anywhere else is copied into the skin's data folder (next to the
# skin settings, so it travels with a build) and the copy's special:// path is stored.
# Every picker opens here (the Kodi home folder), so browsing starts in a place that exists on every device.
BROWSE_START = "special://home/"
USER_DIR = "special://profile/addon_data/skin.onyx/"
IMAGE_DIR = USER_DIR + "images/"
SLIDESHOW_DIR = USER_DIR + "slideshow/"
# Most specific first. Temp is left out on purpose: it is cleared and is not part of a build.
SPECIAL_ROOTS = ["special://profile/", "special://masterprofile/", "special://skin/", "special://xbmc/",
                 "special://home/"]
# Stored as is: already portable, or not a file at all.
KEEP_SCHEMES = ("special://", "resource://", "image://", "http://", "https://", "plugin://", "addons://",
                "androidapp://")
# Every skin string that holds an image picked by the user (the folder of the slideshow is separate)
IMAGE_STRINGS = ["CustomBackgroundPath", "CustomChannelsBackgroundImage", "CustomRecordingsBackgroundImage",
                 "MoviesShelf_Icon", "PVRShelf_Icon", "TVShelf_Icon", "CustomSec1Shelf_Icon",
                 "CustomSec2Shelf_Icon", "CustomSec3Shelf_Icon", "AddonsShelf_Icon", "XBMCShelf_Icon",
                 "MusicShelf_Icon", "PicturesShelf_Icon"]
FOLDER_STRINGS = ["CustomSlideshowPath"]


def norm(path):
    return os.path.normcase(os.path.normpath(path))


def to_special(path):
    """
    'path' written as a special:// path if it lies inside one of Kodi's own folders, else None.
    Paths that are already portable (see KEEP_SCHEMES) come back unchanged.
    """
    if not path:
        return path
    if path.lower().startswith(KEEP_SCHEMES):
        return path
    if "://" in path:  # smb://, nfs://, ... : not a local file, so no special:// form
        return None
    given = os.path.normpath(path)
    for root in SPECIAL_ROOTS:
        real = os.path.normpath(xbmcvfs.translatePath(root))
        if norm(given) == norm(real) or norm(given).startswith(norm(real).rstrip(os.sep) + os.sep):
            rel = given[len(real):].lstrip("\\/").replace(os.sep, "/")  # keeps the case of the original
            if rel and path.endswith(("/", "\\")):
                rel += "/"
            return root + rel
    return None


def safe_name(name):
    return re.sub(r"[^\w.\- ]", "_", name)


def clear_prefix(folder, prefix):
    """Remove the earlier copies made for one setting (only ever inside our own data folder)."""
    if not xbmcvfs.exists(folder):
        return
    for name in xbmcvfs.listdir(folder)[1]:
        if name.startswith(prefix):
            xbmcvfs.delete(folder + name)


def import_image(path, key):
    """The portable form of the image 'path' (copying it into IMAGE_DIR when needed), or None."""
    special = to_special(path)
    if special is not None:
        return special
    if not xbmcvfs.exists(path):
        return None
    xbmcvfs.mkdirs(IMAGE_DIR)
    clear_prefix(IMAGE_DIR, key + "_")
    dest = IMAGE_DIR + key + "_" + safe_name(os.path.basename(path.rstrip("/\\")))
    if not xbmcvfs.copy(path, dest):
        log("could not copy %s to %s" % (path, dest))
        return None
    return dest


def picture_exts():
    return tuple(e for e in xbmc.getSupportedMedia("picture").lower().split("|") if e)


def nothing_picked(path, current):
    """
    True when the browser was backed out of. Kodi hands back the path the browser was opened at when it
    is cancelled (here BROWSE_START), not an empty string, so that counts as 'nothing picked', as do an
    empty result and the value that is already set.
    """
    return not path or path == current or path.rstrip("/\\") == BROWSE_START.rstrip("/")


def pick_image(key):
    current = xbmc.getInfoLabel("Skin.String(%s)" % key)
    mask = xbmc.getSupportedMedia("picture")
    path = DIALOG.browse(2, "Choose an image", "files", mask, False, False, BROWSE_START)
    if nothing_picked(path, current):
        return
    # only an actual picture file counts as a pick, never a folder
    if path.endswith(("/", "\\")) or not path.lower().endswith(picture_exts()) or not xbmcvfs.exists(path):
        return
    stored = import_image(path, key)
    if stored is None:
        DIALOG.notification("Onyx", "Could not use that image", xbmcgui.NOTIFICATION_ERROR)
        return
    set_string(key, stored)


def picture_files(folder):
    exts = picture_exts()
    return [n for n in xbmcvfs.listdir(folder)[1] if n.lower().endswith(exts)]


def pick_folder(key):
    current = xbmc.getInfoLabel("Skin.String(%s)" % key)
    path = DIALOG.browse(0, "Choose a folder of pictures", "files", "", False, False, BROWSE_START)
    if nothing_picked(path, current) or not xbmcvfs.exists(path):
        return
    special = to_special(path)
    if special is not None:
        set_string(key, special)
        return
    files = picture_files(path)
    if not files:
        DIALOG.notification("Onyx", "No pictures found in that folder", xbmcgui.NOTIFICATION_WARNING)
        return
    # backing out of this question picks nothing (a yes/no dialog would count it as "No")
    answer = DIALOG.select("Folder is outside Kodi's own folders",
                           ["Copy its %d pictures into Kodi's data folder (works on other devices)" % len(files),
                            "Use the folder where it is (only works on this device)"])
    if answer < 0:
        return
    if answer == 1:
        set_string(key, path)
        return
    dest = SLIDESHOW_DIR + safe_name(key) + "/"
    xbmcvfs.mkdirs(dest)
    before = set(xbmcvfs.listdir(dest)[1])  # an earlier copy for this setting: ours, replaced once the new one is complete
    progress = xbmcgui.DialogProgress()
    progress.create("Custom slideshow folder", "Copying pictures...")
    sep = "" if path.endswith(("/", "\\")) else "/"
    copied = []
    cancelled = False
    for i, name in enumerate(files):
        if progress.iscanceled():
            cancelled = True
            break
        progress.update(int(100.0 * i / len(files)), name)
        if xbmcvfs.copy(path + sep + name, dest + safe_name(name)):
            copied.append(safe_name(name))
    progress.close()
    if cancelled:  # backed out half way: nothing changes, and the files already copied are removed again
        for name in copied:
            if name not in before:
                xbmcvfs.delete(dest + name)
        return
    if not copied:
        DIALOG.notification("Onyx", "Could not copy the pictures", xbmcgui.NOTIFICATION_ERROR)
        return
    for name in before - set(copied):
        xbmcvfs.delete(dest + name)
    set_string(key, dest)


# ---------------------------------------------------------------- focus color
DEFAULT_HL = "FFD7B98E"  # Sand, the skin's stock focus color (HL in colors/defaults.xml)
DEFAULT_PLAYER = "FF66A7D7"  # Blue, the stock color of the player buttons (PlayerButtonColor in Includes_Variables.xml)
DEFAULT_HIGHLIGHT = "FF80E0B0"  # Mint, the skin's stock highlight color (HighlightColor in Includes_Variables.xml)
PALETTE = [
    # blues
    ("Blue", "FF66A7D7"), ("Ice blue", "FFA8D8F0"), ("Sky blue", "FF4FC3F7"), ("Azure", "FF2196F3"),
    ("Royal blue", "FF448AFF"), ("Midnight", "FF2866A4"), ("Indigo", "FF7986CB"),
    # cyans and teals
    ("Cyan", "FF26C6DA"), ("Aqua", "FF00E5FF"), ("Teal", "FF009688"), ("Turquoise", "FF1DE9B6"),
    # greens
    ("Mint", "FF80E0B0"), ("Emerald", "FF2ECC71"), ("Green", "FF66BB6A"), ("Jade", "FF00C853"),
    ("Chartreuse", "FF4FAF00"), ("Lime", "FFC0CA33"), ("Olive", "FFB5B84A"),
    # yellows and oranges
    ("Yellow", "FFFFEB3B"), ("Golden", "FFFFF000"), ("Gold", "FFFFCA28"), ("Amber", "FFE99931"),
    ("Orange", "FFFF9800"), ("Tangerine", "FFFF6D00"), ("Coral", "FFFF7043"), ("Salmon", "FFFF8A80"),
    # reds and pinks
    ("Red", "FFEF5350"), ("Scarlet", "FFFF5252"), ("Crimson", "FFE5395A"), ("Rose", "FFF06292"),
    ("Pink", "FFEC407A"), ("Hot pink", "FFFF4081"),
    # purples
    ("Magenta", "FFE040FB"), ("Violet", "FFC050FF"), ("Grape", "FFAB47BC"), ("Orchid", "FFDA70D6"),
    ("Lavender", "FFB39DDB"),
    # deeper tones (darker, so they read less brightly on dark backgrounds)
    ("Dark red", "FFB71C1C"), ("Burgundy", "FF9B1B30"), ("Maroon", "FFA12B2B"), ("Brick", "FFC0392B"),
    ("Burnt orange", "FFCC5500"), ("Rust", "FFB7410E"), ("Dark gold", "FFB8860B"), ("Brown", "FF8D6E63"),
    ("Forest", "FF2E7D32"), ("Dark teal", "FF00796B"), ("Dark blue", "FF1976D2"), ("Navy", "FF3949AB"),
    ("Deep purple", "FF7E57C2"), ("Plum", "FF8E4585"), ("Dark pink", "FFC2185B"), ("Slate", "FF607D8B"),
    # earth tones and neutrals
    ("Sand", "FFD7B98E"), ("Taupe", "FFA1887F"), ("Silver", "FFBDBDBD"), ("Charcoal", "FFA2A2A2"), ("White", "FFFFFFFF"),
]


def tint(name, hexcolor):
    return "[COLOR %s]%s[/COLOR]" % (hexcolor, name)


def choose_color(heading, default_label=None, default_hex=None):
    """
    Shared color chooser. Returns (name, 'FFRRGGBB'), ("", "") when the optional
    default entry is picked, or None if cancelled / invalid.
    default_hex: the color the default entry stands for; its palette entry is left out so it
    is not listed twice.
    """
    palette = [(n, c) for n, c in PALETTE if not (default_label and default_hex and c == default_hex)]
    items = []
    if default_label:
        # the default entry is shown in its own color too, like the rest of the palette
        items.append(make_item(tint(default_label, default_hex), keep_color=True) if default_hex else make_item(default_label))
    items += [make_item(tint(n, c), c[2:], keep_color=True) for n, c in palette]
    items.append(make_item("Custom hex color..."))
    # tell the select dialog to always draw its focus box here (color swatches are hard to tell apart without it)
    home = xbmcgui.Window(10000)
    home.setProperty("onyx.boxalways", "1")
    try:
        choice = DIALOG.select(heading, items)
    finally:
        home.clearProperty("onyx.boxalways")
    if choice < 0:
        return None
    if default_label:
        if choice == 0:
            return ("", "")
        choice -= 1
    if choice < len(palette):
        return palette[choice]
    raw = DIALOG.input("Hex color, e.g. FF8800", defaultt="").strip().lstrip("#")
    if not re.match(r"^[0-9A-Fa-f]{6}$", raw):
        DIALOG.notification("Onyx", "Enter 6 hex digits, e.g. FF8800", xbmcgui.NOTIFICATION_WARNING)
        return None
    hexcolor = "FF" + raw.upper()
    return ("#" + hexcolor[2:], hexcolor)


def pick_color():
    """Focus color: stored as skin strings only. Picking the default clears them (the skin then uses Sand)."""
    res = choose_color("Focus color", "Sand (default)", DEFAULT_HL)
    if not res:
        return
    name, hexcolor = res
    if not hexcolor or hexcolor == DEFAULT_HL:
        xbmc.executebuiltin("Skin.Reset(FocusColor)")
        xbmc.executebuiltin("Skin.Reset(FocusColorName)")
        return
    set_string("FocusColor", hexcolor)
    set_string("FocusColorName", name)


def pick_highlight_color():
    """Color of headings, section titles and description text. Stored as skin strings, no reload needed."""
    res = choose_color("Highlight color", "Mint (default)", DEFAULT_HIGHLIGHT)
    if not res:
        return
    name, hexcolor = res
    if not hexcolor:
        xbmc.executebuiltin("Skin.Reset(HighlightColor)")
        xbmc.executebuiltin("Skin.Reset(HighlightColorName)")
        return
    set_string("HighlightColor", hexcolor)
    set_string("HighlightColorName", name)


def pick_player_color():
    """Color of the focused player (OSD) buttons. Stored as skin strings, no reload needed."""
    res = choose_color("Player button color", "Blue (default)", DEFAULT_PLAYER)
    if not res:
        return
    name, hexcolor = res
    if not hexcolor or hexcolor == DEFAULT_PLAYER:
        xbmc.executebuiltin("Skin.Reset(PlayerButtonColor)")
        xbmc.executebuiltin("Skin.Reset(PlayerButtonColorName)")
        return
    set_string("PlayerButtonColor", hexcolor)
    set_string("PlayerButtonColorName", name)


def load_changelog():
    """Put changelog.txt into a window property so Skin Settings can show it (skin XML can't read files)."""
    text = ""
    try:
        f = xbmcvfs.File("special://skin/changelog.txt")
        try:
            raw = f.read()
        finally:
            f.close()
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
    except Exception as exc:  # never break Skin Settings over a missing file
        log("could not read changelog: %s" % exc)
    xbmcgui.Window(10000).setProperty("onyx.changelog", text.replace("\r\n", "\n") or "No changelog found.")


# ---------------------------------------------------------------- parent folder ".."
def toggle_parentdir():
    setting = "filelists.showparentdiritems"
    get = {"jsonrpc": "2.0", "id": 1, "method": "Settings.GetSettingValue", "params": {"setting": setting}}
    current = json.loads(xbmc.executeJSONRPC(json.dumps(get))).get("result", {}).get("value")
    if current is None:
        log("could not read %s" % setting)
        return
    put = {"jsonrpc": "2.0", "id": 1, "method": "Settings.SetSettingValue",
           "params": {"setting": setting, "value": not current}}
    xbmc.executeJSONRPC(json.dumps(put))


TOUCH_KEYMAP = "special://profile/keymaps/kodipovil_onyx_touch.xml"
TOUCH_KEYMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Kodi POV IL - Onyx: on a touch screen a swipe up goes down a row of the home, a swipe
     down goes back up. A swipe only names itself in a home property; the Onyx skin's timer
     povil_swipe moves the focus, and any other skin ignores the property. Written by the
     Onyx skin (scripts/onyx_tools.py touchkeymap). -->
<keymap>
  <home>
    <touch>
      <swipe direction="up">SetProperty(povil.swipe,down,home)</swipe>
      <swipe direction="down">SetProperty(povil.swipe,up,home)</swipe>
    </touch>
  </home>
</keymap>
"""


def touch_keymap():
    path = xbmcvfs.translatePath(TOUCH_KEYMAP)
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == TOUCH_KEYMAP_XML:
                return
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(TOUCH_KEYMAP_XML)
    except OSError as exc:
        log("touch keymap not written: %s" % exc)
        return
    xbmc.executebuiltin("Action(reloadkeymaps)")


def main():
    args = sys.argv[1:]
    if args and args[0].strip() == "touchkeymap":
        touch_keymap()
        return
    if args and args[0].strip() == "color":
        pick_color()
        return
    if args and args[0].strip() == "changelog":
        load_changelog()
        return
    if args and args[0].strip() == "highlightcolor":
        pick_highlight_color()
        return
    if args and args[0].strip() == "image" and len(args) > 1:
        pick_image(args[1].strip())
        return
    if args and args[0].strip() == "folder" and len(args) > 1:
        pick_folder(args[1].strip())
        return
    if args and args[0].strip() == "playercolor":
        pick_player_color()
        return
    if args and args[0].strip() == "parentdir":
        toggle_parentdir()
        return
    if len(args) < 2:
        log("expected: <menu|widget> <property>, got %s" % args)
        return
    mode, prop = args[0].strip(), args[1].strip()
    if mode == "menu":
        pick_menu(prop)
    elif mode == "widget":
        pick_widget(prop)


if __name__ == "__main__":
    main()