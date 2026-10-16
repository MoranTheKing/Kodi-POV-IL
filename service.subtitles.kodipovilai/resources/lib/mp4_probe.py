"""Bounded MP4 timed-text reference for subtitle timing checks.

Reads only the movie index, never the video/audio payload. Unsupported sample
codecs, fragmented files, and complex edit lists fail closed.
"""
import array
import struct
import sys
import time
from pathlib import Path

_MAX_INDEX_BYTES = 16 * 1024 * 1024

# A 1 ms nap at most every 20 ms in the long per-frame loops, so a new Kodi
# script (the subtitle chooser) can start meanwhile -- see sync_align._breathe.
_BREATHE_SLICE = 0.02
_breath = [0.0]


def _breathe():
    now = time.monotonic()
    if now - _breath[0] >= _BREATHE_SLICE:
        time.sleep(0.001)
        _breath[0] = time.monotonic()

_MAX_SUBTITLE_SAMPLES = 50000


def _read_movie_index_source(file_size, read, max_bytes=None):
    """Read one moov box using bounded positional reads, including tail moov."""
    if file_size < 16:
        raise ValueError('short MP4 file')
    pos = 0
    while pos + 8 <= file_size:
        header = read(pos, min(16, file_size - pos))
        if len(header) < 8:
            break
        size = struct.unpack_from('>I', header)[0]
        kind = header[4:8]
        min_header = 8
        if size == 1:
            if len(header) < 16:
                raise ValueError('short large-box header')
            size = struct.unpack_from('>Q', header, 8)[0]
            min_header = 16
        elif size == 0:
            size = file_size - pos
        if size < min_header or size > file_size - pos:
            raise ValueError('bad MP4 box size')
        if kind == b'moov':
            if size > (max_bytes or _MAX_INDEX_BYTES):
                raise ValueError('MP4 index exceeds read limit')
            chunks = []
            for offset in range(0, size, 4 * 1024 * 1024):
                want = min(4 * 1024 * 1024, size - offset)
                piece = read(pos + offset, want)
                if len(piece) != want:
                    raise ValueError('short MP4 index')
                chunks.append(piece)
            return b''.join(chunks)
        pos += size
    raise ValueError('MP4 movie index absent')


def _read_movie_index(path):
    """Read the bounded moov box from a local file."""
    file_size = Path(path).stat().st_size
    with open(path, 'rb') as source:
        def read(offset, size):
            source.seek(offset)
            return source.read(size)
        return _read_movie_index_source(file_size, read)


def boxes(data, begin=0, end=None):
    end = len(data) if end is None else end
    pos = begin
    while pos + 8 <= end:
        size = struct.unpack_from('>I', data, pos)[0]
        kind = data[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                raise ValueError('truncated large box')
            size = struct.unpack_from('>Q', data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise ValueError('invalid MP4 box')
        yield kind, pos + header, pos + size
        pos += size


def child(data, begin, end, kind):
    return next(((start, stop) for typ, start, stop in boxes(data, begin, end)
                 if typ == kind), None)


def seek(data, bounds, *path):
    for kind in path:
        bounds = child(data, *bounds, kind)
        if bounds is None:
            return None
    return bounds


def fullbox(data, bounds):
    start, end = bounds
    if start + 4 > end:
        raise ValueError('truncated full box')
    return data[start], start + 4, end


def duration_runs(data, bounds):
    _version, pos, end = fullbox(data, bounds)
    if pos + 4 > end:
        raise ValueError('truncated stts')
    count = struct.unpack_from('>I', data, pos)[0]
    pos += 4
    if count > _MAX_SUBTITLE_SAMPLES or pos + 8 * count > end:
        raise ValueError('invalid stts')
    return [struct.unpack_from('>II', data, pos + 8 * i)
            for i in range(count)]


def sample_sizes(data, bounds):
    _version, pos, end = fullbox(data, bounds)
    if pos + 8 > end:
        raise ValueError('truncated stsz')
    constant, count = struct.unpack_from('>II', data, pos)
    pos += 8
    if count > _MAX_SUBTITLE_SAMPLES:
        raise ValueError('excessive sample count')
    if constant:
        return [constant] * count
    if pos + 4 * count > end:
        raise ValueError('truncated sample sizes')
    return list(struct.unpack_from('>%dI' % count, data, pos))


def media_timescale(data, bounds):
    version, pos, end = fullbox(data, bounds)
    offset = 16 if version == 1 else 8
    if pos + offset + 4 > end:
        raise ValueError('truncated mdhd')
    return struct.unpack_from('>I', data, pos + offset)[0]


def movie_timescale(data, bounds):
    version, pos, end = fullbox(data, bounds)
    offset = 16 if version == 1 else 8
    if pos + offset + 4 > end:
        raise ValueError('truncated mvhd')
    return struct.unpack_from('>I', data, pos + offset)[0]


def handler(data, bounds):
    _version, pos, end = fullbox(data, bounds)
    if pos + 8 > end:
        raise ValueError('truncated hdlr')
    return data[pos + 4:pos + 8]


def simple_edit(data, trak, movie_scale, media_scale):
    bounds = seek(data, trak, b'edts', b'elst')
    if not bounds:
        return 0, 0
    version, pos, end = fullbox(data, bounds)
    if pos + 4 > end:
        raise ValueError('truncated elst')
    count = struct.unpack_from('>I', data, pos)[0]
    pos += 4
    if count > 2:
        raise ValueError('complex edit list')
    blank_ms = 0
    media_start = None
    for _ in range(count):
        fmt = '>Qqhh' if version == 1 else '>Ii hh'
        size = struct.calcsize(fmt)
        if pos + size > end:
            raise ValueError('truncated elst entry')
        duration, start, rate_i, rate_f = struct.unpack_from(fmt, data, pos)
        pos += size
        if (rate_i, rate_f) != (1, 0):
            raise ValueError('non-unit edit rate')
        if start < 0:
            if media_start is not None:
                raise ValueError('late empty edit')
            blank_ms += round(duration * 1000 / movie_scale)
        else:
            if media_start is not None:
                raise ValueError('multiple media edits')
            media_start = round(start * 1000 / media_scale)
    return blank_ms, media_start or 0


def cue_onsets(path, index_data=None):
    data = index_data if index_data is not None else _read_movie_index(path)
    top = list(boxes(data))
    moov = next(((a, b) for k, a, b in top if k == b'moov'), None)
    if not moov:
        raise ValueError('no moov')
    if seek(data, moov, b'mvex'):
        raise ValueError('fragmented MP4 unsupported')
    mvhd = seek(data, moov, b'mvhd')
    movie_scale = movie_timescale(data, mvhd)
    result = []
    for kind, start, end in boxes(data, *moov):
        if kind != b'trak':
            continue
        trak = (start, end)
        hdlr = seek(data, trak, b'mdia', b'hdlr')
        if not hdlr or handler(data, hdlr) not in (b'sbtl', b'subt', b'text'):
            continue
        stbl = seek(data, trak, b'mdia', b'minf', b'stbl')
        mdhd = seek(data, trak, b'mdia', b'mdhd')
        if not stbl or not mdhd:
            continue
        timescale = media_timescale(data, mdhd)
        stsd = seek(data, stbl, b'stsd')
        if not stsd:
            continue
        _v, pos, stop = fullbox(data, stsd)
        if pos + 12 > stop or struct.unpack_from('>I', data, pos)[0] != 1:
            raise ValueError('unsupported sample description')
        sample_type = data[pos + 8:pos + 12]
        if sample_type not in (b'tx3g', b'text'):
            raise ValueError('timed-text codec unsupported')
        stts = seek(data, stbl, b'stts')
        stsz = seek(data, stbl, b'stsz')
        if not stts or not stsz or not timescale:
            continue
        sizes = sample_sizes(data, stsz)
        durations = duration_runs(data, stts)
        if sum(count for count, _delta in durations) != len(sizes):
            raise ValueError('stts/stsz count mismatch')
        blank_ms, trim_ms = simple_edit(data, trak, movie_scale, timescale)
        starts = []
        tick = 0
        index = 0
        for count, delta in durations:
            for _ in range(count):
                if sizes[index] > 2:
                    start_ms = round(tick * 1000 / timescale) + blank_ms - trim_ms
                    if start_ms >= 0:
                        starts.append(start_ms)
                tick += delta
                index += 1
        result.append({'codec': sample_type.decode(), 'timescale': timescale,
                       'samples': len(sizes), 'cues': starts})
    return result


def _reference_from_index(index_bytes, log=None):
    emit = log or (lambda _message: None)
    try:
        profiles = cue_onsets(None, index_data=index_bytes)
    except (OSError, ValueError, struct.error, OverflowError) as exc:
        emit('MP4 index probe skipped: %s' % type(exc).__name__)
        return None
    if not profiles:
        return None

    def as_cues(starts):
        points = sorted(set(starts))
        return [{'start': t,
                 'end': t + max(600, min(3000, points[i + 1] - t - 100))
                 if i + 1 < len(points) else t + 3000}
                for i, t in enumerate(points)]

    track_cues = []
    for track_num, profile in enumerate(profiles, 1):
        cues = as_cues(profile['cues'])
        if len(cues) < 25:
            continue
        track = {'num': track_num, 'codec': profile['codec'],
                 'type': 17, 'forced': False}
        track_cues.append({'track': track, 'cues': cues})
    if not track_cues:
        return None
    union = {cue['start'] for item in track_cues for cue in item['cues']}
    cues = as_cues(union)
    best = max(track_cues, key=lambda item: len(item['cues']))
    emit('MP4 index probe: %d cues from %d timed-text track(s)'
         % (len(cues), len(track_cues)))
    return {'cues': cues, 'track_cues': track_cues,
            'track': best['track'],
            'tracks': [item['track'] for item in track_cues],
            'bytes': len(index_bytes)}


def subtitle_reference(path, log=None):
    """Return per-track cues from a local MP4/MOV file."""
    try:
        index_bytes = _read_movie_index(path)
    except (OSError, ValueError, struct.error, OverflowError) as exc:
        (log or (lambda _message: None))(
            'MP4 index probe skipped: %s' % type(exc).__name__)
        return None
    return _reference_from_index(index_bytes, log=log)


def subtitle_reference_source(file_size, read, log=None):
    """Return cues from a positional byte source (e.g. safe HTTP Range).

    The caller owns HTTP readiness, request limits and connection cleanup.
    This parser itself reads only box headers and at most 16 MiB of moov.
    """
    try:
        index_bytes = _read_movie_index_source(file_size, read)
    except (OSError, ValueError, struct.error, OverflowError) as exc:
        (log or (lambda _message: None))(
            'MP4 index probe skipped: %s' % type(exc).__name__)
        return None
    return _reference_from_index(index_bytes, log=log)


# ---- audio frame-size envelope --------------------------------------------
# AAC is variable-bitrate: the encoder spends a different number of bytes on
# speech than on music/effects/silence.  The per-frame sizes in ``stsz`` are
# therefore a free, decode-less loudness proxy read from the same movie index
# as the timed-text probe.  Constant-size codecs (AC-3, CBR) carry no signal
# and are refused.
_MAX_AUDIO_FRAMES = 2000000
_ENVELOPE_STEP_MS = 100
_ENVELOPE_TREND_BINS = 40
_ENVELOPE_MIN_DISTINCT = 32
_ENVELOPE_MAX_MS = 6 * 3600 * 1000


def _audio_runs(data, bounds):
    _version, pos, end = fullbox(data, bounds)
    if pos + 4 > end:
        raise ValueError('truncated stts')
    count = struct.unpack_from('>I', data, pos)[0]
    pos += 4
    if count > _MAX_AUDIO_FRAMES or pos + 8 * count > end:
        raise ValueError('invalid stts')
    return [struct.unpack_from('>II', data, pos + 8 * i)
            for i in range(count)]


def _audio_sizes(data, bounds):
    _version, pos, end = fullbox(data, bounds)
    if pos + 8 > end:
        raise ValueError('truncated stsz')
    constant, count = struct.unpack_from('>II', data, pos)
    pos += 8
    if count > _MAX_AUDIO_FRAMES:
        raise ValueError('excessive audio frame count')
    if constant:
        return [constant] * count
    if pos + 4 * count > end:
        raise ValueError('truncated sample sizes')
    # A compact machine array (4 bytes a frame, not a Python int object):
    # a three-hour film has ~500k frames.
    sizes = array.array('I')
    if sizes.itemsize != 4:
        return list(struct.unpack_from('>%dI' % count, data, pos))
    sizes.frombytes(data[pos:pos + 4 * count])
    if sys.byteorder == 'little':
        sizes.byteswap()
    return sizes


def audio_envelope(index_data, step_ms=_ENVELOPE_STEP_MS):
    """Detrended log frame-size envelope of the first AAC track, or None.

    Returns ``{'step_ms', 'values', 'frames', 'distinct', 'codec'}`` where
    ``values`` are small signed ints, one per ``step_ms`` of movie time
    (edit lists applied).  Only relative structure matters; whether speech
    raises or lowers the bitrate is left to the consumer.
    """
    import math
    data = index_data
    top = list(boxes(data))
    moov = next(((a, b) for k, a, b in top if k == b'moov'), None)
    if not moov or seek(data, moov, b'mvex'):
        return None
    mvhd = seek(data, moov, b'mvhd')
    movie_scale = movie_timescale(data, mvhd)
    for kind, start, end in boxes(data, *moov):
        if kind != b'trak':
            continue
        trak = (start, end)
        hdlr = seek(data, trak, b'mdia', b'hdlr')
        if not hdlr or handler(data, hdlr) != b'soun':
            continue
        stbl = seek(data, trak, b'mdia', b'minf', b'stbl')
        mdhd = seek(data, trak, b'mdia', b'mdhd')
        stsd = seek(data, stbl, b'stsd') if stbl else None
        if not stbl or not mdhd or not stsd:
            continue
        _v, pos, stop = fullbox(data, stsd)
        if pos + 12 > stop:
            continue
        codec = data[pos + 8:pos + 12]
        if codec != b'mp4a':
            continue
        timescale = media_timescale(data, mdhd)
        stts = seek(data, stbl, b'stts')
        stsz = seek(data, stbl, b'stsz')
        if not stts or not stsz or not timescale:
            continue
        sizes = _audio_sizes(data, stsz)
        runs = _audio_runs(data, stts)
        if sum(count for count, _delta in runs) != len(sizes):
            raise ValueError('stts/stsz count mismatch')
        distinct = len(set(sizes))
        if len(sizes) < 1000 or distinct < _ENVELOPE_MIN_DISTINCT:
            return None
        blank_ms, trim_ms = simple_edit(data, trak, movie_scale, timescale)
        total_ticks = sum(count * delta for count, delta in runs)
        bins = int((total_ticks * 1000.0 / timescale + blank_ms) / step_ms) + 2
        # A corrupt duration must not allocate a film's worth of bins per
        # bogus hour on a low-memory box: nothing real runs past 6 hours.
        if bins > _ENVELOPE_MAX_MS // step_ms + 2:
            return None
        sums = [0] * bins
        counts = [0] * bins
        tick = 0
        index = 0
        scale = 1000.0 / timescale
        for count, delta in runs:
            for _ in range(count):
                if not index & 1023:
                    _breathe()
                at = tick * scale + blank_ms - trim_ms
                if at >= 0:
                    b = int(at / step_ms)
                    if b < bins:
                        sums[b] += sizes[index]
                        counts[b] += 1
                tick += delta
                index += 1
        level = []
        last = 0.0
        for total, count in zip(sums, counts):
            if count:
                last = math.log(total / float(count) + 1.0)
            level.append(last)
        prefix = [0.0]
        for value in level:
            prefix.append(prefix[-1] + value)
        half = _ENVELOPE_TREND_BINS // 2
        values = []
        for i, value in enumerate(level):
            if not i & 1023:
                _breathe()
            lo = max(0, i - half)
            hi = min(len(level), i + half)
            trend = (prefix[hi] - prefix[lo]) / float(hi - lo)
            values.append(max(-127, min(127, int(round((value - trend)
                                                       * 64.0)))))
        return {'step_ms': step_ms, 'values': values, 'frames': len(sizes),
                'distinct': distinct, 'codec': codec.decode('latin-1')}
    return None


def audio_envelope_source(file_size, read, index_data=None, log=None):
    """Envelope from a positional byte source; None when unavailable."""
    emit = log or (lambda _message: None)
    try:
        data = (index_data if index_data is not None
                else _read_movie_index_source(file_size, read))
        envelope = audio_envelope(data)
    except (OSError, ValueError, struct.error, OverflowError,
            ZeroDivisionError, TypeError, MemoryError) as exc:
        emit('MP4 audio envelope skipped: %s' % type(exc).__name__)
        return None
    if envelope:
        emit('MP4 audio envelope: %d frames, %d distinct sizes, %d bins'
             % (envelope['frames'], envelope['distinct'],
                len(envelope['values'])))
    return envelope
