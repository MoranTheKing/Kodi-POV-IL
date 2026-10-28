"""Extract an XBT bundle to PNGs: python xbt_extract.py Textures.xbt OUTDIR
Animated (multi-frame) textures are written as name.frameN.png."""
import os, sys
from PIL import Image
import lzo1x
from xbt_info import read

ver, files, d = read(sys.argv[1])
out = sys.argv[2]
bad = 0
for name, loop, frames in files:
    for i, (w, h, fmt, packed, unpacked, dur, off) in enumerate(frames):
        raw = d[off:off + packed]
        if packed != unpacked:
            raw = lzo1x.decompress(raw, unpacked)
        assert fmt == 16, (name, fmt)
        img = Image.frombytes('RGBA', (w, h), raw, 'raw', 'BGRA')
        path = os.path.join(out, name if len(frames) == 1 else '%s.frame%d.png' % (name, i))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not path.lower().endswith('.png'):
            path += '.png'
        img.save(path)
print('extracted', len(files))
