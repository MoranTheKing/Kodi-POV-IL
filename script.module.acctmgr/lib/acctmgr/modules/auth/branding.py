# -*- coding: utf-8 -*-
"""
Per-provider color/logo configuration for the device-authorization dialog.

A provider subclass (see base_auth.BaseDeviceAuth) can brand its dialog in
two ways, and they can be mixed:

1. Central lookup table - add an entry to PROVIDER_BRANDING keyed by a
   `provider_key` the subclass sets:

       class Premiumize(BaseDeviceAuth):
           provider_name = 'Premiumize'
           provider_key = 'premiumize'          # looked up below
           icon = 'special://home/addons/.../premiumize.png'   # doubles as logo

2. Per-class attributes on the subclass itself, which always win over the
   table entry (handy for a one-off provider, or a local override without
   touching the shared table):

       class Premiumize(BaseDeviceAuth):
           provider_name = 'Premiumize'
           header_color = 'FF1B1F3B'
           accent_color = 'FFFF6A00'
           logo = 'special://home/addons/script.module.acctmgr/resources/media/premiumize.png'

If a provider supplies nothing at all, DEFAULT_BRANDING (the dialog's
original blue/cyan scheme) is used, so this is purely additive - existing
providers keep working unchanged.

Colors are Kodi's native 8-char ARGB hex: AARRGGBB.
"""

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

# Alpha byte used for the translucent "faint" tint behind the verification
# URL box, i.e. AccentColorFaint = ALPHA_FAINT + accent_color's RRGGBB.
ALPHA_FAINT = '2A'          # ~16% opacity

# Relative-luminance cutoff (0-1) used by contrast_text_color(). A background
# above this luminance reads as "light" and gets dark text; at/below, "dark"
# and gets light text. 0.42 (rather than the textbook 0.5) biases saturated
# mid-tone brand colors - which is what most provider palettes actually are -
# toward "give it white text", since a strict midpoint flips too early on
# colorful (as opposed to gray) backgrounds.
LUMINANCE_CUTOFF = 0.42

DEFAULT_BRANDING = {
    'header_color': 'FF185F9D',   # dialog's original blue
    'accent_color': 'FF38BDF8',   # dialog's original cyan
    'logo': None,
    'logo_needs_light_bg': False,
}

# --------------------------------------------------------------------------
# Central provider table (optional - see module docstring, option 1)
# --------------------------------------------------------------------------

PROVIDER_BRANDING = {
    'premiumize': {
        'header_color': 'FF1B1F3B',
        'accent_color': 'FFFF6A00',
    },
    'real-debrid': {
        'header_color': 'FF14213D',
        'accent_color': 'FFFFC94A',
    },
    'alldebrid': {
        'header_color': 'FF1B1B1B',
        'accent_color': 'FFE0263B',
        # AllDebrid's mark is dark-on-transparent - give it a light card
        # behind it instead of letting it disappear into the dark header.
        'logo_needs_light_bg': True,
    },
    # Add further providers here, or just set header_color/accent_color/logo
    # directly as class attributes on the provider's BaseDeviceAuth subclass.
}


# --------------------------------------------------------------------------
# Color math
# --------------------------------------------------------------------------

def _hex_to_rgb(hex_color):
    """Parse an 8-char ARGB or 6-char RGB hex string into an (r, g, b) tuple."""
    h = str(hex_color).strip().lstrip('#')
    if len(h) == 8:        # AARRGGBB - drop the alpha byte
        h = h[2:]
    if len(h) != 6:
        raise ValueError('expected AARRGGBB or RRGGBB, got %r' % hex_color)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def with_alpha(hex_color, alpha_hex):
    """Return hex_color's RGB re-packed with a different alpha byte."""
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except (ValueError, TypeError):
        r, g, b = _hex_to_rgb(DEFAULT_BRANDING['accent_color'])
    return '%s%02X%02X%02X' % (alpha_hex, r, g, b)


def contrast_text_color(hex_color, light='FFFFFFFF', dark='FF0B0F14'):
    """
    Pick a readable foreground color (light or dark) for a given background
    hex, via relative luminance (WCAG-style, gamma-corrected).

    Falls back to `light` if hex_color can't be parsed - the dialog's body
    is dark overall, so defaulting to light text is the safer failure mode.
    """
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except (ValueError, TypeError):
        return light

    def _linear(channel):
        c = channel / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)
    return dark if luminance > LUMINANCE_CUTOFF else light


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def resolve_branding(provider_key, overrides=None):
    """
    Build the fully-resolved branding dict that DeviceAuthWindow.set_branding()
    expects, merging (later wins):

        DEFAULT_BRANDING  ->  PROVIDER_BRANDING[provider_key]  ->  overrides

    `overrides` is typically the values read straight off a BaseDeviceAuth
    subclass (header_color, accent_color, logo, logo_needs_light_bg), so
    per-class attributes always take priority over the shared table. A None
    in `overrides` means "the subclass didn't set this", not "clear it", and
    is ignored rather than blanking out a table/default value.

    Any *_text_color / *_faint value the caller doesn't supply is derived
    automatically - that's the point of this function: a provider only ever
    has to think about two colors (plus an optional logo).
    """
    cfg = dict(DEFAULT_BRANDING)
    cfg.update(PROVIDER_BRANDING.get(provider_key) or {})
    if overrides:
        cfg.update((k, v) for k, v in overrides.items() if v is not None)

    header_color = cfg.get('header_color') or DEFAULT_BRANDING['header_color']
    accent_color = cfg.get('accent_color') or DEFAULT_BRANDING['accent_color']

    return {
        'logo': cfg.get('logo'),
        'header_color': header_color,
        'header_text_color': cfg.get('header_text_color') or contrast_text_color(header_color),
        'accent_color': accent_color,
        'accent_color_faint': cfg.get('accent_color_faint') or with_alpha(accent_color, ALPHA_FAINT),
        'accent_text_color': cfg.get('accent_text_color') or contrast_text_color(accent_color),
        'logo_backdrop_color': (
            cfg.get('logo_backdrop_color')
            or ('FFFFFFFF' if cfg.get('logo_needs_light_bg') else '00FFFFFF')
        ),
    }
