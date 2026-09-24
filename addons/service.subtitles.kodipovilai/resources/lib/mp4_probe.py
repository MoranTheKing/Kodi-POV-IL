"""Bounded, local-only MP4 timed-text reference for subtitle timing checks.

Reads only the movie index, never the video/audio payload. Unsupported sample
codecs, fragmented files, and complex edit lists fail closed.
"""
import struct
from pathlib import Path

_MAX_INDEX_BYTES = 16 * 1024 * 1024
_MAX_SUBTITLE_SAMPLES = 50000


def _read_movie_index(path):
    """Read a single bounded moov box, even when it is at the file tail."""
    file_size = Path(path).stat().st_size
    if file_size < 16:
        raise ValueError('short MP4 file')
    with open(path, 'rb') as source:
        pos = 0
        while pos + 8 <= file_size:
            source.seek(pos)
            header = source.read(16)
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
                if size > _MAX_INDEX_BYTES:
                    raise ValueError('MP4 index exceeds read limit')
                source.seek(pos)
                data = source.read(size)
                if len(data) != size:
                    raise ValueError('short MP4 index')
                return data
            pos += size
    raise ValueError('MP4 movie index absent')


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


def subtitle_reference(path, log=None):
    """Return the same per-track cue profile shape as the Matroska probe."""
    emit = log or (lambda _message: None)
    try:
        index_bytes = _read_movie_index(path)
        profiles = cue_onsets(path, index_data=index_bytes)
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
