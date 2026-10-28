"""List an XBT texture bundle: python xbt_info.py Textures.xbt"""
import struct, sys, collections

def read(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'XBTF', d[:4]
    ver = d[4:5]; n = struct.unpack_from('<I', d, 5)[0]; p = 9
    files = []
    for _ in range(n):
        name = d[p:p+256].split(b'\0')[0].decode('utf-8'); p += 256
        loop, nf = struct.unpack_from('<II', d, p); p += 8
        frames = []
        for _ in range(nf):
            w, h, fmt, packed, unpacked, dur, off = struct.unpack_from('<IIIQQIQ', d, p); p += 40
            frames.append((w, h, fmt, packed, unpacked, dur, off))
        files.append((name, loop, frames))
    return ver, files, d

if __name__ == '__main__':
    ver, files, d = read(sys.argv[1])
    print('version', ver, 'files', len(files))
    fmts = collections.Counter((f[2][0][2], f[2][0][3] != f[2][0][4]) for f in files)
    print('format/packed counts', fmts)
    for f in files[:15]:
        print(f[0], f[2][0][:5])
