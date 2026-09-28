"""
pov_content_logger.py
Engine V2 decoupled patch module — Content Logger (telemetry) feature.

ARCHITECTURE
------------
Native POV code wraps entire item-building loops in a bare `except: pass`.
Engine V2 forbids removing or rewriting that except clause, so we can't
catch-and-log from the inside.

Instead we use Python's own low-level exception hook: `sys.settrace` /
`threading.settrace`. Once a trace function is installed, Python calls it
with event == 'exception' the moment an exception is raised in a traced
frame — this fires BEFORE the enclosing except clause runs, regardless of
whether that clause ends up swallowing it. No monkey-patching of
self.append, no global state dicts, no success/failure inference.

We scope the tracer tightly (enable at the top of run(), disable at the
bottom) so the overhead only exists while POV is actually building a
directory listing, not for the lifetime of the Python process.

`threading.settrace` is required in addition to `sys.settrace` because
POV builds items in worker threads (via TaskPool -> Thread); sys.settrace
alone only affects the thread that calls it, and only for frames entered
after the call. threading.settrace propagates the tracer to any thread
started after it's set, which is why we enable it before self.worker()
spawns its Thread pool.
"""
import sys
import threading

try:
	import xbmc
	_log = lambda msg: xbmc.log(msg, xbmc.LOGWARNING)
except Exception:
	_log = print  # fallback so the module is importable/testable outside Kodi

_LOG_PREFIX = '[POV Wizard][ContentLogger]'

# Only these call frames are traced line-by-line; everything else returns
# None immediately at the 'call' event, which tells the tracer to stop
# descending into that frame. This keeps overhead limited to POV's own
# item-building code instead of every stdlib/requests call underneath it.
TRACE_TARGETS = frozenset({
	'build_movie_content', 'build_tvshow_content', 'build_episode_content',
	'build_movies_results', 'build_collections_results',
	'run', 'worker',
	# pov_my_lists.py -- covers anything NOT already caught by that
	# module's own per-source try/except (e.g. a bug in the merge/dedup
	# logic itself rather than an API fetch failure).
	'maybe_populate_movies', 'maybe_populate_tvshows',
	'_populate', '_merge_tmdb', '_merge_trakt',
})

_enabled_lock = threading.Lock()
_depth = 0  # supports nested enable/disable calls safely (defensive, cheap)


def _local_tracer(frame, event, arg):
	if event == 'exception':
		exc_type, exc_value, _tb = arg
		co = frame.f_code
		try:
			context = ', '.join(
				'%s=%r' % (k, v) for k, v in frame.f_locals.items()
				if k in ('tag', 'position', 'ep_data', 'tmdb_id')
			)
		except Exception:
			context = ''
		_log('%s swallowed %s in %s() line %d: %s%s' % (
			_LOG_PREFIX, exc_type.__name__, co.co_name, frame.f_lineno, exc_value,
			' [%s]' % context if context else ''
		))
	return _local_tracer


def _global_tracer(frame, event, arg):
	if event == 'call' and frame.f_code.co_name in TRACE_TARGETS:
		return _local_tracer
	return None  # prune: don't trace unrelated frames at all


def enable():
	global _depth
	with _enabled_lock:
		_depth += 1
		if _depth == 1:
			sys.settrace(_global_tracer)
			threading.settrace(_global_tracer)


def disable():
	global _depth
	with _enabled_lock:
		_depth = max(0, _depth - 1)
		if _depth == 0:
			sys.settrace(None)
			threading.settrace(None)
