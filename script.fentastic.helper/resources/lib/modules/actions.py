# -*- coding: utf-8 -*-
from xbmc import executebuiltin, getInfoLabel

# from modules.logger import logger


def person_search(params):
    return executebuiltin(
        "RunPlugin(plugin://plugin.video.pov/?mode=person_search&query=%s)"
        % params["query"]
    )


def extras(params):
    return executebuiltin(
        "RunPlugin(%s)" % getInfoLabel("ListItem.Property(pov.extras_params)")
    )
