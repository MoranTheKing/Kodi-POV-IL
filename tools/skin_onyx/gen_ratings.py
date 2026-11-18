# -*- coding: utf-8 -*-
"""Draw the rating marks of skin.povil.onyx into media/povil/ratings.

    python gen_ratings.py ../../skin.povil.onyx/media/povil

One mark per site in the ratings row (see ratings_row.py): a name tag in the site's
own colours for IMDb, TMDb and Trakt, a tomato (fresh, certified, rotten) and a
popcorn bucket (upright, spilled) for Rotten Tomatoes' critics and audience, three
dots for Letterboxd, and for Metacritic its initial on a ringed disc beside a plain
rounded square that the skin tints by the verdict and writes the score on. Drawn here, at 4x and reduced; no site's artwork
is copied. Shown 28 pixels high, kept at twice that.
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(sys.argv[1], 'ratings')
os.makedirs(OUT, exist_ok=True)
FONT = os.path.join(HERE, '..', '..', 'skin.povil.onyx', 'fonts', 'Heebo-Bold.ttf')
H, SS = 56, 4          # kept height, supersampling


def P(v):
    return int(round(v * SS))


def canvas(width):
    return Image.new('RGBA', (P(width), P(H)), (0, 0, 0, 0))


def save(img, name):
    img.resize((img.width // SS, img.height // SS), Image.LANCZOS).save(os.path.join(OUT, name + '.png'), optimize=True)


def tag(name, text, fill, ink, width=112, size=30):
    """A name tag: the site's short name on its own colour."""
    img = canvas(width)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, P(4), P(width) - 1, P(H - 4) - 1), P(9), fill=fill)
    font = ImageFont.truetype(FONT, P(size))
    box = d.textbbox((0, 0), text, font=font)
    d.text(((P(width) - (box[2] - box[0])) / 2 - box[0], (P(H) - (box[3] - box[1])) / 2 - box[1]), text, font=font, fill=ink)
    save(img, name)


def tomato(name, body, leaf, ring=None):
    img = canvas(H)
    d = ImageDraw.Draw(img)
    if ring:
        d.ellipse((P(1), P(3), P(55), P(57 - 2)), fill=ring)
        d.ellipse((P(6), P(8), P(50), P(50)), fill=body)
    else:
        d.ellipse((P(4), P(10), P(52), P(54)), fill=body)
    # the calyx: a small five-pointed star on top
    cx, cy, outer, inner = 28, (15 if not ring else 14), 13, 5
    points = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / 5
        points.append((P(cx + radius * math.cos(angle)), P(cy + radius * math.sin(angle) * 0.7)))
    d.polygon(points, fill=leaf)
    save(img, name)


def splat(name, fill):
    """A rotten tomato: a green splat."""
    img = canvas(H)
    d = ImageDraw.Draw(img)
    cx, cy = 28, 30
    points = []
    for i in range(24):
        radius = (24, 15, 21, 13)[i % 4]
        angle = i * math.pi / 12 + 0.2
        points.append((P(cx + radius * math.cos(angle)), P(cy + radius * math.sin(angle) * 0.92)))
    d.polygon(points, fill=fill)
    d.ellipse((P(cx - 14), P(cy - 13), P(cx + 14), P(cy + 13)), fill=fill)
    save(img, name)


def popcorn(name, bucket, stripe, corn):
    img = canvas(H)
    d = ImageDraw.Draw(img)
    # popped corn above the rim
    for x, y, r in ((17, 17, 8), (28, 12, 9), (39, 17, 8), (22, 22, 7), (34, 22, 7)):
        d.ellipse((P(x - r), P(y - r), P(x + r), P(y + r)), fill=corn)
    # the bucket, narrower at its foot, with two stripes
    d.polygon([(P(10), P(22)), (P(46), P(22)), (P(41), P(53)), (P(15), P(53))], fill=bucket)
    for left in (19.5, 31.5):
        d.polygon([(P(left), P(22)), (P(left + 5), P(22)), (P(left + 4.4), P(53)), (P(left + 0.6), P(53))], fill=stripe)
    save(img, name)


def dots(name):
    """Letterboxd: three dots, the middle one over its neighbours."""
    width = 92
    img = canvas(width)
    for x, fill in ((20, (255, 128, 0, 255)), (72, (64, 188, 244, 255)), (46, (0, 224, 84, 255))):
        layer = canvas(width)
        ImageDraw.Draw(layer).ellipse((P(x - 18), P(10), P(x + 18), P(46)), fill=fill)
        img = Image.alpha_composite(img, layer)
    save(img, name)


def lettered_disc(name, letter, disc, ring, ink):
    """Metacritic's mark: a dark disc in a yellow ring with the site's initial (the owner, Nov 2026:
    a score in a bare coloured square did not say whose score it was)."""
    img = canvas(H)
    d = ImageDraw.Draw(img)
    d.ellipse((P(2), P(2), P(H - 2) - 1, P(H - 2) - 1), fill=ring)
    d.ellipse((P(6.5), P(6.5), P(H - 6.5) - 1, P(H - 6.5) - 1), fill=disc)
    font = ImageFont.truetype(FONT, P(31))
    box = d.textbbox((0, 0), letter, font=font)
    d.text(((P(H) - (box[2] - box[0])) / 2 - box[0], (P(H) - (box[3] - box[1])) / 2 - box[1]), letter, font=font, fill=ink)
    save(img, name)


def square(name):
    """Metacritic's score plate: the skin tints it by the verdict and writes the score on it."""
    width = 68
    img = canvas(width)
    ImageDraw.Draw(img).rounded_rectangle((0, P(2), P(width) - 1, P(H - 2) - 1), P(10), fill=(255, 255, 255, 255))
    save(img, name)


def badge(name):
    """The plate of the rating on a poster's corner: dark glass with a hairline and a gold star at its left;
    the skin writes the number beside the star. Kept at twice its size on screen (78 x 34)."""
    width, height = 156, 68
    img = Image.new('RGBA', (P(width), P(height)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, P(width) - 1, P(height) - 1), P(height / 2), fill=(255, 255, 255, 64))
    d.rounded_rectangle((P(2), P(2), P(width - 2) - 1, P(height - 2) - 1), P(height / 2 - 2), fill=(13, 13, 16, 224))
    cx, cy, outer, inner = 40, 33, 17, 7.2
    points = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / 5
        points.append((P(cx + radius * math.cos(angle)), P(cy + 1 + radius * math.sin(angle))))
    d.polygon(points, fill=(217, 183, 126, 255))
    img.resize((width, height), Image.LANCZOS).save(os.path.join(OUT, name + '.png'), optimize=True)


tag('imdb', 'IMDb', (245, 197, 24, 255), (0, 0, 0, 255))
tag('tmdb', 'TMDB', (13, 37, 63, 255), (1, 180, 228, 255), size=27)
tag('trakt', 'trakt', (237, 28, 36, 255), (255, 255, 255, 255))
tomato('tomato_fresh', (250, 50, 10, 255), (0, 145, 45, 255))
tomato('tomato_certified', (250, 50, 10, 255), (0, 145, 45, 255), ring=(255, 214, 0, 255))
splat('tomato_rotten', (10, 200, 85, 255))
popcorn('popcorn_upright', (250, 50, 10, 255), (255, 255, 255, 255), (255, 209, 92, 255))
popcorn('popcorn_spilled', (0, 145, 45, 255), (255, 255, 255, 255), (198, 214, 150, 255))
dots('letterboxd')
lettered_disc('meta', 'M', (16, 16, 18, 255), (255, 204, 51, 255), (255, 255, 255, 255))
square('square')
badge('badge')
print('rating marks drawn: %s' % ', '.join(sorted(os.listdir(OUT))))
