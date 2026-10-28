"""Write skin.povil.onyx/xml/Font.xml: Heebo for Hebrew + Latin (default),
and Kodi's arial.ttf as a fallback fontset for other scripts."""
import sys
OUT = sys.argv[1]
R, M, SB, B, L = 'Heebo-Regular.ttf', 'Heebo-Medium.ttf', 'Heebo-SemiBold.ttf', 'Heebo-Bold.ttf', 'Heebo-Light.ttf'
# name, Heebo file, size (Onyx's Arial sizes; Heebo runs ~4% smaller, so +1 on body sizes)
FONTS = [
    ('font12', R, 22), ('font13', R, 28), ('EPGfont', R, 24),
    ('size14', R, 22), ('size15', R, 23), ('size16', R, 25), ('size17', R, 27),
    ('size18', R, 28), ('size19', R, 29), ('size20', R, 31), ('size22', R, 34),
    ('size22B', SB, 34), ('size23', R, 35), ('size24', R, 37), ('size24B', SB, 37),
    ('size25', R, 39), ('size26', R, 40), ('size26B', SB, 40), ('size28', R, 43),
    ('size28B', SB, 43), ('Scroll', B, 100), ('Scroll2', B, 50), ('font32_title', M, 40),
    # Kodi POV IL home and views
    ('povil_hero', L, 66), ('povil_hero_small', L, 52), ('povil_meta', R, 26),
    ('povil_meta_bold', SB, 26), ('povil_plot', L, 28), ('povil_menu', M, 31),
    ('povil_row', M, 27), ('povil_chip', M, 23), ('povil_small', R, 21), ('povil_tiny', M, 18),
    ('povil_clock', L, 40), ('povil_badge', SB, 19), ('povil_info_title', L, 58),
]
ARIAL = {'Heebo-Regular.ttf': ('arial.ttf', ''), 'Heebo-Medium.ttf': ('arial.ttf', ''),
         'Heebo-Light.ttf': ('arial.ttf', ''), 'Heebo-SemiBold.ttf': ('arial.ttf', 'bold'),
         'Heebo-Bold.ttf': ('arial.ttf', 'bold')}
out = ['<?xml version="1.0" encoding="UTF-8"?>', '<fonts>',
       '\t<!-- Heebo (SIL OFL 1.1, fonts/heebo_license.txt): Hebrew and Latin. -->',
       '\t<fontset id="Default" unicode="true">']
def block(name, fn, size, style=''):
    s = ['\t\t<font>', '\t\t\t<name>%s</name>' % name, '\t\t\t<filename>%s</filename>' % fn, '\t\t\t<size>%d</size>' % size]
    if style:
        s.append('\t\t\t<style>%s</style>' % style)
    s.append('\t\t</font>')
    return s
for n, fn, sz in FONTS:
    out += block(n, fn, sz)
out += block('Mono30', 'NotoMono-Regular.ttf', 30)
out += ['\t</fontset>',
        '\t<!-- Kodi\'s own arial.ttf: for titles in scripts Heebo does not cover (Settings > Interface > Skin > Fonts). -->',
        '\t<fontset id="Arial" unicode="true">']
for n, fn, sz in FONTS:
    a, st = ARIAL[fn]
    out += block(n, a, sz - 1, st)
out += block('Mono30', 'NotoMono-Regular.ttf', 30)
out += ['\t</fontset>', '</fonts>', '']
open(OUT, 'w', encoding='utf-8', newline='\n').write('\n'.join(out))
print('fonts', len(FONTS) + 1)
