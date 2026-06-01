#!/usr/bin/env python3
"""In-place package rename inside an extracted Kodi APK's dex + arsc.

Why this exists: apktool's baksmali->smali round-trip re-assembles
classes.dex, and on Kodi that subtly breaks JNI native registration, so
System.loadLibrary("kodi") crashes in nativeLoad on launch (this is what
sank 21.3-povil.27). Instead of editing smali, we patch the ORIGINAL dex
bytes directly: org/xbmc/kodi -> org/mora/kodi is the same length (13
chars), so every string offset/length in the dex stays valid; we only fix
the dex header's Adler-32 checksum and SHA-1 signature. The compiled
bytecode is otherwise byte-identical to upstream Kodi -- nothing for
apktool to break.

Three string forms get renamed in the dex:
  slash  Lorg/xbmc/kodi/Main;      class descriptors
  dotted org.xbmc.kodi.media       authorities / Class.getName()
  dash   ...$org-xbmc-kodi-Splash  synthetic-lambda method names

Only classes*.dex are patched here. resources.arsc is intentionally NOT
touched: apktool's own rebuilt arsc already carries the renamed package and
stays STORED (uncompressed); re-injecting/patching arsc via zip recompresses
it, and modern Android refuses to install an apk with a compressed
resources.arsc. (If a resources.arsc happens to be present in the dir it is
patched in place for completeness, but the workflow does not pass one.)

Usage:
    patch_dex_package.py <dir-with-classes.dex> <old.pkg> <new.pkg>

<old.pkg>/<new.pkg> are the dotted ids, e.g. org.xbmc.kodi org.xbmc.povi.
They MUST be the same length. Exits non-zero (failing the build) if any
old reference survives.
"""
import glob
import hashlib
import os
import struct
import sys
import zlib


def forms(pkg):
    """The three byte forms a package id appears as inside a dex."""
    return {
        'slash': pkg.replace('.', '/').encode('ascii'),
        'dotted': pkg.encode('ascii'),
        'dash': pkg.replace('.', '-').encode('ascii'),
    }


def patch_dex(path, old, new):
    data = bytearray(open(path, 'rb').read())
    of, nf = forms(old), forms(new)
    for key in ('slash', 'dotted', 'dash'):
        assert len(of[key]) == len(nf[key]), 'package ids must be same length'
        data = bytearray(data.replace(of[key], nf[key]))
    # DEX header: checksum (Adler-32) @ offset 8 [4 bytes],
    #             signature (SHA-1)  @ offset 12 [20 bytes].
    # SHA-1 covers everything after the signature field (offset 32 on).
    data[12:32] = hashlib.sha1(bytes(data[32:])).digest()
    # Adler-32 covers everything after the checksum field (offset 12 on).
    data[8:12] = struct.pack('<I', zlib.adler32(bytes(data[12:])) & 0xffffffff)
    left = data.count(of['slash'])
    if left:
        sys.exit('ERROR: {0}: {1} leftover {2} refs'.format(
            path, left, of['slash'].decode()))
    open(path, 'wb').write(data)
    print('patched {0}: {1} x{2}, leftover 0, checksums fixed'.format(
        os.path.basename(path), nf['slash'].decode(),
        data.count(nf['slash'])))


def patch_arsc(path, old, new):
    if not os.path.isfile(path):
        return
    a = open(path, 'rb').read()
    for o, n in ((old, new), (old.replace('.', '/'), new.replace('.', '/'))):
        a = a.replace(o.encode('utf-16-le'), n.encode('utf-16-le'))
    open(path, 'wb').write(a)
    print('patched resources.arsc (utf-16 package strings)')


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    work, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
    if len(old) != len(new):
        sys.exit('ERROR: old/new package ids must be the same length '
                 '({0} vs {1})'.format(old, new))
    dexes = sorted(glob.glob(os.path.join(work, 'classes*.dex')))
    if not dexes:
        sys.exit('ERROR: no classes*.dex found in ' + work)
    for dex in dexes:
        patch_dex(dex, old, new)
    patch_arsc(os.path.join(work, 'resources.arsc'), old, new)


if __name__ == '__main__':
    main()
