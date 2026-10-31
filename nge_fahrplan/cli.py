"""Kommandozeile:  python -m nge_fahrplan <befehl> ...   (oder: nge-fahrplan <befehl>)"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import didok, download, hrdf, lines, nge, validate

DATA = Path("data")
DB = DATA / "stations.csv"
HRDF_ZIP = DATA / "hrdf.zip"
DEFAULT_DAY = None  # -> Dienstag in der Mitte der Fahrplanperiode


def _ref_day(h: hrdf.HRDF, day: str | None) -> dt.date:
    if day:
        return dt.date.fromisoformat(day)
    mid = h.start + (h.end - h.start) / 2
    return mid + dt.timedelta(days=(1 - mid.weekday()) % 7)   # naechster Dienstag


def _stations(a, db: didok.StationDB) -> list[didok.Station]:
    out = []
    if getattr(a, "all_stations", False):
        return [s for s in db.by_num.values() if s.abbr or s.number // 100000 != 85]
    if a.stations:
        for tok in a.stations.split(","):
            if tok.strip():
                out.append(db.resolve(tok))
    if a.around:
        c = db.resolve(a.around)
        out += db.within(c.lat, c.lon, a.radius)
    if not out:
        raise SystemExit("keine Stationen: --stations BN,NE,... und/oder --around NE --radius 15")
    seen, uniq = set(), []
    for s in out:
        if s.number not in seen:
            seen.add(s.number)
            uniq.append(s)
    return uniq


def cmd_fetch(a):
    kinds = [k for k in ("didok", "hrdf", "topo", "release") if getattr(a, k)] or ["topo", "didok", "hrdf"]
    for k in kinds:
        try:
            download.fetch(k, Path(a.data), year=a.year, url=a.url, force=a.force)
        except Exception as e:  # eine fehlende Quelle soll die anderen nicht blockieren
            print(f"{k}: FEHLER {type(e).__name__}: {e}", file=sys.stderr)


def cmd_stations(a):
    sp = [Path(p) for p in a.didok] if a.didok else []
    if not sp and (Path(a.data) / "didok.csv").exists():
        sp = [Path(a.data) / "didok.csv"]
    hz = Path(a.hrdf) if a.hrdf else (HRDF_ZIP if HRDF_ZIP.exists() else None)
    topo = [Path(a.topo)] if a.topo else ([Path(a.data) / "betriebspunkte.json"]
                                          if (Path(a.data) / "betriebspunkte.json").exists() else [])
    if not sp and not hz and not topo:
        raise SystemExit("weder DIDOK-CSV, topo-daten noch HRDF-ZIP gefunden – zuerst 'fetch'")
    didok.build_db(sp, hz, Path(a.out), all_modes=a.all_modes, topo=topo)


def cmd_find(a):
    db = didok.StationDB(Path(a.db))
    q = a.query.lower()
    hits = [s for s in db.by_num.values()
            if q in s.name.lower() or q == s.abbr.lower() or q == str(s.number)]
    for s in sorted(hits, key=lambda s: (s.abbr.lower() != q, s.name))[:40]:
        print(f"{s.abbr:8} {s.number}  {s.name:40} {s.lat or '':>10} {s.lon or '':>10}")


def cmd_extract(a):
    db = didok.StationDB(Path(a.db))
    sts = _stations(a, db)
    print(f"{len(sts)} Stationen: " + ",".join(s.abbr for s in sts[:40]), file=sys.stderr)
    cats = set(a.categories.split(",")) if a.categories else lines.RAIL
    src = a.from_trips or (str(Path(a.db).parent / "trips_bahn.json.gz")
                           if not Path(a.hrdf).exists() and (Path(a.db).parent / "trips_bahn.json.gz").exists() else None)
    if src:
        data = hrdf.subset(hrdf.load_trips(Path(src)), [s.number for s in sts], cats,
                           split_gaps=getattr(a, "split_gaps", False))
        hrdf.save_trips(data, Path(a.out))
        print(f"{len(data['trips'])} Fahrten aus {src} (Tag {data['meta'].get('day')}) -> {a.out}", file=sys.stderr)
        return
    h = hrdf.HRDF(Path(a.hrdf))
    day = None if a.all_days else _ref_day(h, a.day)
    if day:
        print(f"Referenztag {day} (Fahrplan {h.start}..{h.end})", file=sys.stderr)
    hrdf.extract(Path(a.hrdf), [s.number for s in sts], Path(a.out), day, cats, verbose=True)


def cmd_lines(a):
    print(lines.table(Path(a.trips), didok.StationDB(Path(a.db))))


def cmd_suggest(a):
    spec = lines.suggest(Path(a.trips), didok.StationDB(Path(a.db)), Path(a.out), a.name,
                         merge=not a.no_merge, include_rare=a.include_rare,
                         grundtakt=getattr(a, "grundtakt", False))
    print(f"{len(spec['trainruns'])} Linien -> {a.out}", file=sys.stderr)


def cmd_build(a):
    spec = json.loads(Path(a.spec).read_text())
    db = didok.StationDB(Path(a.db)) if a.db and Path(a.db).exists() else None
    meta = json.loads(Path(a.metadata).read_text())["metadata"] if a.metadata else None
    pos = json.loads(Path(a.positions).read_text()) if a.positions else None
    out, warn = nge.build(spec, db, a.upk, meta, pos)
    for w in warn:
        print("Hinweis:", w, file=sys.stderr)
    errs = validate.validate(out)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{len(out['nodes'])} Knoten, {len(out['trainruns'])} Linien, "
          f"{len(out['trainrunSections'])} Abschnitte -> {a.out}", file=sys.stderr)
    if errs:
        print("\n".join("FEHLER: " + e for e in errs), file=sys.stderr)
        sys.exit(1)


def cmd_validate(a):
    errs = validate.validate(json.loads(Path(a.file).read_text()))
    print("\n".join(errs) if errs else "OK – keine Fehler")
    sys.exit(1 if errs else 0)


def cmd_departures(a):
    print("\n".join(validate.departures(json.loads(Path(a.file).read_text()), a.node)))


def cmd_positions(a):
    pos = nge.positions_from([Path(f) for f in a.files])
    Path(a.out).write_text(json.dumps(pos, indent=1))
    print(f"{len(pos)} Positionen -> {a.out}", file=sys.stderr)


def cmd_run(a):
    """extract + suggest + build in einem Schritt."""
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    a.out_final = a.out
    a.out = str(work / "trips.json"); cmd_extract(a)
    a.trips = a.out; a.out = str(work / "spec.json"); a.no_merge = False; a.include_rare = False
    cmd_suggest(a)
    print(lines.table(Path(a.trips), didok.StationDB(Path(a.db))), file=sys.stderr)
    a.spec = a.out; a.out = a.out_final; a.metadata = None
    cmd_build(a)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nge-fahrplan", description=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def sub(name, fn, help):
        p = sp.add_parser(name, help=help)
        p.set_defaults(fn=fn)
        return p

    p = sub("fetch", cmd_fetch, "DIDOK/atlas und HRDF von opentransportdata.swiss laden")
    p.add_argument("--didok", action="store_true"); p.add_argument("--hrdf", action="store_true")
    p.add_argument("--topo", action="store_true", help="betriebspunkte.json aus VXstone/topo-daten")
    p.add_argument("--release", action="store_true",
                   help="vorbereitete Daten (stations.csv + trips_bahn.json.gz) aus dem Release 'fahrplandaten'")
    p.add_argument("--year", type=int, default=dt.date.today().year + (dt.date.today().month == 12))
    p.add_argument("--url", help="direkte Download-URL statt CKAN-Suche")
    p.add_argument("--data", default=str(DATA)); p.add_argument("--force", action="store_true")

    p = sub("stations", cmd_stations, "Stationsdatenbank (Kuerzel, Name, Koordinaten) bauen")
    p.add_argument("--didok", nargs="*", help="DIDOK/atlas/haltekante-CSV(s)")
    p.add_argument("--hrdf", help="HRDF-ZIP (ergaenzt fehlende Stationen/Koordinaten)")
    p.add_argument("--topo", help="betriebspunkte.json aus topo-daten (Standard: data/betriebspunkte.json)")
    p.add_argument("--all-modes", action="store_true", help="auch Bus/Tram/Schiff")
    p.add_argument("--data", default=str(DATA)); p.add_argument("--out", default=str(DB))

    p = sub("find", cmd_find, "Station suchen"); p.add_argument("query"); p.add_argument("--db", default=str(DB))

    def region(p):
        p.add_argument("--db", default=str(DB)); p.add_argument("--hrdf", default=str(HRDF_ZIP))
        p.add_argument("--stations", help="Komma-Liste: Kuerzel, Nummern oder Namen")
        p.add_argument("--around", help="Zentrum (Kuerzel), zusammen mit --radius")
        p.add_argument("--radius", type=float, default=10, help="km")
        p.add_argument("--day", help="Referenztag JJJJ-MM-TT (Standard: Dienstag Mitte Fahrplanjahr)")
        p.add_argument("--all-days", action="store_true", help="keine Verkehrstagsfilterung")
        p.add_argument("--categories", help="HRDF-Gattungen, z.B. IC,IR,RE,S (Standard: alle Bahn)")
        p.add_argument("--all-stations", action="store_true", help="alle Stationen der Datenbank (ganze Schweiz)")
        p.add_argument("--from-trips", help="vorbereitete Fahrtendatei statt HRDF (trips_bahn.json.gz)")
        p.add_argument("--split-gaps", action="store_true",
                       help="Fahrten trennen, wo sie die Region verlassen (keine Abkuerzungs-Abschnitte)")

    p = sub("extract", cmd_extract, "Fahrten aus HRDF ziehen"); region(p)
    p.add_argument("--out", default="trips.json")

    p = sub("lines", cmd_lines, "Linientabelle zur QA"); p.add_argument("--trips", default="trips.json")
    p.add_argument("--db", default=str(DB))

    p = sub("suggest", cmd_suggest, "Spec-Entwurf aus Fahrten")
    p.add_argument("--trips", default="trips.json"); p.add_argument("--db", default=str(DB))
    p.add_argument("--out", default="spec.json"); p.add_argument("--name", default="NGE Netz")
    p.add_argument("--no-merge", action="store_true", help="30'/20'/15' nicht zusammenfassen")
    p.add_argument("--include-rare", action="store_true")
    p.add_argument("--grundtakt", action="store_true", help="nur ganztaegige Lagen (ohne HVZ/zeitweise)")

    def buildopts(p):
        p.add_argument("--upk", type=float, default=80, help="NGE-Einheiten pro km (Layoutdichte)")
        p.add_argument("--positions", help="positions.json (Handverschiebungen)")

    p = sub("build", cmd_build, "spec.json -> NGE-JSON")
    p.add_argument("--spec", default="spec.json"); p.add_argument("--db", default=str(DB))
    p.add_argument("--out", default="netzgrafik.json")
    p.add_argument("--metadata", help="echter NGE-Export als Metadaten-Quelle")
    buildopts(p)

    p = sub("run", cmd_run, "extract + suggest + build in einem Schritt"); region(p); buildopts(p)
    p.add_argument("--name", default="NGE Netz"); p.add_argument("--work", default="work")
    p.add_argument("--grundtakt", action="store_true", help="nur ganztaegige Lagen (ohne HVZ/zeitweise)")
    p.add_argument("--out", default="netzgrafik.json")

    p = sub("validate", cmd_validate, "NGE-JSON pruefen"); p.add_argument("file")
    p = sub("departures", cmd_departures, "Minuten an einem Knoten")
    p.add_argument("file"); p.add_argument("node")
    p = sub("positions", cmd_positions, "Knotenpositionen aus NGE-Exporten sammeln")
    p.add_argument("files", nargs="+"); p.add_argument("--out", default="positions.json")

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
