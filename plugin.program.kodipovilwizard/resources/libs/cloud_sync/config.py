"""The build's Google project for the device-to-device sync (a "TVs and Limited Input devices" OAuth client whose
only permission is drive.appdata). For an app that runs on the viewer's own device Google does not treat the
client secret as a secret: it is in every copy of the app, as here.

Empty until the owner's project is made: the sync tile then says it is not available yet.
"""
CLIENT_ID = ''
CLIENT_SECRET = ''


def ready():
    return bool(CLIENT_ID and CLIENT_SECRET)
