
import zipfile
import xbmcvfs
import os,gzip,shutil
from resources.lib.subs_engine import log
exts = [".idx", ".sup", ".srt", ".sub", ".str", ".ass"]
def convert_to_utf(file):
    import codecs
    try:
        with codecs.open(file, "r", "cp1255") as f:
            srt_data = f.read()

        with codecs.open(file, 'w', 'utf-8') as output:
            output.write(srt_data)
    except: pass
    
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