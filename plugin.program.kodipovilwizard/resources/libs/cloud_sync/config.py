"""The build's Google project for the device-to-device sync (a "TVs and Limited Input devices" OAuth client whose
only permission is drive.file -- the files it made itself). For an app that runs on the viewer's own device Google does not treat the
client secret as a secret: it is in every copy of the app, as here.

(Empty here, the sync tile says it is not available yet.)
"""
CLIENT_ID = '599636788218-adj40qk8qff187a0o17gs3b0vdfhokb7.apps.googleusercontent.com'
CLIENT_SECRET = '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'


def ready():
    return bool(CLIENT_ID and CLIENT_SECRET)
