# -*- coding: utf-8 -*-
"""Draw the dialogs' panel and focus box of skin.povil.onyx into media/povil.

    python gen_dialog_textures.py ../../skin.povil.onyx/media/povil

Onyx's own dialogs (the context menu, the yes/no and OK questions, the select lists, the
keyboard, the add-on dialogs ...) all sit on one texture, img/DialogCE.png -- a pure black
square with a white hairline -- and mark the focused row with img/MediaButton2.png, a flat
grey rectangle. patch_onyx.py points every use of the two at the textures drawn here, which
keep the originals' geometry so that no dialog's layout changes:

  panel.png      320x320, the body inset 24 pixels like the original (9-slice border 128):
                 charcoal glass with a soft gold hairline and a shadow in the margin.
  focus_box.png  a rounded box for the focused row or button (9-slice border 14, so it fits
                 a control from 28 pixels high): a touch of white with a brighter edge;
                 the skin tints it as it tinted the original.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

OUT = sys.argv[1]
SS = 4


def panel():
    size, inset, radius = 320, 24, 26
    big = size * SS
    box = (inset * SS, inset * SS, (size - inset) * SS - 1, (size - inset) * SS - 1)
    # the shadow, in the margin around the body
    shade = Image.new('L', (big, big), 0)
    ImageDraw.Draw(shade).rounded_rectangle((box[0], box[1] + 5 * SS, box[2], box[3] + 5 * SS), radius * SS, fill=170)
    shade = shade.filter(ImageFilter.GaussianBlur(9 * SS))
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    img.putalpha(shade)
    # the body: charcoal, a little lighter at the top
    body = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(body)
    for y in range(box[1], box[3] + 1):
        t = (y - box[1]) / float(box[3] - box[1])
        draw.line((box[0], y, box[2], y), fill=(int(34 - 10 * t), int(35 - 10 * t), int(41 - 11 * t), 250))
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius * SS, fill=255)
    body.putalpha(Image.composite(body.split()[3], Image.new('L', (big, big), 0), mask))
    img = Image.alpha_composite(img, body)
    # the hairline: the build's gold, soft
    edge = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(box, radius * SS, outline=(217, 183, 126, 120), width=int(1.5 * SS))
    img = Image.alpha_composite(img, edge)
    img.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, 'panel.png'), optimize=True)


def focus_box():
    width, height, radius = 96, 64, 12
    big = Image.new('RGBA', (width * SS, height * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle((0, 0, width * SS - 1, height * SS - 1), radius * SS, fill=(255, 255, 255, 44))
    draw.rounded_rectangle((0, 0, width * SS - 1, height * SS - 1), radius * SS, outline=(255, 255, 255, 96), width=int(1.5 * SS))
    big.resize((width, height), Image.LANCZOS).save(os.path.join(OUT, 'focus_box.png'), optimize=True)


panel()
focus_box()
print('dialog textures drawn: panel.png, focus_box.png')
