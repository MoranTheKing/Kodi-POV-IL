"""Wizard 0.5.16: on an LG TV the trailer goes to Kodi's own player (FFmpeg) as an HLS playlist, 1080p H.264.

The owner's LG (webOS 26, Kodi 21.0), Nov 2026: films play, every trailer was refused by the TV's decoder --
720p H.264 and 720p VP9 through inputstream.adaptive. A film is 1080p and up and is read by Kodi's own player;
so is the trailer now: the YouTube add-on's DASH manifest is turned into an HLS playlist whose pieces are byte
ranges of the same files (each file's 'sidx' box lists them), served by the add-on's own server.
"""
import importlib.util
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('trailers_hls_test', ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py')
trailers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trailers)

BASE = 'http://127.0.0.1:50152/youtube/stream?itag=%s&amp;expire=1&amp;x=y'
MPD = '''<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" mediaPresentationDuration="PT62S" type="static">
	<Period>
		<AdaptationSet id="0" contentType="video" mimeType="video/mp4" default="true">
			<Representation id="137" codecs="avc1.640028" mimeType="video/mp4" bandwidth="4400000" width="1920" height="1080" frameRate="24000/1001">
				<BaseURL>%(v137)s</BaseURL>
				<SegmentBase indexRange="741-892"><Initialization range="0-740"/></SegmentBase>
			</Representation>
			<Representation id="136" codecs="avc1.64001F" mimeType="video/mp4" bandwidth="2476891" width="1280" height="720" frameRate="24000/1001">
				<BaseURL>%(v136)s</BaseURL>
				<SegmentBase indexRange="739-890"><Initialization range="0-738"/></SegmentBase>
			</Representation>
		</AdaptationSet>
		<AdaptationSet id="1" contentType="video" mimeType="video/webm">
			<Representation id="248" codecs="vp9" mimeType="video/webm" bandwidth="3000000" width="1920" height="1080">
				<BaseURL>%(v248)s</BaseURL>
				<SegmentBase indexRange="200-300"><Initialization range="0-199"/></SegmentBase>
			</Representation>
		</AdaptationSet>
		<AdaptationSet id="2" contentType="audio" mimeType="audio/mp4" default="true">
			<Representation id="140" codecs="mp4a.40.2" mimeType="audio/mp4" bandwidth="130000">
				<BaseURL>%(a140)s</BaseURL>
				<SegmentBase indexRange="632-1003"><Initialization range="0-631"/></SegmentBase>
			</Representation>
		</AdaptationSet>
		<AdaptationSet id="3" contentType="audio" mimeType="audio/webm">
			<Representation id="251" codecs="opus" mimeType="audio/webm" bandwidth="140000">
				<BaseURL>%(a251)s</BaseURL>
				<SegmentBase indexRange="100-200"><Initialization range="0-99"/></SegmentBase>
			</Representation>
		</AdaptationSet>
	</Period>
</MPD>''' % {'v137': BASE % 137, 'v136': BASE % 136, 'v248': BASE % 248, 'a140': BASE % 140, 'a251': BASE % 251}


def sidx(timescale, first, pieces, version=0):
    """An MP4 'sidx' box: pieces = [(size, duration in timescale units)]."""
    body = struct.pack('>B3xII', version, 1, timescale)
    body += struct.pack('>II', 0, first) if version == 0 else struct.pack('>QQ', 0, first)
    body += struct.pack('>HH', 0, len(pieces))
    for size, duration in pieces:
        body += struct.pack('>III', size, duration, 0x90000000)
    return struct.pack('>I', 8 + len(body)) + b'sidx' + body


class HlsTests(unittest.TestCase):
    def test_the_pieces_of_a_file_are_read_from_its_sidx_box(self):
        box = sidx(90000, 0, [(1000, 450000), (2000, 450000), (500, 180000)])
        self.assertEqual(trailers.parse_sidx(box, 741),
                         [(741 + len(box), 1000, 5.0), (741 + len(box) + 1000, 2000, 5.0), (741 + len(box) + 3000, 500, 2.0)])
        # version 1 (64-bit times), and a first piece that does not follow the box at once
        box = sidx(1000, 16, [(10, 2500)], version=1)
        self.assertEqual(trailers.parse_sidx(box, 0), [(len(box) + 16, 10, 2.5)])
        for bad in (b'', b'moov' * 4, box[:-6]):
            with self.assertRaises(ValueError):
                trailers.parse_sidx(bad, 0)

    def test_the_picture_is_the_tallest_h264_mp4_up_to_1080p_and_the_sound_the_default_aac(self):
        video, audio = trailers.mpd_choice(MPD)
        self.assertEqual((video['height'], video['codecs'], video['init'], video['index']), (1080, 'avc1.640028', (0, 740), (741, 892)))
        self.assertEqual(video['url'], (BASE % 137).replace('&amp;', '&'), 'the address as the server reads it')
        self.assertEqual((audio['codecs'], audio['init'], audio['index']), ('mp4a.40.2', (0, 631), (632, 1003)))
        self.assertEqual(trailers.mpd_choice(MPD, max_height=720)[0]['height'], 720)
        self.assertIsNone(trailers.mpd_choice(MPD.replace('audio/mp4', 'audio/x'))[1] and None)
        # no H.264 at all: the tallest MP4 of another codec; WebM is never taken (FFmpeg reads MP4 pieces)
        only_vp9 = MPD.replace('avc1.640028', 'vp09.00.40.08').replace('avc1.64001F', 'vp09.00.31.08')
        self.assertEqual(trailers.mpd_choice(only_vp9)[0]['codecs'], 'vp09.00.40.08')

    def test_the_playlists_kodis_player_reads(self):
        video, audio = trailers.mpd_choice(MPD)
        text = trailers.media_playlist(video, [(900, 1000, 5.005), (1900, 2000, 4.2)])
        lines = text.splitlines()
        self.assertEqual(lines[:6], ['#EXTM3U', '#EXT-X-VERSION:7', '#EXT-X-TARGETDURATION:6', '#EXT-X-MEDIA-SEQUENCE:0',
                                     '#EXT-X-PLAYLIST-TYPE:VOD', '#EXT-X-MAP:URI="%s&povil=0.mp4",BYTERANGE="741@0"' % video['url']])
        self.assertEqual(lines[6:9], ['#EXTINF:5.005,', '#EXT-X-BYTERANGE:1000@900', video['url'] + '&povil=1.mp4'])
        # Kodi 22's FFmpeg (QA Kodi 22.0 RC2, Nov 2026): it refuses the playlist when a piece's address does not end
        # like a media file, and it reads pieces that share one address as one stream (the picture stopped after
        # the first piece) -- so each piece has an address of its own, ending in .mp4
        addresses = [line for line in lines if line.startswith('http')]
        self.assertTrue(all(address.endswith('.mp4') for address in addresses))
        self.assertEqual(len(set(addresses)), len(addresses))
        self.assertEqual(trailers.piece_address('http://h/youtube/stream', 3), 'http://h/youtube/stream?povil=3.mp4')
        self.assertEqual(lines[-1], '#EXT-X-ENDLIST')
        master = trailers.master_playlist(video, audio, 'http://h/v.m3u8', 'http://h/a.m3u8').splitlines()
        self.assertIn('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="audio",DEFAULT=YES,AUTOSELECT=YES,URI="http://h/a.m3u8"', master)
        self.assertIn('#EXT-X-STREAM-INF:BANDWIDTH=4530000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2",AUDIO="audio"', master)
        self.assertEqual(master[-1], 'http://h/v.m3u8')
        # served by the YouTube add-on's own server, beside its manifest (its `file` field); the name ends in .m3u8,
        # which is how FFmpeg knows the playlist
        self.assertEqual(trailers.served_address('http://127.0.0.1:50152/youtube/manifest/dash?file=9O-OCPbf28o.mpd', 'povil_hls_x.m3u8'),
                         'http://127.0.0.1:50152/youtube/manifest/dash?file=povil_hls_x.m3u8')

    def test_the_stream_comes_back_as_the_playlist_or_not_at_all(self):
        address = 'http://127.0.0.1:50152/youtube/manifest/dash?file=9O-OCPbf28o.mpd'
        boxes = {'bytes=741-892': sidx(90000, 0, [(1000, 450000)]), 'bytes=632-1003': sidx(44100, 0, [(300, 220500)])}
        asked, kept = [], {}

        def fetch(url, headers, seconds, span):
            asked.append((url, span))
            return MPD.encode('utf-8') if span is None else boxes[span]

        def save(name, text):
            kept[name] = text
            return trailers.served_address(address, name)
        said = []
        stream = trailers.webos_hls({'url': address, 'container': 'mpd', 'headers': {}}, fetch, save, said.append)
        self.assertEqual(stream['url'], 'http://127.0.0.1:50152/youtube/manifest/dash?file=povil_hls_9O-OCPbf28o.m3u8')
        self.assertEqual((stream['container'], stream['ffmpeg'], stream['height']), ('hls', True, 1080))
        self.assertEqual(sorted(kept), ['povil_hls_9O-OCPbf28o.m3u8', 'povil_hls_9O-OCPbf28o_a.m3u8', 'povil_hls_9O-OCPbf28o_v.m3u8'])
        self.assertIn('povil_hls_9O-OCPbf28o_a.m3u8', kept['povil_hls_9O-OCPbf28o.m3u8'])
        self.assertEqual([span for _url, span in asked], [None, 'bytes=741-892', 'bytes=632-1003'])
        self.assertEqual(said, [])
        # anything wrong: no stream, and the log says why (never the address)
        broken = trailers.webos_hls({'url': address}, lambda *a: (_ for _ in ()).throw(OSError('refused')), save, said.append)
        self.assertIsNone(broken)
        self.assertTrue(said and said[-1].startswith('no HLS: ') and 'http' not in said[-1])

    def test_kodis_own_player_gets_it(self):
        source = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py').read_text('utf-8')
        item = source[source.index('    def make_item(url, stream):'):]
        item = item[:item.index('    home = xbmcgui.Window(10000)')]
        self.assertLess(item.index("if stream.get('ffmpeg'):"), item.index("item.setProperty('inputstream', 'inputstream.adaptive')"))
        self.assertIn("item.setMimeType('application/vnd.apple.mpegurl')", item)
        self.assertIn('stream = webos_hls(stream, fetch, lambda name, text: save_named(name, text, manifest), log)', source)
        # (each reading names its own manifest: a trailer read ahead and one asked for may be read at once)
        self.assertNotIn('served[0]', source)


if __name__ == '__main__':
    unittest.main()
