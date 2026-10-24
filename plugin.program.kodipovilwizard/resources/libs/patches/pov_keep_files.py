"""Keep the build's own files in POV's data folder through POV's clean-up.

POV's remove_old_databases (modules/cache.py) runs with its database
maintenance every three days and deletes every file in its data folder whose
name is not one of POV's own databases. The build keeps a few files there:
- povil-shortcuts-defaults-v1.json, the receipt that the build's shortcut
  folders were seeded once. Without it every start seeds them again, so a
  folder the user had deleted came back (QA Kodi, 24 Oct 2026);
- navigator.before-*.db, the menu backups the Wizard takes before it edits
  POV's menu (shortcuts, catalogue);
- povil_dropped_<provider>.json and its lock, the dropped-shows cache.
keep() widens POV's set of names so these stay.
"""

_OURS = ('povil', 'navigator.before-')


class _Keep(set):
    def __contains__(self, name):
        return set.__contains__(self, name) or str(name).startswith(_OURS)


def keep(names):
    return _Keep(names)
