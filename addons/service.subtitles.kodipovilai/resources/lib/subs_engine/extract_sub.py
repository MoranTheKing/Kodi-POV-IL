
import zipfile
import xbmcvfs
import os,gzip,shutil
from resources.lib.subs_engine import log
exts = [".idx", ".sup", ".srt", ".sub", ".str", ".ass"]
def convert_to_utf(file):
    """Normalize a downloaded subtitle file to UTF-8 on disk.

    Historically this ASSUMED cp1255 (legacy Israeli Hebrew) and blindly
    re-decoded EVERY downloaded file that way -- which corrupted any file that
    was actually UTF-8. An English/SDH sub is pure ASCII except its music note
    U+266A (bytes E2 99 AA), and cp1255 turns exactly those bytes into
    'gimel + trademark + multiplication' -- the ugly garble users saw at the
    start/end of song lines. ASCII is identical in both encodings, so the
    English text survived and only the note was mangled; a file carrying a byte
    UNdefined in cp1255 raised and was left alone, which is why only some subs
    broke.

    Now: try UTF-8 first (utf-8-sig, so a leading BOM is dropped). A genuine
    cp1255 Hebrew file is essentially never valid UTF-8 -- its 0xE0-0xFA letter
    bytes are not valid UTF-8 continuation bytes -- so it fails the strict UTF-8
    decode and correctly falls through to cp1255, while a real UTF-8 file
    (English with a music note, or modern UTF-8 Hebrew) is preserved untouched.
    Fail-open: on any read/decode/write error the file is left exactly as it was
    (the historical behaviour when the cp1255 decode raised)."""
    import codecs
    try:
        with open(file, 'rb') as f:
            raw = f.read()
    except Exception:
        return
    text = None
    for enc in ('utf-8-sig', 'cp1255'):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        return                       # unknown encoding -> leave file untouched
    try:
        with codecs.open(file, 'w', 'utf-8') as output:
            output.write(text)
    except Exception:
        pass
    
def extract(archive_file,MySubFolder):
    try:
        with zipfile.ZipFile(archive_file, 'r') as zip_ref:
            names = zip_ref.namelist()
            zip_ref.extractall(MySubFolder)

        os.remove(archive_file)
        # Return a subtitle file THIS archive actually contained -- keyed off the
        # zip's own namelist, NOT "the first subtitle-shaped file in the shared
        # folder". The folder is reused by every source/title, so scanning the
        # whole folder could hand back a LEFTOVER from a previous, unrelated
        # download (a different title, or an English file from another source
        # stamped Hebrew). We resolve each entry to its extracted path.
        for name in names:
            base = os.path.basename(name)
            if not base:
                continue                      # directory entry
            if os.path.splitext(base)[1].lower() in exts:
                cand = os.path.join(MySubFolder, *name.split('/'))
                if not os.path.isfile(cand):
                    cand = os.path.join(MySubFolder, base)
                if os.path.isfile(cand):
                    convert_to_utf(cand)
                    return cand
        # Fallback for an oddly-packed archive with no recognised entry name:
        # the old whole-folder scan (kept so such archives still work).
        for file_ in xbmcvfs.listdir(MySubFolder)[1]:
            ufile = file_
            file_ = os.path.join(MySubFolder, ufile)
            for items in exts:
                if os.path.splitext(ufile)[1] == items:
                    convert_to_utf(file_)

                    return file_
    except Exception as e:
        log.warning('Error Extract:'+str(e))
        return archive_file
    return '0'
def g_extract(archive_file,dest,MySubFolder):
    log.warning(archive_file)
    with gzip.open(archive_file, 'rb') as f_in:
            with open(dest, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
    os.remove(archive_file)
    for file_ in xbmcvfs.listdir(MySubFolder)[1]:
        ufile = file_
        file_ = os.path.join(MySubFolder, ufile)
        if os.path.splitext(ufile)[1] in exts:
            convert_to_utf(file_)
            
            return file_