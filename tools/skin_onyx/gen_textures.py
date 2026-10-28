"""Draw the Kodi POV IL textures for skin.povil.onyx/media/povil (4x supersampled, then reduced)."""
import math, os, sys
from PIL import Image, ImageDraw, ImageFilter

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
SS = 4


def save(img, name):
    img.save(os.path.join(OUT, name), optimize=True)


def rounded_mask(w, h, r):
    big = Image.new('L', (w * SS, h * SS), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=255)
    m = big.resize((w, h), Image.LANCZOS)
    img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    img.putalpha(m)
    return img


def ring(w, h, r, stroke):
    big = Image.new('L', (w * SS, h * SS), 0)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=255)
    d.rounded_rectangle((stroke * SS, stroke * SS, (w - stroke) * SS - 1, (h - stroke) * SS - 1),
                        max(1, (r - stroke)) * SS, fill=0)
    m = big.resize((w, h), Image.LANCZOS)
    img = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    img.putalpha(m)
    return img


def glow(w, h, r, spread, strength):
    """A soft halo around a rounded rect (for the focused item); centre left clear."""
    W, H = w + 2 * spread, h + 2 * spread
    m = Image.new('L', (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle((spread, spread, spread + w - 1, spread + h - 1), r, fill=int(255 * strength))
    m = m.filter(ImageFilter.GaussianBlur(spread / 2.2))
    hole = Image.new('L', (W, H), 0)
    ImageDraw.Draw(hole).rounded_rectangle((spread + 2, spread + 2, spread + w - 3, spread + h - 3), r, fill=255)
    m = Image.composite(Image.new('L', (W, H), 0), m, hole)
    img = Image.new('RGBA', (W, H), (255, 255, 255, 0))
    img.putalpha(m)
    return img


def shadow(w, h, r, spread, strength):
    W, H = w + 2 * spread, h + 2 * spread
    m = Image.new('L', (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle((spread, spread + spread // 4, spread + w - 1, spread + h - 1 + spread // 4), r, fill=int(255 * strength))
    m = m.filter(ImageFilter.GaussianBlur(spread / 2.5))
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    img.putalpha(m)
    return img


def gradient(w, h, stops, axis):
    """stops: [(pos 0..1, alpha 0..255)] along axis 'x' (left->right) or 'y' (top->bottom); smoothstep between stops."""
    n = w if axis == 'x' else h
    vals = []
    for i in range(n):
        p = i / (n - 1)
        for (p0, a0), (p1, a1) in zip(stops, stops[1:]):
            if p0 <= p <= p1:
                t = 0 if p1 == p0 else (p - p0) / (p1 - p0)
                t = t * t * (3 - 2 * t)
                vals.append(int(round(a0 + (a1 - a0) * t)))
                break
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    px = img.load()
    for i, a in enumerate(vals):
        if axis == 'x':
            for y in range(h):
                px[i, y] = (0, 0, 0, a)
        else:
            for x in range(w):
                px[x, i] = (0, 0, 0, a)
    return img


def vignette(w, h):
    img = Image.new('L', (w, h), 0)
    px = img.load()
    for y in range(h):
        for x in range(w):
            dx = (x - w / 2) / (w / 2); dy = (y - h / 2) / (h / 2)
            d = min(1.0, math.sqrt(dx * dx * 0.8 + dy * dy * 1.1))
            px[x, y] = int(255 * 0.55 * (d ** 2.2))
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0)); out.putalpha(img)
    return out


save(rounded_mask(400, 600, 22), 'mask_poster.png')
save(rounded_mask(640, 360, 18), 'mask_landscape.png')
save(rounded_mask(400, 400, 22), 'mask_square.png')
save(rounded_mask(120, 120, 24), 'rounded_fill.png')          # 9-slice panels (border 30)
save(rounded_mask(64, 64, 32), 'pill.png')                     # 9-slice pills (border 31)
save(ring(120, 120, 24, 4), 'focus_ring.png')                  # 9-slice (border 30), tinted gold
save(ring(120, 120, 24, 2), 'focus_ring_thin.png')
save(glow(120, 120, 24, 36, 0.9), 'focus_glow.png')            # 9-slice (border 66)
save(shadow(120, 120, 24, 30, 0.85), 'shadow.png')             # 9-slice (border 60)
save(gradient(1024, 8, [(0, 0), (0.30, 40), (0.62, 200), (1, 245)], 'x'), 'grad_right.png')   # dark on the right (RTL text)
save(gradient(8, 1024, [(0, 0), (0.38, 60), (0.70, 215), (1, 250)], 'y'), 'grad_bottom.png')
save(gradient(8, 512, [(0, 200), (0.55, 60), (1, 0)], 'y'), 'grad_top.png')
save(gradient(8, 512, [(0, 0), (1, 255)], 'y'), 'grad_simple.png')
save(vignette(480, 270), 'vignette.png')
w = Image.new('RGBA', (8, 8), (255, 255, 255, 255)); save(w, 'white.png')
# Underline with soft ends
u = Image.new('RGBA', (200, 6), (255, 255, 255, 0))
ImageDraw.Draw(u).rounded_rectangle((0, 0, 199, 5), 3, fill=(255, 255, 255, 255)); save(u, 'underline.png')
# Small star for ratings
s = Image.new('L', (64 * SS, 64 * SS), 0)
pts = []
for i in range(10):
    ang = -math.pi / 2 + i * math.pi / 5
    rr = (30 if i % 2 == 0 else 12.5) * SS
    pts.append((32 * SS + rr * math.cos(ang), 33 * SS + rr * math.sin(ang)))
ImageDraw.Draw(s).polygon(pts, fill=255)
star = Image.new('RGBA', (64, 64), (255, 255, 255, 0)); star.putalpha(s.resize((64, 64), Image.LANCZOS)); save(star, 'star.png')
# Progress bar track/fill (rounded, 9-slice border 4)
save(rounded_mask(16, 8, 4), 'progress.png')
print('textures in', OUT, len(os.listdir(OUT)))


# 48px-high pill for chips (9-slice border 24) and a watched check badge
save(rounded_mask(96, 48, 24), 'pill48.png')
c = Image.new('L', (64 * SS, 64 * SS), 0)
dc = ImageDraw.Draw(c)
dc.ellipse((0, 0, 64 * SS - 1, 64 * SS - 1), fill=255)
dc.line([(18 * SS, 33 * SS), (28 * SS, 43 * SS), (46 * SS, 23 * SS)], fill=0, width=6 * SS, joint='curve')
chk = Image.new('RGBA', (64, 64), (255, 255, 255, 0)); chk.putalpha(c.resize((64, 64), Image.LANCZOS)); save(chk, 'check.png')

# Ambient backdrop for items without fanart (Israeli VOD, channels, favourites)
import random
W, H = 1920, 1080
base = Image.new('RGB', (W, H), (9, 9, 11))
glow_l = Image.new('L', (W, H), 0)
d = ImageDraw.Draw(glow_l)
d.ellipse((W * 0.52, -H * 0.55, W * 1.35, H * 0.75), fill=150)
glow_l = glow_l.filter(ImageFilter.GaussianBlur(260))
gold = Image.new('RGB', (W, H), (122, 92, 52))
base = Image.composite(gold, base, glow_l)
glow2 = Image.new('L', (W, H), 0)
ImageDraw.Draw(glow2).ellipse((-W * 0.35, H * 0.45, W * 0.45, H * 1.5), fill=95)
glow2 = glow2.filter(ImageFilter.GaussianBlur(280))
base = Image.composite(Image.new('RGB', (W, H), (28, 44, 58)), base, glow2)
random.seed(7)
noise = Image.effect_noise((W, H), 9).convert('L')
base = Image.blend(base, Image.merge('RGB', (noise, noise, noise)), 0.035)
base.save(os.path.join(os.path.dirname(OUT.rstrip('/')), '..', 'extras', 'povil_ambient.jpg') if False else os.path.join(OUT, 'ambient.jpg'), quality=90, optimize=True, progressive=True)
print('ambient done')
