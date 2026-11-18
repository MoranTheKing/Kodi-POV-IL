"""The line under the chosen tab of the Onyx home, as a texture of the tab's own button (Onyx 1.0.18).

    python tools/skin_onyx/gen_tabline.py skin.povil.onyx/media/povil

The bar is a list of buttons (a tab the viewer took off the bar leaves no gap, gen_home.py BAR), and a list
lays out every child it has -- so the line cannot be a control of its own beside the button. It is the
button's texture: transparent but for a 44 x 4 line at the bottom, one file per cell width. White: the skin
colours it.
"""
import os
import sys

from PIL import Image

HEIGHT, LINE_W, LINE_H = 64, 44, 4
WIDTHS = dict(('tab_line_%d.png' % width, width) for width in (146, 166, 170, 208))     # gen_home.py: TAB_W, TAB_WIDE


def make(width):
    image = Image.new('RGBA', (width, HEIGHT), (255, 255, 255, 0))
    left = (width - LINE_W) // 2
    for x in range(left, left + LINE_W):
        for y in range(HEIGHT - LINE_H, HEIGHT):
            # (rounded ends: the corner pixels are left out)
            if (x in (left, left + LINE_W - 1)) and y in (HEIGHT - LINE_H, HEIGHT - 1):
                continue
            image.putpixel((x, y), (255, 255, 255, 255))
    return image


def main(folder):
    for name, width in WIDTHS.items():
        make(width).save(os.path.join(folder, name))
    print('tab lines generated: %s' % ', '.join(sorted(WIDTHS)))


if __name__ == '__main__':
    main(sys.argv[1])
