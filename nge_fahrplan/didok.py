"""Stationsdatenbank aus DIDOK / atlas-Dienststellen (+ HRDF als Ergaenzung).

Ergebnis ist eine kleine CSV (number, abbr, name, lat, lon, source), die alle
weiteren Schritte nutzen. Unterstuetzte Eingaben:

* atlas v2 ``*-swiss-service-point.csv`` (opentransportdata.swiss / opendata.swiss)
* alter DIDOK-Export ``dienststellen-gemass-opentransportdataswiss.csv`` (data.sbb.ch)
* ``haltestelle-haltekante.csv`` (data.sbb.ch)
* HRDF ``BAHNHOF`` + ``BFKOORD_WGS`` (aus dem Fahrplan-ZIP; fuellt Luecken)

Die Spaltennamen der offenen Datensaetze haben sich in der Vergangenheit
geaendert; darum werden sie ueber Alias-Listen erkannt. Wird eine Pflichtspalte
nicht gefunden, bricht der Import mit der Liste der vorhandenen Spalten ab –
dann einfach den Alias unten ergaenzen.
"""
from __future__ import annotations

import csv
import io
import math
import sys
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

ALIASES = {
    "number": ["number", "servicepointnumber", "bpuic", "uic", "didok", "didok_code",
               "nummer", "stop_id", "number_uic"],
    "number_short": ["numbershort", "number_short", "didok_kurz"],
    "country": ["uiccountrycode", "uic_country_code", "laendercode"],
    "abbr": ["abbreviation", "abkuerzung", "abkurzung", "abk", "abbr", "abbreviation_bav",
             "operatingpointabbreviation"],
    "name": ["designationofficial", "designation_official", "bezeichnung_offiziell",
             "designationlong", "name", "stop_name", "designation", "bezeichnung"],
    "lat": ["wgs84north", "wgs84_north", "lat", "latitude", "n_wgs84", "geopos_lat"],
    "lon": ["wgs84east", "wgs84_east", "lon", "lng", "longitude", "e_wgs84", "geopos_lon"],
    "geopos": ["geopos", "geo_point_2d", "geoposition"],
    "lv95e": ["lv95east", "lv95_east", "e_lv95", "e"],
    "lv95n": ["lv95north", "lv95_north", "n_lv95", "n"],
    "transport": ["meansoftransport", "means_of_transport", "verkehrsmittel"],
    "valid_to": ["validto", "valid_to", "gueltig_bis"],
    "valid_from": ["validfrom", "valid_from", "gueltig_von"],
}


@dataclass
class Station:
    number: int
    abbr: str
    name: str
    lat: float | None
    lon: float | None
    source: str = ""


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower().strip().lstrip("﻿") if ch.isalnum() or ch == "_")


def _find(header: list[str], key: str) -> str | None:
    normed = {_norm(h): h for h in header}
    for a in ALIASES[key]:
        if _norm(a) in normed:
            return normed[_norm(a)]
    return None


def lv95_to_wgs84(e: float, n: float) -> tuple[float, float]:
    """swisstopo-Naeherungsformel LV95 -> WGS84 (Genauigkeit ~1 m)."""
    y = (e - 2600000) / 1e6
    x = (n - 1200000) / 1e6
    lon = (2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x
           - 0.0436 * y ** 3)
    lat = (16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x
           - 0.0447 * y * y * x - 0.0140 * x ** 3)
    return lat * 100 / 36, lon * 100 / 36


def _open_text(path: Path):
    """CSV direkt oder erste CSV in einem ZIP."""
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return io.TextIOWrapper(z.open(name), encoding="utf-8-sig", newline="")
    return open(path, encoding="utf-8-sig", newline="")


def _float(v) -> float | None:
    try:
        f = float(str(v).replace(",", ".")) if v not in (None, "") else None
        return f if f is not None and math.isfinite(f) else None
    except ValueError:
        return None


def read_service_points(path: Path, all_modes: bool = False) -> list[Station]:
    """Liest eine DIDOK/atlas/Haltekante-CSV. Behaelt Punkte mit Abkuerzung
    (= Bahnhoefe und Betriebspunkte); Bus-/Tramhaltestellen haben keine."""
    with _open_text(path) as f0:
        first = f0.readline()
    delim = max(";,\t", key=first.count)
    f = _open_text(path)
    rd = csv.DictReader(f, delimiter=delim)
    h = rd.fieldnames or []
    col = {k: _find(h, k) for k in ALIASES}
    missing = [k for k in ("abbr", "name") if not col[k]]
    if not (col["number"] or (col["number_short"] and col["country"])):
        missing.append("number")
    if missing:
        raise SystemExit(f"{path.name}: Spalten {missing} nicht erkannt.\n"
                         f"Vorhanden: {h}\n-> Alias in nge_fahrplan/didok.py ergaenzen.")

    best: dict[int, tuple[str, Station]] = {}
    for row in rd:
        abbr = (row.get(col["abbr"]) or "").strip()
        if not abbr:
            continue
        if col["transport"] and not all_modes:
            t = (row.get(col["transport"]) or "").upper()
            # leere Angabe = Betriebspunkt ohne Publikumsverkehr -> behalten
            if t and "TRAIN" not in t and "ZUG" not in t and "RACK" not in t:
                continue
        try:
            if col["number"] and row.get(col["number"]):
                num = int(float(row[col["number"]]))
            else:
                num = int(row[col["country"]]) * 100000 + int(row[col["number_short"]])
        except (TypeError, ValueError):
            continue
        if num < 1000000:  # Kurznummer ohne Laendercode -> Schweiz
            num += 8500000
        lat = _float(row.get(col["lat"])) if col["lat"] else None
        lon = _float(row.get(col["lon"])) if col["lon"] else None
        if (lat is None or lon is None) and col["geopos"] and row.get(col["geopos"]):
            parts = row[col["geopos"]].replace(";", ",").split(",")
            if len(parts) == 2:
                lat, lon = _float(parts[0]), _float(parts[1])
        if (lat is None or lon is None) and col["lv95e"] and col["lv95n"]:
            e, n = _float(row.get(col["lv95e"])), _float(row.get(col["lv95n"]))
            if e and n and e > 2e6:
                lat, lon = lv95_to_wgs84(e, n)
        st = Station(num, abbr, (row.get(col["name"]) or "").strip(), lat, lon, path.name)
        # bei mehreren Versionen die mit dem spaetesten Gueltigkeitsende nehmen
        key = (row.get(col["valid_to"]) or "") if col["valid_to"] else ""
        key += (row.get(col["valid_from"]) or "") if col["valid_from"] else ""
        if num not in best or key >= best[num][0]:
            best[num] = (key, st)
    return [s for _, s in best.values()]


def read_hrdf_stations(hrdf_zip: Path) -> list[Station]:
    """BAHNHOF (Name, Abkuerzung $<3>) + BFKOORD_WGS (Koordinaten) aus dem HRDF-ZIP."""
    z = zipfile.ZipFile(hrdf_zip)
    names = {n.rsplit("/", 1)[-1].upper(): n for n in z.namelist()}
    coords: dict[int, tuple[float, float]] = {}
    if "BFKOORD_WGS" in names:
        for line in io.TextIOWrapper(z.open(names["BFKOORD_WGS"]), encoding="utf-8", errors="replace"):
            p = line.split("%")[0].split()
            if len(p) >= 3 and p[0].isdigit():
                coords[int(p[0])] = (float(p[2]), float(p[1]))  # lat, lon
    out = []
    for line in io.TextIOWrapper(z.open(names["BAHNHOF"]), encoding="utf-8", errors="replace"):
        if len(line) < 9 or not line[:7].isdigit():
            continue
        num = int(line[:7])
        parts = line[12:].rstrip("\n").split("$")
        name, abbr = parts[0].strip(), ""
        for txt, tag in zip(parts[0::2], parts[1::2]):
            if tag.startswith("<1>"):
                name = txt.strip()
            elif tag.startswith("<3>"):
                abbr = txt.strip()
        lat, lon = coords.get(num, (None, None))
        out.append(Station(num, abbr, name, lat, lon, "HRDF"))
    return out


def build_db(service_points: list[Path], hrdf_zip: Path | None, out: Path,
             all_modes: bool = False) -> list[Station]:
    by_num: dict[int, Station] = {}
    for p in service_points:
        for s in read_service_points(p, all_modes):
            by_num.setdefault(s.number, s)
    if hrdf_zip:
        for s in read_hrdf_stations(hrdf_zip):
            cur = by_num.get(s.number)
            if cur is None:
                if s.abbr or s.number // 100000 != 85:   # Ausland hat oft keine Abk.
                    by_num[s.number] = s
            else:
                if cur.lat is None and s.lat is not None:
                    cur.lat, cur.lon = s.lat, s.lon
    rows = sorted(by_num.values(), key=lambda s: s.number)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()) if rows else ["number"])
        w.writeheader()
        for s in rows:
            w.writerow(asdict(s))
    print(f"{len(rows)} Stationen -> {out}", file=sys.stderr)
    return rows


class StationDB:
    def __init__(self, path: Path):
        self.by_num: dict[int, Station] = {}
        self.by_abbr: dict[str, Station] = {}
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                s = Station(int(r["number"]), r["abbr"], r["name"],
                            _float(r["lat"]), _float(r["lon"]), r.get("source", ""))
                self.by_num[s.number] = s
                if s.abbr:
                    # Schweizer Eintrag gewinnt bei Doppelungen
                    if s.abbr.upper() not in self.by_abbr or s.number // 100000 == 85:
                        self.by_abbr[s.abbr.upper()] = s

    def resolve(self, token: str) -> Station:
        """Abkuerzung (NE), Nummer (8504221) oder eindeutiger Namensteil."""
        t = token.strip()
        if t.isdigit():
            n = int(t)
            if n < 1000000:
                n += 8500000
            if n in self.by_num:
                return self.by_num[n]
        if t.upper() in self.by_abbr:
            return self.by_abbr[t.upper()]
        hits = [s for s in self.by_num.values() if s.name.lower() == t.lower()]
        if not hits:
            hits = [s for s in self.by_num.values() if t.lower() in s.name.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise KeyError(f"Station '{token}' nicht gefunden")
        raise KeyError(f"'{token}' mehrdeutig: " + ", ".join(f"{s.abbr}={s.name}" for s in hits[:8]))

    def within(self, lat: float, lon: float, radius_km: float) -> list[Station]:
        out = []
        for s in self.by_num.values():
            if s.lat is None or not s.abbr:
                continue
            d = math.hypot((s.lat - lat) * 111.32, (s.lon - lon) * 111.32 * math.cos(math.radians(lat)))
            if d <= radius_km:
                out.append(s)
        return out
