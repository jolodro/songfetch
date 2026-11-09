import json, unittest
from songfetch.resolvers import (parse_video_title, track_from_video_info, tracks_from_embed,
                                 track_from_meta)


class ResolversTest(unittest.TestCase):
    def test_video_title_parsing(self):
        self.assertEqual(parse_video_title("Skank - Vamos Fugir (Lyric Video)", "Skank"), ("Skank", "Vamos Fugir"))
        self.assertEqual(parse_video_title("vamos fugir", "Skank - Topic"), ("Skank", "vamos fugir"))

    def test_track_from_video_info_prefers_music_metadata(self):
        t = track_from_video_info({"id": "abc", "title": "qualquer", "track": "Faixa", "artist": "A, B", "album": "Alb", "duration": 200})
        self.assertEqual((t.name, t.artists, t.album, t.duration_s, t.id), ("Faixa", ["A", "B"], "Alb", 200, "yt:abc"))
        self.assertEqual(t.direct_url, "https://www.youtube.com/watch?v=abc")

    def test_playlist_entries_carry_playlist(self):
        t = track_from_video_info({"id": "z", "title": "A - B", "duration": 10}, "PL", ("youtube:playlist:PLx", "Minha PL"))
        self.assertEqual(t.playlists, {"youtube:playlist:PLx": "Minha PL"})

    # dados SINTÉTICOS no formato que o parser espera (não são respostas reais do Spotify)
    def test_embed_track_and_playlist(self):
        track = {"props": {"pageProps": {"state": {"data": {"entity": {"name": "Faixa", "artists": [{"name": "A"}, {"name": "B"}], "duration": 283813}}}}}}
        ts, err = tracks_from_embed(track, "track", "T1")
        self.assertIsNone(err); self.assertEqual((ts[0].name, ts[0].artists, round(ts[0].duration_s), ts[0].uri), ("Faixa", ["A", "B"], 284, "spotify:track:T1"))
        self.assertEqual(ts[0].playlists, {})
        pl = {"props": {"pageProps": {"state": {"data": {"entity": {"name": "Minha Lista", "trackList": [
            {"title": "S1", "subtitle": "X,\xa0Y", "duration": 180000, "uri": "spotify:track:AA"},
            {"title": "S2", "subtitle": "Z", "duration": 200000, "uri": "spotify:track:BB"}]}}}}}}
        ts, err = tracks_from_embed(pl, "playlist", "PLID")
        self.assertEqual([t.name for t in ts], ["S1", "S2"]); self.assertEqual(ts[0].artists, ["X", "Y"])
        self.assertEqual(ts[0].playlists, {"spotify:playlist:PLID": "Minha Lista"})
        ts, _ = tracks_from_embed(pl, "album", "ALB")
        self.assertEqual(ts[0].album, "Minha Lista"); self.assertEqual(ts[0].playlists, {})
        self.assertEqual(tracks_from_embed({}, "playlist", "X")[0], [])

    def test_meta_fallback(self):
        html = '<meta property="og:title" content="Vamos Fugir"><meta property="og:description" content="Skank · Cosmotron · Song · 2003"><meta name="music:duration" content="200">'
        t = track_from_meta(html, "ID1")
        self.assertEqual((t.name, t.artists, t.duration_s), ("Vamos Fugir", ["Skank"], 200.0))
        self.assertIsNone(track_from_meta("<html></html>", "ID1"))


if __name__ == "__main__":
    unittest.main()
