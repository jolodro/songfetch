import unittest
from songfetch.matcher import evaluate, rank_candidates, loose_rows
from songfetch.models import make_track
from songfetch.textutil import clean_title, norm, parse_duration, pretty_name, sanitize


class MatcherTest(unittest.TestCase):
    def best(self, t, entries):
        ok, why = rank_candidates(t, entries)
        return (ok[0] if ok else None), why

    def test_text_helpers(self):
        self.assertEqual(norm("Nada Mais/Uma Vez"), "nada mais uma vez")
        self.assertEqual(clean_title("Dream On - Remastered 2004"), "Dream On")
        self.assertEqual(clean_title("Amor I Love You / Citação: Trecho \"Primo Basilio\""), "Amor I Love You")
        self.assertEqual(clean_title("Nada Mais/Uma Vez"), "Nada Mais/Uma Vez")
        self.assertEqual(pretty_name("Andre___Julia_S2"), "Andre Julia S2")
        self.assertEqual(sanitize('a/b:c*d?"e'), "a-b-cde")
        self.assertEqual(parse_duration("4:22"), 262); self.assertEqual(parse_duration("283813"), 283.813)
        self.assertEqual(parse_duration("225"), 225)

    def test_multi_artist_prefers_topic(self):
        t = make_track("Se Deus É por Nós", "Leandro Soares;Marcelo Markes", "Alb", 262)
        E = [{"id": "cover1", "title": "Se Deus É por Nós (cover)", "channel": "Fulano", "duration": 262},
             {"id": "lyr", "title": "Leandro Soares, Marcelo Markes - Se Deus É por Nós (Letra)", "channel": "Letras", "duration": 263},
             {"id": "topic", "title": "Se Deus É por Nós", "channel": "Leandro Soares - Topic", "duration": 262},
             {"id": "longo", "title": "Marcelo Markes - Se Deus É por Nós", "channel": "Marcelo Markes", "duration": 400}]
        self.assertTrue(self.best(t, E)[0]["url"].endswith("topic"))

    def test_discover_ok_cover_rejected(self):
        t = make_track("Discover Love", "Band", "A", 200)
        self.assertIsNotNone(self.best(t, [{"id": "a", "title": "Band - Discover Love", "channel": "Band", "duration": 201}])[0])
        self.assertIsNone(self.best(t, [{"id": "b", "title": "Band - Discover Love (Cover)", "channel": "X", "duration": 200}])[0])

    def test_live_vs_studio(self):
        live = make_track("Me Atraiu - Ao Vivo", "Gabriela Rocha", "Album", 300)
        E = [{"id": "est", "title": "Gabriela Rocha - Me Atraiu", "channel": "Gabriela Rocha", "duration": 300},
             {"id": "live", "title": "Gabriela Rocha - Me Atraiu (Ao Vivo)", "channel": "Gabriela Rocha", "duration": 305}]
        self.assertTrue(self.best(live, E)[0]["url"].endswith("live"))
        studio = make_track("Dream On", "Aerosmith", "Aerosmith", 268)
        E = [{"id": "live", "title": "Aerosmith - Dream On (Live)", "channel": "Aerosmith", "duration": 270},
             {"id": "est", "title": "Aerosmith - Dream On", "channel": "Aerosmith", "duration": 269}]
        self.assertTrue(self.best(studio, E)[0]["url"].endswith("est"))

    def test_duration_out_of_tolerance(self):
        t = make_track("Dream On", "Aerosmith", "", 268)
        info, why = self.best(t, [{"id": "q", "title": "Aerosmith - Dream On", "channel": "Aerosmith", "duration": 400}])
        self.assertIsNone(info); self.assertIn("duração", why[0])

    def test_long_title_with_slash_matches_short_video(self):
        t = make_track('Amor I Love You / Citação: Trecho da Obra Intitulada "Primo Basilio" De Eça de Queiroz Declamado por Arnaldo Antunes', "Marisa Monte", "", 270)
        info, _ = evaluate(t, {"id": "ok", "title": "Marisa Monte - Amor I Love You", "channel": "Marisa Monte", "duration": 272})
        self.assertIsNotNone(info)

    def test_no_artist_given_still_matches_by_title(self):
        t = make_track("Vamos Fugir", [], "", 0)
        info, _ = evaluate(t, {"id": "x", "title": "Skank - Vamos Fugir", "channel": "Skank", "duration": 200})
        self.assertIsNotNone(info)

    def test_loose_rows_orders_by_duration_and_skips_karaoke(self):
        t = make_track("Se Deus É por Nós", "A", "", 262)
        rows = loose_rows(t, [{"id": "k", "title": "Se Deus (Karaokê)", "duration": 262},
                              {"id": "far", "title": "x", "duration": 900},
                              {"id": "near", "title": "y", "duration": 263}])
        self.assertEqual([r[1]["id"] for r in rows], ["near", "far"])

    def test_artist_variants(self):
        t = make_track("X", "Jefferson & Suellen", "", 1)
        self.assertIn("suellen", t.artist_norms); self.assertIn("jefferson suellen", t.artist_norms)


if __name__ == "__main__":
    unittest.main()
