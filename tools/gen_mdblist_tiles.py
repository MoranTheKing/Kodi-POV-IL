#!/usr/bin/env python3
"""Generate My_Movies_MDBList.png / My_Shows_MDBList.png by cloning the existing
Twilight personal tiles and swapping ONLY the top-right service logo (the base
button + folder + film-strip banner are service-independent). The old logo
region is (285,109)-(415,202); we paint an opaque MDBList wordmark badge over it."""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = ('/home/user/Kodi-POV-IL/addons/service.subtitles.kodipovilai/'
        'resources/lib/media_assets/build_icons/Twilight')
FONT_B = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

# The badge covers the old-logo bbox with a small safety margin so the previous
# service mark is fully hidden.
BOX = (281, 105, 419, 206)          # l, u, r, d  (~138 x 101)

TEAL = (43, 169, 156, 255)          # MDBList teal ("MDB")
NAVY = (24, 38, 58, 255)            # dark navy   ("List")
PANEL = (255, 255, 255, 245)        # near-opaque white panel (like TMDB's)
PANEL_BORDER = (43, 169, 156, 255)  # teal hairline border


def _fit_font(text, target_w, start, path=FONT_B, floor=10):
    size = start
    while size > floor:
        f = ImageFont.truetype(path, size)
        w = f.getbbox(text)[2] - f.getbbox(text)[0]
        if w <= target_w:
            return f
        size -= 1
    return ImageFont.truetype(path, floor)


def _badge():
    l, u, r, d = BOX
    w, h = r - l, d - u
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    rad = 16
    dr.rounded_rectangle([1, 1, w - 2, h - 2], radius=rad, fill=PANEL,
                         outline=PANEL_BORDER, width=3)
    # Two-tone wordmark: "MDB" (teal) over "List" (navy), centered.
    inner_w = w - 20
    f1 = _fit_font('MDB', inner_w, 46)
    f2 = _fit_font('List', inner_w, 34)
    def _tw(f, t): b = f.getbbox(t); return b[2] - b[0], b[3] - b[1]
    w1, h1 = _tw(f1, 'MDB')
    w2, h2 = _tw(f2, 'List')
    gap = 4
    total_h = h1 + gap + h2
    y0 = (h - total_h) // 2 - f1.getbbox('MDB')[1]
    dr.text(((w - w1) // 2, y0), 'MDB', font=f1, fill=TEAL)
    y1 = (h - total_h) // 2 + h1 + gap - f2.getbbox('List')[1]
    dr.text(((w - w2) // 2, y1), 'List', font=f2, fill=NAVY)
    return img


def build(src_rel, out_rel):
    src = os.path.join(BASE, src_rel)
    tile = Image.open(src).convert('RGBA')
    badge = _badge()
    tile.alpha_composite(badge, (BOX[0], BOX[1]))
    out = os.path.join(BASE, out_rel)
    tile.save(out)
    print('wrote', out, tile.size)
    return out


# Use the POV variant as the clean base (its logo is fully inside our BOX).
build('Movies/My_Movies_POV.png', 'Movies/My_Movies_MDBList.png')
build('Shows/My_Shows_POV.png', 'Shows/My_Shows_MDBList.png')
print('DONE')
