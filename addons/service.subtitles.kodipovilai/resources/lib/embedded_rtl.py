# Embedded Hebrew subtitle track: the RTL repair Kodi's renderer never applies.
#
# THE DEFECT (field report, 0.2.495). "Suddenly all the embedded subtitles are
# reversed -- the punctuation is at the START of the sentence instead of the
# end. Here the marks are fine except the question mark."
#
# THE CAUSE. Kodi draws an EMBEDDED subtitle track itself, straight out of the
# container, and its text layout resolves BiDi with a LEFT-TO-RIGHT base
# direction. Under the Unicode BiDi algorithm a punctuation mark is a NEUTRAL
# character: one sitting BETWEEN two Hebrew letters takes their direction and
# renders correctly, but one at the END of a line has no strong character after
# it, so it takes the PARAGRAPH's direction instead -- and with an LTR paragraph
# it is drawn to the right of the Hebrew run, which for an RTL sentence is its
# visual BEGINNING. That is exactly the reported shape: every mark inside the
# line is fine, the one that closes the line is not.
#
# Every subtitle we deliver as a FILE already avoids this. srt.fix_rtl_punctuation
# wraps each line in RLE..PDF, which forces an RTL base direction for that run,
# and it is the default (rtl_base) precisely because these setups default to LTR
# -- verified on-device back in 0.2.416. A track inside the video is the one
# place that fix cannot reach: we do not own those bytes and Kodi never asks us
# about them.
#
# WHY IT SURFACED NOW. Auto-on-play started SELECTING an embedded Hebrew track
# whenever the file has one (autosub_service, 2026-07-22) -- it is perfectly
# synced, so it is the best subtitle available. That turned a track the user
# used to have to go looking for into the one they get by default, and with it a
# long-standing rendering flaw became "suddenly all embedded subtitles".
#
# THE FIX. Stop letting Kodi render it: extract the track's text, run the same
# RTL fix over it, and hand the result back as an EXTERNAL subtitle. The native
# track is still selected first and keeps playing the whole time, so the user is
# never left without subtitles -- the corrected copy swaps in when it is ready.
# The cue timestamps come out of the container, so the swap keeps the perfect
# sync that made the embedded track worth preferring.
#
# WHAT THIS COSTS, AND WHO DECIDES. Extraction reads the container: one cheap
# sequential pass for a local file, surgical HTTP Range requests over a debrid
# stream. That is the SAME operation the embedded-AI path already performs, so
# it is governed by the SAME user setting rather than a new one -- if embedded
# extraction is off, or restricted to local files, this respects that. It also
# inherits that path's protections: one extraction at a time, pacing, and an
# abort the moment playback stalls or ends.
#
# KNOWN LIMIT: the track is chosen by LANGUAGE, not by the stream the user
# picked. Kodi's subtitle stream index is a PLAYER index and the extractor wants
# a Matroska track number; they are not the same number and pairing them is
# guesswork. A file with two distinct Hebrew text tracks may therefore be
# repaired from the other one. Every real-world file we have seen has at most
# one, and delivering the wrong Hebrew track is far less likely than the
# mis-mapping that pretending to pair them would cause.

import errno
import os
import time

try:
    import xbmc
except Exception:
    xbmc = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


ADDON_ID = 'service.subtitles.kodipovilai'
ACTION = 'embedded_rtl'

# One repair per playing file, enforced by an ATOMIC lock and not by a window
# property. The same track can be selected by auto-on-play, by the native
# picker and by our own chooser within seconds of each other -- and Kodi's
# onAVStarted is documented in autosub_service as firing more than once for one
# file, which starts a second auto-on-play thread. Each of those fires this, in
# its own RunScript PROCESS.
#
# A window property cannot arbitrate that. getProperty-then-setProperty is a
# check-then-set with a gap in the middle, so two processes that read before
# either writes both conclude they are first -- and the thing they would then
# both do is a network-heavy container extraction against the same debrid URL.
# Two concurrent extractions saturating one token is precisely what closed a
# movie in the field once already. os.open(O_CREAT|O_EXCL) has no gap: the
# kernel hands the file to exactly one caller.
_LOCK_NAME = 'embedded_rtl.lock'

# Deliberately shorter than the embedded-AI extraction budget (900s). Nothing is
# broken while this runs -- the user is watching the native track -- so a job
# that cannot finish in this long is not worth the requests it keeps spending.
_DEADLINE_S = 600.0

_OUT_NAME = 'embedded_he_fixed.he.srt'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('embedded_rtl: ' + msg, level=level)
    except Exception:
        pass


def _playing_file():
    try:
        return (xbmc.Player().getPlayingFile() or '').strip()
    except Exception:
        return ''


def _lock_path():
    return os.path.join(kodi_utils.cache_dir(), _LOCK_NAME)


def _read_lock(path):
    """(state, when, url) of an existing lock, or ('', 0.0, '')."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            parts = f.read().split('\n')
        return parts[0].strip(), float(parts[1].strip()), parts[2].strip()
    except Exception:
        # Unreadable or half-written -- treat as a corpse, not as a live claim.
        return '', 0.0, ''


def _stale_after():
    # A live extraction is bounded by its own deadline; anything older than
    # that plus a margin belongs to a process Kodi has already killed.
    return _DEADLINE_S + 120


def _claim(url):
    """'ok' to proceed, 'already' if this file is done, 'busy' if someone
    else holds it. Never raises."""
    try:
        path = _lock_path()
    except Exception:
        return 'ok'          # no cache dir to lock in -- do not block the fix
    payload = 'busy\n{0}\n{1}\n'.format(time.time(), url)
    for second_try in (False, True):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError as e:
            if e.errno != errno.EEXIST:
                _log('lock unavailable ({0}) -- proceeding unlocked'.format(e),
                     level='WARNING')
                return 'ok'
        except Exception:
            return 'ok'
        else:
            try:
                os.write(fd, payload.encode('utf-8'))
            except Exception:
                pass
            finally:
                try:
                    os.close(fd)
                except Exception:
                    pass
            return 'ok'
        state, when, owner = _read_lock(path)
        age = time.time() - when
        # A claim dated in the FUTURE is fresh, not dead. It reads as negative
        # age from a clock step on a cheap box -- and, less exotically, from the
        # stamp simply being rounded forward when it was written. Treating that
        # as stale reclaims a lock somebody is actively holding, which is the
        # one thing this lock exists to prevent; translate.py's own extraction
        # flag carries the same clamp for the same reason.
        if age < 0:
            age = 0.0
        if owner == url:
            if state == 'done':
                return 'already'
            if age < _stale_after():
                return 'busy'
        elif state == 'busy' and age < _stale_after():
            # A live claim on a DIFFERENT file. There is one player, so that
            # claim is obsolete by definition -- the process holding it is
            # extracting from a video that is no longer playing, its own
            # abort-on-playback-end is already unwinding it, and its moved_on
            # guard will stop it delivering. Taking the lock is what lets the
            # file the user IS watching get repaired; refusing here would mean
            # the next thing they play is never fixed.
            _log('taking over a lock left by a previous file', level='INFO')
        if second_try:
            return 'busy'
        try:
            os.remove(path)
        except OSError:
            return 'busy'
    return 'busy'


def _release(url, done):
    """Mark the file finished, or drop the claim so a later fire can retry.

    Only an outcome that would repeat itself is recorded as done. A transient
    one -- an extraction the player stalled, a delivery we declined because the
    user was mid-something -- releases the lock, so re-picking the track
    actually tries again instead of being told it already happened.
    """
    try:
        path = _lock_path()
        if done:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('done\n{0}\n{1}\n'.format(time.time(), url))
        else:
            os.remove(path)
    except Exception:
        pass


def _is_hebrew_name(name):
    """Kodi's name for a subtitle stream ('heb', 'Hebrew', 'he', ...)."""
    n = (name or '').strip().lower()
    if not n:
        return False
    try:
        from resources.lib.subs_engine_bridge import _LANG_NORMALIZE
    except Exception:
        _LANG_NORMALIZE = {'iw': 'he', 'heb': 'he', 'hebrew': 'he'}
    return _LANG_NORMALIZE.get(n, n[:2]) == 'he'


def fire():
    """Start the repair in its own process. Never blocks, never raises.

    Called right after an embedded HEBREW track is selected, from whichever
    process made that selection (the auto-on-play thread, the native picker
    subprocess, our chooser). Those processes must stay responsive -- the picker
    one is about to be ended by endOfDirectory -- so the work goes to a fresh
    RunScript invocation.
    """
    if xbmc is None:
        return False
    try:
        xbmc.executebuiltin('RunScript({0},action={1})'.format(ADDON_ID, ACTION))
        return True
    except Exception as e:
        _log('fire failed: {0}'.format(e), level='WARNING')
        return False


def repair():
    """Extract the embedded Hebrew track, RTL-fix it, and swap it in.

    Returns a short status string for the log. Never raises: on any problem the
    natively-rendered track simply stays, which is what the user has today.
    """
    if xbmc is None or kodi_utils is None:
        return 'no_kodi'
    try:
        from resources.lib import translate
    except Exception as e:
        _log('imports failed: {0}'.format(e), level='WARNING')
        return 'no_modules'

    try:
        if not xbmc.Player().isPlayingVideo():
            return 'not_playing'
    except Exception:
        return 'not_playing'

    url = _playing_file()
    if not url:
        return 'no_url'

    # The user's embedded-extraction setting governs this too. 'off' and
    # 'align_only' both mean "do not read the container for subtitle text", and
    # 'local_only' means "not over the network" -- this is the same read, so it
    # obeys the same answer instead of inventing a second switch for it.
    #
    # Checked BEFORE the lock is taken, so a setting the user changes
    # mid-playback takes effect on the next pick rather than on the next file.
    try:
        policy = translate._embedded_translation_policy()
    except Exception:
        policy = {'enabled': True, 'try_extract': True, 'allow_http': True}
    if not policy.get('enabled') or not policy.get('try_extract'):
        _log('skipped: embedded extraction is off (mode={0})'.format(
            policy.get('mode')), level='INFO')
        return 'disabled'
    allow_http = bool(policy.get('allow_http'))
    if '://' in url and not allow_http:
        _log('skipped: remote file and HTTP extraction is off', level='INFO')
        return 'http_not_allowed'

    claim = _claim(url)
    if claim != 'ok':
        _log('not starting: {0}'.format(claim), level='INFO')
        return claim
    status = 'failed'
    try:
        status = _repair_locked(translate, url, allow_http)
    except Exception as e:
        _log('repair raised: {0}'.format(e), level='WARNING')
        status = 'failed'
    finally:
        # Only an outcome that would repeat itself identically is recorded as
        # finished. Everything else releases, so re-picking the track retries.
        _release(url, status in ('delivered', 'no_change'))
    return status


def _repair_locked(translate, url, allow_http):
    """The repair proper, with this file's lock held."""
    from resources.lib import srt

    # Silence the extractor's own toasts. They are worded for the AI pipeline
    # ("AI: מחלץ תרגום מובנה...") which has nothing to do with this, and the user
    # is already watching a working subtitle -- there is nothing here for them to
    # act on. Quiet mode also keeps this run from setting the picker's
    # "extraction paused" flag, which belongs to a pick the user actually made.
    was_quiet = getattr(translate, '_QUIET', False)
    try:
        translate.set_quiet(True)
        src_path = translate._extract_embedded_srt(
            {}, 'he', deadline_s=_DEADLINE_S, allow_http=allow_http)
    except Exception as e:
        _log('extraction raised: {0}'.format(e), level='WARNING')
        return 'extract_failed'
    finally:
        try:
            translate.set_quiet(was_quiet)
        except Exception:
            pass

    if not src_path or not os.path.isfile(src_path):
        _log('no embedded Hebrew text extracted', level='INFO')
        return 'no_text'

    try:
        with open(src_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    try:
        fixed = srt.fix_rtl_punctuation(text)
    except Exception as e:
        _log('rtl fix raised: {0}'.format(e), level='WARNING')
        return 'fix_failed'
    if fixed == text:
        # rtl_punct_mode is set to a mode that changes nothing here, or the
        # track needed nothing. Either way, swapping an identical file in would
        # cost a visible flicker and buy the user nothing.
        _log('no change needed -- leaving the native track', level='INFO')
        return 'no_change'

    # Playback must still be the SAME file. An extraction can run for minutes;
    # the episode can end and the next one start inside that window, and
    # delivering this file's subtitle onto that one is worse than the defect.
    if _playing_file() != url:
        _log('playing file changed during extraction -- not delivering',
             level='INFO')
        return 'moved_on'

    # ...and the user must not have moved on WITHIN this file either.
    #
    # Two questions, because one of them is not enough. Our own record
    # (moransubs.current_sub) is written by our pick flows only -- Kodi's
    # native subtitle button, the OSD track list and the "subtitles off"
    # toggle never touch it -- and this run can last minutes, which is
    # plenty of time for the user to reach for the remote. Trusting that
    # record alone would let us switch a track back on that they had just
    # switched off, which is a worse thing to do than the defect we came to
    # fix. So ask the player what is actually on RIGHT NOW as well.
    try:
        if not xbmc.getCondVisibility('VideoPlayer.SubtitlesEnabled'):
            _log('subtitles were turned off -- not delivering', level='INFO')
            return 'subs_off'
    except Exception:
        pass
    try:
        current = xbmc.Player().getSubtitles() or ''
    except Exception:
        current = ''
    if current and not _is_hebrew_name(current):
        _log('the active subtitle is {0!r}, no longer Hebrew -- not delivering'
             .format(current), level='INFO')
        return 'superseded'
    try:
        cur_link = kodi_utils.get_current_subtitle() or ''
        if cur_link:
            payload = translate._decode_link(cur_link) or {}
            if not payload.get('embedded'):
                _log('user picked another subtitle -- not delivering',
                     level='INFO')
                return 'superseded'
    except Exception:
        pass

    out = os.path.join(kodi_utils.cache_dir(), _OUT_NAME)
    tmp = out + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(fixed)
        os.replace(tmp, out)
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    try:
        player = xbmc.Player()
        player.setSubtitles(out)
        player.showSubtitles(True)
    except Exception as e:
        _log('setSubtitles failed: {0}'.format(e), level='WARNING')
        return 'deliver_failed'

    _log('delivered {0} cue(s) with RTL punctuation repaired'.format(
        text.count('-->')), level='INFO')
    try:
        kodi_utils.notify('תוקן כיוון הפיסוק בתרגום המובנה', time_ms=2500)
    except Exception:
        pass
    return 'delivered'
