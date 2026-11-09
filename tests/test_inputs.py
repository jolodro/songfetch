import csv, json, tempfile, unittest
from pathlib import Path

from songfetch.inputs import collect, load_file, parse_query, header_key
from songfetch.resolvers import classify, to_spotify_uri

EXPORTIFY = ["Track URI", "Track Name", "Album Name", "Artist Name(s)", "Release Date",
             "Duration (ms)", "Popularity", "ISRC"]


def write_csv(path, header, rows, delim=","):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=delim)
        w.writerow(header)
        w.writerows(rows)


class InputsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def collect(self, *inputs, resolve=None):
        kw = {"resolve": resolve} if resolve else {}
        return collect([str(i) for i in inputs], {}, **kw)

    def test_exportify_csv_playlist_name_from_file(self):
        p = self.tmp / "Rock_pra_Brócolas____.csv"
        write_csv(p, EXPORTIFY, [["spotify:track:AAA", "Vamos Fugir", "Cosmotron", "Skank", "2003", "200000", "50", "BRX1"],
                                 ["spotify:track:BBB", "X", "Alb", "A;B", "2000", "180500", "1", "BRX2"]])
        tracks, notes, pls = self.collect(p)
        self.assertEqual(notes, [])
        self.assertEqual(list(pls.values()), ["Rock pra Brócolas"])
        t = tracks[0]
        self.assertEqual((t.name, t.artists, t.album, t.duration_s, t.id), ("Vamos Fugir", ["Skank"], "Cosmotron", 200.0, "isrc:BRX1"))
        self.assertEqual(tracks[1].artists, ["A", "B"])
        self.assertEqual(tracks[0].uri, "spotify:track:AAA")

    def test_two_files_same_name_have_different_keys(self):
        (self.tmp / "a").mkdir(); (self.tmp / "b").mkdir()
        for d in "ab":
            write_csv(self.tmp / d / "Rock.csv", EXPORTIFY, [["u" + d, "Faixa " + d, "Al", "Art", "", "1000", "", ""]])
        tracks, _, pls = self.collect(self.tmp / "a" / "Rock.csv", self.tmp / "b" / "Rock.csv")
        self.assertEqual(len(pls), 2)
        self.assertEqual(list(pls.values()), ["Rock", "Rock"])

    def test_track_in_two_playlists_is_merged(self):
        for n in ("A", "B"):
            write_csv(self.tmp / f"{n}.csv", EXPORTIFY, [["u1", "Mesma", "Al", "Art", "", "1000", "", "ISRC1"]])
        tracks, _, pls = self.collect(self.tmp / "A.csv", self.tmp / "B.csv")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(list(tracks[0].playlists.values()), ["A", "B"])
        self.assertEqual(list(pls.values()), ["A", "B"])

    def test_simple_portuguese_table_and_semicolon(self):
        p = self.tmp / "minhas.csv"
        write_csv(p, ["Música", "Artista", "Álbum", "Duração"], [["Se Deus É por Nós", "Leandro Soares;Marcelo Markes", "Alb", "4:22"]], ";")
        t = self.collect(p)[0][0]
        self.assertEqual((t.name, t.artists, t.duration_s), ("Se Deus É por Nós", ["Leandro Soares", "Marcelo Markes"], 262.0))

    def test_playlist_column_splits_playlists(self):
        p = self.tmp / "tudo.csv"
        write_csv(p, ["Track name", "Artist name", "Playlist name"],
                  [["S1", "Art", "Rock"], ["S2", "Art", "Louvor"], ["S3", "Art", "Rock"]])
        tracks, _, pls = self.collect(p)
        self.assertEqual(sorted(pls.values()), ["Louvor", "Rock"])
        self.assertEqual(len(tracks), 3)

    def test_txt_queries_links_and_comments(self):
        p = self.tmp / "desejos.txt"
        p.write_text("# minha lista\nSkank - Vamos Fugir\n\nSó o título\nhttps://youtu.be/abcdefghijk\n", encoding="utf-8")
        seen = []
        def fake(link, opts):
            seen.append(link)
            from songfetch.models import make_track
            return [make_track("Vídeo", "Canal", direct_url="https://www.youtube.com/watch?v=abcdefghijk", tid="yt:abcdefghijk")], None
        tracks, notes, pls = self.collect(p, resolve=fake)
        self.assertEqual([t.name for t in tracks], ["Vamos Fugir", "Só o título", "Vídeo"])
        self.assertEqual(tracks[0].artists, ["Skank"]); self.assertEqual(tracks[1].artists, [])
        self.assertEqual(list(pls.values()), ["desejos"])
        self.assertEqual(list(tracks[2].playlists.values()), ["desejos"])   # link solto herda a lista
        self.assertEqual(seen, ["https://youtu.be/abcdefghijk"])

    def test_playlist_link_keeps_its_own_playlist(self):
        from songfetch.models import make_track
        def fake(link, opts):
            return [make_track("T", "A", playlist=("spotify:playlist:XYZ", "Minha Lista Spotify"))], None
        tracks, _, pls = collect(["https://open.spotify.com/playlist/XYZ"], {}, resolve=fake)
        self.assertEqual(list(pls.values()), ["Minha Lista Spotify"])

    def test_cli_text_and_single_track_have_no_playlist(self):
        tracks, _, pls = collect(["Skank - Vamos Fugir"], {})
        self.assertEqual(pls, {}); self.assertEqual(tracks[0].playlists, {})

    def test_spotify_data_export_json_names_playlists(self):
        p = self.tmp / "Playlist1.json"
        p.write_text(json.dumps({"playlists": [
            {"name": "Treino", "items": [{"track": {"trackName": "A", "artistName": "X", "albumName": "Al", "trackUri": "spotify:track:T1"}}]},
            {"name": "Treino", "items": [{"track": {"trackName": "B", "artistName": "Y", "albumName": "Bl", "trackUri": "spotify:track:T2"}}]}]}), encoding="utf-8")
        tracks, _, pls = self.collect(p)
        self.assertEqual(list(pls.values()), ["Treino", "Treino"])    # iguais, chaves diferentes
        self.assertEqual(tracks[0].uri, "spotify:track:T1")

    def test_json_list_of_strings_and_objects(self):
        p = self.tmp / "l.json"
        p.write_text(json.dumps(["Skank - Vamos Fugir", {"title": "Outra", "artist": "Z"}]), encoding="utf-8")
        tracks, notes, _ = self.collect(p)
        self.assertEqual({t.name for t in tracks}, {"Vamos Fugir", "Outra"})

    def test_xlsx(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl ausente")
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(["Track Name", "Artist Name(s)", "Duration (ms)"]); ws.append(["Faixa X", "Art", 180000])
        p = self.tmp / "planilha.xlsx"; wb.save(p)
        t = self.collect(p)[0][0]
        self.assertEqual((t.name, t.duration_s), ("Faixa X", 180.0))

    def test_directory_scan_ignores_state_and_unknown_files(self):
        write_csv(self.tmp / "ok.csv", EXPORTIFY, [["u", "N", "A", "Art", "", "1000", "", ""]])
        write_csv(self.tmp / "lixo.csv", ["foo", "bar"], [["1", "2"]])
        (self.tmp / "download_log.json").write_text("{}")
        (self.tmp / "preview_links.csv").write_text("x,y\n")
        tracks, notes, pls = self.collect(self.tmp)
        self.assertEqual(len(tracks), 1); self.assertEqual(notes, [])

    def test_explicit_unrecognized_file_and_missing_file_give_notes(self):
        write_csv(self.tmp / "lixo.csv", ["foo", "bar"], [["1", "2"]])
        _, notes, _ = self.collect(self.tmp / "lixo.csv", self.tmp / "nao_existe.csv")
        self.assertEqual(len(notes), 2)
        self.assertIn("colunas não reconhecidas", notes[0]); self.assertIn("não encontrado", notes[1])

    def test_misc_helpers(self):
        self.assertEqual(header_key("trackName"), "track name")
        self.assertEqual(classify("https://open.spotify.com/intl-pt/track/4uLU6hMCjMI75M1A2tKUQC?si=x"), ("spotify", "track", "4uLU6hMCjMI75M1A2tKUQC"))
        self.assertEqual(classify("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"), ("spotify", "playlist", "37i9dQZF1DXcBWIGoYBM5M"))
        self.assertEqual(classify("https://youtu.be/dQw4w9WgXcQ?t=3"), ("youtube", "video", "dQw4w9WgXcQ"))
        self.assertEqual(classify("https://www.youtube.com/watch?v=abc&list=PLx"), ("youtube", "video", "abc"))
        self.assertEqual(classify("https://www.youtube.com/playlist?list=PLx"), ("youtube", "playlist", "PLx"))
        self.assertEqual(classify("https://example.com/x"), None)
        self.assertEqual(to_spotify_uri("https://open.spotify.com/track/ABC123?si=1"), "spotify:track:ABC123")
        t = parse_query("Marisa Monte - Amor I Love You")
        self.assertEqual((t.artists, t.name), (["Marisa Monte"], "Amor I Love You"))


if __name__ == "__main__":
    unittest.main()
