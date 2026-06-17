# Vendored DarkSubs subtitle-fetching engine (Phase B1 of the MoranSubs
# unification). DORMANT in B1 -- nothing imports this at runtime yet; it is
# wired into search/download in B2. See MORANSUBS_PLAN.md.
#
# _libs/ holds third-party packages that import themselves by absolute name
# (e.g. pysrt: `from pysrt import ...`), so _libs/ must be on sys.path. Kept in
# a private subdir so only those libs land on the path -- never our engine
# modules (cache.py/srt.py would otherwise collide with MoranSubs' own).
import os as _os
import sys as _sys
_libs = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '_libs')
if _libs not in _sys.path:
    _sys.path.insert(0, _libs)
