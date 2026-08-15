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

import os

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

# One repair per playing file. The same track can be selected by auto-on-play,
# by the native picker and by our own chooser within seconds of each other, and
# each of those fires this; the property holds the URL the repair is FOR, so a
# genuinely new file is never mistaken for a repeat. It lives on the home window
# because every fire runs in its own RunScript process.
_DONE_PROP = 'povil.embedded_rtl_for'

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
        from resources.lib import srt, translate
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

    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
    except Exception:
        win = None

    if win is not None:
        try:
            if (win.getProperty(_DONE_PROP) or '') == url:
                return 'already'
        except Exception:
            pass

    # The user's embedded-extraction setting governs this too. 'off' and
    # 'align_only' both mean "do not read the container for subtitle text", and
    # 'local_only' means "not over the network" -- this is the same read, so it
    # obeys the same answer instead of inventing a second switch for it.
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

    # Claim the file now: BEFORE the extraction, because the extraction is the
    # thing we must not do twice, and AFTER the refusals above, because a run
    # that declined to do anything has nothing to claim -- flagging it would
    # make a setting the user changes mid-playback take until the next file to
    # have any effect.
    if win is not None:
        try:
            win.setProperty(_DONE_PROP, url)
        except Exception:
            pass

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

    # ...and the user must not have chosen something else meanwhile. Every pick
    # records itself here, so anything that is no longer an embedded entry is a
    # deliberate choice we must not overwrite.
    try:
        cur = kodi_utils.get_current_subtitle() or ''
        if cur:
            payload = translate._decode_link(cur) or {}
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
