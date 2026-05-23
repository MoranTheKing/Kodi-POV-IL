# Look for SRT files alongside the currently playing video. Used as
# a no-API-call fallback when OpenSubtitles isn't configured. Only
# meaningful for local-file playback -- for streams (URLs, plugin://
# paths) we just return [].

import os

from . import language_detect


SRT_SUFFIXES = ('.srt',)


def find_alongside(video_path):
    """Return [(path, detected_lang_code), ...] for SRTs that look
    like they belong to this video.

    Heuristic: any .srt in the same directory whose basename starts
    with the video's basename. e.g. for Movie.mkv we pick up
    Movie.srt, Movie.en.srt, Movie.eng.srt, etc.
    """
    if not video_path:
        return []
    # Streams have no usable filesystem path.
    if video_path.startswith(('http://', 'https://', 'plugin://',
                              'rtsp://', 'udp://', 'rtmp://')):
        return []
    try:
        if not os.path.isfile(video_path):
            return []
        video_dir = os.path.dirname(video_path)
        base = os.path.splitext(os.path.basename(video_path))[0]
        if not video_dir or not base:
            return []
        out = []
        for name in os.listdir(video_dir):
            lname = name.lower()
            if not lname.endswith(SRT_SUFFIXES):
                continue
            if not name.lower().startswith(base.lower()):
                continue
            full = os.path.join(video_dir, name)
            lang = language_detect.from_filename(full)
            if not lang:
                # Content-sniff a small sample.
                try:
                    with open(full, 'r', encoding='utf-8',
                              errors='replace') as f:
                        sample = f.read(4000)
                    lang = language_detect.detect(sample)
                except (IOError, OSError):
                    continue
            out.append((full, lang or ''))
        return out
    except (OSError, IOError):
        return []
