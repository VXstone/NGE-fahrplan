"""Vorbereitete Fahrplandaten bauen (laeuft im GitHub-Workflow 'fahrplandaten').

  python tools/fahrplandaten.py <ausgabeordner> [--day JJJJ-MM-TT] [--year JJJJ]

Schritte: fetch (topo-daten, atlas, HRDF) -> stations -> extract (alle Bahnstationen,
Referenztag) -> stand.json. Zusaetzlich (unabhaengig, zaehlt nicht fuer den Erfolg des
Laufs): Zugzahlen je Streckenabschnitt von data.sbb.ch -> zugzahlen*.csv.gz. Jeder Schritt wird protokolliert, ein Fehler bricht nicht
alles ab: stand.json wird immer geschrieben, weil die Lauf-Logs ausserhalb von GitHub
nicht lesbar sind.
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nge_fahrplan import cli, download, hrdf  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--day")
ap.add_argument("--year", type=int)
a = ap.parse_args()
out = Path(a.out)
data = out / "roh"
out.mkdir(parents=True, exist_ok=True)
year = a.year or (dt.date.today().year + (dt.date.today().month == 12))

stand = {"erzeugt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
         "lauf": f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}"
                 f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
         "fahrplanjahr": year, "schritte": {}, "quellen": {}}


def schritt(name, fn):
    t0 = time.time()
    try:
        r = fn()
        stand["schritte"][name] = f"OK ({time.time() - t0:.0f} s)"
        return r
    except BaseException as e:  # SystemExit aus argparse/cli mitnehmen
        stand["schritte"][name] = f"FEHLER {type(e).__name__}: {e}"[:400]
        stand.setdefault("fehler", {})[name] = traceback.format_exc()[-2000:]
        return None


def fetch(kind):
    p = download.fetch(kind, data, year=year)
    stand["quellen"][kind] = {"datei": Path(p).name, "groesse_mb": round(Path(p).stat().st_size / 1e6, 1)}
    if kind != "topo":
        try:
            stand["quellen"][kind].update(download.find_resource(kind, year))
        except Exception:
            pass


for k in ("topo", "didok", "hrdf"):
    schritt(f"fetch_{k}", lambda k=k: fetch(k))

didok_csv = next((p for p in sorted(data.glob("*.csv")) if "service-point" in p.name), None)
hrdf_zip = next(iter(sorted(data.glob("*hrdf*.zip"))), None)
args = ["stations", "--out", str(out / "stations.csv"), "--data", str(data)]
if didok_csv:
    args += ["--didok", str(didok_csv)]
if hrdf_zip:
    args += ["--hrdf", str(hrdf_zip)]
if (data / "betriebspunkte.json").exists():
    args += ["--topo", str(data / "betriebspunkte.json")]
schritt("stations", lambda: cli.main(args))

alle = data / "trips_alle_tage.json.gz"
if hrdf_zip and (out / "stations.csv").exists():
    ex = ["extract", "--db", str(out / "stations.csv"), "--hrdf", str(hrdf_zip), "--all-stations",
          "--all-days", "--out", str(alle)]
    schritt("extract", lambda: cli.main(ex))


def tag_filtern():
    h = hrdf.HRDF(hrdf_zip)
    d = hrdf.load_trips(alle)
    ref = dt.date.fromisoformat(a.day) if a.day else cli._ref_day(h, None)
    off, prot = hrdf.calibrate_offset(h, d, ref)
    stand["verkehrstage"] = {
        "bit_offset": off, "erwartet": 0,
        "fahrten_je_wochentag_Mo_bis_So_je_offset": prot,
        "ohne_bitfeld": sum(1 for t in d["trips"] if not t.get("bitfield")),
        "mit_bitfeld": sum(1 for t in d["trips"] if t.get("bitfield")),
        "fahrten_je_tag": hrdf.runs_per_day(h, d, ref - dt.timedelta(days=ref.weekday()), 14),
    }
    hrdf.save_trips(hrdf.filter_day(h, d, ref), out / "trips_bahn.json.gz")


if alle.exists():
    schritt("verkehrstag", tag_filtern)

tb = out / "trips_bahn.json.gz"
if tb.exists():
    d = hrdf.load_trips(tb)
    st = cli.didok.StationDB(out / "stations.csv")
    by_cat = collections.Counter(t["cat"] for t in d["trips"])
    halte = collections.Counter(s["num"] for t in d["trips"] for s in t["stops"] if not s["pass"])
    stand["fahrten"] = {
        "tag": d["meta"].get("day"), "fahrplanperiode": d["meta"].get("period"),
        "hrdf": d["meta"].get("hrdf"), "anzahl": len(d["trips"]),
        "groesse_mb": round(tb.stat().st_size / 1e6, 1),
        "nach_gattung": dict(by_cat.most_common()),
        "stichproben_halte": {a: halte.get(st.resolve(a).number, 0)
                              for a in ("BN", "ZUE", "OL", "NE", "BS", "GE", "LS", "OLO") if a in st.by_abbr},
        "linien_beispiel": sorted({f"{t['cat']} {t['line']}" for t in d["trips"]
                                   if 8504221 in {s['num'] for s in t['stops']}})[:40],
    }

# Zusatz: Zugzahlen (data.sbb.ch). Eigener Bereich in stand.json, damit ein Fehler hier
# das Hochladen der Fahrplandaten nicht blockiert.
def zugzahlen():
    download.fetch_zugzahlen(out)
    info = {}
    import gzip
    for f in sorted(out.glob("zugzahlen*.csv.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            kopf = fh.readline().strip().split(";")
            info[f.name] = {"zeilen": sum(1 for _ in fh), "spalten": kopf,
                            "groesse_mb": round(f.stat().st_size / 1e6, 2)}
    stand["zugzahlen"] = info


t0 = time.time()
try:
    zugzahlen()
    stand["zusatz"] = {"zugzahlen": f"OK ({time.time() - t0:.0f} s)"}
except BaseException as e:
    stand["zusatz"] = {"zugzahlen": f"FEHLER {type(e).__name__}: {e}"[:400]}

stand["stationen"] = sum(1 for _ in open(out / "stations.csv")) - 1 if (out / "stations.csv").exists() else 0
(out / "stand.json").write_text(json.dumps(stand, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in stand.items() if k != "fehler"}, ensure_ascii=False, indent=1))
sys.exit(0 if all(v.startswith("OK") for v in stand["schritte"].values()) else 1)
