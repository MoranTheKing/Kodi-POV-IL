# B1 dormant stub. The real telethon-backed Telegram provider is vendored in
# Phase B3. Until then this satisfies engine.py's import + provider interface
# and simply returns no results (telegram disabled).
global_var = []
site_id = '[Telegram]'
sub_color = 'deepskyblue'


def get_subs(*args, **kwargs):
    return


def download(*args, **kwargs):
    return None
