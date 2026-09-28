# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_resolve_diag.py

def run(instance, files, selected_files):
    """
    Evaluates the failure condition natively. If true, raises a highly detailed exception,
    bypassing the native `raise Exception('selected_files failed')` completely.
    """
    if not selected_files:
        files_list = files or []
        debrid_name = getattr(instance, 'debrid', '?')

        if files_list:
            filtered = ' | '.join(str((_f or {}).get('filename'))[-70:] for _f in files_list[:6])
            msg = "selected_files failed (%s file(s) from %s, filtered out: %s)" % (len(files_list), debrid_name, filtered)
        else:
            msg = "selected_files failed (0 file(s) from %s)" % debrid_name

        raise Exception(msg)