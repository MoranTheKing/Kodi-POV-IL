################################################################################
#      Copyright (C) 2019 drinfernoo                                           #
#                                                                              #
#  This Program is free software; you can redistribute it and/or modify        #
#  it under the terms of the GNU General Public License as published by        #
#  the Free Software Foundation; either version 2, or (at your option)         #
#  any later version.                                                          #
#                                                                              #
#  This Program is distributed in the hope that it will be useful,             #
#  but WITHOUT ANY WARRANTY; without even the implied warranty of              #
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                #
#  GNU General Public License for more details.                                #
#                                                                              #
#  You should have received a copy of the GNU General Public License           #
#  along with XBMC; see the file COPYING.  If not, write to                    #
#  the Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.       #
#  http://www.gnu.org/copyleft/gpl.html                                        #
################################################################################


if __name__ == '__main__':
    import sys

    _handle = int(sys.argv[1])
    _params = sys.argv[2][1:]

    # The Onyx home's favourites and live TV rows and its hero's details: straight to their modules, not the menus
    from urllib.parse import parse_qsl
    _query = dict(parse_qsl(_params))
    if _query.get('mode') == 'favourites_row':
        from resources.libs import favourites_row
        favourites_row.row(_handle)
    elif _query.get('mode') == 'favourite_run':
        from resources.libs import favourites_row
        favourites_row.run(_handle, _query)
    elif _query.get('mode') == 'pvr_row':
        from resources.libs import pvr_row
        pvr_row.row(_handle)
    elif _query.get('mode') == 'pvr_play':
        from resources.libs import pvr_row
        pvr_row.play(_handle, _query)
    elif _query.get('mode') == 'hero_details':
        from resources.libs import hero_details
        hero_details.run()
    else:
        from resources.libs.common import router
        dispatcher = router.Router()
        dispatcher.dispatch(_handle, _params)
