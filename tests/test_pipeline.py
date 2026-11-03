import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_fixtures import make  # noqa: E402
from nge_fahrplan import didok, hrdf, lines, nge, validate  # noqa: E402
from nge_fahrplan.cli import main  # noqa: E402


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.zip, cls.csv = make(cls.tmp / "fx")
        cls.db_path = cls.tmp / "stations.csv"
        didok.build_db([cls.csv], cls.zip, cls.db_path)
        cls.db = didok.StationDB(cls.db_path)

    def test_stationsdb(self):
        self.assertEqual(self.db.resolve("ne").name, "Neuchâtel")
        self.assertEqual(self.db.resolve("8507000").abbr, "BN")
        self.assertEqual(self.db.resolve("Gampelen").abbr, "GAMP")      # nur aus HRDF
        self.assertIsNotNone(self.db.resolve("GAMP").lat)
        self.assertNotIn(8512345, self.db.by_num)                      # Bus ohne Abk.
        self.assertTrue(len(self.db.within(46.99, 7.0, 15)) >= 3)

    def test_topo_betriebspunkte(self):
        topo = self.tmp / "betriebspunkte.json"
        topo.write_text(json.dumps([
            {"name": "Olten Ost (Abzw)", "abk": "OLO", "typ": "Abzweigstelle", "lat": 47.3586,
             "lon": 7.9256, "didok": 244, "linie": 450, "km": 39.1},
            {"name": "Neuchâtel", "abk": "NE", "lat": 1.0, "lon": 1.0, "didok": 4221}]))
        out = self.tmp / "st_topo.csv"
        didok.build_db([self.csv], None, out, topo=[topo])
        db = didok.StationDB(out)
        self.assertEqual(db.resolve("OLO").number, 8500244)          # neu aus topo-daten
        self.assertAlmostEqual(db.resolve("NE").lat, 46.99677, 4)     # atlas hat Vorrang

    def test_time_parse(self):
        self.assertEqual(hrdf.parse_time(" 00813"), 8 * 60 + 13)
        self.assertEqual(hrdf.parse_time("-02405"), 24 * 60 + 5)
        self.assertIsNone(hrdf.parse_time("      "))

    def test_extract_and_bitfield(self):
        h = hrdf.HRDF(self.zip)
        self.assertEqual(h.start, dt.date(2025, 12, 14))
        nums = {s.number for s in self.db.by_num.values()}
        even, odd = h.start + dt.timedelta(days=100), h.start + dt.timedelta(days=101)
        re_even = [t for t in h.trips(nums, even, lines.RAIL) if t["cat"] == "RE"]
        re_odd = [t for t in h.trips(nums, odd, lines.RAIL) if t["cat"] == "RE"]
        self.assertEqual(len(re_even), 16)
        self.assertEqual(len(re_odd), 0)
        self.assertEqual(re_even[0]["line"], "RE5")                      # *L #0000001 -> LINIE
        self.assertTrue(re_even[0]["stops"][1]["pass"])                  # KZ Durchfahrt
        s5 = [t for t in h.trips(nums, even, lines.RAIL) if t["line"] == "S5"]
        self.assertEqual(len(s5), 64)                                    # 2 x (1+31) Taktfahrten
        self.assertEqual(s5[0]["stops"][-1]["skipped"], 1)
        self.assertFalse(any(t["cat"] == "B" for t in h.trips(nums, even, lines.RAIL)))

    def test_cli_run_end_to_end(self):
        out = self.tmp / "netz.json"
        main(["run", "--db", str(self.db_path), "--hrdf", str(self.zip),
              "--stations", "BN,KZ,INS,GAMP,NE", "--day", "2026-03-24",
              "--work", str(self.tmp / "work"), "--out", str(out)])
        d = json.loads(out.read_text())
        self.assertEqual(validate.validate(d), [])
        names = sorted(t["name"] for t in d["trainruns"])
        self.assertIn("66 BN-NE", names)
        self.assertIn("S5 INS-NE", names)
        spec = json.loads((self.tmp / "work" / "spec.json").read_text())
        freq = {t["name"]: t["frequency"] for t in spec["trainruns"]}
        self.assertEqual(freq["S5 INS-NE"], "30")
        self.assertEqual(freq["66 BN-NE"], "60")
        re = [t for t in spec["trainruns"] if t["hrdf"]["cat"] == "RE"]
        if re:  # Referenztag kann ein Nicht-Verkehrstag sein
            self.assertIn(re[0]["frequency"], ("120", "120+"))

        # IR 66: echte asymmetrische Rueckfahrt
        ir = next(t for t in d["trainruns"] if t["name"] == "66 BN-NE")
        nid = {n["id"]: n["betriebspunktName"] for n in d["nodes"]}
        secs = {(nid[s["sourceNodeId"]], nid[s["targetNodeId"]]): s
                for s in d["trainrunSections"] if s["trainrunId"] == ir["id"]}
        bn_kz = secs[("BN", "KZ")]
        self.assertEqual(bn_kz["sourceDeparture"]["time"], 13)
        self.assertEqual(bn_kz["targetArrival"]["time"], 30)
        self.assertEqual(bn_kz["sourceArrival"]["time"], 47)
        self.assertEqual(bn_kz["targetDeparture"]["time"], 30)
        self.assertEqual(bn_kz["travelTime"]["time"], 17)
        self.assertEqual(bn_kz["backwardTravelTime"]["time"], 17)
        self.assertTrue(bn_kz["sourceSymmetry"])           # 13 / 47
        self.assertFalse(secs[("INS", "NE")]["targetSymmetry"])  # an :48, ab :11
        ne = next(n for n in d["nodes"] if n["betriebspunktName"] == "NE")
        bn = next(n for n in d["nodes"] if n["betriebspunktName"] == "BN")
        self.assertLess(ne["positionX"], bn["positionX"])                # NE liegt westlich
        port = next(p for p in bn["ports"] if p["trainrunSectionId"] == bn_kz["id"])
        self.assertEqual(port["positionAlignment"], nge.LEFT)
        # Transition an KZ, INS
        kz = next(n for n in d["nodes"] if n["betriebspunktName"] == "KZ")
        self.assertTrue(kz["transitions"])

    def test_full_extract_then_subset(self):
        full = self.tmp / "trips_bahn.json.gz"
        main(["extract", "--db", str(self.db_path), "--hrdf", str(self.zip), "--all-stations",
              "--day", "2026-03-24", "--out", str(full)])
        sub = self.tmp / "sub.json"
        main(["extract", "--db", str(self.db_path), "--from-trips", str(full),
              "--stations", "BN,KZ,INS,NE", "--out", str(sub)])
        d = hrdf.load_trips(sub)
        s5 = [t for t in d["trips"] if t["line"] == "S5" and t["stops"][0]["num"] == 8504488]
        self.assertTrue(s5)
        self.assertEqual([s["num"] for s in s5[0]["stops"]], [8504488, 8504221])
        self.assertEqual(s5[0]["stops"][1]["skipped"], 2)               # GAMP + Fiktiv
        out = self.tmp / "netz_sub.json"
        main(["run", "--db", str(self.db_path), "--hrdf", "/nicht/da.zip", "--from-trips", str(full),
              "--stations", "BN,KZ,INS,NE", "--work", str(self.tmp / "w2"), "--out", str(out)])
        n = json.loads(out.read_text())
        self.assertEqual(validate.validate(n), [])
        sec = next(x for x in n["trainrunSections"]
                   if x["numberOfStops"] == 2)
        self.assertEqual(sec["travelTime"]["time"], 17)

    def test_split_gaps(self):
        full = self.tmp / "tb2.json.gz"
        main(["extract", "--db", str(self.db_path), "--hrdf", str(self.zip), "--all-stations",
              "--day", "2026-03-24", "--out", str(full)])
        # BN und INS ohne KZ: IR 66 verlaesst die Region nicht -> bleibt ganz;
        # mit KZ,NE ohne INS/GAMP: S5 INS..NE faellt weg, IR 66 KZ-NE wird getrennt
        d = hrdf.subset(hrdf.load_trips(full), [8504489, 8504221], split_gaps=True)
        self.assertFalse([t for t in d["trips"] if len(t["stops"]) >= 2
                          and t["stops"][-1]["skipped"]])
        d2 = hrdf.subset(hrdf.load_trips(full), [8504489, 8504221], split_gaps=False)
        self.assertTrue(any(t["cat"] == "IR" for t in d2["trips"]))
        self.assertFalse(any(t["cat"] == "IR" for t in d["trips"]))

    def test_symmetric_build_without_back(self):
        spec = {"trainruns": [{"name": "X", "category": "IC", "frequency": "30",
                               "stops": [{"at": "BN", "dep": 2}, {"at": "FR", "arr": 22, "dep": 24},
                                         {"at": "NE", "arr": 70}]}]}
        d, warn = nge.build(spec, self.db)
        self.assertEqual(validate.validate(d), [])
        s = d["trainrunSections"]
        self.assertEqual(s[0]["sourceArrival"]["time"], 58)
        self.assertEqual(s[1]["targetArrival"]["time"], 10)
        self.assertEqual(s[1]["travelTime"]["time"], 46)
        self.assertEqual(s[1]["backwardTravelTime"]["time"], 46)
        self.assertTrue(all(x["sourceSymmetry"] and x["targetSymmetry"] for x in s))

    def test_validator_catches_orphans(self):
        spec = {"trainruns": [{"name": "X", "stops": [{"at": "BN", "dep": 0}, {"at": "KZ", "arr": 17, "dep": 18},
                                                       {"at": "INS", "arr": 24}]}]}
        d, _ = nge.build(spec, self.db)
        d["trainrunSections"].pop()
        errs = validate.validate(d)
        self.assertTrue(any("fehlende Section" in e for e in errs))


if __name__ == "__main__":
    unittest.main()


class Perlschnur(unittest.TestCase):
    def test_ast_gleichmaessig_aufgereiht(self):
        # Stern: Knoten H mit drei Aesten; Ast nach Westen hat 4 Zwischenhalte
        class St:
            def __init__(s, abbr, lat, lon): s.abbr, s.name, s.lat, s.lon = abbr, abbr, lat, lon
        coords = {"H": (47.5, 8.2), "A1": (47.51, 8.1), "A2": (47.5, 8.0), "A3": (47.52, 7.9),
                  "A4": (47.51, 7.8), "AE": (47.53, 7.6), "N": (47.6, 8.2), "O": (47.5, 8.4)}

        class DB:
            def resolve(s, a): return St(a, *coords[a])
        spec = {"trainruns": [
            {"name": "w", "category": "S", "stops": [{"at": a, "dep": 0} for a in
                                                     ("H", "A1", "A2", "A3", "A4", "AE")]},
            {"name": "n", "category": "S", "stops": [{"at": "H", "dep": 0}, {"at": "N", "arr": 5}]},
            {"name": "o", "category": "S", "stops": [{"at": "H", "dep": 0}, {"at": "O", "arr": 5}]}]}
        for tr in spec["trainruns"]:
            for i, s in enumerate(tr["stops"]):
                s.pop("dep", None); s.pop("arr", None)
                if i: s["arr"] = 2 * i
                if i < len(tr["stops"]) - 1: s["dep"] = 2 * i + 1
        out, _ = nge.build(spec, DB(), layout="perlschnur", spacing=256)
        self.assertEqual(validate.validate(out), [])
        p = {n["betriebspunktName"]: (n["positionX"], n["positionY"]) for n in out["nodes"]}
        ys = {p[k][1] for k in ("H", "A1", "A2", "A3", "A4", "AE")}
        self.assertEqual(len(ys), 1)                                  # eine Reihe
        xs = [p[k][0] for k in ("A1", "A2", "A3", "A4", "AE")]
        self.assertEqual({a - b for a, b in zip(xs, xs[1:])}, {256})  # gleicher Abstand
        self.assertLess(xs[0], p["H"][0])                             # nach Westen
