import csv, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from songfetch import cli, downloader, pipeline
from songfetch.library import Library, target_dir
from songfetch.models import make_track
from songfetch.pipeline import Ctx, Settings, organize, process

HEAD = ["Track URI", "Track Name", "Album Name", "Artist Name(s)", "Duration (ms)", "ISRC"]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(HEAD); w.writerows(rows)


def fake_download(info, track, out_dir, base_opts, **kw):
    """Cria um arquivo de verdade no lugar do download."""
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{', '.join(track.artists)} - {track.name}.opus"
    p.write_text("audio:" + info["url"])
    return p


def fake_candidates(track, base_opts, use_fallback, notes):
    yield {"url": "https://www.youtube.com/watch?v=" + track.id.split(":")[-1][:11].ljust(11, "x"),
           "title": track.name, "channel": "c", "kind": "topic", "duration": 1, "diff": 0,
           "score": 1, "verified": True}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "downloads"
        self.state = self.tmp / "state"
        self.lib = Library(self.state)
        self.s = Settings(out=self.out)
        self.ctx = Ctx(self.s, {}, self.lib, has_ffmpeg=False)
        p1 = mock.patch.object(pipeline, "download", fake_download)
        p2 = mock.patch.object(pipeline, "candidates", fake_candidates)
        p1.start(); p2.start(); self.addCleanup(mock.patch.stopall)

    def track(self, name, album="Alb", playlists=(), isrc=None):
        t = make_track(name, "Art", album, 100, isrc=isrc or name.upper().replace(" ", ""))
        for k, n in playlists:
            t.playlists[k] = n
        return t


class FolderNamesTest(Base):
    def test_duplicate_playlist_names_get_numbers(self):
        a = self.lib.playlist_folder("k1", "Rock")
        b = self.lib.playlist_folder("k2", "Rock")
        c = self.lib.playlist_folder("k3", "rock")        # maiúsculas diferentes colidem em Windows/macOS
        d = self.lib.playlist_folder("k4", "Rock")
        self.assertEqual([a, b, c, d], ["Rock", "Rock (1)", "rock (2)", "Rock (3)"])
        self.assertEqual(self.lib.playlist_folder("k2", "Rock"), "Rock (1)")   # mesma playlist = mesma pasta

    def test_registry_survives_restart(self):
        self.lib.playlist_folder("k1", "Rock"); self.lib.playlist_folder("k2", "Rock"); self.lib.save()
        again = Library(self.state)
        self.assertEqual(again.playlist_folder("k2", "Rock"), "Rock (1)")
        self.assertEqual(again.playlist_folder("k3", "Rock"), "Rock (2)")

    def test_sanitized_name(self):
        self.assertEqual(self.lib.playlist_folder("k", 'Rock/Pop: "2020"?'), "Rock-Pop- 2020")


class PlaylistPlacementTest(Base):
    def test_download_goes_inside_playlist_then_album_folder(self):
        t = self.track("Vamos Fugir", "Cosmotron", [("k1", "Rock")])
        self.assertEqual(process(t, self.ctx), "ok")
        f = self.lib.path_of(self.lib.log[t.id]["file"])
        self.assertEqual(f, (self.out / "Rock" / "Cosmotron" / "Art - Vamos Fugir.opus").resolve())
        self.assertTrue(f.exists())

    def test_track_in_two_playlists_is_downloaded_once_and_hardlinked(self):
        t = self.track("Dream On", "Aero", [("k1", "Rock"), ("k2", "Favoritas")])
        calls = []
        with mock.patch.object(pipeline, "download", lambda *a, **k: (calls.append(1), fake_download(*a, **k))[1]):
            process(t, self.ctx)
        self.assertEqual(len(calls), 1)
        a = self.out / "Rock" / "Aero" / "Art - Dream On.opus"
        b = self.out / "Favoritas" / "Aero" / "Art - Dream On.opus"
        self.assertTrue(a.exists() and b.exists()); self.assertTrue(os.path.samefile(a, b))
        e = self.lib.log[t.id]
        self.assertEqual(e["playlists"], ["Rock", "Favoritas"]); self.assertEqual(len(e["copies"]), 1)

    def test_no_playlist_means_album_folder_only(self):
        t = self.track("Solta", "Single")
        process(t, self.ctx)
        self.assertTrue((self.out / "Single" / "Art - Solta.opus").exists())

    def test_no_playlist_folders_flag(self):
        self.s.playlist_folders = False
        t = self.track("X", "Alb", [("k1", "Rock")])
        process(t, self.ctx)
        self.assertTrue((self.out / "Alb" / "Art - X.opus").exists()); self.assertFalse((self.out / "Rock").exists())

    def test_layouts(self):
        t = self.track("X", "Alb", [("k1", "Rock")])
        self.assertEqual(target_dir(self.out, t, "flat", "Rock"), self.out / "Rock")
        self.assertEqual(target_dir(self.out, t, "artist", "Rock"), self.out / "Rock" / "Art" / "Alb")

    def test_old_library_files_are_moved_into_playlist_folders(self):
        old_dir = self.out / "Alb"; old_dir.mkdir(parents=True)
        old = old_dir / "Art - Antiga.opus"; old.write_text("x")
        t = self.track("Antiga", "Alb", [("k1", "Rock"), ("k2", "Outra")])
        self.lib.log[t.id] = {"status": "success", "url": "https://yt/1", "file": self.lib.rel(old), "title": "t", "channel": "c", "kind": "topic", "verified": True}
        self.assertTrue(organize(t, self.ctx))
        new = self.out / "Rock" / "Alb" / "Art - Antiga.opus"
        self.assertTrue(new.exists()); self.assertFalse(old.exists()); self.assertFalse(old_dir.exists())   # pasta vazia removida
        self.assertTrue((self.out / "Outra" / "Alb" / "Art - Antiga.opus").exists())
        self.assertEqual(self.lib.path_of(self.lib.log[t.id]["file"]), new.resolve())
        self.assertFalse(organize(t, self.ctx))      # segunda vez: nada a fazer

    def test_shared_file_is_not_moved_but_linked(self):
        d = self.out / "Alb"; d.mkdir(parents=True)
        f = d / "Art - Comp.opus"; f.write_text("x")
        t1 = self.track("Um", "Alb", [("k1", "Rock")]); t2 = self.track("Dois", "Alb", [("k2", "Pop")])
        for t in (t1, t2):
            self.lib.log[t.id] = {"status": "success", "url": "https://yt/same", "file": self.lib.rel(f), "title": "t", "channel": "c", "kind": "topic", "verified": True}
        organize(t1, self.ctx)
        self.assertTrue(f.exists())      # original continua porque t2 ainda aponta para ele
        self.assertTrue((self.out / "Rock" / "Alb" / "Art - Comp.opus").exists())

    def test_reused_video_links_instead_of_downloading(self):
        t1 = self.track("Mesma", "Alb", [("k1", "Rock")]); t2 = self.track("Mesma Versao", "Alb", [("k2", "Pop")], isrc="OTHER")
        process(t1, self.ctx)
        with mock.patch.object(pipeline, "download", side_effect=AssertionError("não deveria baixar")):
            with mock.patch.object(pipeline, "candidates", lambda *a, **k: iter([{"url": self.lib.log[t1.id]["url"], "title": "t", "channel": "c", "kind": "topic", "duration": 1, "diff": 0, "score": 1, "verified": True}])):
                self.assertEqual(process(t2, self.ctx), "ok")
        self.assertTrue(any((self.out / "Pop").rglob("*.opus"))); self.assertTrue(any((self.out / "Rock").rglob("*.opus")))

    def test_dry_run_writes_nothing(self):
        self.s.dry_run = True
        t = self.track("X", "Alb", [("k1", "Rock")])
        process(t, self.ctx)
        self.assertFalse(self.out.exists()); self.assertEqual(self.ctx.preview[0]["playlist"], "Rock")


class CliEndToEndTest(Base):
    def run_cli(self, *args):
        with mock.patch("songfetch.cli.time.sleep"), mock.patch("songfetch.cli.shutil.which", return_value="/usr/bin/ffmpeg"):
            return cli.main([*args, "--out", str(self.out), "--state-dir", str(self.state), "--no-cover"])

    def test_two_csvs_same_name_and_shared_track(self):
        write_csv(self.tmp / "x" / "Rock.csv", [["u1", "Dream On", "Aero", "Aerosmith", "1000", "I1"], ["u2", "Só Rock X", "Al", "A", "1000", "I2"]])
        write_csv(self.tmp / "y" / "Rock.csv", [["u1", "Dream On", "Aero", "Aerosmith", "1000", "I1"], ["u3", "Só Rock Y", "Al", "B", "1000", "I3"]])
        self.assertEqual(self.run_cli(str(self.tmp / "x" / "Rock.csv"), str(self.tmp / "y" / "Rock.csv")), 0)
        rock = sorted(p.name for p in (self.out / "Rock").rglob("*.opus"))
        rock1 = sorted(p.name for p in (self.out / "Rock (1)").rglob("*.opus"))
        self.assertEqual(rock, ["A - Só Rock X.opus", "Aerosmith - Dream On.opus"])
        self.assertEqual(rock1, ["Aerosmith - Dream On.opus", "B - Só Rock Y.opus"])
        # segunda execução: nada pendente, mesmas pastas (não cria Rock (2))
        self.assertEqual(self.run_cli(str(self.tmp / "x" / "Rock.csv"), str(self.tmp / "y" / "Rock.csv")), 0)
        self.assertFalse((self.out / "Rock (2)").exists())

    def test_rerun_after_moving_old_library_into_playlists(self):
        write_csv(self.tmp / "Lista_Nova.csv", [["u1", "Faixa Velha", "Alb", "Art", "1000", "I1"]])
        old = self.out / "Alb"; old.mkdir(parents=True); f = old / "Art - Faixa Velha.opus"; f.write_text("x")
        t = make_track("Faixa Velha", "Art", "Alb", 1, isrc="I1")
        self.lib.log[t.id] = {"status": "success", "url": "https://yt/1", "file": self.lib.rel(f), "title": "t", "channel": "c", "kind": "topic", "verified": True}
        self.lib.save()
        self.assertEqual(self.run_cli(str(self.tmp / "Lista_Nova.csv")), 0)
        self.assertTrue((self.out / "Lista Nova" / "Alb" / "Art - Faixa Velha.opus").exists()); self.assertFalse(f.exists())

    def test_no_inputs_prints_help(self):
        self.assertEqual(cli.main([]), 1)


class Download403Test(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.t = make_track("Vamos Fugir", "Skank", "Alb", 200)
        self.calls = []

    def run_dl(self, plan):
        tmp, calls = self.tmp, self.calls
        class Fake:
            def __init__(s, o): calls.append(o.get("extractor_args"))
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def extract_info(s, url, download=True):
                r = plan.pop(0)
                if isinstance(r, Exception):
                    (tmp / "Skank - Vamos Fugir.webm.part").write_text("x"); raise r
                f = tmp / "Skank - Vamos Fugir.opus"; f.write_text("ok")
                return {"requested_downloads": [{"filepath": str(f)}]}
        sleeps = []
        with mock.patch.object(downloader.yt_dlp, "YoutubeDL", Fake), mock.patch.object(downloader.time, "sleep", sleeps.append), \
             mock.patch.object(downloader, "add_cover", return_value=True), mock.patch.object(downloader, "tag_file"):
            p = downloader.download({"url": "u"}, self.t, self.tmp, {}, fmt="best", cover=True, has_ffmpeg=False)
        return p, sleeps

    E403 = Exception("ERROR: unable to download video data: HTTP Error 403: Forbidden")

    def test_recovers_after_403(self):
        p, sleeps = self.run_dl([self.E403, self.E403, None])
        self.assertIsNotNone(p); self.assertEqual(sleeps, [8, 20])
        self.assertEqual(self.calls[2], {"youtube": {"player_client": ["web_safari"]}})
        self.assertFalse(list(self.tmp.glob("*.part")))

    def test_persistent_403_gives_up_after_4_attempts(self):
        p, sleeps = self.run_dl([self.E403] * 4)
        self.assertIsNone(p); self.assertEqual(sleeps, [8, 20, 40]); self.assertEqual(len(self.calls), 4)

    def test_other_errors_do_not_retry(self):
        p, sleeps = self.run_dl([Exception("ERROR: Video unavailable")])
        self.assertIsNone(p); self.assertEqual(sleeps, []); self.assertEqual(len(self.calls), 1)


class CandidatesTest(unittest.TestCase):
    def test_direct_link_skips_search_and_plan_b_follows_plan_a(self):
        from songfetch import youtube
        direct = make_track("T", "A", direct_url="https://www.youtube.com/watch?v=abcdefghijk", tid="yt:abcdefghijk")
        with mock.patch.object(youtube, "search", side_effect=AssertionError("não deveria buscar")):
            got = list(youtube.candidates(direct, {}, True, []))
        self.assertEqual([g["kind"] for g in got], ["direct"])

        t = make_track("Se Deus É por Nós", "Leandro Soares;Marcelo Markes", "Alb", 262)
        def fake_search(q, opts, n=15):
            if n == 5:
                return [{"id": "karaoke1", "title": "Se Deus É por Nós (Karaokê)", "duration": 262},
                        {"id": "longe", "title": "Culto completo", "duration": 900},
                        {"id": "perto", "title": "Se Deus é por nós", "channel": "Y", "duration": 263}]
            return [{"id": "x", "title": "Outra coisa", "channel": "Z", "duration": 262}]
        with mock.patch.object(youtube, "search", fake_search):
            kinds = [(g["kind"], g["url"][-5:]) for g in youtube.candidates(t, {}, True, [])]
            self.assertEqual(kinds, [("fallback", "perto")])
            self.assertEqual(list(youtube.candidates(t, {}, False, [])), [])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg ausente")
class CoversTest(unittest.TestCase):
    def test_embed_and_fix_covers_including_copies(self):
        import io
        from PIL import Image
        from songfetch import tagging
        tmp = Path(tempfile.mkdtemp())
        base = tmp / "a.opus"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libopus", str(base)], check=True)
        buf = io.BytesIO(); Image.new("RGB", (8, 8), (200, 0, 0)).save(buf, "JPEG")
        shutil.copy(base, tmp / "b.opus")
        lib = Library(tmp / "st"); ctx = Ctx(Settings(out=tmp), {}, lib)
        lib.log["x"] = {"status": "success", "file": str(base), "copies": [str(tmp / "b.opus")], "track": "T", "artist": "A", "album": "Al", "uri": ""}
        with mock.patch.object(tagging, "fetch_cover", return_value=(buf.getvalue(), "image/jpeg")):
            novos, ja, sem = pipeline.fix_covers(ctx)
        self.assertEqual((novos, ja, sem), (2, 0, 0))
        self.assertTrue(tagging.has_cover(base) and tagging.has_cover(tmp / "b.opus"))


if __name__ == "__main__":
    unittest.main()
