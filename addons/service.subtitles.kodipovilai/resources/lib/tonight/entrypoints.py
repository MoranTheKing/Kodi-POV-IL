"""One-time integrated home shortcut for the build's favourites-based skins."""
import os
import re
import tempfile
import xml.etree.ElementTree as ET

ACTION='RunScript(service.subtitles.kodipovilai,action=tonight)'
MARKER='<!-- MORAN_TONIGHT_SEEN_V1 -->'
OLD_NAME='הערב שלי — התנסות'
NAME='הערב שלי'
LEGACY_ICON='special://home/addons/service.subtitles.kodipovilai/icon.png'
ICON=('special://home/addons/service.subtitles.kodipovilai/'
      'resources/media/tonight.png')


def insert(content):
    try:
        root=ET.fromstring(content)
        if root.tag!='favourites':return content
    except ET.ParseError:return content
    # Upgrade only our exact generated shortcut. Custom names/thumbs and a
    # shortcut the user deleted remain owned by the user.
    replacement=('name="'+NAME+'" thumb="'+ICON+'">'+ACTION)
    for generated_name in (OLD_NAME,NAME):
        legacy=('name="'+generated_name+'" thumb="'+LEGACY_ICON+'">'+ACTION)
        content=content.replace(legacy,replacement)
    content=content.replace(
        'name="'+OLD_NAME+'" thumb="'+ICON+'">'+ACTION,replacement)
    if MARKER in content:return content
    exists=any((f.text or '').strip()==ACTION for f in root.findall('favourite'))
    snippet='' if exists else ('  <favourite name="'+NAME+'" thumb="'+ICON+'">'+ACTION+'</favourite>\n')
    if not list(root) and not (root.text or '').strip():
        content=re.sub(r'<favourites\s*/>', '<favourites></favourites>',content,count=1)
    # Preserve all existing bytes, names and custom actions.
    return re.sub(r'</favourites>\s*$',lambda m:snippet+MARKER+'\n'+m.group(),content,count=1)


def ensure():
    import xbmcvfs
    path=xbmcvfs.translatePath('special://profile/favourites.xml')
    if not os.path.isfile(path):return 'missing'
    with open(path,encoding='utf-8',newline='') as f:before=f.read()
    after=insert(before)
    if after==before:return 'unchanged'
    fd,tmp=tempfile.mkstemp(prefix='.tonight-entry-',dir=os.path.dirname(path))
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:f.write(after)
        # Do not overwrite a concurrent user edit detected during preparation.
        with open(path,encoding='utf-8',newline='') as f:
            if f.read()!=before:return 'changed_concurrently'
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return 'added'
