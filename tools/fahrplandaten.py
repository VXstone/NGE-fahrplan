"""Vorbereitete Fahrplandaten bauen (laeuft im GitHub-Workflow 'fahrplandaten').

  python tools/fahrplandaten.py <ausgabeordner> [--day JJJJ-MM-TT] [--year JJJJ]

Schritte: fetch (topo-daten, atlas, HRDF) -> stations -> extract (alle Bahnstationen,
Referenztag) -> stand.json. Jeder Schritt wird protokolliert, ein Fehler bricht nicht
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

if hrdf_zip and (out / "stations.csv").exists():
    ex = ["extract", "--db", str(out / "stations.csv"), "--hrdf", str(hrdf_zip), "--all-stations",
          "--out", str(out / "trips_bahn.json.gz")]
    if a.day:
        ex += ["--day", a.day]
    schritt("extract", lambda: cli.main(ex))

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
stand["stationen"] = sum(1 for _ in open(out / "stations.csv")) - 1 if (out / "stations.csv").exists() else 0
(out / "stand.json").write_text(json.dumps(stand, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in stand.items() if k != "fehler"}, ensure_ascii=False, indent=1))
sys.exit(0 if all(v.startswith("OK") for v in stand["schritte"].values()) else 1)
