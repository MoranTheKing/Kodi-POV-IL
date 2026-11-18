# -*- coding: utf-8 -*-
"""The build's colours in POV's and Umbrella's own windows, once.

The owner (Nov 2026): "the design, a level up, everywhere". The windows a viewer sees
at every play -- the source list and the search progress of POV and of Umbrella --
are the add-ons' own, in the add-ons' own default colours: magenta and cyan in POV,
green, yellow and turquoise in Umbrella, over a build that is charcoal and gold.
Both add-ons take their colours from their settings, so the build's palette is a
matter of settings, not of replacing their files.

Only a colour that still holds the add-on's own default is changed: a colour the
viewer chose is the viewer's. Done once per add-on (a hidden Wizard setting marks
it), so a viewer who goes back to magenta afterwards keeps it; an add-on that is not
installed yet is left for the start at which it is. One case runs it again: every
colour at the add-on's default once more, which is the settings file replaced whole
(a fresh install run again over the device), not a viewer's choice.
"""
import xbmc
import xbmcaddon
import xbmcgui

# One accent per quality (POV) or per service (Umbrella), as the add-ons mean their colours to be told
# apart at a glance (the owner, Nov 2026: "the colours in the source window separate 4K from 1080 from
# 720 -- keep that"): the build's gold for the best, then tones that sit beside it on charcoal.
GOLD, ICE, SAGE, SLATE = 'FFD9B77E', 'FF8CC8F0', 'FF9BD3A8', 'FFA39E97'
AMETHYST, ROSE, STONE, WHITE = 'FFB9A3E3', 'FFE3A3B4', 'FFB8B2A7', 'FFF5F2EC'
WIZARD = 'plugin.program.kodipovilwizard'

# setting id -> (the add-on's own defaults, the build's colour)
POV = {
    'scraper_4k_highlight': (('magenta',), GOLD),
    'scraper_1080p_highlight': (('cyan', 'lawngreen'), ICE),
    'scraper_720p_highlight': (('mediumorchid', 'gold'), SAGE),
    'scraper_SD_highlight': (('dodgerblue', 'lightsaltegray'), SLATE),
    'int_dialog_highlight': (('magenta', 'dodgerblue'), GOLD),
    'ext_dialog_highlight': (('cyan', 'magenta'), ICE),
}
UMBRELLA = {
    'highlight.color': (('FF33ADFF', 'FFFFFF33', 'FF4DFFFF'), GOLD),
    'scraper.dialog.color': (('FFFFFF33',), GOLD),
    'sources.highlight.color': (('FF4DFFFF',), WHITE),
    'dialogs.customcolor': (('FF00B8E6',), GOLD),
    'dialogs.titlebar.color': (('FF00B8E6',), GOLD),
    'dialogs.button.color': (('FF00B8E6',), GOLD),
    'sources.torbox.color': (('FF00B445',), GOLD),
    'sources.real-debrid.color': (('FFFF3334',), ICE),
    'sources.alldebrid.color': (('FFFFB84E',), SAGE),
    'sources.premiumize.me.color': (('FF4700B4',), AMETHYST),
    'sources.offcloud.color': (('FF5824b3',), ROSE),
    'sources.easynews.color': (('FF24B301',), STONE),
}
ADDONS = (
    ('plugin.video.pov', POV, '_pov_palette_v1', False, 'pov_settings'),
    # Umbrella keeps, beside each colour, the line its settings page shows for it
    ('plugin.video.umbrella', UMBRELLA, '_umbrella_palette_v1', True, 'umbrella_settings'),
)


def _log(text, level=xbmc.LOGINFO):
    xbmc.log('[Wizard: palette] ' + text, level)


def changes(current, palette):
    """{setting id: the build's colour} for every colour that still holds the add-on's default."""
    out = {}
    for key, (defaults, colour) in palette.items():
        value = (current.get(key) or '').strip()
        if not value or value.lower() in tuple(d.lower() for d in defaults):
            out[key] = colour
    return out


def apply_once():
    """Start-up: give each installed add-on the build's colours, one time. Returns the ids changed."""
    done = []
    try:
        wizard = xbmcaddon.Addon(WIZARD)
    except Exception:
        return done
    for addon_id, palette, mark, with_display, settings_copy in ADDONS:
        try:
            marked = (wizard.getSetting(mark) or '').strip().lower() == 'true'
            if not xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id):
                continue                # not installed yet: this start does not count
            addon = xbmcaddon.Addon(addon_id)
            todo = changes({key: addon.getSetting(key) for key in palette}, palette)
            # Done once -- unless every one of the colours is the add-on's own default again: that is
            # not a viewer's choice of one colour but the settings file replaced whole (a fresh
            # install run again over this device puts the pack's file there), and the mark outlived it
            if marked and len(todo) < len(palette):
                continue
            for key, colour in sorted(todo.items()):
                addon.setSetting(key, colour)
                if with_display:
                    addon.setSetting(key + '.display', '[COLOR=%s]%s[/COLOR]' % (colour, colour))
            if not marked:
                wizard.setSetting(mark, 'true')
            if todo:
                # Both add-ons read their settings from a copy they keep in a window property:
                # without it they build the copy again from the settings just written
                try:
                    xbmcgui.Window(10000).clearProperty(settings_copy)
                except Exception:
                    pass
            _log('%s: %d of %d colours set' % (addon_id, len(todo), len(palette)))
            done.extend(sorted(todo))
        except Exception as error:
            _log('%s: %s: %s' % (addon_id, type(error).__name__, error), xbmc.LOGWARNING)
    return done
