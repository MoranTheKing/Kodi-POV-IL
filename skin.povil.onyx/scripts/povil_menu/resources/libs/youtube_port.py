"""The YouTube add-on's own server on a port this device lets it open (Wizard 0.5.23).

A viewer, Nov 2026: "YouTube gives an error every time Kodi starts -- it worked until now; the trailers do not
play; error 10013; from the info screen the trailer does play". His log: the add-on's server could not open
127.0.0.1:50152 -- "[WinError 10013] An attempt was made to access a socket in a way forbidden by its access
permissions" -- and every home trailer (read through that server, trailers.py) found it asleep. Windows keeps
ranges of ports for itself (Hyper-V, WSL, Docker take blocks of 49152-65535 at boot, and a Windows update or
a reboot can move them onto 50152); another program holding the port exclusively gives the same error. The
info screen's trailer plays the add-on's own way, without that server.

At start-up (and again when a trailer finds the server asleep) the add-on's port is checked: its server
answers there, or a server could open it -- left alone; otherwise the add-on is given the first port of
CANDIDATES that can be opened (its own setting, kodion.http.port: the add-on starts its server again on it as
soon as the setting changes). Outside Windows' dynamic range first, where Windows takes no ports.
"""
YOUTUBE = 'plugin.video.youtube'
PORT_SETTING, LISTEN_SETTING = 'kodion.http.port', 'kodion.http.listen'
DEFAULT_PORT, DEFAULT_LISTEN = 50152, '127.0.0.1'
CANDIDATES = (41152, 42152, 43152, 38152, 34152, 30152, 50152, 50252, 51152)


def usable(address, port):
    """True when a server could listen on address:port now (a test socket, closed at once). As the add-on's
    own server binds: with SO_REUSEADDR outside Windows (else a port its server closed a moment ago, still in
    TIME_WAIT, would look blocked); never on Windows, where it would take over a port another program holds."""
    import socket
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    probe = socket.socket(family, socket.SOCK_STREAM)
    try:
        if not hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):      # (only Windows has it)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((address, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def answers(address, port, seconds=2.0):
    """True when the YouTube add-on's own server answers its ping there (204)."""
    import urllib.error
    import urllib.request
    host = '127.0.0.1' if address in ('0.0.0.0', '') else ('[%s]' % address if ':' in address else address)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://%s:%d/youtube/ping' % (host, port), timeout=seconds) as reply:
            return reply.status in (200, 204)
    except urllib.error.HTTPError as reply:
        return reply.code == 204
    except Exception:
        return False


def choose(address, port, can_open=usable, serving=answers):
    """None when the add-on's port is fine (its server answers there, or it can be opened); else the port to
    give it, or 0 when none of CANDIDATES can be opened either."""
    if serving(address, port) or can_open(address, port):
        return None
    for candidate in CANDIDATES:
        if candidate != port and can_open(address, candidate):
            return candidate
    return 0


def current(addon):
    try:
        port = int(addon.getSetting(PORT_SETTING) or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    return (addon.getSetting(LISTEN_SETTING) or DEFAULT_LISTEN).strip(), port


def run(log):
    """Check the add-on's port; move it when it cannot be opened. Returns the new port, or None."""
    import xbmc
    import xbmcaddon
    if not xbmc.getCondVisibility('System.AddonIsEnabled(%s)' % YOUTUBE):
        return None
    addon = xbmcaddon.Addon(YOUTUBE)
    address, port = current(addon)
    port_now = choose(address, port)
    if port_now is None:
        return None
    if not port_now:
        log('the YouTube add-on cannot open its port %d, and none of %d others is free either' % (port, len(CANDIDATES)))
        return None
    addon.setSetting(PORT_SETTING, str(port_now))
    log('the YouTube add-on could not open port %d on this device: moved to %d' % (port, port_now))
    refresh_loaded()
    return port_now


def refresh_loaded():
    """The add-on's own modules loaded in this interpreter (the home trailers read through them, trailers.py)
    keep the settings they read first: they read them again, or every trailer would still be read from the old
    port (QA Kodi: "manifest URLError" after the move, with the add-on's server up on the new one)."""
    import sys
    context = sys.modules.get('youtube_plugin.kodion.context')
    if context is not None:
        context.XbmcContext().get_settings(refresh=True)
