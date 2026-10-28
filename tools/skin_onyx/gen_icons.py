# -*- coding: utf-8 -*-
"""Draw the player (OSD) icons of skin.povil.onyx into media/povil/osd.

    python gen_icons.py ../../skin.povil.onyx/media/povil

Each icon is drawn at 4x and reduced: <name>.png is the white icon (not
focused), <name>_fo.png the focused button (a gold disc with a dark icon).
"""
import math
import os
import sys

from PIL import Image, ImageDraw

OUT = os.path.join(sys.argv[1], 'osd')
os.makedirs(OUT, exist_ok=True)
SIZE, SS = 96, 4
S = SIZE * SS
GOLD = (217, 183, 126, 255)
INK = (23, 19, 13, 255)
WHITE = (255, 255, 255, 255)


def P(v):
    return v * SS


def canvas():
    return Image.new('L', (S, S), 0)


def tri(d, pts):
    d.polygon([(P(x), P(y)) for x, y in pts], fill=255)


def rbar(d, x0, y0, x1, y1, r):
    d.rounded_rectangle((P(x0), P(y0), P(x1), P(y1)), P(r), fill=255)


def ring(d, cx, cy, r, w, start=0, end=360):
    d.arc((P(cx - r), P(cy - r), P(cx + r), P(cy + r)), start, end, fill=255, width=P(w))


def play(d):
    tri(d, [(36, 26), (36, 70), (72, 48)])


def pause(d):
    rbar(d, 31, 27, 42, 69, 3)
    rbar(d, 54, 27, 65, 69, 3)


def stop(d):
    rbar(d, 31, 31, 65, 65, 5)


def rewind(d):
    tri(d, [(48, 30), (48, 66), (24, 48)])
    tri(d, [(72, 30), (72, 66), (48, 48)])


def forward(d):
    tri(d, [(24, 30), (24, 66), (48, 48)])
    tri(d, [(48, 30), (48, 66), (72, 48)])


def subtitles(d):
    d.rounded_rectangle((P(18), P(26), P(78), P(70)), P(9), outline=255, width=P(4))
    rbar(d, 27, 44, 47, 49, 2)
    rbar(d, 52, 44, 69, 49, 2)
    rbar(d, 27, 55, 39, 60, 2)
    rbar(d, 44, 55, 69, 60, 2)


def audio(d):
    tri(d, [(22, 40), (34, 40), (48, 28), (48, 68), (34, 56), (22, 56)])
    ring(d, 50, 48, 12, 4, -55, 55)
    ring(d, 50, 48, 22, 4, -55, 55)


def source(d):
    # two arrows: right on top, left below
    rbar(d, 24, 34, 62, 39, 2)
    tri(d, [(60, 26), (74, 36.5), (60, 47)])
    rbar(d, 34, 57, 72, 62, 2)
    tri(d, [(36, 49), (22, 59.5), (36, 70)])


def episodes(d):
    for y in (32, 46, 60):
        rbar(d, 22, y, 30, y + 6, 3)
        rbar(d, 36, y, 74, y + 6, 3)


def sync(d):
    ring(d, 48, 50, 20, 4)
    rbar(d, 46, 37, 50, 52, 2)
    rbar(d, 46, 48, 60, 52, 2)
    rbar(d, 42, 22, 54, 27, 2)


def settings(d):
    cx, cy, r1, r2, teeth = 48, 48, 26, 19, 8
    pts = []
    for i in range(teeth * 4):
        a = 2 * math.pi * i / (teeth * 4)
        r = r1 if (i % 4) in (1, 2) else r2
        pts.append((P(cx + r * math.cos(a)), P(cy + r * math.sin(a))))
    d.polygon(pts, fill=255)
    d.ellipse((P(cx - 8), P(cy - 8), P(cx + 8), P(cy + 8)), fill=0)


def info(d):
    ring(d, 48, 48, 26, 4)
    d.ellipse((P(45), P(31), P(51), P(37)), fill=255)
    rbar(d, 45, 42, 51, 65, 2)


def skipback(d):
    ring(d, 48, 50, 22, 4, 110, 400)
    tri(d, [(30, 20), (30, 40), (14, 30)])


def skipfwd(d):
    ring(d, 48, 50, 22, 4, 140, 430)
    tri(d, [(66, 20), (66, 40), (82, 30)])


ICONS = dict(play=play, pause=pause, stop=stop, rewind=rewind, forward=forward, subtitles=subtitles,
             audio=audio, source=source, episodes=episodes, sync=sync, settings=settings, info=info,
             skipback=skipback, skipfwd=skipfwd)

for name, draw in ICONS.items():
    mask = canvas()
    draw(ImageDraw.Draw(mask))
    mask = mask.resize((SIZE, SIZE), Image.LANCZOS)
    white = Image.new('RGBA', (SIZE, SIZE), (255, 255, 255, 0))
    white.putalpha(mask)
    white.save(os.path.join(OUT, name + '.png'), optimize=True)
    disc = Image.new('L', (S, S), 0)
    ImageDraw.Draw(disc).ellipse((0, 0, S - 1, S - 1), fill=255)
    disc = disc.resize((SIZE, SIZE), Image.LANCZOS)
    fo = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    fo.paste(Image.new('RGBA', (SIZE, SIZE), GOLD), (0, 0), disc)
    fo.paste(Image.new('RGBA', (SIZE, SIZE), INK), (0, 0), mask)
    fo.save(os.path.join(OUT, name + '_fo.png'), optimize=True)
print('icons:', ', '.join(ICONS))
