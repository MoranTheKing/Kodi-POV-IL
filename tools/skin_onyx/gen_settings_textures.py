# -*- coding: utf-8 -*-
"""Draw the settings screens' own pictures into media/povil/settings.

    python gen_settings_textures.py ../../skin.povil.onyx/media/povil

row_focus.png   the focused row or tile: a faint fill inside a gold frame (9-slice, border 30)
switch_*.png    a setting's switch, off and on (and both dimmed, for a setting that is locked)
arrow_*.png     a spinner's two arrows (white; tinted gold when focused)
slider_bar.png  a slider's track, as tall as its knob's picture (9-slice, border 16 left and right)

Needs Pillow; the XML generators do not.
"""
import os
import sys

from PIL import Image, ImageDraw

OUT = os.path.join(sys.argv[1], 'settings')
os.makedirs(OUT, exist_ok=True)
SS = 4
GOLD = (217, 183, 126)
WHITE = (245, 242, 236)


def save(img, name):
    img.save(os.path.join(OUT, name), optimize=True)


def layer(size, draw):
    """An anti-aliased mask: drawn at SS times the size, then reduced."""
    big = Image.new('L', (size[0] * SS, size[1] * SS), 0)
    draw(ImageDraw.Draw(big))
    return big.resize(size, Image.LANCZOS)


def tinted(mask, colour, alpha=255):
    img = Image.new('RGBA', mask.size, colour + (0,))
    img.putalpha(mask.point(lambda v: v * alpha // 255))
    return img


def row_focus():
    size, r, stroke = (120, 120), 24, 3
    fill = layer(size, lambda d: d.rounded_rectangle((0, 0, size[0] * SS - 1, size[1] * SS - 1), r * SS, fill=255))
    ring = layer(size, lambda d: d.rounded_rectangle((0, 0, size[0] * SS - 1, size[1] * SS - 1), r * SS, outline=255, width=stroke * SS))
    img = tinted(fill, WHITE, 34)
    img.alpha_composite(tinted(ring, GOLD))
    return img


def switch(on, dim=False):
    size = (88, 48)
    track = layer(size, lambda d: d.rounded_rectangle((0, 4 * SS, size[0] * SS - 1, (size[1] - 4) * SS - 1), 20 * SS, fill=255))
    cx = (size[0] - 24) if on else 24
    knob = layer(size, lambda d: d.ellipse(((cx - 15) * SS, 9 * SS, (cx + 15) * SS, 39 * SS), fill=255))
    img = tinted(track, GOLD if on else WHITE, 255 if on else 60)
    img.alpha_composite(tinted(knob, (23, 19, 13) if on else WHITE, 255 if on else 215))
    if dim:
        img.putalpha(img.getchannel('A').point(lambda v: v * 90 // 255))
    return img


def arrow(up):
    size = (40, 40)
    pts = [(9, 25), (20, 14), (31, 25)] if up else [(9, 15), (20, 26), (31, 15)]
    mask = layer(size, lambda d: d.line([(x * SS, y * SS) for x, y in pts], fill=255, width=4 * SS, joint='curve'))
    return tinted(mask, (255, 255, 255))


def slider_bar():
    size = (64, 64)
    mask = layer(size, lambda d: d.rounded_rectangle((0, 28 * SS, size[0] * SS - 1, 36 * SS - 1), 4 * SS, fill=255))
    return tinted(mask, (255, 255, 255))


save(row_focus(), 'row_focus.png')
save(switch(False), 'switch_off.png')
save(switch(True), 'switch_on.png')
save(switch(False, True), 'switch_off_dim.png')
save(switch(True, True), 'switch_on_dim.png')
save(arrow(True), 'arrow_up.png')
save(arrow(False), 'arrow_down.png')
save(slider_bar(), 'slider_bar.png')
print('settings textures in', OUT, len(os.listdir(OUT)))
